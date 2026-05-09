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
