"""Plugin GROWATT (página 17): dashboard inversor solar Growatt.

Lee server.growatt.com vía la lib `growattServer` (PyPI, no oficial pero
estable). Polling cada 30s en thread daemon. Credenciales en
~/.config/streamdeb/growatt.toml (preferido) o plugins/growatt/credentials.toml
(fallback — gitignored).

Layout (página 17, 8×4):
  Fila 0  (0-7):   nav row (compartida)
  Fila 1  (8-15):  PRODUCCIÓN SOLAR (PV)
  Fila 2  (16-23): BATERÍA + RED
  Fila 3  (24-31): CARGA + TOTALES
"""
import os
import time
import threading
import tomllib
from pathlib import Path

from PIL import ImageDraw, ImageFont
from core.config import FONT_PATH
from core.widgets import (
    dibujar_panel_metrica, dibujar_panel_info, dibujar_panel_2lineas,
    dibujar_panel_pings,
    _nuevo_lienzo, con_marco, es_lcars, _lcars_chrome, _lcars_remap,
)

try:
    import growattServer
    GROWATT_DISPONIBLE = True
except ImportError:
    GROWATT_DISPONIBLE = False


# --- Estado live (mutado por tareas_fondo, leído por render) ---
gw_info = {
    "online":     False,    # ¿última poll OK?
    "logged":     False,    # ¿sesión activa?
    "plant_name": "---",
    "plant_id":   None,
    "last_update": 0,       # epoch del último poll OK

    # PV (entrada solar)
    "pv_power":   0.0,      # W ahora
    "pv_today":   0.0,      # kWh hoy
    "pv_total":   0.0,      # kWh acumulado
    "pv1_v":      0.0,
    "pv2_v":      0.0,

    # Batería
    "bat_soc":    None,     # %  (None = sin batería)
    "bat_power":  0.0,      # W (positivo=carga, negativo=descarga)
    "bat_v":      0.0,
    "bat_chg_today": 0.0,   # kWh cargados hoy
    "bat_dis_today": 0.0,   # kWh descargados hoy

    # Red eléctrica
    "grid_power": 0.0,      # W (positivo=import, negativo=export)
    "grid_v":     0.0,
    "grid_hz":    0.0,
    "grid_today_import": 0.0,
    "grid_today_export": 0.0,

    # Consumo (carga)
    "load_power": 0.0,      # W
    "load_today": 0.0,      # kWh

    # Económico (si Growatt lo provee)
    "income_today": 0.0,
    "income_total": 0.0,

    # Estado
    "status":     "---",    # Normal / Fault / Offline
    "error":      None,     # último error si lo hubo
}

# Lock para mutación atómica del dict (varios campos a la vez)
_lock = threading.Lock()

# Event para despertar el thread de polling tras un refresh manual.
_refresh_event = threading.Event()


# --- Credenciales ---

_CREDS_USER_PATH = Path(os.path.expanduser("~/.config/streamdeb/growatt.toml"))
_CREDS_REPO_PATH = Path(__file__).parent / "credentials.toml"


def _load_credentials():
    """Devuelve dict {user, password, plant_id?} o None si no hay credenciales.
    Prueba primero ~/.config (fuera del repo) y luego plugins/growatt/."""
    for p in (_CREDS_USER_PATH, _CREDS_REPO_PATH):
        if not p.exists():
            continue
        try:
            with open(p, "rb") as f:
                data = tomllib.load(f)
            g = data.get("growatt", {})
            if g.get("user") and g.get("password"):
                return {
                    "user": g["user"],
                    "password": g["password"],
                    "plant_id": str(g["plant_id"]) if g.get("plant_id") else None,
                    "source": str(p),
                }
        except Exception as e:
            print(f"[GROWATT] error leyendo {p}: {e}", flush=True)
    return None


# --- API client ---

_api = None
_user_id = None


