"""Icon picker dialog: lista los iconos del tema actual de GTK y permite
buscar y elegir uno por nombre. Devuelve el nombre del icono (string)
al callback. Es lo que llena el campo `icon` de un AppButton o KeyButton."""
from __future__ import annotations

from typing import Callable, Optional

import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, Gdk, GLib, Pango


# Listado completo de iconos del tema (cacheado entre invocaciones)
_CACHED_NAMES: Optional[list[str]] = None


def _list_icon_names() -> list[str]:
    """Devuelve todos los iconos del tema actual, ordenados, sin duplicados."""
    global _CACHED_NAMES
    if _CACHED_NAMES is not None:
        return _CACHED_NAMES
    display = Gdk.Display.get_default()
    if display is None:
        _CACHED_NAMES = []
        return _CACHED_NAMES
    theme = Gtk.IconTheme.get_for_display(display)
    names = list(theme.get_icon_names() or [])
    # Quitar variantes -symbolic duplicadas (suelen ser monocromas
    # que confunden al usuario buscando un icono "normal")
    names = sorted(set(n for n in names if not n.endswith("-symbolic")))
    _CACHED_NAMES = names
    return _CACHED_NAMES


# Límite de iconos renderizados para mantener la lista responsive
_MAX_RESULTS = 200


class IconPicker(Gtk.Window):
    """Modal con buscador y grid de iconos. Llama `on_pick(name)` al elegir."""

    def __init__(self, parent: Gtk.Window, on_pick: Callable[[str], None],
                 initial: str = ""):
        super().__init__()
        self.set_transient_for(parent)
        self.set_modal(True)
        self.set_title("Elegir icono")
        self.set_default_size(640, 620)
        self._on_pick = on_pick
        self._names = _list_icon_names()
        self._selected: Optional[str] = None

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
        self.search.set_placeholder_text(
            f"Buscar entre {len(self._names)} iconos…")
        self.search.connect("search-changed", self._on_search_changed)
        body.append(self.search)

        # FlowBox para una rejilla flexible de iconos
        scroller = Gtk.ScrolledWindow(vexpand=True)
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.flow = Gtk.FlowBox()
        self.flow.set_valign(Gtk.Align.START)
        self.flow.set_max_children_per_line(6)
        self.flow.set_min_children_per_line(4)
        self.flow.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.flow.set_homogeneous(True)
        self.flow.connect("selected-children-changed", self._on_selection)
        self.flow.connect("child-activated", lambda *_: self._on_ok(None))
        scroller.set_child(self.flow)
        body.append(scroller)

        # Selected name preview + counter
        self.preview = Gtk.Label(xalign=0)
        self.preview.add_css_class("dim-label")
        self.preview.add_css_class("caption")
        body.append(self.preview)

        # Initial state — populate with first results / matching `initial`
        if initial:
            self.search.set_text(initial)
        else:
            self._populate("")

    def _populate(self, query: str):
        q = query.strip().lower()
        # Clear flow
        child = self.flow.get_first_child()
        while child:
            self.flow.remove(child)
            child = self.flow.get_first_child()

        if q:
            matches = [n for n in self._names if q in n.lower()]
        else:
            # Sin query, muestra los primeros _MAX_RESULTS alfabéticos
            matches = self._names[:]

        total = len(matches)
        shown = matches[:_MAX_RESULTS]
        for name in shown:
            self.flow.append(self._make_tile(name))
        more = f" (+{total - len(shown)} más al filtrar)" if total > len(shown) else ""
        self.preview.set_text(f"{len(shown)} de {total} resultados{more}")
        self._selected = None
        self._ok.set_sensitive(False)

    def _make_tile(self, name: str) -> Gtk.FlowBoxChild:
        child = Gtk.FlowBoxChild()
        child.icon_name = name  # type: ignore[attr-defined]
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4,
                       margin_start=6, margin_end=6,
                       margin_top=8, margin_bottom=8)
        img = Gtk.Image.new_from_icon_name(name)
        img.set_pixel_size(48)
        box.append(img)
        lbl = Gtk.Label(label=name, xalign=0.5)
        lbl.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        lbl.set_max_width_chars(14)
        lbl.add_css_class("caption")
        box.append(lbl)
        child.set_child(box)
        return child

    def _on_search_changed(self, entry: Gtk.SearchEntry):
        self._populate(entry.get_text())

    def _on_selection(self, _flow):
        sel = self.flow.get_selected_children()
        if sel:
            name = getattr(sel[0], "icon_name", None)
            self._selected = name
            self._ok.set_sensitive(name is not None)
            if name:
                self.preview.set_text(f"Seleccionado: {name}")
        else:
            self._selected = None
            self._ok.set_sensitive(False)

    def _on_ok(self, _btn):
        if not self._selected:
            return
        self._on_pick(self._selected)
        self.close()
