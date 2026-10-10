"""ArcIDE main window.

Layout is the one people already know: a file tree on the left, tabs in the
middle, output and problems along the bottom, and the handful of buttons
that matter in a header bar.
"""

from __future__ import annotations

import os
import re
import subprocess
import threading
import time

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gio, GLib, Gdk, Gtk  # noqa: E402

from ..languages import command_for, for_path  # noqa: E402
from .editor import Editor  # noqa: E402

# g++ style: file:line:col: severity: message
def connect_if(widget, signal: str, handler) -> bool:
    """Connect a signal only if this GTK version has it.

    Notebook signals moved around between GTK 4.0 and 4.10, and a hard
    connect would stop the editor from starting on an older GTK.
    """
    try:
        widget.connect(signal, handler)
        return True
    except TypeError:
        return False


DIAG_RE = re.compile(
    r"^(?P<file>[^:\n]+):(?P<line>\d+)(?::(?P<col>\d+))?:\s*"
    r"(?P<severity>error|warning|note|fatal error):\s*(?P<message>.*)$"
)


class ArcIDEWindow(Gtk.ApplicationWindow):
    __gtype_name__ = "ArcIDEWindow"

    def __init__(self, application, folder: str | None = None) -> None:
        super().__init__(application=application, title="ArcIDE")
        self.set_default_size(1180, 760)
        self.folder = folder or os.path.expanduser("~")
        self.editors: list = []
        self.process: subprocess.Popen | None = None
        self._starting: set = set()

        self._build_header()
        self._build_body()
        self._build_status()
        self.load_css()

        self.connect("close-request", self._on_close)
        self.explorer_refresh()
        self._update_title()

    # -- chrome -------------------------------------------------------
    def _build_header(self) -> None:
        header = Gtk.HeaderBar()
        header.set_show_title_buttons(False)
        self.set_titlebar(header)

        open_btn = Gtk.Button(icon_name="document-open-symbolic",
                              tooltip_text="Open a file (Ctrl+O)")
        open_btn.connect("clicked", lambda *_: self.choose_file())
        header.pack_start(open_btn)

        folder_btn = Gtk.Button(icon_name="folder-symbolic",
                                tooltip_text="Open a folder")
        folder_btn.connect("clicked", lambda *_: self.choose_folder())
        header.pack_start(folder_btn)

        self.lang_label = Gtk.Label(label="")
        self.lang_label.add_css_class("dim-label")
        self.lang_label.set_margin_start(12)
        header.pack_start(self.lang_label)

        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        header.pack_start(spacer)

        self.problems_btn = Gtk.Button(label="0")
        self.problems_btn.add_css_class("flat")
        self.problems_btn.set_tooltip_text("Problems")
        self.problems_btn.connect("clicked", lambda *_: self._show_panel("Problems"))
        header.pack_end(self.problems_btn)

        self.stop_btn = Gtk.Button(icon_name="process-stop-symbolic",
                                   tooltip_text="Stop (Ctrl+.)")
        self.stop_btn.add_css_class("destructive-action")
        self.stop_btn.set_sensitive(False)
        self.stop_btn.connect("clicked", lambda *_: self.stop())
        header.pack_end(self.stop_btn)

        self.run_btn = Gtk.Button(icon_name="media-playback-start-symbolic",
                                  tooltip_text="Run (F5)")
        self.run_btn.add_css_class("suggested-action")
        self.run_btn.connect("clicked", lambda *_: self.run())
        header.pack_end(self.run_btn)

    def _build_body(self) -> None:
        outer = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        outer.set_position(240)
        outer.set_vexpand(True)

        # -- explorer
        self.explorer = Gtk.TreeView(model=Gtk.TreeStore(str, str, bool))
        self.explorer.set_headers_visible(False)
        col = Gtk.TreeViewColumn()
        cell = Gtk.CellRendererText()
        col.pack_start(cell, False)
        col.set_cell_data_func(cell, self._tree_data)
        self.explorer.append_column(col)
        # GTK 4 replaced set_row_activate_func() with a signal, and dropped
        # the built-in TreeView search, so guard the older API.
        self.explorer.connect("row-activated", self._on_row_activated)
        if hasattr(self.explorer, "set_enable_search"):
            self.explorer.set_enable_search(True)
            self.explorer.set_search_column(0)

        tree_scroll = Gtk.ScrolledWindow()
        tree_scroll.set_policy(Gtk.PolicyType.AUTOMATIC,
                               Gtk.PolicyType.AUTOMATIC)
        tree_scroll.set_child(self.explorer)

        side = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        side_label = Gtk.Label(label="Explorer")
        side_label.add_css_class("panel-title")
        side_label.set_margin_top(8)
        side_label.set_margin_start(10)
        side.append(side_label)
        side.append(tree_scroll)
        side.set_size_request(200, -1)
        outer.set_start_child(side)

        # -- right: editors over panels
        right = Gtk.Paned(orientation=Gtk.Orientation.VERTICAL)
        right.set_position(470)

        self.tabs = Gtk.Notebook()
        self.tabs.set_vexpand(True)
        connect_if(self.tabs, "switch-page", self._on_tab_switched)
        if not connect_if(self.tabs, "close-page", self._on_tab_closed):
            connect_if(self.tabs, "remove-page", self._on_tab_removed)
        right.set_start_child(self.tabs)

        # -- output / problems
        self.output_view = Gtk.TextView()
        self.output_view.set_editable(False)
        self.output_view.set_monospace(True)
        self.output_view.add_css_class("arcide-code")

        self.problems_store = Gtk.ListStore(str, int, str, str)
        self.problems_view = Gtk.TreeView(model=self.problems_store)
        for title, index in (("File", 0), ("Line", 1), ("Kind", 2),
                             ("Message", 3)):
            self.problems_view.append_column(
                Gtk.TreeViewColumn(title, Gtk.CellRendererText(), text=index)
            )
        problems_scroll = Gtk.ScrolledWindow()
        problems_scroll.set_child(self.problems_view)

        self.panels = Gtk.Notebook()
        out_scroll = Gtk.ScrolledWindow()
        out_scroll.set_child(self.output_view)
        self.panels.append_page(out_scroll, Gtk.Label(label="Output"))
        self.panels.append_page(problems_scroll, Gtk.Label(label="Problems"))
        self.panels.set_vexpand(False)
        right.set_end_child(self.panels)

        outer.set_end_child(right)
        self._main_area = outer

    def _build_status(self) -> None:
        self.status = Gtk.Statusbar()
        self.status_ctx = self.status.get_context_id("arcide")
        # The window has one content child, so the paned area and the status
        # bar live together in a vertical box.
        wrapper = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        wrapper.append(self._main_area)
        wrapper.append(self.status)
        self.set_content(wrapper)

    def load_css(self) -> None:
        provider = Gtk.CssProvider()
        provider.load_from_data(b"""
            .arcide-code { font-family: monospace; font-size: 12pt; }
            .arcide-gutter { font-family: monospace; font-size: 12pt;
                             background: #0A1725; }
            .panel-title { font-weight: bold; font-size: 11pt; }
            .dim-label { font-size: 10pt; opacity: 0.7; }
            .arcide-editor { background: #06101C; }
            window { background: #06101C; }
            textview { color: #C9D6E4; }
        """)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

    # -- explorer -----------------------------------------------------
    def _tree_data(self, _column, cell, tree_model, tree_iter, _data) -> None:
        name, kind, is_dir = tree_model.get(tree_iter, 0, 1, 2)
        cell.set_property("text", ("▸ " if False else "") + name)
        cell.set_property(
            "style", 2 if is_dir else 0
        )
        if is_dir:
            cell.set_property("foreground", "#7FC9F3")

    def explorer_refresh(self) -> None:
        store = self.explorer.get_model()
        store.clear()
        base = self.folder
        if base:
            root = store.append(None, [os.path.basename(base) or base, "dir",
                                       True])
            self._walk(store, root, base)

    def _walk(self, store, parent, path: str, depth: int = 0) -> None:
        if depth > 6:
            return
        try:
            names = sorted(os.listdir(path))
        except OSError:
            return
        # Directories first, then alphabetical.
        for name in sorted(
            names,
            key=lambda n: (not os.path.isdir(os.path.join(path, n)), n.lower()),
        ):
            if name.startswith("."):
                continue
            if name in ("node_modules", "__pycache__", "dist", "build"):
                continue
            full = os.path.join(path, name)
            if os.path.isdir(full):
                row = store.append(parent, [name, "dir", True])
                self._walk(store, row, full, depth + 1)
            else:
                store.append(parent, [name, "file", False])

    def _on_row_activated(self, _view, path, _column) -> None:
        self._tree_activate(path)

    def _tree_activate(self, path) -> None:
        model = self.explorer.get_model()
        row = model.get_iter(path)
        name, kind, is_dir = model.get(row, 0, 1, 2)
        if is_dir:
            return
        full = os.path.join(self.folder, name)
        self.open_file(full)

    def choose_folder(self) -> None:
        dialog = Gtk.FileChooserNative.new(
            "Open Folder", self, Gtk.FileChooserAction.SELECT_FOLDER,
            "Open", "Cancel",
        )
        dialog.connect("response", self._on_folder_chosen)
        dialog.show()

    def _on_folder_chosen(self, dialog, response) -> None:
        if response == Gtk.ResponseType.ACCEPT and dialog.get_file():
            self.folder = dialog.get_file().get_path()
            self.explorer_refresh()
        dialog.destroy()

    def choose_file(self) -> None:
        dialog = Gtk.FileChooserNative.new(
            "Open File", self, Gtk.FileChooserAction.OPEN, "Open", "Cancel",
        )
        dialog.connect("response", self._on_file_chosen)
        dialog.show()

    def _on_file_chosen(self, dialog, response) -> None:
        if response == Gtk.ResponseType.ACCEPT and dialog.get_file():
            self.open_file(dialog.get_file().get_path())
        dialog.destroy()

    # -- tabs ---------------------------------------------------------
    def open_file(self, path: str) -> Editor:
        for editor in self.editors:
            if editor.path and os.path.abspath(editor.path) == os.path.abspath(path):
                page = self.tabs.page_num(editor)
                self.tabs.set_current_page(page)
                return editor
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        except OSError as exc:
            self._append_output(f"could not open {path}: {exc}\n")
            return None
        editor = Editor(path=path, text=text)
        self.editors.append(editor)
        label = Gtk.Label(label=editor.display_name)
        self.tabs.append_page(editor, label)
        self.tabs.set_current_page(self.tabs.page_num(editor))
        self._update_title()
        return editor

    def current_editor(self) -> Editor | None:
        page = self.tabs.get_current_page()
        if page < 0:
            return None
        return self.tabs.get_nth_page(page)

    def _on_tab_switched(self, notebook, page, _num) -> None:
        editor = notebook.get_nth_page(page)
        if editor is not None:
            self._update_title()

    def _on_tab_closed(self, notebook, page, _num=None) -> None:
        if page in self.editors:
            self.editors.remove(page)

    def _on_tab_removed(self, notebook, page, _num) -> None:
        self._on_tab_closed(notebook, page)

    def _update_title(self) -> None:
        editor = self.current_editor()
        if editor is None:
            self.set_title("ArcIDE")
            self.lang_label.set_label("")
        else:
            mark = "*" if editor.dirty else ""
            self.set_title(f"{mark}{editor.display_name} - ArcIDE")
            self.lang_label.set_label(
                f"{editor.language.name}  |  {len(editor.get_text().splitlines())} lines"
            )

    # -- running ------------------------------------------------------
    def run(self) -> None:
        editor = self.current_editor()
        if editor is None:
            self._append_output("open a file first\n")
            return
        if not editor.path:
            self._append_output("save the file before running it\n")
            return
        if editor.language.internal:
            return self._run_zing(editor)
        if not editor.language.run:
            self._append_output(
                f"{editor.language.name} files cannot be run\n"
            )
            return
        try:
            argv = command_for(editor.language, editor.path)
        except ValueError as exc:
            self._append_output(f"{exc}\n")
            return

        self.problems_store.clear()
        self._update_problem_count()
        self._append_output(
            f"$ {' '.join(argv[2:])}\n\n"
        )
        self._set_running(True)
        self._show_panel("Output")

        def worker() -> None:
            try:
                proc = subprocess.Popen(
                    argv,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL,
                    cwd=os.path.dirname(editor.path) or ".",
                    text=True,
                    bufsize=1,
                    env={**os.environ, "PYTHONUNBUFFERED": "1"},
                )
            except OSError as exc:
                GLib.idle_add(self._on_run_finished, f"failed to start: {exc}\n", -1)
                return
            self.process = proc
            code = 0
            try:
                for line in proc.stdout:
                    GLib.idle_add(self._on_output, line)
                code = proc.wait()
            except Exception as exc:  # noqa: BLE001
                GLib.idle_add(self._on_output, f"\n{exc}\n")
                code = -1
            GLib.idle_add(self._on_run_finished, f"\n[exit {code}]\n", code)

        threading.Thread(target=worker, daemon=True).start()

    def _run_zing(self, editor) -> None:
        """Run a .zng file inside this process, so no zing on PATH needed."""
        self.problems_store.clear()
        self._update_problem_count()
        self._show_panel("Output")
        self._set_running(True)
        self._append_output(f"$ zing run {editor.display_name}\n\n")

        def worker() -> None:
            import io
            import traceback

            from ..zing.interp import Output as JaiOut
            from ..zing.interp import run_source

            buffer = io.StringIO()

            class Sink(JaiOut):
                def write(self, _ignored):
                    pass

            out = Sink()
            out.lines = []

            def emit(text):
                buffer.write(text + "\n")
                GLib.idle_add(self._on_output, text + "\n")

            out.write = emit
            code = 0
            try:
                interp = run_source(editor.get_text(), out=out)
                code = interp.exited or 0
            except Exception as exc:  # noqa: BLE001
                GLib.idle_add(self._on_output, f"\n{type(exc).__name__}: {exc}\n")
                code = 1
                GLib.idle_add(
                    self._add_problem,
                    editor.path or "untitled",
                    editor.get_text()[:exc.__dict__.get("line", 1) - 1].count("\n") + 1
                    if isinstance(exc.__dict__.get("line"), int) else 1,
                    "error",
                    str(exc),
                )
            GLib.idle_add(self._on_run_finished, f"\n[exit {code}]\n", code)

        threading.Thread(target=worker, daemon=True).start()

    def _on_output(self, text: str) -> bool:
        self.output_view.get_buffer().insert(
            self.output_view.get_buffer().get_end_iter(), text
        )
        self._maybe_diagnose(text)
        return False

    def _maybe_diagnose(self, text: str) -> None:
        match = DIAG_RE.match(text.strip())
        if not match:
            return
        severity = match.group("severity")
        kind = "error" if "error" in severity else "warning"
        self._add_problem(
            match.group("file"),
            int(match.group("line")),
            kind,
            match.group("message").strip(),
        )

    def _add_problem(self, file: str, line: int, kind: str, message: str) -> None:
        self.problems_store.append([file, line, kind, message])
        self._update_problem_count()

    def _update_problem_count(self) -> None:
        total = len(self.problems_store)
        errors = sum(
            1 for row in self.problems_store if row[2] == "error"
        )
        self.problems_btn.set_label(str(total) if total else "0")
        self.problems_btn.set_tooltip_text(
            f"{errors} error(s), {total - errors} warning(s)"
        )
        if total:
            for index in range(self.panels.get_n_pages()):
                page = self.panels.get_nth_page(index)
                widget = self.panels.get_tab_label(page)
                if isinstance(widget, Gtk.Label) and widget.get_label() == "Problems":
                    self.problems_btn.add_css_class("destructive-action")

    def _on_run_finished(self, text: str, code: int) -> bool:
        if text:
            self.output_view.get_buffer().insert(
                self.output_view.get_buffer().get_end_iter(), text
            )
        self._set_running(False)
        self.process = None
        return False

    def _set_running(self, running: bool) -> None:
        self.run_btn.set_sensitive(not running)
        self.stop_btn.set_sensitive(running)
        self._update_title()

    def stop(self) -> None:
        proc = self.process
        if proc is None:
            return
        try:
            proc.terminate()
            # Give it a moment, then insist.
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
        except OSError:
            pass
        self._append_output("\n[stopped]\n")

    def _show_panel(self, name: str) -> None:
        for index in range(self.panels.get_n_pages()):
            page = self.panels.get_nth_page(index)
            label = self.panels.get_tab_label(page)
            if isinstance(label, Gtk.Label) and label.get_label() == name:
                self.panels.set_current_page(index)
                return

    def _append_output(self, text: str) -> None:
        buf = self.output_view.get_buffer()
        buf.insert(buf.get_end_iter(), text)

    # -- lifecycle ----------------------------------------------------
    def _on_close(self, *_args) -> bool:
        self.stop()
        return False

    def do_activate(self) -> None:
        self.present()