def _ensure_login(creds):
    """Login lazy; devuelve True si la sesión está lista."""
    global _api, _user_id
    if _api is not None and _user_id is not None:
        return True
    try:
        # UA de browser: el default Dalvik/... lo bloquea Cloudflare (403).
        # server_url al server web real (no openapi, que requiere API key).
        _api = growattServer.GrowattApi(
            agent_identifier="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
        )
        _api.server_url = "https://server.growatt.com/"
        resp = _api.login(creds["user"], creds["password"])
        if not resp or not resp.get("success"):
            msg = (resp or {}).get("error") or (resp or {}).get("msg") or "login failed"
            with _lock:
                gw_info["error"] = f"login: {msg}"
                gw_info["logged"] = False
            print(f"[GROWATT] login rechazado: {msg}", flush=True)
            return False
        _user_id = resp["user"]["id"]
        with _lock:
            gw_info["logged"] = True
            gw_info["error"] = None
        print(f"[GROWATT] login OK userId={_user_id}", flush=True)
        return True
    except Exception as e:
        with _lock:
            gw_info["error"] = f"login: {type(e).__name__}"
            gw_info["logged"] = False
        print(f"[GROWATT] login error: {e}", flush=True)
        _api = None
        _user_id = None
        return False


def _pick_plant(creds):
    """Resuelve plant_id de la cuenta: usa el de creds si lo hay, si no, el primero."""
    plants = _api.plant_list(_user_id)
    # plant_list devuelve dict con 'data' (lista) en versiones recientes.
    rows = plants.get("data", plants) if isinstance(plants, dict) else plants
    if not rows:
        return None, None
    if creds.get("plant_id"):
        for p in rows:
            if str(p.get("plantId")) == creds["plant_id"] or \
               str(p.get("id")) == creds["plant_id"]:
                return p.get("plantId") or p.get("id"), p.get("plantName") or p.get("name")
    first = rows[0]
    return (first.get("plantId") or first.get("id"),
            first.get("plantName") or first.get("name", "Planta"))


