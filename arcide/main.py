"""ArcIDE entry point.

    arcide                  open the editor
    arcide FILE...          open files
    arcide --folder DIR     open a folder
"""

from __future__ import annotations

import argparse
import os
import sys

# Allow running straight from a checkout: 'python3 -m arcide'.
if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main(argv: list | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="arcide", description="A small IDE for many languages."
    )
    parser.add_argument("files", nargs="*", help="files to open")
    parser.add_argument("--folder", help="folder to show in the explorer")
    parser.add_argument("--version", action="store_true")
    args = parser.parse_args(argv)

    if args.version:
        print("ArcIDE 0.1.0")
        return 0

    try:
        import gi

        gi.require_version("Gtk", "4.0")
        from gi.repository import Gio, Gtk
    except (ImportError, ValueError) as exc:
        print(
            f"ArcIDE needs GTK 4.0 (PyGObject): {exc}\n"
            f"  Ubuntu/Debian: sudo apt install python3-gi gir1.2-gtk-4.0\n"
            f"  Fedora:        sudo dnf install python3-gobject gtk4\n"
            f"  macOS:         brew install pygobject gtk4",
            file=sys.stderr,
        )
        return 1

    from .ui.app import ArcIDEWindow

    class ArcIDE(Gtk.Application):
        __gtype_name__ = "ArcIDE"

        def __init__(self) -> None:
            super().__init__(
                application_id="dev.arcide.ArcIDE",
                flags=Gio.ApplicationFlags.NON_UNIQUE,
            )
            self.folder = args.folder
            self.files = list(args.files)
            self.window = None

        def do_activate(self) -> None:
            if self.window is None:
                folder = self.folder
                if folder is None and self.files:
                    folder = os.path.dirname(os.path.abspath(self.files[0]))
                self.window = ArcIDEWindow(self, folder=folder)
                for path in self.files:
                    if os.path.isfile(path):
                        self.window.open_file(path)
                self.window.connect(
                    "close-request", lambda *_: self._on_closed()
                )
            self.window.present()

        def _on_closed(self) -> bool:
            self.window = None
            return False

    app = ArcIDE()
    return app.run([])


if __name__ == "__main__":
    sys.exit(main())