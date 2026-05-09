"""Persistencia simple de estado vía JSON. Atomic write (temp + rename)
para no corromper si algo se cae a mitad."""
import json
import os
import tempfile

STATE_DIR  = os.path.expanduser("~/.config/streamdeb")
STATE_PATH = os.path.join(STATE_DIR, "state.json")


def load():
    """Devuelve dict con el estado guardado, o {} si no existe / está corrupto."""
    if not os.path.exists(STATE_PATH):
        return {}
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except Exception as e:
        print(f"[STATE] error cargando {STATE_PATH}: {e}", flush=True)
    return {}


def save(state):
    """Escribe `state` (dict) atómicamente a STATE_PATH."""
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        # tempfile en el mismo dir para que rename sea atómico (mismo FS).
        fd, tmp = tempfile.mkstemp(dir=STATE_DIR, prefix=".state-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(state, f, indent=2, sort_keys=True)
            os.replace(tmp, STATE_PATH)
        except Exception:
            try: os.unlink(tmp)
            except Exception: pass
            raise
    except Exception as e:
        print(f"[STATE] error guardando {STATE_PATH}: {e}", flush=True)