def _poll_once(creds):
    """Una pasada: actualiza gw_info in-place. Lanza si hay error de red."""
    global _api, _user_id

    if not _ensure_login(creds):
        return False

    # Resolver planta solo una vez (cacheado en gw_info)
    with _lock:
        plant_id = gw_info["plant_id"]
    if plant_id is None:
        plant_id, plant_name = _pick_plant(creds)
        if plant_id is None:
            with _lock:
                gw_info["error"] = "no plants"
            return False
        with _lock:
            gw_info["plant_id"]   = plant_id
            gw_info["plant_name"] = plant_name or "Planta"

    def _to_float(v, default=0.0):
        if v is None: return default
        try:
            s = str(v).strip().replace(",", "")
            # Growatt mezcla unidades en strings — strip sufijos
            for suf in ("MWh", "kWh", "Wh", "kW", "W", "%", "V", "Hz", "VA"):
                if s.endswith(suf):
                    s = s[:-len(suf)].strip()
            return float(s) if s else default
        except Exception:
            return default

    # 1) plant_list — agregados de la planta (currentPower, todayEnergy, etc.)
    # Re-pedido cada poll porque trae values en vivo de currentPower.
    try:
        pl = _api.plant_list(_user_id)
        plants = pl.get("data", []) if isinstance(pl, dict) else []
        plant_row = next((p for p in plants if str(p.get("plantId")) == str(plant_id)),
                         plants[0] if plants else {})
        total_data = pl.get("totalData", {}) if isinstance(pl, dict) else {}
    except Exception as e:
        plant_row = {}
        total_data = {}
        print(f"[GROWATT] plant_list error: {e}", flush=True)

    # totalEnergy de plant_list viene en MWh→ string; convertimos manualmente
    def _kwh_from(value):
        """Convierte '10.7 MWh' / '450 kWh' / '120 Wh' → kWh float."""
        if value is None: return 0.0
        s = str(value).strip()
        mult = 1.0
        if "MWh" in s: mult = 1000.0
        elif "Wh" in s and "kWh" not in s and "MWh" not in s: mult = 0.001
        return _to_float(s) * mult

    pv_total_plant     = _kwh_from(plant_row.get("totalEnergy"))
    pv_today_plant     = _kwh_from(plant_row.get("todayEnergy"))
    income_total       = _to_float(plant_row.get("plantMoneyText"))
    income_today       = _to_float(total_data.get("eTotalMoneyText"))

    # 2) device_list → SN + tipo
    try:
        devices = _api.device_list(plant_id) or []
    except Exception:
        devices = []

    # Defaults
    bat_soc = None
    bat_power = 0.0
    bat_v = 0.0
    bat_chg_today = 0.0
    bat_dis_today = 0.0
    grid_power = 0.0
    grid_v = 0.0
    grid_hz = 0.0
    load_power = 0.0
    load_today = 0.0
    grid_export_today = 0.0
    grid_import_today = 0.0
    status = "Online"
    pv1_v = 0.0
    pv2_v = 0.0
    pv_power_now = 0.0
    pv_today = pv_today_plant
    pv_total = pv_total_plant

    for dev in devices:
        sn    = dev.get("deviceSn") or dev.get("sn") or dev.get("deviceAilas")
        dtype = (dev.get("deviceType") or dev.get("type") or "").lower()
        if not sn:
            continue
        try:
            if "storage" in dtype:
                # Inversor SPF off-grid. Datos canónicos en storage_params
                # (storageDetailBean) — campos `ppv`, `outPutPower`, `pCharge`
                # son los que la web UI usa para "Current Power" / consumo.
                try:
                    params = _api.storage_params(sn) or {}
                    det = params.get("storageDetailBean", {}) or {}
                except Exception as e:
                    print(f"[GROWATT] storage_params {sn}: {e}", flush=True)
                    det = {}
                # Fallback a storage_detail si params falla
                if not det:
                    try:
                        det = _api.storage_detail(sn) or {}
                    except Exception:
                        det = {}

                pv_power_now = _to_float(det.get("ppv"))            # W reales
                if pv_power_now <= 0:
                    pv_power_now = (_to_float(det.get("ppv1"))
                                    + _to_float(det.get("ppv2")))
                pv1_v = _to_float(det.get("vpv1"))
                pv2_v = _to_float(det.get("vpv2"))
                bat_soc   = _to_float(det.get("capacity"), bat_soc)
                bat_v     = _to_float(det.get("vbat") or det.get("vBat"))
                p_chg     = _to_float(det.get("pCharge") or det.get("pCharge1"))
                p_dis     = _to_float(det.get("pDischarge"))
                bat_power = p_chg - p_dis                            # +carga, -descarga
                load_power = _to_float(det.get("outPutPower")
                                       or det.get("activePower"))   # consumo casa
                # Red: pAcInPut = import; pacToGrid = export
                p_imp = _to_float(det.get("pAcInPut"))
                p_exp = _to_float(det.get("pacToGrid"))
                grid_power = p_imp - p_exp
                grid_v    = _to_float(det.get("vGrid"))
                grid_hz   = _to_float(det.get("freqGrid"))
                pv_today  = _to_float(det.get("epvToday"), pv_today)
                pv_total  = _to_float(det.get("epvTotal"), pv_total)
                bat_chg_today = _to_float(det.get("eBatChargeToday")
                                          or det.get("eChargeToday"))
                bat_dis_today = _to_float(det.get("eBatDisChargeToday")
                                          or det.get("eDischargeToday"))

                # Overview: import/export/consumo hoy (acumulados)
                try:
                    ov = _api.storage_energy_overview(plant_id, sn)
                    grid_export_today = _to_float(ov.get("eToGridToday"))
                    grid_import_today = _to_float(ov.get("eToUserToday"))
                    load_today        = _to_float(ov.get("useEnergyToday"))
                except Exception as e:
                    print(f"[GROWATT] energy_overview {sn}: {e}", flush=True)

            elif "mix" in dtype:
                info = _api.mix_system_status(sn, plant_id)
                bat_soc      = _to_float(info.get("SOC"), bat_soc)
                pv_power_now = _to_float(info.get("pPv1")) + _to_float(info.get("pPv2"))
                bat_power    = _to_float(info.get("chargePower")) - _to_float(info.get("disChargePower"))
                grid_power   = _to_float(info.get("pactogrid"))
                load_power   = _to_float(info.get("pLocalLoad"))
                pv1_v        = _to_float(info.get("vPv1"))
                pv2_v        = _to_float(info.get("vPv2"))

            elif "tlx" in dtype or "min" in dtype:
                info = _api.tlx_system_status(sn, plant_id)
                bat_soc      = _to_float(info.get("SOC"), bat_soc)
                bat_power    = _to_float(info.get("chargePower")) - _to_float(info.get("disChargePower"))
                pv1_v        = _to_float(info.get("vPv1"))
                pv2_v        = _to_float(info.get("vPv2"))

            else:
                info = _api.inverter_detail(sn)
                pv1_v = _to_float(info.get("vpv1"))
                pv2_v = _to_float(info.get("vpv2"))

        except Exception as e:
            print(f"[GROWATT] device {sn} ({dtype}) error: {e}", flush=True)

    # Fallback: si no extrajimos pv_power_now del device, usar plant.currentPower
    if pv_power_now <= 0:
        pv_power_now = _to_float(plant_row.get("currentPower"))

    with _lock:
        gw_info["online"]     = True
        gw_info["last_update"] = time.time()
        gw_info["error"]      = None
        gw_info["pv_power"]   = pv_power_now
        gw_info["pv_today"]   = pv_today
        gw_info["pv_total"]   = pv_total
        gw_info["pv1_v"]      = pv1_v
        gw_info["pv2_v"]      = pv2_v
        gw_info["bat_soc"]    = bat_soc
        gw_info["bat_power"]  = bat_power
        gw_info["bat_v"]      = bat_v
        gw_info["bat_chg_today"] = bat_chg_today
        gw_info["bat_dis_today"] = bat_dis_today
        gw_info["grid_power"] = grid_power
        gw_info["grid_v"]     = grid_v
        gw_info["grid_hz"]    = grid_hz
        gw_info["grid_today_import"] = grid_import_today
        gw_info["grid_today_export"] = grid_export_today
        gw_info["load_power"] = load_power
        gw_info["load_today"] = load_today
        gw_info["income_today"] = income_today
        gw_info["income_total"] = income_total
        gw_info["status"]     = status
    return True


