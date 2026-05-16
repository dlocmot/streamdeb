"""App picker dialog: lista .desktop entries del sistema y permite buscar
y elegir una. Devuelve dict {name, exec, icon, comment, path} al callback.

Usado desde el panel APPS para llenar label/command/icon de un slot."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Callable, Optional

import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, Pango


# Ubicaciones estándar XDG + Flatpak system/user
_DESKTOP_DIRS = [
    Path("/usr/share/applications"),
    Path("/usr/local/share/applications"),
    Path.home() / ".local/share/applications",
    Path("/var/lib/flatpak/exports/share/applications"),
    Path.home() / ".local/share/flatpak/exports/share/applications",
]


def _clean_exec(exec_line: str) -> str:
    """Quita los field codes %f %u %F %U %i %c %k de la línea Exec."""
    return re.sub(r"\s*%[fFuUdDnNickvm]\b", "", exec_line).strip()


def _parse_desktop(path: Path) -> Optional[dict]:
    """Lee un .desktop. Devuelve None si NoDisplay/Hidden/no es Application."""
    name = exec_cmd = icon = comment = None
    no_display = hidden = False
    type_app = False
    in_main = False
    try:
        for line in path.read_text(encoding="utf-8",
                                     errors="replace").splitlines():
            line = line.strip()
            if line == "[Desktop Entry]":
                in_main = True
                continue
            if line.startswith("[") and line.endswith("]"):
                in_main = False
                continue
            if not in_main or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k = k.strip()
            v = v.strip()
            if k == "Name" and name is None:
                name = v
            elif k == "Exec" and exec_cmd is None:
                exec_cmd = _clean_exec(v)
            elif k == "Icon" and icon is None:
                icon = v
            elif k == "Comment" and comment is None:
                comment = v
            elif k == "NoDisplay" and v.lower() == "true":
                no_display = True
            elif k == "Hidden" and v.lower() == "true":
                hidden = True
            elif k == "Type":
                type_app = v.lower() == "application"
    except Exception:
        return None
    if no_display or hidden or not type_app or not name or not exec_cmd:
        return None
    return {
        "name": name, "exec": exec_cmd, "icon": icon,
        "comment": comment or "", "path": str(path),
    }


def list_apps() -> list[dict]:
    """Apps visibles del sistema, ordenadas por nombre, sin duplicados."""
    apps: list[dict] = []
    seen: set[str] = set()
    for d in _DESKTOP_DIRS:
        if not d.exists():
            continue
        for f in sorted(d.glob("*.desktop")):
            entry = _parse_desktop(f)
            if entry is None:
                continue
            key = entry["name"].lower()
            if key in seen:
                continue
            seen.add(key)
            apps.append(entry)
    apps.sort(key=lambda e: e["name"].lower())
    return apps


class AppPicker(Gtk.Window):
    """Modal con buscador y lista de apps. Llama `on_pick(app_dict)` al elegir."""

    def __init__(self, parent: Gtk.Window, on_pick: Callable[[dict], None]):
        super().__init__()
        self.set_transient_for(parent)
        self.set_modal(True)
        self.set_title("Elegir aplicación")
        self.set_default_size(560, 620)
        self._on_pick = on_pick
        self._apps = list_apps()

        # HeaderBar
        header = Gtk.HeaderBar()
        self.set_titlebar(header)
        cancel = Gtk.Button(label="Cancelar")
        cancel.connect("clicked", lambda _: self.close())
        header.pack_start(cancel)
        self._ok = Gtk.Button(label="Elegir")
        self._ok.add_css_class("suggested-action")
        self._ok.set_sensitive(False)
        self._ok.connect("clicked", self._on_ok)
        header.pack_end(self._ok)

        # Body
        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8,
                        margin_start=10, margin_end=10,
                        margin_top=8, margin_bottom=10)
        self.set_child(body)

        self.search = Gtk.SearchEntry()
        self.search.set_placeholder_text("Buscar nombre o descripción…")
        self.search.connect("search-changed", self._on_search_changed)
        body.append(self.search)

        scroller = Gtk.ScrolledWindow(vexpand=True)
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.listbox = Gtk.ListBox()
        self.listbox.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.listbox.connect("row-selected", self._on_row_selected)
        self.listbox.connect("row-activated",
                              lambda *_: self._on_ok(None))
        scroller.set_child(self.listbox)
        body.append(scroller)

        self.count_label = Gtk.Label(xalign=0)
        self.count_label.add_css_class("dim-label")
        self.count_label.add_css_class("caption")
        body.append(self.count_label)

        # Focus al buscador y populate inicial
        self.search.grab_focus()
        self._populate("")

    def _populate(self, query: str):
        q = query.strip().lower()
        child = self.listbox.get_first_child()
        while child:
            self.listbox.remove(child)
            child = self.listbox.get_first_child()
        shown = 0
        for app in self._apps:
            if q:
                hay = app["name"].lower() + " " + app["comment"].lower()
                if q not in hay:
                    continue
            self.listbox.append(self._make_row(app))
            shown += 1
        self.count_label.set_text(f"{shown} de {len(self._apps)} apps")
        self._ok.set_sensitive(False)

    def _make_row(self, app: dict) -> Gtk.ListBoxRow:
        row = Gtk.ListBoxRow()
        row.app_entry = app  # type: ignore[attr-defined]
        hb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10,
                      margin_start=8, margin_end=8,
                      margin_top=6, margin_bottom=6)
        # icono — tema del sistema o fallback
        icon_name = (app.get("icon") or "application-x-executable").strip()
        if icon_name.startswith("/"):
            img = Gtk.Image.new_from_file(icon_name)
        else:
            img = Gtk.Image.new_from_icon_name(icon_name)
        img.set_pixel_size(36)
        hb.append(img)

        vb = Gtk.Box(orientation=Gtk.Orientation.VERTICAL,
                      spacing=2, hexpand=True)
        title = Gtk.Label(label=app["name"], xalign=0)
        title.set_ellipsize(Pango.EllipsizeMode.END)
        vb.append(title)
        sub_text = app.get("comment") or app["exec"]
        sub = Gtk.Label(label=sub_text, xalign=0)
        sub.set_ellipsize(Pango.EllipsizeMode.END)
        sub.add_css_class("dim-label")
        sub.add_css_class("caption")
        vb.append(sub)
        hb.append(vb)

        row.set_child(hb)
        return row

    def _on_search_changed(self, entry: Gtk.SearchEntry):
        self._populate(entry.get_text())

    def _on_row_selected(self, _lb, row):
        self._ok.set_sensitive(row is not None)

    def _on_ok(self, _btn):
        row = self.listbox.get_selected_row()
        if row is None:
            return
        app = getattr(row, "app_entry", None)
        if app is None:
            return
        self._on_pick(app)
        self.close()
