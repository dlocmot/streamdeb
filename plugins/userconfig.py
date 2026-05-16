"""Plugin userconfig: schema + loader para ~/.config/streamdeb/config.toml.

Fase 0 del roadmap configurador GUI. Esta capa es la fuente de verdad
declarativa para los plugins editables por el futuro GUI:

    APPS_PAGINA, WEB_PAGINA, KEYS_PAGINA, VENT_PAGINA

En Fase 0 el módulo solo expone `load()` y los dataclasses. En Fase 1
los plugins migran a leer su data de aquí en lugar de hardcodear dicts.

Validación: dataclasses + chequeos manuales (sin pydantic, deps cero).
Formato: TOML, requiere Python ≥ 3.11 (tomllib).
"""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

SCHEMA_VERSION = 1

# Path por defecto (override con env var STREAMDEB_CONFIG)
DEFAULT_CONFIG_PATH = Path(
    os.environ.get(
        "STREAMDEB_CONFIG",
        str(Path.home() / ".config" / "streamdeb" / "config.toml"),
    )
)

# Path al config "default" versionado en el repo (fallback / ejemplo)
REPO_DEFAULT_PATH = Path(__file__).resolve().parent.parent / "config" / "default.toml"


class ConfigError(Exception):
    """Schema inválido o archivo TOML mal formado."""


# ─────────────────────── dataclasses ───────────────────────


@dataclass
class AppButton:
    key: int
    category: str
    label: str
    command: str
    color: str
    icon: Optional[str] = None


@dataclass
class WebButton:
    key: int
    label: str
    sub: str
    url: str
    color: str


@dataclass
class KeyAction:
    """Tipos:
    - combo: keys = "ctrl+shift+c" o "print_screen" (parser en core/keyboard.py)
    - type:  text = "string a tipear via keyboard.type()"
    """
    type: str
    keys: Optional[str] = None
    text: Optional[str] = None


@dataclass
class KeyButton:
    key: int
    label: str
    action: KeyAction
    icon: Optional[str] = None


@dataclass
class VentButton:
    key: int
    label: str
    fraction_x: tuple[float, float]
    fraction_y: tuple[float, float]
    wmctrl_geom: str  # ej "0,0,27,1276,1168"


@dataclass
class AppsPage:
    display_name: str = "APP"
    buttons: list[AppButton] = field(default_factory=list)


@dataclass
class WebPage:
    display_name: str = "WEB"
    buttons: list[WebButton] = field(default_factory=list)
    icon_overrides: dict[str, str] = field(default_factory=dict)


@dataclass
class KeysPage:
    display_name: str = "KEYS"
    color: str = "#ffcc33"
    buttons: list[KeyButton] = field(default_factory=list)


@dataclass
class VentPage:
    display_name: str = "VENT"
    buttons: list[VentButton] = field(default_factory=list)


@dataclass
class Settings:
    brillo: int = 75
    fallback_seconds: int = 300
    dim_seconds: int = 1800
    profile: int = 2
    banner_enabled: bool = False
    theme_lcars: str = "classic"
    monitor_brightness: int = 100


@dataclass
class ApiConfig:
    host: str = "http://192.168.18.10"
    user: str = "StreamDeck"


@dataclass
class Config:
    schema_version: int = SCHEMA_VERSION
    settings: Settings = field(default_factory=Settings)
    api: ApiConfig = field(default_factory=ApiConfig)
    apps: AppsPage = field(default_factory=AppsPage)
    web: WebPage = field(default_factory=WebPage)
    keys: KeysPage = field(default_factory=KeysPage)
    vent: VentPage = field(default_factory=VentPage)


# ─────────────────────── parser ───────────────────────


def _require(d: dict, key: str, ctx: str):
    if key not in d:
        raise ConfigError(f"{ctx}: falta campo obligatorio '{key}'")
    return d[key]


def _check_key_index(k: int, ctx: str):
    if not (0 <= k <= 31):
        raise ConfigError(f"{ctx}: key={k} fuera de rango 0..31 (deck XL)")


def _parse_app_button(raw: dict, idx: int) -> AppButton:
    ctx = f"pages.apps.buttons[{idx}]"
    key = _require(raw, "key", ctx)
    _check_key_index(key, ctx)
    return AppButton(
        key=key,
        category=_require(raw, "category", ctx),
        label=_require(raw, "label", ctx),
        command=_require(raw, "command", ctx),
        color=_require(raw, "color", ctx),
        icon=raw.get("icon"),
    )


def _parse_web_button(raw: dict, idx: int) -> WebButton:
    ctx = f"pages.web.buttons[{idx}]"
    key = _require(raw, "key", ctx)
    _check_key_index(key, ctx)
    return WebButton(
        key=key,
        label=_require(raw, "label", ctx),
        sub=_require(raw, "sub", ctx),
        url=_require(raw, "url", ctx),
        color=_require(raw, "color", ctx),
    )