def tareas_fondo():
    """Thread daemon: poll Growatt cada 30s. Auto-relogin tras fallo prolongado."""
    if not GROWATT_DISPONIBLE:
        print("[GROWATT] lib growattServer no instalada — plugin inactivo", flush=True)
        with _lock:
            gw_info["error"] = "growattServer not installed"
        return
    creds = _load_credentials()
    if creds is None:
        print("[GROWATT] sin credenciales — crea ~/.config/streamdeb/growatt.toml", flush=True)
        with _lock:
            gw_info["error"] = "no credentials"
        return
    print(f"[GROWATT] credenciales OK ({creds['source']})", flush=True)

    fallos = 0
    while True:
        try:
            ok = _poll_once(creds)
            if ok:
                fallos = 0
            else:
                fallos += 1
        except Exception as e:
            fallos += 1
            with _lock:
                gw_info["online"] = False
                gw_info["error"]  = f"{type(e).__name__}: {e}"
            print(f"[GROWATT] poll error #{fallos}: {e}", flush=True)
            # Tras 3 fallos seguidos, fuerza re-login.
            if fallos >= 3:
                global _api, _user_id
                _api = None
                _user_id = None
                with _lock:
                    gw_info["logged"] = False

        # Espera 30s o hasta refresh manual
        _refresh_event.wait(timeout=30)
        _refresh_event.clear()


# --- Render página GROWATT (17) ---

def _fmt_power(w):
    """Formatea W → '1.23 kW' o '450 W' según magnitud."""
    if w is None: return "---"
    w = abs(w)
    if w >= 1000:
        return f"{w/1000:.2f} kW"
    return f"{int(w)} W"


def _fmt_energy(kwh):
    if kwh is None: return "---"
    if kwh >= 1000:
        return f"{kwh/1000:.1f} MWh"
    return f"{kwh:.1f} kWh"


