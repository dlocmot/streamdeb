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
from PIL import Image                                           # noqa: E402

from plugins import userconfig                                  # noqa: E402
from plugins.vent import dibujar_vent_preview, dibujar_boton_vent_nav  # noqa: E402
from core import widgets as W                                   # noqa: E402
from core.iconos import buscar_icono                            # noqa: E402
from core.keyboard import parse_combo                           # noqa: E402
from streamdeb_config.picker_app import AppPicker               # noqa: E402
from streamdeb_config.picker_icon import IconPicker             # noqa: E402


THUMB_PX = 96    # tamaño nativo del deck XL (entrada a core/widgets)
DISPLAY_PX = 84  # tamaño visible en el grid (downscale ligero)

# Layout de la fila 0 — coincide con dashboard_pro.botones_navegacion().
# Estos slots NO son editables desde el GUI: el render runtime los pisa
# con los nav buttons (cuenta AWA en vivo, volumen, etc). Key 5 está libre.
NAV_LAYOUT: dict[int, tuple[str, str]] = {
    0: ("SIS",   "#ffaa00"),
    1: ("AWA",   "#00ddff"),
    2: ("MEDIA", "#cc66ff"),
    3: ("APP",   "#33ff66"),
    4: ("CTX",   "#22dd88"),
    # 5: libre
    6: ("KEYS",  "#ffcc33"),
    7: ("VENT",  "#66ddff"),
}

# Paths de iconos para los nav iconizados — copiados de dashboard_pro.py.
_NAV_APP_ICONS = (
    "/usr/share/icons/gnome/256x256/places/start-here.png",
)
_NAV_KEYS_ICONS = (
    "/usr/share/icons/gnome/256x256/apps/preferences-desktop-keyboard-shortcuts.png",
    "/usr/share/icons/gnome/256x256/apps/preferences-desktop-keyboard.png",
)
_nav_cache: dict[str, dict] = {"app": {}, "keys": {}, "vent": {}, "ctx": {}}

# Mapping de los nombres internos del GUI → page_id del deck.
# Necesario para localizar los tile PNGs en vivo que escribe streamdeb.
PAGE_IDS: dict[str, int] = {"apps": 4, "web": 6, "keys": 7, "vent": 8}

# Mapping GUI page_name → tecla nav que la activa en el deck. Clickear
# en la sidebar manda el press equivalente para que el deck siga al GUI.
# WEB (6) no tiene nav directo — entra desde CTX en browsers; lo dejamos
# fuera (sidebar click cambia solo la vista).
NAV_KEY_FOR_PAGE: dict[str, int] = {
    "apps":    3,   # APP nav
    "keys":    6,   # KEYS nav
    "vent":    7,   # VENT nav
    "view_1":  0,   # SIS
    "view_2":  1,   # AWA
    "view_3":  2,   # MEDIA
    "view_12": 4,   # CTX
}

# Páginas no editables (view-only) — solo aparecen cuando el deck las
# ha visitado al menos una vez. id deck → label sidebar.
VIEW_ONLY_PAGES: dict[int, str] = {
    1: "SIS",    2: "AWA",    3: "MEDIA",  5: "CONF",
    10: "DOCKER", 11: "CLIMA", 12: "CTX",
    13: "CORES", 14: "PINGS", 15: "NET", 16: "TEMPS",
}

_PREVIEW_ROOT = Path("/tmp/streamdeb-preview")
_CURRENT_PAGE_FILE = _PREVIEW_ROOT / "current_page"

# Reverso de PAGE_IDS: deck page_id → GUI page_name
PAGE_ID_TO_NAME = {4: "apps", 6: "web", 7: "keys", 8: "vent"}


def _page_id_for(page_name: str) -> int | None:
    """page_name puede ser editable ('apps' etc) o 'view_<id>' para no editable."""
    if page_name in PAGE_IDS:
        return PAGE_IDS[page_name]
    if page_name.startswith("view_"):
        try:
            return int(page_name[5:])
        except ValueError:
            return None
    return None


