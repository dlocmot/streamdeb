"""Plugin KEYS (página 7): atajos de teclado y typed strings.

Data declarativa en `config/default.toml` o `~/.config/streamdeb/config.toml`.
Las acciones se persisten como tipo discriminado ({type=combo|type, ...}) y
se parsean a la lista que enviar_combo() espera, o a un string para .type()."""
from core.iconos import buscar_icono as _buscar_icono
from core.keyboard import enviar_combo, KB_DISPONIBLE, keyboard, parse_combo
from core.widgets import dibujar_lanzador_web


# Misma forma: key → (label, combo_str, accion, icon)
#   accion = lista de teclas (combo) o string (type)
KEYS_PAGINA: dict[int, tuple] = {}

# Color base de los botones KEYS (configurable vía TOML)
_KEYS_COLOR = "#ffcc33"


def reload(cfg=None):
    """Reconstruye KEYS_PAGINA desde el config TOML. Combos string → list."""
    global _KEYS_COLOR
    if cfg is None:
        from plugins.userconfig import load as _load
        cfg = _load()
    _KEYS_COLOR = cfg.keys.color
    KEYS_PAGINA.clear()
    for b in cfg.keys.buttons:
        if b.action.type == "combo":
            try:
                accion = parse_combo(b.action.keys)
                combo_str = b.action.keys
            except ValueError as e:
                print(f"[USERCONFIG] keys[{b.key}] combo inválido: {e}", flush=True)
                continue
        elif b.action.type == "type":
            accion = b.action.text   # string crudo, on_press detecta por isinstance
            combo_str = "(typed)"
        else:
            print(f"[USERCONFIG] keys[{b.key}] action.type desconocido", flush=True)
            continue
        KEYS_PAGINA[b.key] = (b.label, combo_str, accion, b.icon)
    print(f"[USERCONFIG] keys: {len(KEYS_PAGINA)} botones, color={_KEYS_COLOR}",
          flush=True)


reload()


def render_pagina_keys(deck, tam, nav_imgs):
    imgs = dict(nav_imgs)
    for tecla, (label, _combo, _accion, icono) in KEYS_PAGINA.items():
        path = _buscar_icono(icono) if icono else None
        imgs[tecla] = dibujar_lanzador_web(deck, tam, label, _KEYS_COLOR, path)
    return imgs


def on_press(tecla):
    if tecla not in KEYS_PAGINA:
        return False
    accion = KEYS_PAGINA[tecla][2]
    if isinstance(accion, str):
        if KB_DISPONIBLE:
            keyboard.type(accion)
    else:
        enviar_combo(accion)
    return True
