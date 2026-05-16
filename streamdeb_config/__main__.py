"""Entry point: `python3 -m streamdeb_config` desde el repo root.

Fase 2 del roadmap GUI: ventana read-only que muestra el contenido de
`config.toml` con thumbnails idénticos a los del deck real. Sidebar
con las 4 páginas editables (apps/web/keys/vent), grid 8×4 al centro,
panel de propiedades a la derecha. Botón refresh re-lee el TOML.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Hacer importables `core` y `plugins` del repo (estamos en streamdeb_config/).
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GLib, GdkPixbuf  # noqa: E402

from plugins import userconfig                          # noqa: E402
from plugins.vent import dibujar_vent_preview           # noqa: E402
from core import widgets as W                           # noqa: E402
from core.iconos import buscar_icono                     # noqa: E402


THUMB_PX = 96   # tamaño nativo del deck XL
DISPLAY_PX = 84  # tamaño visible en el grid (ligero downscale)


# ─────────────────────── thumbnails ───────────────────────


def _pil_to_pixbuf(img):
    """PIL.Image RGBA → GdkPixbuf para usar en Gtk.Picture."""
    img = img.convert("RGBA")
    data = img.tobytes()
    return GdkPixbuf.Pixbuf.new_from_bytes(
        GLib.Bytes.new(data),
        GdkPixbuf.Colorspace.RGB,
        True,            # has_alpha
        8,               # bits/sample
        img.width, img.height,
        img.width * 4,   # rowstride
    )


def _vent_color(btn):
    """Misma lógica que plugins.vent.render_pagina_vent."""
    es_mitad_x = (btn.fraction_x[1] - btn.fraction_x[0]) > 0.34
    es_alto_completo = (btn.fraction_y[1] - btn.fraction_y[0]) > 0.99
    if es_mitad_x:
        return "#cc66ff" if es_alto_completo else "#aa55cc"
    return "#66ddff" if es_alto_completo else "#4499bb"


def render_button(page_name: str, btn) -> "Image.Image":
    """Devuelve un PIL.Image 96×96 imitando el render del deck real.
    `deck=None` se pasa a widgets — no se usa internamente."""
    size = (THUMB_PX, THUMB_PX)
    if page_name == "apps":
        return W.dibujar_lanzador(None, size, btn.category, btn.color,
                                   icono=btn.icon, fallback=btn.label)
    if page_name == "web":
        # En el render real, la URL determina el favicon. Para el preview
        # en read-only, omitimos descarga: el label + color basta para
        # validar layout. (Iconos reales en Fase 3 cuando el GUI tenga
        # caché propia.)
        return W.dibujar_lanzador_web(None, size, btn.label, btn.color, None)
    if page_name == "keys":
        path = buscar_icono(btn.icon) if btn.icon else None
        return W.dibujar_lanzador_web(None, size, btn.label, "#ffcc33", path)
    if page_name == "vent":
        return dibujar_vent_preview(
            None, size, btn.label,
            btn.fraction_x[0], btn.fraction_x[1],
            btn.fraction_y[0], btn.fraction_y[1],
            _vent_color(btn),
        )
    return W._nuevo_lienzo(size)


# ─────────────────────── ventana ───────────────────────


class ConfigWindow(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="streamdeb config")
        self.set_default_size(1180, 740)

        self.cfg = None
        self.cfg_error = None
        self.current_page = "apps"
        self.selected_key = None

        # HeaderBar
        header = Gtk.HeaderBar()
        self.set_titlebar(header)
        reload_btn = Gtk.Button.new_from_icon_name("view-refresh-symbolic")
        reload_btn.set_tooltip_text("Recargar config.toml")
        reload_btn.connect("clicked", self._on_reload_clicked)
        header.pack_end(reload_btn)
        self.status_label = Gtk.Label()
        header.pack_start(self.status_label)

        # Body: HBox 3 zonas
        body = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        self.set_child(body)

        # — Sidebar de páginas
        self.sidebar = Gtk.ListBox()
        self.sidebar.add_css_class("navigation-sidebar")
        self.sidebar.set_size_request(200, -1)
        self.sidebar.connect("row-selected", self._on_page_selected)
        body.append(self.sidebar)

        body.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))

        # — Centro: título de página + grid 8×4
        center = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True,
                          spacing=8, margin_start=20, margin_end=20,
                          margin_top=14, margin_bottom=14)
        self.page_title = Gtk.Label(xalign=0)
        self.page_title.add_css_class("title-2")
        center.append(self.page_title)
        self.grid = Gtk.Grid(row_spacing=10, column_spacing=10,
                              halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER,
                              vexpand=True)
        center.append(self.grid)
        body.append(center)

        body.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))

        # — Panel derecho
        self.panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL,
                              spacing=10, margin_start=18, margin_end=18,
                              margin_top=18, margin_bottom=18)
        self.panel.set_size_request(300, -1)
        panel_title = Gtk.Label(label="Propiedades", xalign=0)
        panel_title.add_css_class("title-3")
        self.panel.append(panel_title)
        self.panel_grid = Gtk.Grid(column_spacing=14, row_spacing=6)
        self.panel.append(self.panel_grid)
        self.panel_empty = Gtk.Label(label="(haz click en una tecla)",
                                       xalign=0)
        self.panel_empty.add_css_class("dim-label")
        self.panel.append(self.panel_empty)
        body.append(self.panel)

        # Carga inicial
        self._reload_config()

    # ── carga / reload ──

    def _reload_config(self):
        try:
            self.cfg = userconfig.load()
            self.cfg_error = None
            self.status_label.set_text("")
        except userconfig.ConfigError as e:
            self.cfg_error = str(e)
            self.status_label.set_text(f"⚠ {e}")
            self.status_label.add_css_class("error")
            if self.cfg is None:
                self.cfg = userconfig.Config()  # vacío
        self._rebuild_sidebar()
        self._populate_grid()
        self._update_panel()

    def _rebuild_sidebar(self):
        # Limpiar
        child = self.sidebar.get_first_child()
        while child:
            self.sidebar.remove(child)
            child = self.sidebar.get_first_child()
        selected_row = None
        for name, page in (
            ("apps", self.cfg.apps), ("web", self.cfg.web),
            ("keys", self.cfg.keys), ("vent", self.cfg.vent),
        ):
            row = Gtk.ListBoxRow()
            row.page_name = name  # type: ignore[attr-defined]
            lbl = Gtk.Label(
                label=f"{page.display_name}   ({len(page.buttons)})",
                xalign=0,
                margin_top=10, margin_bottom=10,
                margin_start=18, margin_end=18,
            )
            row.set_child(lbl)
            self.sidebar.append(row)
            if name == self.current_page:
                selected_row = row
        if selected_row is not None:
            self.sidebar.select_row(selected_row)
        else:
            # current_page eliminada del schema → fallback a apps
            self.current_page = "apps"
            self.sidebar.select_row(self.sidebar.get_row_at_index(0))

    def _on_page_selected(self, _listbox, row):
        if row is None:
            return
        name = getattr(row, "page_name", None)
        if name and name != self.current_page:
            self.current_page = name
            self.selected_key = None
            self._populate_grid()
            self._update_panel()

    def _on_reload_clicked(self, _btn):
        self._reload_config()

    # ── grid 8×4 ──

    def _populate_grid(self):
        # Clear
        child = self.grid.get_first_child()
        while child:
            self.grid.remove(child)
            child = self.grid.get_first_child()

        page = getattr(self.cfg, self.current_page)
        self.page_title.set_text(page.display_name)
        by_key = {b.key: b for b in page.buttons}

        for k in range(32):
            col = k % 8
            row = k // 8
            btn_widget = Gtk.Button()
            btn_widget.set_size_request(DISPLAY_PX, DISPLAY_PX)
            btn_widget.add_css_class("flat")
            btn = by_key.get(k)
            if btn is not None:
                try:
                    img = render_button(self.current_page, btn)
                    pix = _pil_to_pixbuf(img)
                    if img.width != DISPLAY_PX:
                        pix = pix.scale_simple(
                            DISPLAY_PX, DISPLAY_PX,
                            GdkPixbuf.InterpType.BILINEAR,
                        )
                    pic = Gtk.Picture.new_for_pixbuf(pix)
                    pic.set_can_shrink(False)
                    btn_widget.set_child(pic)
                except Exception as e:
                    btn_widget.set_label(f"err\n{k}")
                    print(f"[GUI] render error {self.current_page}[{k}]: {e}",
                          file=sys.stderr)
                btn_widget.set_tooltip_text(f"key {k} — {btn.label}")
            else:
                lbl = Gtk.Label(label=str(k))
                lbl.add_css_class("dim-label")
                btn_widget.set_child(lbl)
                btn_widget.set_tooltip_text(f"key {k} — (vacío)")
            btn_widget.connect("clicked", self._on_cell_clicked, k)
            if k == self.selected_key:
                btn_widget.add_css_class("suggested-action")
            self.grid.attach(btn_widget, col, row, 1, 1)

    def _on_cell_clicked(self, _btn, key):
        self.selected_key = key
        self._populate_grid()  # para re-resaltar
        self._update_panel()

    # ── panel propiedades ──

    def _update_panel(self):
        child = self.panel_grid.get_first_child()
        while child:
            self.panel_grid.remove(child)
            child = self.panel_grid.get_first_child()

        if self.selected_key is None:
            self.panel_empty.set_visible(True)
            return
        self.panel_empty.set_visible(False)

        page = getattr(self.cfg, self.current_page)
        by_key = {b.key: b for b in page.buttons}
        btn = by_key.get(self.selected_key)

        rows = [("Key", str(self.selected_key))]
        if btn is None:
            rows.append(("Estado", "(vacío)"))
        elif self.current_page == "apps":
            rows += [
                ("Categoría", btn.category),
                ("Label",     btn.label),
                ("Comando",   btn.command),
                ("Color",     btn.color),
                ("Icono",     btn.icon or "(sin icono)"),
            ]
        elif self.current_page == "web":
            rows += [
                ("Label", btn.label),
                ("Sub",   btn.sub),
                ("URL",   btn.url),
                ("Color", btn.color),
            ]
        elif self.current_page == "keys":
            a = btn.action
            atext = f"combo: {a.keys}" if a.type == "combo" else f"type: {a.text}"
            rows += [
                ("Label",  btn.label),
                ("Acción", atext),
                ("Icono",  btn.icon or "(sin icono)"),
            ]
        elif self.current_page == "vent":
            fx = f"{btn.fraction_x[0]:.3f} → {btn.fraction_x[1]:.3f}"
            fy = f"{btn.fraction_y[0]:.3f} → {btn.fraction_y[1]:.3f}"
            rows += [
                ("Label",       btn.label),
                ("Fracción X",  fx),
                ("Fracción Y",  fy),
                ("wmctrl geom", btn.wmctrl_geom),
            ]

        for i, (k, v) in enumerate(rows):
            lk = Gtk.Label(label=k, xalign=0, valign=Gtk.Align.START)
            lk.add_css_class("caption-heading")
            lv = Gtk.Label(label=v, xalign=0, wrap=True,
                            max_width_chars=34, selectable=True)
            self.panel_grid.attach(lk, 0, i, 1, 1)
            self.panel_grid.attach(lv, 1, i, 1, 1)


# ─────────────────────── application ───────────────────────


class ConfigApp(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="com.streamdeb.config")

    def do_activate(self):
        win = ConfigWindow(self)
        win.present()


def main():
    return ConfigApp().run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