def _parse_key_action(raw: dict, ctx: str) -> KeyAction:
    if not isinstance(raw, dict):
        raise ConfigError(f"{ctx}: action debe ser tabla (type/keys|text)")
    t = _require(raw, "type", ctx)
    if t == "combo":
        keys = _require(raw, "keys", ctx + ".action")
        return KeyAction(type="combo", keys=keys)
    if t == "type":
        text = _require(raw, "text", ctx + ".action")
        return KeyAction(type="type", text=text)
    raise ConfigError(f"{ctx}: action.type='{t}' no soportado (combo|type)")


def _parse_key_button(raw: dict, idx: int) -> KeyButton:
    ctx = f"pages.keys.buttons[{idx}]"
    key = _require(raw, "key", ctx)
    _check_key_index(key, ctx)
    return KeyButton(
        key=key,
        label=_require(raw, "label", ctx),
        action=_parse_key_action(_require(raw, "action", ctx), ctx),
        icon=raw.get("icon"),
    )


def _parse_vent_button(raw: dict, idx: int) -> VentButton:
    ctx = f"pages.vent.buttons[{idx}]"
    key = _require(raw, "key", ctx)
    _check_key_index(key, ctx)
    fx = _require(raw, "fraction_x", ctx)
    fy = _require(raw, "fraction_y", ctx)
    if not (isinstance(fx, list) and len(fx) == 2):
        raise ConfigError(f"{ctx}: fraction_x debe ser [min, max]")
    if not (isinstance(fy, list) and len(fy) == 2):
        raise ConfigError(f"{ctx}: fraction_y debe ser [min, max]")
    return VentButton(
        key=key,
        label=_require(raw, "label", ctx),
        fraction_x=(float(fx[0]), float(fx[1])),
        fraction_y=(float(fy[0]), float(fy[1])),
        wmctrl_geom=_require(raw, "wmctrl_geom", ctx),
    )


def _parse_settings(raw: dict) -> Settings:
    s = Settings()
    for f in (
        "brillo", "fallback_seconds", "dim_seconds", "profile",
        "banner_enabled", "theme_lcars", "monitor_brightness",
    ):
        if f in raw:
            setattr(s, f, raw[f])
    return s


def _parse_api(raw: dict) -> ApiConfig:
    a = ApiConfig()
    if "host" in raw:
        a.host = raw["host"]
    if "user" in raw:
        a.user = raw["user"]
    return a


def _parse(raw: dict) -> Config:
    sv = raw.get("schema_version", 1)
    if sv != SCHEMA_VERSION:
        raise ConfigError(
            f"schema_version={sv} no soportado (esperado {SCHEMA_VERSION})"
        )
    cfg = Config()
    cfg.schema_version = sv
    if "settings" in raw:
        cfg.settings = _parse_settings(raw["settings"])
        if "api" in raw["settings"]:
            cfg.api = _parse_api(raw["settings"]["api"])
    pages = raw.get("pages", {})
    if "apps" in pages:
        p = pages["apps"]
        cfg.apps.display_name = p.get("display_name", cfg.apps.display_name)
        cfg.apps.buttons = [
            _parse_app_button(b, i) for i, b in enumerate(p.get("buttons", []))
        ]
    if "web" in pages:
        p = pages["web"]
        cfg.web.display_name = p.get("display_name", cfg.web.display_name)
        cfg.web.buttons = [
            _parse_web_button(b, i) for i, b in enumerate(p.get("buttons", []))
        ]
        cfg.web.icon_overrides = dict(p.get("icon_overrides", {}))
    if "keys" in pages:
        p = pages["keys"]
        cfg.keys.display_name = p.get("display_name", cfg.keys.display_name)
        cfg.keys.color = p.get("color", cfg.keys.color)
        cfg.keys.buttons = [
            _parse_key_button(b, i) for i, b in enumerate(p.get("buttons", []))
        ]
    if "vent" in pages:
        p = pages["vent"]
        cfg.vent.display_name = p.get("display_name", cfg.vent.display_name)
        cfg.vent.buttons = [
            _parse_vent_button(b, i) for i, b in enumerate(p.get("buttons", []))
        ]
    _check_no_key_collisions(cfg)
    return cfg


def _check_no_key_collisions(cfg: Config):
    for name, page in (
        ("apps", cfg.apps), ("web", cfg.web),
        ("keys", cfg.keys), ("vent", cfg.vent),
    ):
        seen = set()
        for b in page.buttons:
            if b.key in seen:
                raise ConfigError(f"pages.{name}: key={b.key} duplicada")
            seen.add(b.key)


# ─────────────────────── API pública ───────────────────────


def load(path: Optional[Path] = None) -> Config:
    """Carga el config. Orden de búsqueda:
    1. `path` explícito (si se pasa).
    2. `$STREAMDEB_CONFIG` (env var).
    3. `~/.config/streamdeb/config.toml`.
    4. `<repo>/config/default.toml` (fallback de instalación).

    Si nada existe, devuelve `Config()` con defaults (decks vacíos)."""
    candidates = []
    if path is not None:
        candidates.append(Path(path))
    candidates.append(DEFAULT_CONFIG_PATH)
    candidates.append(REPO_DEFAULT_PATH)
    for p in candidates:
        if p.exists():
            with p.open("rb") as f:
                raw = tomllib.load(f)
            return _parse(raw)
    return Config()
