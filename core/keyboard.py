"""Wrapper sobre pynput para enviar combos y tipear texto.
Si pynput no está disponible, las funciones loguean warning y se vuelven no-op."""
import time

try:
    from pynput.keyboard import Controller, Key
    keyboard = Controller()
    KB_DISPONIBLE = True
except Exception as e:
    print(f"[WARN] pynput no disponible: {e}")
    KB_DISPONIBLE = False
    Key = None
    keyboard = None


# ─────────────────────── parser de combos declarativos ───────────────────────
# Mapea tokens del TOML ("ctrl+shift+c", "super+l", "shift+print_screen") a la
# lista que enviar_combo() espera: ej [Key.ctrl, Key.shift, 'c'].

# Aliases token → atributo de Key. Tokens en minúscula, separados por '+'.
_KEY_ALIASES = {
    "ctrl": "ctrl", "control": "ctrl",
    "shift": "shift",
    "alt": "alt", "option": "alt",
    "super": "cmd", "cmd": "cmd", "meta": "cmd", "win": "cmd",
    "tab": "tab",
    "enter": "enter", "return": "enter",
    "esc": "esc", "escape": "esc",
    "space": "space",
    "backspace": "backspace",
    "delete": "delete", "del": "delete",
    "home": "home", "end": "end",
    "page_up": "page_up", "pgup": "page_up",
    "page_down": "page_down", "pgdn": "page_down",
    "up": "up", "down": "down", "left": "left", "right": "right",
    "insert": "insert", "ins": "insert",
    "print_screen": "print_screen", "print": "print_screen", "prtsc": "print_screen",
    "caps_lock": "caps_lock", "caps": "caps_lock",
    "num_lock": "num_lock",
    "scroll_lock": "scroll_lock",
    "pause": "pause",
}
# F1..F24
for _i in range(1, 25):
    _KEY_ALIASES[f"f{_i}"] = f"f{_i}"


def parse_combo(spec: str):
    """Convierte "ctrl+shift+c" en [Key.ctrl, Key.shift, 'c'].

    - Tokens reconocidos (ver _KEY_ALIASES) → Key.<atributo>.
    - Tokens de 1 char → literal en minúscula.
    - Levanta ValueError ante tokens vacíos o desconocidos largos.
    """
    if not isinstance(spec, str) or not spec.strip():
        raise ValueError("combo vacío")
    out = []
    for tok in spec.lower().split("+"):
        tok = tok.strip()
        if not tok:
            raise ValueError(f"combo malformado: '{spec}' (token vacío)")
        if tok in _KEY_ALIASES:
            if not KB_DISPONIBLE:
                # Sin pynput, devolvemos placeholder; enviar_combo() ya es no-op.
                out.append(tok)
            else:
                out.append(getattr(Key, _KEY_ALIASES[tok]))
        elif len(tok) == 1:
            out.append(tok)
        else:
            raise ValueError(f"combo: token desconocido '{tok}' en '{spec}'")
    return out


def enviar_combo(keys):
    """Pulsa todas las `keys` en orden, mantiene 50ms, libera en orden inverso."""
    if not KB_DISPONIBLE:
        print("[WARN] pynput no disponible, no se envía combo", flush=True)
        return
    pressed = []
    try:
        for k in keys:
            keyboard.press(k); pressed.append(k)
            time.sleep(0.02)
        time.sleep(0.05)
    finally:
        for k in reversed(pressed):
            try: keyboard.release(k)
            except Exception: pass


def tipear_url(url):
    """Ctrl+T (nueva pestaña), tipea URL, Enter. La app destino debe estar enfocada."""
    if not KB_DISPONIBLE:
        print("[WARN] pynput no disponible, no se tipea URL", flush=True)
        return
    enviar_combo([Key.ctrl, 't'])
    time.sleep(0.35)
    keyboard.type(url)
    time.sleep(0.05)
    keyboard.press(Key.enter); keyboard.release(Key.enter)