def _fmt_age(ts):
    if not ts: return "---"
    age = int(time.time() - ts)
    if age < 60: return f"{age}s"
    if age < 3600: return f"{age//60}m"
    return f"{age//3600}h"


def render_pagina_growatt(deck, tam, nav_imgs):
    """Renderiza la página GROWATT. nav_imgs ya trae botones de fila 0."""
    with _lock:
        info = dict(gw_info)

    online = info["online"]
    err    = info.get("error")

    # Colores semánticos
    yellow  = "#ffcc00"   # sol / PV
    green   = "#33ff33"   # batería OK / export
    red     = "#ff3333"   # offline / fault / import alto
    cyan    = "#00ddff"   # red / load
    grey    = "#666666"

    # PV color: amarillo si produce, gris si no
    pv_color = yellow if info["pv_power"] > 10 else grey
    # Batería: verde si SOC>50, amarillo 20-50, rojo <20, gris si sin batería
    soc = info["bat_soc"]
    if soc is None:
        bat_color = grey
    elif soc >= 50:
        bat_color = green
    elif soc >= 20:
        bat_color = yellow
    else:
        bat_color = red
    # Red: verde si exportamos (grid_power<0), cyan neutral, rojo si importamos mucho
    gp = info["grid_power"]
    if gp < -50:    grid_color = green
    elif gp > 500:  grid_color = red
    elif gp > 50:   grid_color = yellow
    else:           grid_color = cyan

    imgs = dict(nav_imgs)

    if not online and err:
        # Banner de error en mitad de la pantalla
        imgs[12] = dibujar_panel_2lineas(deck, tam, "ERROR", err[:24], red)
        imgs[19] = dibujar_panel_info(deck, tam, "Reintento", "30s", grey)
        imgs[20] = dibujar_panel_info(deck, tam, "Refresh", "↻ Tap", cyan)
        imgs[28] = dibujar_panel_info(deck, tam, "Planta", info["plant_name"][:8], grey)
        return imgs

    # --- Fila 1: POTENCIAS EN VIVO (panel principal Growatt) ---
    # Replica los 3 valores que muestra el dashboard web en grande:
    # PV ahora · Consumo ahora · Cargando batería ahora.
    pv_w   = info["pv_power"]
    load_w = info["load_power"]
    bat_w  = info["bat_power"]  # +carga, -descarga

    # Escala 0..100% basada en 5kW (capacidad Pmax del inversor)
    PMAX = 5000.0
    pv_pct   = min(100, int(pv_w   * 100 / PMAX)) if pv_w   > 0 else 0
    load_pct = min(100, int(load_w * 100 / PMAX)) if load_w > 0 else 0

    imgs[8]  = dibujar_panel_metrica(deck, tam, "PV",
                                      _fmt_power(pv_w), pv_color, pct=pv_pct)
    imgs[9]  = dibujar_panel_metrica(deck, tam, "Consumo",
                                      _fmt_power(load_w), cyan, pct=load_pct)
    if bat_w >= 0:
        # Cargando — verde si batería SOC ≥50, amarillo si menor
        chg_color = green if (soc is not None and soc >= 50) else yellow
        chg_pct   = min(100, int(bat_w * 100 / PMAX)) if bat_w > 0 else 0
        imgs[10] = dibujar_panel_metrica(deck, tam, "Cargando",
                                          _fmt_power(bat_w), chg_color, pct=chg_pct)
    else:
        # Descargando — naranja/rojo, magnitud absoluta
        imgs[10] = dibujar_panel_metrica(deck, tam, "Descarga",
                                          _fmt_power(bat_w), "#ff9933",
                                          pct=min(100, int(abs(bat_w)*100/PMAX)))

    imgs[11] = dibujar_panel_info(deck, tam, "PV Hoy",  _fmt_energy(info["pv_today"]), yellow)
    imgs[12] = dibujar_panel_info(deck, tam, "PV Total", _fmt_energy(info["pv_total"]), yellow)
    imgs[13] = dibujar_panel_info(deck, tam, "Estado",   info["status"][:6],
                                   green if info["status"].lower() == "online" else grey)
    imgs[14] = dibujar_panel_info(deck, tam, "Update",   _fmt_age(info["last_update"]), cyan)
    imgs[15] = dibujar_panel_info(deck, tam, "Refresh",  "Tap", cyan)

    # --- Fila 2: BATERÍA + RED ---
    if soc is not None:
        imgs[16] = dibujar_panel_metrica(deck, tam, "BAT SOC", f"{soc:.0f}%",
                                          bat_color, pct=int(soc))
        bp = info["bat_power"]
        if bp > 5:
            bat_flow_txt, bat_flow_col = f"+{_fmt_power(bp)}", green   # cargando
        elif bp < -5:
            bat_flow_txt, bat_flow_col = f"-{_fmt_power(bp)}", yellow  # descargando
        else:
            bat_flow_txt, bat_flow_col = "Idle", grey
        imgs[17] = dibujar_panel_info(deck, tam, "Bat Flow", bat_flow_txt, bat_flow_col)
        imgs[18] = dibujar_panel_info(deck, tam, "Bat V",
                                       f"{info['bat_v']:.1f}V" if info['bat_v'] else "---",
                                       bat_color)
    else:
        imgs[16] = dibujar_panel_info(deck, tam, "BAT",  "N/D", grey)
        imgs[17] = dibujar_panel_info(deck, tam, "Flow", "---", grey)
        imgs[18] = dibujar_panel_info(deck, tam, "Bat",  "---", grey)

    if gp < -5:
        grid_lbl = f"-{_fmt_power(gp)}"   # exportando
    elif gp > 5:
        grid_lbl = f"+{_fmt_power(gp)}"   # importando
    else:
        grid_lbl = "0 W"
    # Para storage off-grid: V/Hz de red son más informativos que grid_power.
    grid_v  = info.get("grid_v", 0)
    grid_hz = info.get("grid_hz", 0)
    if grid_v > 50:
        imgs[19] = dibujar_panel_metrica(deck, tam, "RED V", f"{grid_v:.0f}V",
                                          green if 190 < grid_v < 250 else red)
    else:
        imgs[19] = dibujar_panel_info(deck, tam, "RED",  "OFF", grey)
    imgs[20] = dibujar_panel_info(deck, tam, "RED Hz",  f"{grid_hz:.1f}",
                                   green if 49 < grid_hz < 61 else grey)
    imgs[21] = dibujar_panel_info(deck, tam, "Imp Hoy", _fmt_energy(info["grid_today_import"]), red)
    imgs[22] = dibujar_panel_info(deck, tam, "Exp Hoy", _fmt_energy(info["grid_today_export"]), green)
    # Slot 23: flujo de red en W (import/export en tiempo real)
    gp_w = info["grid_power"]
    if gp_w > 50:
        imgs[23] = dibujar_panel_info(deck, tam, "RED W", f"+{_fmt_power(gp_w)}", red)
    elif gp_w < -50:
        imgs[23] = dibujar_panel_info(deck, tam, "RED W", f"-{_fmt_power(gp_w)}", green)
    else:
        imgs[23] = dibujar_panel_info(deck, tam, "RED W", "0", grey)

    # --- Fila 3: ENERGÍAS HOY + RESUMEN ---
    # Slot 24: descarga acumulada hoy (contraparte a "Carga Hoy" en kWh)
    imgs[24] = dibujar_panel_info(deck, tam, "Desc Hoy",
                                   _fmt_energy(info.get("bat_dis_today", 0)), yellow)
    imgs[25] = dibujar_panel_info(deck, tam, "Carga Hoy", _fmt_energy(info["load_today"]), cyan)

    # Auto-consumo: % del consumo que viene del PV+batería (no de red)
    if info["load_power"] > 0:
        from_grid = max(0, info["grid_power"])
        self_use = max(0, min(100, 100 * (1 - from_grid / max(info["load_power"], 1))))
        imgs[26] = dibujar_panel_metrica(deck, tam, "Self %", f"{self_use:.0f}%",
                                          green if self_use > 70 else yellow,
                                          pct=int(self_use))
    else:
        imgs[26] = dibujar_panel_info(deck, tam, "Self %", "---", grey)

    imgs[27] = dibujar_panel_info(deck, tam, "$ Total",
                                   f"{info['income_total']:.0f}", green)
    imgs[28] = dibujar_panel_2lineas(deck, tam, "Planta",
                                      str(info["plant_name"])[:16], yellow)
    imgs[29] = dibujar_panel_info(deck, tam, "Logged",
                                   "OK" if info["logged"] else "OFF",
                                   green if info["logged"] else red)
    imgs[30] = dibujar_panel_info(deck, tam, "Lib",
                                   "OK" if GROWATT_DISPONIBLE else "MISS",
                                   green if GROWATT_DISPONIBLE else red)
    imgs[31] = dibujar_panel_info(deck, tam, "Refresh", "↻ Tap", cyan)

    return imgs


