"""Wizard inicial: detecta Stream Decks conectados antes de abrir la
ventana principal. Si hay un deck guardado y sigue presente, salta
directo. Si no hay ninguno conectado muestra "No deck", si hay uno
solo lo elige automático, y con múltiples deja al usuario seleccionar.

Guarda el serial elegido en `~/.config/streamdeb/selected_deck.json`
para que la próxima vez la GUI arranque sin el wizard."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Callable

import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GLib


_REPO_ROOT = Path(__file__).resolve().parent.parent
_DETECT_SCRIPT = _REPO_ROOT / "bin" / "detect-decks"

_PREVIEW_ROOT = Path("/tmp/streamdeb-preview")
_DECK_JSON = _PREVIEW_ROOT / "deck.json"

_SELECTED_PATH = Path.home() / ".config" / "streamdeb" / "selected_deck.json"


def _read_streamdeb_deck() -> dict | None:
    """Si streamdeb está corriendo, ya tiene info del deck en disco."""
    if not _DECK_JSON.exists():
        return None
    try:
        return json.loads(_DECK_JSON.read_text())
    except Exception:
        return None


def _enumerate_via_subprocess() -> tuple[list[dict], str | None]:
    """Llama `bin/detect-decks`. Devuelve (decks, error_msg)."""
    if not _DETECT_SCRIPT.exists():
        return [], f"helper no encontrado: {_DETECT_SCRIPT}"
    try:
        r = subprocess.run([str(_DETECT_SCRIPT)],
                            capture_output=True, text=True, timeout=5)
    except subprocess.TimeoutExpired:
        return [], "detección excedió 5 s (¿USB colgado?)"
    except Exception as e:
        return [], f"{type(e).__name__}: {e}"
    if r.returncode != 0:
        return [], f"helper rc={r.returncode}: {r.stderr.strip()[:200]}"
    try:
        data = json.loads(r.stdout)
    except json.JSONDecodeError as e:
        return [], f"helper output no es JSON: {e}"
    return data.get("decks", []), data.get("error")


def detect_decks() -> list[dict]:
    """Mezcla USB enum + lo que streamdeb publicó. Si un deck ya está
    abierto por el servicio (serial=None en USB enum), completa con el
    serial del deck.json. Cada entrada: {type, id, serial, firmware, error}."""
    usb, err = _enumerate_via_subprocess()
    sd = _read_streamdeb_deck()
    if sd and sd.get("serial"):
        # Si USB enum no resolvió serial pero streamdeb sí, propaga.
        matched = False
        for d in usb:
            if d.get("serial") is None and d.get("type") == sd.get("type"):
                d["serial"]   = sd["serial"]
                d["firmware"] = sd.get("firmware")
                d["error"]    = "(in use by streamdeb)"
                matched = True
                break
        if not matched:
            # USB no lo vio (raro), añade el que reporta streamdeb.
            usb.append({
                "type":     sd.get("type", "Stream Deck"),
                "id":       "(driven by streamdeb)",
                "serial":   sd.get("serial"),
                "firmware": sd.get("firmware"),
                "error":    None,
            })
    return usb


def read_saved_serial() -> str | None:
    if not _SELECTED_PATH.exists():
        return None
    try:
        return json.loads(_SELECTED_PATH.read_text()).get("serial")
    except Exception:
        return None


def save_selected(deck: dict):
    _SELECTED_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _SELECTED_PATH.open("w") as f:
        json.dump({"serial": deck.get("serial"),
                    "type":   deck.get("type")}, f, indent=2)


class DeckWizard(Gtk.Window):
    """Modal de selección/error. on_done(deck or None) — None = cancel."""

    def __init__(self, decks: list[dict], on_done: Callable[[dict | None], None]):
        super().__init__()
        self.set_title("streamdeb — Selecciona tu Stream Deck")
        self.set_default_size(520, 360)
        self.set_modal(True)
        self._on_done = on_done
        self._decks = decks
        self._selected: dict | None = None

        header = Gtk.HeaderBar()
        self.set_titlebar(header)
        cancel = Gtk.Button(label="Salir")
        cancel.connect("clicked", lambda _: self._finish(None))
        header.pack_start(cancel)
        self._ok = Gtk.Button(label="Continuar")
        self._ok.add_css_class("suggested-action")
        self._ok.set_sensitive(False)
        self._ok.connect("clicked", lambda _: self._finish(self._selected))
        header.pack_end(self._ok)
        self._refresh = Gtk.Button.new_from_icon_name("view-refresh-symbolic")
        self._refresh.set_tooltip_text("Volver a buscar")
        self._refresh.connect("clicked", self._on_refresh)
        header.pack_end(self._refresh)

        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12,
                        margin_start=18, margin_end=18,
                        margin_top=14, margin_bottom=14)
        self.set_child(body)

        if not decks:
            title = Gtk.Label(xalign=0)
            title.set_markup(
                "<b>No se detectó ningún Stream Deck</b>")
            title.add_css_class("title-3")
            body.append(title)
            sub = Gtk.Label(
                label=("Conecta el dispositivo USB y pulsa ⟳ para "
                       "buscar de nuevo. Si el LED está encendido pero "
                       "no aparece, revisa permisos USB (grupo `plugdev` "
                       "y `udev/50-streamdeck.rules`)."),
                xalign=0, wrap=True)
            sub.add_css_class("dim-label")
            body.append(sub)
            return

        title = Gtk.Label(xalign=0)
        title.set_markup(
            f"<b>{len(decks)} Stream Deck"
            f"{'s' if len(decks) > 1 else ''} disponible"
            f"{'s' if len(decks) > 1 else ''}</b>")
        title.add_css_class("title-3")
        body.append(title)
        sub = Gtk.Label(
            label="Elige cuál usar — la selección se recuerda.",
            xalign=0)
        sub.add_css_class("dim-label")
        body.append(sub)

        scroller = Gtk.ScrolledWindow(vexpand=True)
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.listbox = Gtk.ListBox()
        self.listbox.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.listbox.connect("row-selected", self._on_row_selected)
        self.listbox.connect("row-activated",
                              lambda *_: self._finish(self._selected))
        for d in decks:
            self.listbox.append(self._make_row(d))
        scroller.set_child(self.listbox)
        body.append(scroller)

    def _make_row(self, d: dict) -> Gtk.ListBoxRow:
        row = Gtk.ListBoxRow()
        row.deck = d  # type: ignore[attr-defined]
        hb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10,
                      margin_start=8, margin_end=8,
                      margin_top=8, margin_bottom=8)
        img = Gtk.Image.new_from_icon_name("input-keyboard-symbolic")
        img.set_pixel_size(32)
        hb.append(img)
        vb = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2,
                      hexpand=True)
        title = Gtk.Label(label=d.get("type") or "Stream Deck", xalign=0)
        vb.append(title)
        info_parts = []
        if d.get("serial"):
            info_parts.append(f"serial {d['serial']}")
        if d.get("firmware"):
            info_parts.append(f"fw {d['firmware']}")
        if d.get("id"):
            info_parts.append(d["id"])
        if d.get("error"):
            info_parts.append(d["error"])
        sub = Gtk.Label(label=" · ".join(info_parts), xalign=0)
        sub.add_css_class("dim-label")
        sub.add_css_class("caption")
        vb.append(sub)
        hb.append(vb)
        row.set_child(hb)
        return row

    def _on_row_selected(self, _lb, row):
        if row is None:
            self._selected = None
            self._ok.set_sensitive(False)
            return
        self._selected = getattr(row, "deck", None)
        self._ok.set_sensitive(self._selected is not None)

    def _on_refresh(self, _btn):
        new = detect_decks()
        self._decks = new
        # Recrear ventana (simplificado en lugar de mutar in-place)
        on_done = self._on_done
        self.close()
        DeckWizard(new, on_done).present()

    def _finish(self, deck: dict | None):
        self._on_done(deck)
        self.close()


def gate(on_ready: Callable[[dict | None], None], on_quit: Callable[[], None]):
    """Lógica del gate: si hay saved deck presente, llama on_ready con él.
    Si hay 1 deck nuevo, lo guarda y llama on_ready. Si hay varios, abre
    wizard. Si hay 0, abre wizard con mensaje de error. on_quit = el
    usuario salió sin elegir."""
    decks = detect_decks()
    saved = read_saved_serial()

    # Saved deck sigue presente → directo
    if saved:
        for d in decks:
            if d.get("serial") == saved:
                on_ready(d)
                return

    # Exactamente uno → auto-pick
    if len(decks) == 1:
        save_selected(decks[0])
        on_ready(decks[0])
        return

    # 0 ó >1 → wizard
    def _done(deck: dict | None):
        if deck is None:
            on_quit()
            return
        save_selected(deck)
        on_ready(deck)

    DeckWizard(decks, _done).present()
