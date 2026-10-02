"""The code editor: line numbers, current-line highlight, syntax colouring.

Built on a plain Gtk.TextView rather than GtkSourceView, because GtkSource
is not guaranteed to be installed and an editor that refuses to start is
worse than one without folding or search.
"""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, Gtk  # noqa: E402

from ..highlight import THEME, Highlighter  # noqa: E402
from ..languages import Language, for_path  # noqa: E402

MONO = "monospace"


class Gutter(Gtk.TextView):
    """The strip of line numbers down the left side."""

    __gtype_name__ = "ArcIDEGutter"

    def __init__(self) -> None:
        super().__init__()
        self.set_editable(False)
        self.set_cursor_visible(False)
        self.set_monospace(True)
        self.set_show_line_numbers(False)
        self.set_can_focus(False)
        self.set_left_margin(8)
        self.set_right_margin(8)
        self.set_top_margin(4)
        self.set_bottom_margin(4)
        self.add_css_class("arcide-gutter")
        buf = self.get_buffer()
        buf.set_text("1")
        tag = buf.create_tag("num", foreground="#5C7080", justification=2)
        buf.get_iter_at_mark(buf.get_insert())  # keep the tag object alive
        self._tag = tag

    def set_count(self, total: int, current: int) -> None:
        """Show line numbers up to `total`, highlighting the current one."""
        # Wider files get more room so the digits do not get clipped.
        self.set_size_request(46 + 8 * (len(str(max(total, 1))) - 1), -1)
        if self._shown == (total, current):
            return
        self._shown = (total, current)
        buf = self.get_buffer()
        buf.set_text("".join(f"{i + 1}\n" for i in range(total)).rstrip("\n"))
        self._tag.set_property(
            "weight", 700 if current == total else 400
        )

    _shown = (-1, -1)


class Editor(Gtk.Box):
    """One open file."""

    __gtype_name__ = "ArcIDEEditor"

    def __init__(self, path: str | None = None, text: str = "",
                 language: Language | None = None) -> None:
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL)
        self.path = path
        self.add_css_class("arcide-editor")

        self.view = Gtk.TextView()
        self.view.set_monospace(True)
        self.view.set_show_line_numbers(False)
        self.view.set_auto_indent(True)
        self.view.set_indent_width(4)
        self.view.set_tab_width(4)
        self.view.set_insert_spaces_instead_of_tabs(True)
        self.view.set_smart_home_end(True)
        self.view.set_left_margin(10)
        self.view.set_top_margin(4)
        self.view.set_bottom_margin(4)
        self.view.set_monospace(True)
        self.view.add_css_class("arcide-code")
        self.view.set_tooltip_text(path or "untitled")

        self.gutter = Gutter()
        self.gutter.set_vexpand(True)

        self.buffer = self.view.get_buffer()
        self.buffer.set_text(text)

        self._tags = {}
        for name, style in THEME.items():
            self._tags[name] = self.buffer.create_tag(
                name,
                foreground=style.foreground,
                background=style.background,
                weight=700 if style.bold else 400,
                style=2 if style.italic else 0,
                underline=1 if style.underline else 0,
            )
        self._current_tag = self.buffer.create_tag(
            "current-line", background="#0D2438"
        )

        self.set_language(language or for_path(path or ""))

        self._scroller = Gtk.ScrolledWindow()
        self._scroller.set_policy(Gtk.PolicyType.AUTOMATIC,
                                  Gtk.PolicyType.AUTOMATIC)
        self._scroller.set_vexpand(True)
        self._scroller.set_hexpand(True)
        self._scroller.set_child(self.view)

        self.append(self.gutter)
        self.append(self._scroller)

        # Keep the gutter aligned with the text while scrolling.
        self._scroller.get_vadjustment().connect(
            "value-changed", lambda *_: self._sync_scroll()
        )
        self.buffer.connect("changed", self._on_changed)
        self.buffer.connect("mark-set", self._on_mark_set)

        self._apply_tags()

    # -- language -----------------------------------------------------
    def set_language(self, language: Language) -> None:
        self.language = language
        self.highlighter = Highlighter(language)

    @property
    def display_name(self) -> str:
        if self.path:
            import os
            return os.path.basename(self.path)
        return "untitled"

    @property
    def dirty(self) -> bool:
        return getattr(self, "_dirty", False)

    def get_text(self) -> str:
        return self.buffer.get_text(
            self.buffer.get_start_iter(), self.buffer.get_end_iter(), False
        )

    def set_text(self, text: str) -> None:
        self.buffer.set_text(text)

    def save(self, path: str | None = None) -> str:
        target = path or self.path
        if not target:
            raise ValueError("this editor has no file to save to")
        with open(target, "w", encoding="utf-8") as fh:
            fh.write(self.get_text())
        self.path = target
        self._dirty = False
        self.view.set_tooltip_text(target)
        self.set_language(for_path(target))
        self._apply_tags()
        return target

    # -- internals ----------------------------------------------------
    def _on_changed(self, _buf) -> None:
        self._dirty = True
        self._apply_tags()

    def _on_mark_set(self, _buf, _mark, _const) -> None:
        self._highlight_current_line()

    def _sync_scroll(self) -> None:
        self.gutter.set_vscroll_position(self._scroller.get_vadjustment().get_value())

    def _highlight_current_line(self) -> None:
        buf = self.buffer
        # Remove the old band before adding the new one.
        start = buf.get_iter_at_mark(buf.get_insert())
        end = start.copy()
        buf.remove_tag(self._current_tag, start, end)
        if not self.get_realized():
            return
        self._apply_tags()

    def _apply_tags(self) -> None:
        buf = self.buffer
        start = buf.get_start_iter()
        end = buf.get_end_iter()

        # Clear every tag first so removing a keyword elsewhere cannot
        # leave a stale colour behind.
        for tag in self._tags.values():
            buf.remove_tag(tag, start, end)

        text = buf.get_text(start, end, False)
        lines = text.split("\n")
        for number, line in enumerate(lines):
            if not line:
                continue
            spans = self.highlighter.spans(line)
            if not spans:
                continue
            line_start = buf.get_iter_at_line(number)
            for kind, s, e in spans:
                tag = self._tags.get(kind)
                if tag is None:
                    continue
                a = line_start.copy()
                b = line_start.copy()
                a.set_line_offset(s)
                b.set_line_offset(e)
                buf.apply_tag(tag, a, b)

        current = buf.get_iter_at_mark(buf.get_insert()).get_line() + 1
        self.gutter.set_count(len(lines), current)