TECLA_SIS = 11  # Entry tile en SIS (fila 2, slot 4) → abre página GROWATT


def _fmt_w(w):
    """Compacto para tile chico: '904W' o '2.1k'."""
    w = abs(w)
    if w >= 1000:
        return f"{w/1000:.1f}k"
    return f"{int(w)}W"


def _fuente_actual(info):
    """Determina de dónde sale la energía que consume la casa AHORA.
    Devuelve (label, color).
       - SOL: el PV cubre todo el consumo
       - BAT: la batería está descargando hacia la casa
       - RED: importamos de la red
       - MIX: combinación (PV+algo más)
       - OFF: consumo ~0
    """
    pv   = info.get("pv_power", 0) or 0
    load = info.get("load_power", 0) or 0
    bat  = info.get("bat_power", 0) or 0   # +carga -descarga
    grid = info.get("grid_power", 0) or 0  # +import -export

    if load < 20:
        return "OFF", "#666666"
    # PV cubre todo el consumo (con margen 50W)
    if pv >= load - 50:
        return "SOL", "#ffcc00"
    # Importando de la red (>100W del consumo viene de red)
    if grid > 100:
        # Si además batería descarga, es mix
        if bat < -50:
            return "MIX", "#ff9933"
        return "RED", "#ff3333"
    # Descargando batería sin red
    if bat < -50:
        return "BAT", "#33aaff"
    # PV parcial + batería estable
    if pv > 50:
        return "MIX", "#ff9933"
    return "BAT", "#33aaff"