def _live_tile_path(page_name: str, key: int) -> Path | None:
    """Devuelve el path al PNG en vivo del tile, o None si no existe."""
    page_id = _page_id_for(page_name)
    if page_id is None:
        return None
    p = _PREVIEW_ROOT / f"page_{page_id}" / f"tile_{key}.png"
    return p if p.exists() else None


# ─────────────────────── thumbnails ───────────────────────


def _pil_to_texture(img):
    """PIL.Image RGBA → Gdk.Texture, compuesto sobre negro como en el deck.
    `core.widgets._nuevo_lienzo` devuelve un canvas transparente; el deck
    lo compone sobre fondo negro en `core.render._finalizar`. Sin esto, el
    texto blanco de los nav buttons queda invisible en un tema GTK claro."""
    img = img.convert("RGBA")
    bg = Image.new("RGB", img.size, (0, 0, 0))
    bg.paste(img, mask=img.split()[3])  # canal alfa como máscara
    data = bg.tobytes()
    pix = GdkPixbuf.Pixbuf.new_from_bytes(
        GLib.Bytes.new(data),
        GdkPixbuf.Colorspace.RGB,
        False, 8, bg.width, bg.height, bg.width * 3,
    )
    return Gdk.Texture.new_for_pixbuf(pix)


def _vent_color(btn):
    es_mitad_x = (btn.fraction_x[1] - btn.fraction_x[0]) > 0.34
    es_alto_completo = (btn.fraction_y[1] - btn.fraction_y[0]) > 0.99
    if es_mitad_x:
        return "#cc66ff" if es_alto_completo else "#aa55cc"
    return "#66ddff" if es_alto_completo else "#4499bb"


