"""Entry point: `python3 -m streamdeb_config` desde el repo root.

Fase 3 del roadmap GUI: ventana con edición de los campos de texto de
apps/web/keys (vent queda read-only por ahora — geometría wmctrl es
frágil). Botón Save escribe `~/.config/streamdeb/config.toml` y el
servicio streamdeb lo recarga solo en ≤3 s.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Hacer importables `core` y `plugins` del repo (estamos en streamdeb_config/).
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GLib, Gdk, GdkPixbuf            # noqa: E402

from plugins import userconfig                                  # noqa: E402
from plugins.vent import dibujar_vent_preview                   # noqa: E402
from core import widgets as W                                   # noqa: E402
from core.iconos import buscar_icono                            # noqa: E402
from core.keyboard import parse_combo                           # noqa: E402


THUMB_PX = 96    # tamaño nativo del deck XL (entrada a core/widgets)
DISPLAY_PX = 84  # tamaño visible en el grid (downscale ligero)


# ─────────────────────── thumbnails ───────────────────────


def _pil_to_texture(img):
    """PIL.Image RGBA → Gdk.Texture (API moderno, no deprecated)."""
    img = img.convert("RGBA")
    data = img.tobytes()
    pix = GdkPixbuf.Pixbuf.new_from_bytes(
        GLib.Bytes.new(data),
        GdkPixbuf.Colorspace.RGB,
        True, 8, img.width, img.height, img.width * 4,
    )
    return Gdk.Texture.new_for_pixbuf(pix)


def _vent_color(btn):
    es_mitad_x = (btn.fraction_x[1] - btn.fraction_x[0]) > 0.34
    es_alto_completo = (btn.fraction_y[1] - btn.fraction_y[0]) > 0.99
    if es_mitad_x:
        return "#cc66ff" if es_alto_completo else "#aa55cc"
    return "#66ddff" if es_alto_completo else "#4499bb"


def render_button(page_name: str, btn):
    size = (THUMB_PX, THUMB_PX)
    if page_name == "apps":
        return W.dibujar_lanzador(None, size, btn.category, btn.color,
                                   icono=btn.icon, fallback=btn.label)
    if page_name == "web":
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
        self.set_default_size(1180, 760)

        self.cfg: userconfig.Config | None = None
        self.current_page = "apps"
        self.selected_key: int | None = None
        self.dirty = False
        # Debounce para repintar thumbnail al editar (evita 16 redraws
        # por tecla pulsada al tipear)
        self._pending_redraw: int | None = None
        # Cell widgets indexados por key (para repintar uno solo)
        self._cells: dict[int, Gtk.Button] = {}

        # ── HeaderBar ──
        header = Gtk.HeaderBar()
        self.set_titlebar(header)
        self.save_btn = Gtk.Button(label="Guardar")
        self.save_btn.add_css_class("suggested-action")
        self.save_btn.set_sensitive(False)
        self.save_btn.connect("clicked", self._on_save_clicked)
        header.pack_end(self.save_btn)
        self.reload_btn = Gtk.Button.new_from_icon_name("view-refresh-symbolic")
        self.reload_btn.set_tooltip_text(
            "Re-leer config.toml desde disco (descarta cambios sin guardar)")
        self.reload_btn.connect("clicked", self._on_reload_clicked)
        header.pack_end(self.reload_btn)
        self.status_label = Gtk.Label()
        header.pack_start(self.status_label)

        # ── Body ──
        body = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        self.set_child(body)

        self.sidebar = Gtk.ListBox()
        self.sidebar.add_css_class("navigation-sidebar")
        self.sidebar.set_size_request(200, -1)
        self.sidebar.connect("row-selected", self._on_page_selected)
        body.append(self.sidebar)
        body.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))

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

        scroller = Gtk.ScrolledWindow()
        scroller.set_size_request(340, -1)
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL,
                              spacing=10, margin_start=18, margin_end=18,
                              margin_top=18, margin_bottom=18)
        panel_title = Gtk.Label(label="Propiedades", xalign=0)
        panel_title.add_css_class("title-3")
        self.panel.append(panel_title)
        self.panel_grid = Gtk.Grid(column_spacing=12, row_spacing=8)
        self.panel.append(self.panel_grid)
        self.panel_empty = Gtk.Label(label="Click en una tecla para editarla",
                                       xalign=0)
        self.panel_empty.add_css_class("dim-label")
        self.panel.append(self.panel_empty)
        scroller.set_child(self.panel)
        body.append(scroller)

        self._reload_from_disk()

    # ── carga / save ──

    def _reload_from_disk(self):
        try:
            self.cfg = userconfig.load()
            self._set_status("")
        except userconfig.ConfigError as e:
            self._set_status(f"⚠ {e}", error=True)
            if self.cfg is None:
                self.cfg = userconfig.Config()
        self.dirty = False
        self.save_btn.set_sensitive(False)
        self._rebuild_sidebar()
        self._populate_grid()
        self._update_panel()

    def _on_reload_clicked(self, _btn):
        self._reload_from_disk()

    def _on_save_clicked(self, _btn):
        try:
            target = userconfig.save(self.cfg)
        except Exception as e:
            self._set_status(f"⚠ save error: {e}", error=True)
            return
        self.dirty = False
        self.save_btn.set_sensitive(False)
        self._set_status(f"✓ Guardado en {target}")
        # Quitar el mensaje a los 3 s
        GLib.timeout_add_seconds(3, self._clear_status_if_idle)

    def _clear_status_if_idle(self):
        if not self.dirty:
            self._set_status("")
        return False  # one-shot

    def _set_status(self, text: str, *, error: bool = False):
        self.status_label.set_text(text)
        if error:
            self.status_label.add_css_class("error")
        else:
            self.status_label.remove_css_class("error")

    def _mark_dirty(self):
        self.dirty = True
        self.save_btn.set_sensitive(True)

    # ── sidebar ──

    def _rebuild_sidebar(self):
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

    # ── grid 8×4 ──

    def _populate_grid(self):
        child = self.grid.get_first_child()
        while child:
            self.grid.remove(child)
            child = self.grid.get_first_child()
        self._cells.clear()

        page = getattr(self.cfg, self.current_page)
        self.page_title.set_text(page.display_name)
        by_key = {b.key: b for b in page.buttons}

        for k in range(32):
            col = k % 8
            row = k // 8
            cell = self._make_cell(k, by_key.get(k))
            self._cells[k] = cell
            self.grid.attach(cell, col, row, 1, 1)

    def _make_cell(self, k: int, btn) -> Gtk.Button:
        cell = Gtk.Button()
        cell.set_size_request(DISPLAY_PX, DISPLAY_PX)
        cell.add_css_class("flat")
        if btn is not None:
            try:
                img = render_button(self.current_page, btn)
                tex = _pil_to_texture(img)
                pic = Gtk.Picture.new_for_paintable(tex)
                pic.set_can_shrink(True)
                pic.set_size_request(DISPLAY_PX, DISPLAY_PX)
                cell.set_child(pic)
            except Exception as e:
                cell.set_label(f"err\n{k}")
                print(f"[GUI] render error {self.current_page}[{k}]: {e}",
                      file=sys.stderr)
            cell.set_tooltip_text(f"key {k} — {btn.label}")
        else:
            lbl = Gtk.Label(label=str(k))
            lbl.add_css_class("dim-label")
            cell.set_child(lbl)
            cell.set_tooltip_text(f"key {k} — (vacío)")
        cell.connect("clicked", self._on_cell_clicked, k)
        if k == self.selected_key:
            cell.add_css_class("suggested-action")
        return cell

    def _refresh_cell(self, k: int):
        """Repinta solo la celda `k` sin tocar las demás."""
        if k not in self._cells:
            return
        page = getattr(self.cfg, self.current_page)
        by_key = {b.key: b for b in page.buttons}
        old = self._cells[k]
        col, row = k % 8, k // 8
        self.grid.remove(old)
        new = self._make_cell(k, by_key.get(k))
        self._cells[k] = new
        self.grid.attach(new, col, row, 1, 1)

    def _on_cell_clicked(self, _btn, key):
        prev = self.selected_key
        self.selected_key = key
        if prev is not None and prev in self._cells:
            self._cells[prev].remove_css_class("suggested-action")
        if key in self._cells:
            self._cells[key].add_css_class("suggested-action")
        self._update_panel()

    # ── panel propiedades (editable) ──

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

        row_idx = 0
        # Header: key (no editable)
        self._panel_row(row_idx, "Key", Gtk.Label(label=str(self.selected_key),
                                                    xalign=0))
        row_idx += 1

        if btn is None:
            note = Gtk.Label(
                label="(slot vacío — edición de slots nuevos en próxima fase)",
                xalign=0, wrap=True, max_width_chars=34)
            note.add_css_class("dim-label")
            self.panel_grid.attach(note, 0, row_idx, 2, 1)
            return

        page_name = self.current_page
        if page_name == "apps":
            self._panel_entry(row_idx, "Categoría", btn.category,
                              lambda v: self._set_field(btn, "category", v))
            row_idx += 1
            self._panel_entry(row_idx, "Label", btn.label,
                              lambda v: self._set_field(btn, "label", v))
            row_idx += 1
            self._panel_entry(row_idx, "Comando", btn.command,
                              lambda v: self._set_field(btn, "command", v))
            row_idx += 1
            self._panel_entry(row_idx, "Color", btn.color,
                              lambda v: self._set_field(btn, "color", v))
            row_idx += 1
            self._panel_entry(row_idx, "Icono", btn.icon or "",
                              lambda v: self._set_field(btn, "icon", v or None))
        elif page_name == "web":
            self._panel_entry(row_idx, "Label", btn.label,
                              lambda v: self._set_field(btn, "label", v))
            row_idx += 1
            self._panel_entry(row_idx, "Sub", btn.sub,
                              lambda v: self._set_field(btn, "sub", v))
            row_idx += 1
            self._panel_entry(row_idx, "URL", btn.url,
                              lambda v: self._set_field(btn, "url", v))
            row_idx += 1
            self._panel_entry(row_idx, "Color", btn.color,
                              lambda v: self._set_field(btn, "color", v))
        elif page_name == "keys":
            self._panel_entry(row_idx, "Label", btn.label,
                              lambda v: self._set_field(btn, "label", v))
            row_idx += 1
            self._panel_entry(row_idx, "Icono", btn.icon or "",
                              lambda v: self._set_field(btn, "icon", v or None))
            row_idx += 1
            # action: dropdown + entry
            self._panel_action_editor(row_idx, btn)
        elif page_name == "vent":
            # VENT read-only por ahora — geometría wmctrl es frágil.
            for label, val in (
                ("Label",      btn.label),
                ("Fracción X", f"{btn.fraction_x[0]:.3f} → {btn.fraction_x[1]:.3f}"),
                ("Fracción Y", f"{btn.fraction_y[0]:.3f} → {btn.fraction_y[1]:.3f}"),
                ("wmctrl",     btn.wmctrl_geom),
            ):
                self._panel_row(row_idx, label,
                                  Gtk.Label(label=val, xalign=0, wrap=True,
                                             max_width_chars=34, selectable=True))
                row_idx += 1
            note = Gtk.Label(
                label="(VENT read-only — geometría wmctrl no es editable aún)",
                xalign=0, wrap=True, max_width_chars=34)
            note.add_css_class("dim-label")
            self.panel_grid.attach(note, 0, row_idx, 2, 1)

    def _panel_row(self, row: int, key: str, value_widget: Gtk.Widget):
        lk = Gtk.Label(label=key, xalign=0, valign=Gtk.Align.START)
        lk.add_css_class("caption-heading")
        self.panel_grid.attach(lk,             0, row, 1, 1)
        self.panel_grid.attach(value_widget,   1, row, 1, 1)

    def _panel_entry(self, row: int, label: str, initial: str, on_change):
        entry = Gtk.Entry()
        entry.set_text(initial)
        entry.set_hexpand(True)
        entry.set_width_chars(28)
        entry.connect("changed", lambda e: self._on_entry_changed(e, on_change))
        self._panel_row(row, label, entry)

    def _on_entry_changed(self, entry: Gtk.Entry, setter):
        setter(entry.get_text())
        self._mark_dirty()
        self._schedule_thumb_redraw()

    def _set_field(self, btn, name: str, value):
        setattr(btn, name, value)

    def _panel_action_editor(self, row_idx: int, btn):
        # Combo "tipo" + Entry de keys/text. Editar el tipo de acción muta
        # btn.action en sitio para que serialize() lo escriba bien.
        a = btn.action
        lk = Gtk.Label(label="Acción", xalign=0, valign=Gtk.Align.START)
        lk.add_css_class("caption-heading")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        type_dd = Gtk.DropDown.new_from_strings(["combo", "type"])
        type_dd.set_selected(0 if a.type == "combo" else 1)
        box.append(type_dd)
        action_entry = Gtk.Entry()
        action_entry.set_width_chars(28)
        action_entry.set_text(a.keys if a.type == "combo" else (a.text or ""))
        box.append(action_entry)
        hint = Gtk.Label(xalign=0)
        hint.add_css_class("dim-label")
        hint.set_wrap(True)
        hint.set_max_width_chars(34)

        def update_hint(*_):
            if type_dd.get_selected() == 0:
                txt = action_entry.get_text()
                if not txt.strip():
                    hint.set_text("ej: ctrl+shift+c · alt+f4 · super+l")
                    hint.remove_css_class("error")
                    return
                try:
                    parse_combo(txt)
                    hint.set_text("✓ combo válido")
                    hint.remove_css_class("error")
                except ValueError as e:
                    hint.set_text(f"⚠ {e}")
                    hint.add_css_class("error")
            else:
                hint.set_text("texto que se tipeará via pynput.keyboard.type()")
                hint.remove_css_class("error")
        update_hint()
        box.append(hint)

        def on_type_change(_dd, _pspec):
            new_type = "combo" if type_dd.get_selected() == 0 else "type"
            if new_type != a.type:
                if new_type == "combo":
                    a.type = "combo"
                    a.keys = action_entry.get_text() or "ctrl+a"
                    a.text = None
                else:
                    a.type = "type"
                    a.text = action_entry.get_text() or ""
                    a.keys = None
                self._mark_dirty()
                self._schedule_thumb_redraw()
                update_hint()

        def on_entry_change(_e):
            if a.type == "combo":
                a.keys = action_entry.get_text()
            else:
                a.text = action_entry.get_text()
            self._mark_dirty()
            self._schedule_thumb_redraw()
            update_hint()

        type_dd.connect("notify::selected", on_type_change)
        action_entry.connect("changed", on_entry_change)

        self.panel_grid.attach(lk,  0, row_idx, 1, 1)
        self.panel_grid.attach(box, 1, row_idx, 1, 1)

    def _schedule_thumb_redraw(self):
        """Re-pinta la celda actual ~250 ms después del último edit
        (debounce). Evita repintar en cada keystroke."""
        if self._pending_redraw is not None:
            GLib.source_remove(self._pending_redraw)
        self._pending_redraw = GLib.timeout_add(
            250, self._do_thumb_redraw)

    def _do_thumb_redraw(self):
        self._pending_redraw = None
        if self.selected_key is not None:
            self._refresh_cell(self.selected_key)
        return False  # one-shot


# ─────────────────────── application ───────────────────────


class ConfigApp(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="com.streamdeb.config")

    def do_activate(self):
        ConfigWindow(self).present()


def main():
    return ConfigApp().run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