def _fmt_w_compact(w):
    """Formato ultra-compacto para encima de barras chicas.
    '904'(W) o '2.1' (kW). Sin sufijo — el unit-context se infiere del header."""
    w = abs(w)
    if w >= 1000:
        return f"{w/1000:.1f}"
    if w >= 100:
        return f"{int(w)}"
    if w >= 10:
        return f"{int(w)}"
    return f"{w:.0f}"


def _panel_pv_barras(deck, tam, items, frame_color):
    """4 barras verticales con header + valor W encima + label abajo.
    Auto-escala: la barra más alta = max, las demás proporcionales.
    Mismo chrome (marco/título/separador) que dibujar_panel_pings.

    items: lista [(label, valor_w, color, extra), ...]
       `extra` (opcional): (valor_w, color) — segmento apilado ENCIMA.
       Usado para mostrar carga batería apilada sobre USO.
    """
    img = _nuevo_lienzo(tam)
    d   = ImageDraw.Draw(img)
    W, H = tam

    # Header siguiendo el patrón estándar
    if es_lcars():
        frame_color, _ = _lcars_chrome(d, tam, "PV", frame_color, stem=False)
    else:
        if con_marco():
            d.rounded_rectangle((4, 4, W-5, H-5), radius=10,
                                 outline=frame_color, width=2)
        f_tit = ImageFont.truetype(FONT_PATH, 13)
        d.text((W//2, 15), "PV", font=f_tit, fill=frame_color, anchor="mm")
        d.line((10, 27, W-11, 27), fill=frame_color, width=1)

    # Auto-escala: el max actual (incluyendo extras apilados) = 100%
    def _total(item):
        v = item[1]
        if len(item) >= 4 and item[3]:
            v += item[3][0]
        return v
    max_v = max((_total(it) for it in items), default=0)
    if max_v < 1:
        max_v = 1

    n = len(items)
    pad_x = 7
    gap   = 3
    slot_w = (W - 2*pad_x - gap*(n-1)) // n
    bar_w  = int(slot_w * 0.9)       # 10% más angostas
    bar_off = (slot_w - bar_w) // 2  # centra la barra en su slot

    val_y   = 35
    bar_top = 44
    bar_bot = H - 13
    lbl_y   = H - 6
    bar_h   = bar_bot - bar_top

    f_val = ImageFont.truetype(FONT_PATH, 9)
    f_lbl = ImageFont.truetype(FONT_PATH, 9)

    for i, it in enumerate(items):
        lbl, v, color = it[0], it[1], it[2]
        extra = it[3] if len(it) >= 4 else None

        x = pad_x + i * (slot_w + gap) + bar_off
        # Valor encima — base + extra apilado si lo hay
        v_txt = _fmt_w_compact(v)
        if extra and extra[0] > 0:
            # "USO+CHG": muestra ambos compactamente
            v_txt = f"{_fmt_w_compact(v)}+{_fmt_w_compact(extra[0])}"
            v_txt = _fmt_w_compact(v)  # demasiado ancho — vuelve al simple
        d.text((x + bar_w//2, val_y), v_txt,
                font=f_val, fill="white", anchor="mm")
        # Caja
        d.rectangle((x, bar_top, x+bar_w, bar_bot),
                    outline="#333333", fill="#111111")
        # Segmento base
        base_h = int(bar_h * v / max_v)
        base_y = bar_bot - base_h
        if base_h > 0:
            d.rectangle((x, base_y, x+bar_w, bar_bot), fill=color)
        # Segmento apilado encima
        if extra and extra[0] > 0:
            ex_v, ex_col = extra
            ex_h = int(bar_h * ex_v / max_v)
            if ex_h > 0:
                top_y = max(bar_top, base_y - ex_h)
                d.rectangle((x, top_y, x+bar_w, base_y), fill=ex_col)
        # Label abajo
        d.text((x + bar_w//2, lbl_y), lbl,
                font=f_lbl, fill="#aaaaaa", anchor="mm")
    return img


def widget_para_sistema(deck, tam):
    """Tile entry en SIS (tecla 11). Tap → abre página GROWATT.

    4 barras verticales: PV, BAT (aporte), RED (aporte), USO.
    Auto-escala (max actual = 100%). Valor W encima de cada barra.
    Color del marco = fuente actual de la energía.
    """
    with _lock:
        info = dict(gw_info)
    grey = "#666666"

    if not info["online"]:
        return {TECLA_SIS: dibujar_panel_info(deck, tam, "PV", "off", grey)}

    pv   = info["pv_power"]   or 0
    load = info["load_power"] or 0
    bat  = info["bat_power"]  or 0
    grid = info["grid_power"] or 0

    # "Aporte" = lo que cada fuente entrega a la casa (solo positivos)
    bat_aporte  = max(0.0, -bat)
    grid_aporte = max(0.0,  grid)

    # Carga batería apilada ENCIMA del USO: el excedente solar que va a la
    # batería completa visualmente la barra hasta que matchea la altura PV.
    bat_carga = max(0.0, bat)   # +carga, 0 si descarga
    items = [
        ("PV",  pv,          "#ffcc00"),
        ("BAT", bat_aporte,  "#33aaff"),
        ("RED", grid_aporte, "#ff3333"),
        ("USO", load,        "#00ddff", (bat_carga, "#cc66ff")),  # violeta carga
    ]
    _, frame_col = _fuente_actual(info)
    return {TECLA_SIS: _panel_pv_barras(deck, tam, items, frame_col)}


def on_press(tecla):
    """Handler. Tecla 15 o 31 → refresh manual."""
    if tecla in (15, 31):
        _refresh_event.set()
        print("[GROWATT] refresh manual", flush=True)
        return True
    return False