def render_nav_placeholder(key: int):
    """Tile de nav 'locked' usando los mismos renderers que el deck en runtime.
    SIS/AWA/MEDIA llevan mock data para hitting la rama con subs (que es la
    única visualmente pulida); APP/CTX/KEYS/VENT usan los renderers icono+title."""
    size = (THUMB_PX, THUMB_PX)
    if key == 0:  # SIS
        return W.dibujar_boton_nav(None, size, "SIS", "—/—/—", "--:--",
                                    color="#ffaa00")
    if key == 1:  # AWA
        return W.dibujar_boton_nav(None, size, "AWA", "OFFLINE", "---",
                                    color="#00ddff")
    if key == 2:  # MEDIA
        return W.dibujar_boton_nav(None, size, "MEDIA", "--%",
                                    color="#cc66ff")
    if key == 3:  # APP
        return W.dibujar_btn_icono_nav(None, size, _NAV_APP_ICONS,
                                        "#33ff66", "APP", False,
                                        _nav_cache["app"])
    if key == 4:  # CTX
        from plugins.contexto import dibujar_boton_ctx_nav
        return dibujar_boton_ctx_nav(None, size, activo=False)
    if key == 6:  # KEYS
        return W.dibujar_btn_icono_nav(None, size, _NAV_KEYS_ICONS,
                                        "#ffcc33", "KEYS", False,
                                        _nav_cache["keys"])
    if key == 7:  # VENT
        return dibujar_boton_vent_nav(None, size, activo=False)
    # fallback (no debería llegar)
    titulo, color = NAV_LAYOUT[key]
    return W.dibujar_boton_nav(None, size, titulo, color=color)


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
        # mtime de los paths TOML — el watcher polea y refresca cuando cambia
        self._mtimes: dict = {}
        # Follow-deck: si True, la GUI salta a la página activa del deck.
        # Se apaga al clickear una página en la sidebar (manual override) y
        # se vuelve a encender con el botón 📺 del header.
        self._follow_deck = True

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
        # Toggle follow-deck: cuando está apagado, la GUI no salta a la
        # página del deck (útil mientras editas algo y no quieres que te
        # tire a SIS cuando alguien toca el deck).
        self.follow_btn = Gtk.ToggleButton(label="📺")
        self.follow_btn.set_tooltip_text(
            "Seguir la página activa del Stream Deck")
        self.follow_btn.set_active(True)
        self.follow_btn.connect("toggled", self._on_follow_toggled)
        header.pack_end(self.follow_btn)
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
        # Marco negro alrededor del grid, simulando el deck físico
        deck_bg = Gtk.Box(orientation=Gtk.Orientation.VERTICAL,
                           halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER,
                           vexpand=True)
        deck_bg.add_css_class("deck-bg")
        self.grid = Gtk.Grid(row_spacing=10, column_spacing=10,
                              halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
        deck_bg.append(self.grid)
        center.append(deck_bg)
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
        # Pie con acciones (Crear/Eliminar) — se reconstruye en _update_panel
        self.panel_actions = Gtk.Box(orientation=Gtk.Orientation.VERTICAL,
                                       spacing=8, margin_top=14)
        self.panel.append(self.panel_actions)
        self.panel_empty = Gtk.Label(label="Click en una tecla para editarla",
                                       xalign=0)
        self.panel_empty.add_css_class("dim-label")
        self.panel.append(self.panel_empty)
        scroller.set_child(self.panel)
        body.append(scroller)

        self._reload_from_disk()
        # Watcher: 150 ms polling — mirror se siente en vivo. Cada tick
        # son 32 stat() + diff por-tile; solo se repintan las celdas cuyo
        # mtime cambió (no un rebuild del grid entero).
        GLib.timeout_add(150, self._poll_external_changes)

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
        self._refresh_mtimes()
        self._rebuild_sidebar()
        self._populate_grid()
        self._update_panel()

    def _read_deck_page(self) -> str | None:
        """Lee `current_page` que escribe streamdeb. Devuelve el GUI name
        — editable ('apps') o view-only ('view_<id>')."""
        try:
            if not _CURRENT_PAGE_FILE.exists():
                return None
            page_id = int(_CURRENT_PAGE_FILE.read_text().strip())
        except Exception:
            return None
        if page_id in PAGE_ID_TO_NAME:
            return PAGE_ID_TO_NAME[page_id]
        if page_id in VIEW_ONLY_PAGES:
            return f"view_{page_id}"
        return None

    def _refresh_mtimes(self):
        """Captura el mtime actual de los TOML candidatos para que la próxima
        comparación del watcher no detecte nuestro propio escribir."""
        for p in (userconfig.DEFAULT_CONFIG_PATH, userconfig.REPO_DEFAULT_PATH):
            try:
                self._mtimes[p] = p.stat().st_mtime if p.exists() else 0
            except OSError:
                self._mtimes[p] = 0

    def _poll_external_changes(self):
        """Loop GLib que detecta:
        1. ediciones del TOML fuera de la GUI → recarga config + grid
        2. cambios en los tile PNGs del deck → repaint grid (mirror vivo)"""
        toml_changed = False
        for p in (userconfig.DEFAULT_CONFIG_PATH, userconfig.REPO_DEFAULT_PATH):
            try:
                m = p.stat().st_mtime if p.exists() else 0
            except OSError:
                continue
            if self._mtimes.get(p, 0) != m:
                self._mtimes[p] = m
                toml_changed = True
        if toml_changed:
            if self.dirty:
                self._set_status(
                    "⚠ TOML cambió fuera de la GUI — guarda o ⟳ para recargar",
                    error=True)
            else:
                self._reload_from_disk()
                self._set_status("↻ recargado (cambio externo detectado)")
                GLib.timeout_add_seconds(3, self._clear_status_if_idle)
            return True

        # Follow deck: si el deck cambió de página y el toggle de follow
        # está activo y no hay edits sin guardar, salta a esa página.
        if self._follow_deck:
            deck_page_name = self._read_deck_page()
            if (deck_page_name is not None
                    and deck_page_name != self.current_page
                    and not self.dirty):
                self.current_page = deck_page_name
                self.selected_key = None
                self._rebuild_sidebar()
                self._populate_grid()
                self._update_panel()

        # Mirror del deck por TILE: en vez de rebuild del grid entero,
        # solo se actualiza la imagen de las celdas cuyo mtime cambió.
        page_id = _page_id_for(self.current_page)
        if page_id is not None:
            page_dir = _PREVIEW_ROOT / f"page_{page_id}"
            if page_dir.exists():
                for k in range(32):
                    f = page_dir / f"tile_{k}.png"
                    if not f.exists():
                        continue
                    try:
                        m = f.stat().st_mtime
                    except OSError:
                        continue
                    cache_key = ("tile", self.current_page, k)
                    if self._mtimes.get(cache_key, 0) != m:
                        self._mtimes[cache_key] = m
                        self._swap_tile_paintable(k, f)
        return True  # keep polling

    def _swap_tile_paintable(self, k: int, png_path: Path):
        """Reemplaza solo el Gtk.Picture/paintable del Gtk.Button existente
        (no recrea el widget) → mucho más barato que _populate_grid()."""
        cell = self._cells.get(k)
        if cell is None:
            return
        try:
            with Image.open(png_path) as src:
                src.load()           # fuerza decode antes de salir del with
                img = src.convert("RGBA")
            tex = _pil_to_texture(img)
        except Exception:
            # PNG truncado / lectura concurrente con la escritura del deck.
            # Limpiamos el mtime cacheado para retry en el siguiente tick
            # (sin esto el tile queda "pegado" hasta el próximo redraw real).
            self._mtimes.pop(("tile", self.current_page, k), None)
            return
        child = cell.get_child()
        if isinstance(child, Gtk.Picture):
            child.set_paintable(tex)
        else:
            # Antes era Label vacío (slot dim); ahora hay tile real.
            pic = Gtk.Picture.new_for_paintable(tex)
            pic.set_can_shrink(True)
            pic.set_size_request(DISPLAY_PX, DISPLAY_PX)
            cell.set_child(pic)

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
        # Actualiza mtime cacheado para no detectar nuestro propio save
        # como "cambio externo" en el siguiente tick del watcher.
        self._refresh_mtimes()
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
        # 4 páginas editables siempre
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
        # View-only: páginas que el deck ha visitado (existe page_X/)
        for pid, label in VIEW_ONLY_PAGES.items():
            if not (_PREVIEW_ROOT / f"page_{pid}").exists():
                continue
            name = f"view_{pid}"
            row = Gtk.ListBoxRow()
            row.page_name = name  # type: ignore[attr-defined]
            lbl = Gtk.Label(
                label=f"{label}   (view)",
                xalign=0,
                margin_top=10, margin_bottom=10,
                margin_start=18, margin_end=18,
            )
            lbl.add_css_class("dim-label")
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
            # Bidirectional: click en sidebar → press la nav equivalente
            # en el deck si existe. El deck cambiará a esa página y el
            # follow lo verá automáticamente en sync.
            nav_k = NAV_KEY_FOR_PAGE.get(name)
            if nav_k is not None:
                self._send_press_to_deck(nav_k)
            else:
                # Sin nav directa (WEB, etc): apagamos follow para evitar
                # el bounce back inmediato.
                if self._follow_deck:
                    self._follow_deck = False
                    self.follow_btn.set_active(False)
            self._populate_grid()
            self._update_panel()

    def _on_follow_toggled(self, btn):
        self._follow_deck = btn.get_active()
        if self._follow_deck:
            # Re-engage: salta inmediatamente a la página del deck
            deck_page = self._read_deck_page()
            if deck_page and deck_page != self.current_page and not self.dirty:
                self.current_page = deck_page
                self.selected_key = None
                self._rebuild_sidebar()
                self._populate_grid()
                self._update_panel()

    # ── grid 8×4 ──

    def _populate_grid(self):
        child = self.grid.get_first_child()
        while child:
            self.grid.remove(child)
            child = self.grid.get_first_child()
        self._cells.clear()

        if self.current_page.startswith("view_"):
            pid = int(self.current_page[5:])
            self.page_title.set_text(
                f"{VIEW_ONLY_PAGES.get(pid, '?')} (view-only — sin TOML)")
            by_key = {}
        else:
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
        # Fila nav (0..7 menos 5): no editable, pero mostramos el tile en vivo
        # del deck si existe (incluye fecha/hora/cuenta AWA reales); cae a un
        # placeholder mock solo cuando el deck aún no dibujó esa página.
        if k in NAV_LAYOUT:
            try:
                live = _live_tile_path(self.current_page, k)
                if live is not None:
                    img = Image.open(live).convert("RGBA")
                else:
                    img = render_nav_placeholder(k)
                tex = _pil_to_texture(img)
                pic = Gtk.Picture.new_for_paintable(tex)
                pic.set_size_request(DISPLAY_PX, DISPLAY_PX)
                cell.set_child(pic)
            except Exception:
                cell.set_label(NAV_LAYOUT[k][0])
            cell.set_tooltip_text(f"key {k} — nav (no editable)")
            cell.connect("clicked", self._on_cell_clicked, k)
            if k == self.selected_key:
                cell.add_css_class("suggested-action")
            return cell
        # Live mirror SIEMPRE primero: si el deck dibujó este tile en esta
        # página, lo mostramos exactamente (incluye widgets dinámicos de
        # SIS/AWA/MEDIA que no están en el TOML).
        live = _live_tile_path(self.current_page, k)
        if live is not None:
            try:
                img = Image.open(live).convert("RGBA")
                tex = _pil_to_texture(img)
                pic = Gtk.Picture.new_for_paintable(tex)
                pic.set_can_shrink(True)
                pic.set_size_request(DISPLAY_PX, DISPLAY_PX)
                cell.set_child(pic)
                label_for_tooltip = btn.label if btn is not None else f"key {k}"
                cell.set_tooltip_text(f"key {k} — {label_for_tooltip}")
            except Exception as e:
                cell.set_label(f"err\n{k}")
                print(f"[GUI] live read error {self.current_page}[{k}]: {e}",
                      file=sys.stderr)
        elif btn is not None:
            # Fallback: render local del TOML (deck aún no dibujó esta tecla)
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
        # Bidirectional mirror: click en GUI = press físico en el deck.
        # streamdeb lee press_queue y dispatcha el handler.
        self._send_press_to_deck(key)
        # Selección para edición (independiente del press)
        prev = self.selected_key
        self.selected_key = key
        if prev is not None and prev in self._cells:
            self._cells[prev].remove_css_class("suggested-action")
        if key in self._cells:
            self._cells[key].add_css_class("suggested-action")
        self._update_panel()

    def _send_press_to_deck(self, key: int):
        try:
            _PREVIEW_ROOT.mkdir(parents=True, exist_ok=True)
            with (_PREVIEW_ROOT / "press_queue").open("a") as f:
                f.write(f"{key}\n")
        except Exception as e:
            print(f"[GUI] cannot send press: {e}", file=sys.stderr)

    # ── panel propiedades (editable) ──

    def _clear_box(self, box: Gtk.Box):
        child = box.get_first_child()
        while child:
            box.remove(child)
            child = box.get_first_child()

    def _update_panel(self):
        child = self.panel_grid.get_first_child()
        while child:
            self.panel_grid.remove(child)
            child = self.panel_grid.get_first_child()
        self._clear_box(self.panel_actions)

        if self.selected_key is None:
            self.panel_empty.set_visible(True)
            return
        self.panel_empty.set_visible(False)

        # View-only page: solo mostrar mensaje, no editable
        if self.current_page.startswith("view_"):
            pid = int(self.current_page[5:])
            note = Gtk.Label(
                label=f"Página '{VIEW_ONLY_PAGES.get(pid, pid)}' es view-only.\n"
                      f"Su contenido lo genera streamdeb en runtime (widgets "
                      f"dinámicos) y no se almacena en TOML.",
                xalign=0, wrap=True, max_width_chars=34)
            note.add_css_class("dim-label")
            self.panel_grid.attach(note, 0, 0, 2, 1)
            return

        page = getattr(self.cfg, self.current_page)
        by_key = {b.key: b for b in page.buttons}
        btn = by_key.get(self.selected_key)
        page_name = self.current_page

        row_idx = 0
        # Header: key (no editable)
        self._panel_row(row_idx, "Key", Gtk.Label(label=str(self.selected_key),
                                                    xalign=0))
        row_idx += 1

        # Nav slot (locked)
        if self.selected_key in NAV_LAYOUT:
            titulo, color = NAV_LAYOUT[self.selected_key]
            self._panel_row(row_idx, "Tipo",
                              Gtk.Label(label=f"🔒 nav · {titulo}", xalign=0))
            row_idx += 1
            self._panel_row(row_idx, "Color",
                              Gtk.Label(label=color, xalign=0))
            row_idx += 1
            note = Gtk.Label(
                label=("Esta tecla es navegación — la dibuja "
                       "dashboard_pro.botones_navegacion() en runtime con "
                       "datos vivos (cuenta AWA, volumen, etc). No es "
                       "editable desde la GUI."),
                xalign=0, wrap=True, max_width_chars=34)
            note.add_css_class("dim-label")
            self.panel_grid.attach(note, 0, row_idx, 2, 1)
            return

        if btn is None:
            if page_name == "vent":
                note = Gtk.Label(
                    label="(VENT: añadir slots aún no soportado)",
                    xalign=0, wrap=True, max_width_chars=34)
                note.add_css_class("dim-label")
                self.panel_grid.attach(note, 0, row_idx, 2, 1)
                return
            # Slot vacío editable — botón "Crear" en el footer
            note = Gtk.Label(label="(slot vacío)", xalign=0)
            note.add_css_class("dim-label")
            self.panel_grid.attach(note, 0, row_idx, 2, 1)
            add_btn = Gtk.Button(label="＋  Crear botón vacío")
            add_btn.add_css_class("suggested-action")
            add_btn.connect("clicked",
                             lambda _: self._add_button(self.selected_key))
            self.panel_actions.append(add_btn)
            # En APPS, segunda opción: crear desde lista del sistema
            if page_name == "apps":
                pick_btn = Gtk.Button(label="📂  Crear desde app instalada…")
                pick_btn.connect("clicked", lambda _: self._open_app_picker(
                    self._fill_new_from_app))
                self.panel_actions.append(pick_btn)
            return

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
            self._panel_icon_entry(row_idx, btn.icon or "",
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
            self._panel_icon_entry(row_idx, btn.icon or "",
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

        # Footer:
        # - APPS: pickear app del sistema (reemplaza fields) + Eliminar
        # - WEB/KEYS: solo Eliminar
        # - VENT: nada (read-only)
        if page_name == "apps":
            replace_btn = Gtk.Button(label="📂  Reemplazar con app del sistema…")
            replace_btn.connect("clicked", lambda _: self._open_app_picker(
                lambda app: self._replace_apps_btn_fields(btn, app)))
            self.panel_actions.append(replace_btn)
        if page_name != "vent":
            del_btn = Gtk.Button(label="🗑  Eliminar este botón")
            del_btn.add_css_class("destructive-action")
            del_btn.connect("clicked",
                             lambda _: self._delete_button(self.selected_key))
            self.panel_actions.append(del_btn)

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

    def _panel_icon_entry(self, row: int, initial: str, on_change):
        """Entry para nombre de icono + botón que abre el icon picker."""
        entry = Gtk.Entry()
        entry.set_text(initial)
        entry.set_hexpand(True)
        entry.connect("changed", lambda e: self._on_entry_changed(e, on_change))
        pick = Gtk.Button.new_from_icon_name("system-search-symbolic")
        pick.set_tooltip_text("Buscar en el tema de iconos del sistema")
        pick.connect("clicked", lambda _: self._open_icon_picker(entry))
        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        hbox.append(entry)
        hbox.append(pick)
        self._panel_row(row, "Icono", hbox)

    def _open_icon_picker(self, entry: Gtk.Entry):
        def on_pick(name: str):
            entry.set_text(name)  # dispara "changed" → setter + dirty + redraw
        IconPicker(self, on_pick, initial=entry.get_text()).present()

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

    # ── add / delete ──

    def _add_button(self, key: int):
        """Crea un botón en `key` con defaults según la página actual."""
        if key in NAV_LAYOUT:
            return  # no permitir override de nav
        page_name = self.current_page
        if page_name == "apps":
            new = userconfig.AppButton(
                key=key, category="Util", label="New",
                command="", color="#aaaaaa", icon=None,
            )
            self.cfg.apps.buttons.append(new)
        elif page_name == "web":
            new = userconfig.WebButton(
                key=key, label="New", sub="",
                url="https://", color="#cccccc",
            )
            self.cfg.web.buttons.append(new)
        elif page_name == "keys":
            new = userconfig.KeyButton(
                key=key, label="New", icon=None,
                action=userconfig.KeyAction(type="combo", keys="ctrl+a"),
            )
            self.cfg.keys.buttons.append(new)
        else:
            return  # vent: no soportado
        self._mark_dirty()
        self._refresh_cell(key)
        self._rebuild_sidebar()
        self._update_panel()

    def _delete_button(self, key: int):
        page = getattr(self.cfg, self.current_page)
        before = len(page.buttons)
        page.buttons[:] = [b for b in page.buttons if b.key != key]
        if len(page.buttons) == before:
            return  # nada que borrar
        self._mark_dirty()
        self._refresh_cell(key)
        self._rebuild_sidebar()
        self._update_panel()

    # ── app picker integration ──

    def _open_app_picker(self, on_pick):
        picker = AppPicker(self, on_pick)
        picker.present()

    def _fill_new_from_app(self, app: dict):
        """Crea un AppButton nuevo en selected_key con la data del picker."""
        if self.selected_key is None:
            return
        new = userconfig.AppButton(
            key=self.selected_key,
            category="Util",
            label=app["name"][:12],   # se trunca para no desbordar el deck
            command=app["exec"],
            color="#aaaaaa",
            icon=app.get("icon") or None,
        )
        self.cfg.apps.buttons.append(new)
        self._mark_dirty()
        self._refresh_cell(self.selected_key)
        self._rebuild_sidebar()
        self._update_panel()

    def _replace_apps_btn_fields(self, btn, app: dict):
        """Reemplaza label/command/icon (y opcionalmente category) del botón
        existente con los datos del picker. Conserva color y key."""
        btn.label = app["name"][:12]
        btn.command = app["exec"]
        btn.icon = app.get("icon") or None
        self._mark_dirty()
        self._refresh_cell(self.selected_key)
        self._update_panel()

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


_CSS = b"""
.deck-bg {
    background-color: #000000;
    border-radius: 12px;
    padding: 14px;
}
.deck-bg button.flat {
    background-color: transparent;
    border: 1px solid rgba(255, 255, 255, 0.18);
    border-radius: 8px;
    padding: 0;
}
.deck-bg button.flat:hover {
    background-color: rgba(255, 255, 255, 0.06);
    border-color: rgba(255, 255, 255, 0.30);
}
.deck-bg button.suggested-action {
    background-color: rgba(255, 255, 255, 0.10);
    border-color: rgba(255, 220, 100, 0.85);
}
"""


def _install_css():
    provider = Gtk.CssProvider()
    provider.load_from_data(_CSS)
    Gtk.StyleContext.add_provider_for_display(
        Gdk.Display.get_default(),
        provider,
        Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
    )


class ConfigApp(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="com.streamdeb.config")

    def do_activate(self):
        _install_css()
        ConfigWindow(self).present()


def main():
    return ConfigApp().run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
