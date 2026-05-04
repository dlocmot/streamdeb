# streamdeb — Stream Deck dashboards

Dos aplicaciones independientes para Elgato Stream Deck XL, ambas en
Python sobre Debian:

| App                  | Host                     | Servicio              | Propósito                              |
|----------------------|--------------------------|-----------------------|----------------------------------------|
| `dashboard_pro.py`   | PC `dinamo` (Debian)     | `streamdeb` (--user)  | Dashboard general (5 páginas)          |
| `awa_kiosk.py`       | Raspberry Pi 3 headless  | `awa-kiosk` (system)  | Panel dedicado AWAhorro (página única) |

Ambas hablan con el ESP32 **AWAhorro Base** en `192.168.18.10` (control
de válvula de agua). API documentado en [`API.md`](API.md).

> `main.py` es el scaffold original del repositorio, no se usa.

---

## 1) `dashboard_pro.py` — dashboard PC

Stream Deck XL (32 teclas · 4 filas × 8 columnas · 96×96 px). Servicio
`systemd --user` que arranca con la sesión gráfica del usuario `jfqp`.

### Layout — 5 páginas + nav común

Fila 0 (visible en todas las páginas):

| Tecla | Botón | Función                                                   |
|-------|-------|-----------------------------------------------------------|
| 0     | SIS   | Página 1 — sistema                                        |
| 1     | AWA   | Página 2 — control AWAhorro                               |
| 2     | MEDIA | Página 3 — multimedia                                     |
| 3     | APP   | Página 4 — lanzador de aplicaciones                       |
| 7     | CONF  | Página 5 — configuración (engranaje)                      |

> La X roja antigua (apagar / dim manual) ya no vive en fila 0; ahora
> está dentro de la página CONF (tecla 31).

#### Página SIS (default)

```
Fila 1:  Uptime  CPU T   C1   C2   C3   C4   RO123    .
Fila 2:  RAM     SWAP    DISK  .    .    .    .       .
Fila 3:  DOWN    UP      Pub.  Local Gw  1.1.1.1 8.8.8.8 .
```

- `RO123` (tecla 14): tipea password de root vía `pynput`.

#### Página AWA

```
Fila 1: Estado  Cuenta  Modo  Aper.  WiFi  Tank  Usuario  Admin
Fila 2: 1MIN    2MIN    3MIN  4MIN   5MIN   .    .        Ping API
Fila 3: 15MIN   30MIN   1HORA 2HORAS  .     .    .        CERRAR
```

- Estado: fondo verde si Abierta · recuadro rojo si Cerrada · gris si OFFLINE.
- Botones de tiempo: efecto de **vaciado de vaso** (cyan que decrece) en
  el botón cuya duración coincide con `initial_seconds` del API.
- `CERRAR` (tecla 31): rojo, envía `{"action":"close"}`.

#### Página MEDIA

```
Fila 1:   .   .   .   .   .   .   .   VOL+
Fila 2:   .   .   .   .   .   .  PLAY  MUTE
Fila 3:   .   .   .   .   .   .   .   VOL-
```

- VOL+/MUTE/VOL− vertical en última columna (15, 23, 31), PLAY tecla 22.
- Comandos: `pactl set-sink-volume`, `pactl set-sink-mute`, `playerctl play-pause`.

#### Página APP — lanzador

Iconos PNG del tema del sistema (hicolor / mate / gnome). Apps actuales
en `APPS_PAGINA` (`dashboard_pro.py:93`):

- Dev: Term, Arduino, GitHub Desktop
- Web: Brave, Firefox (firejail)
- 3D: PrusaSlicer
- Media: OBS, VLC
- Sec: Burp Suite
- Net: Winbox (wine)
- Util: AnyDesk, SysMon, VirtualBox

#### Página CONF — configuración en vivo

Ajustes editables sin reiniciar el servicio:

- **Brillo** (col 0): +, valor actual %, − (paso 10%, mín 10, máx 100).
- **Fallback a SIS** (col 1): segundos sin interacción antes de volver
  a SIS. Rango 60s – 30min, paso 1 min.
- **Auto-dim** (col 2): segundos sin interacción antes de apagar
  pantalla. Rango 60s – 2h, paso 1 min.
- **Perfil Kiosko** (tecla 15, debajo del gear): cambia al servicio
  `streamdeb-kiosk` (ver sección Perfil switch abajo).
- **X de apagado** (tecla 31, dim manual).

### Comportamientos transversales

- **Auto-fallback a SIS** y **auto-dim** según valores configurados en
  CONF (no más constantes hardcoded).
- **Reconexión**: si el deck se desconecta, reintenta cada 2 s y restaura
  estado al reconectar.
- **Tema horario**: claro 05:30–22:00, oscuro el resto (override desde CONF).

### Setup

```bash
sudo apt install python3-venv libhidapi-hidraw0 libhidapi-libusb0
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt psutil pynput

sudo cp udev/50-streamdeck.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules && sudo udevadm trigger
# desconecta y reconecta el deck

systemctl --user daemon-reload
systemctl --user enable --now streamdeb.service

# opcional: que siga corriendo sin sesión gráfica
sudo loginctl enable-linger jfqp
```

### Operación

```bash
systemctl --user status  streamdeb
systemctl --user restart streamdeb       # tras editar dashboard_pro.py
journalctl --user -u streamdeb -f
```

### Perfil switch (main ↔ kiosko en dinamo)

En dinamo el deck puede correr `awa_kiosk.py` como perfil temporal
sin necesidad de la Pi:

- Servicio paralelo `streamdeb-kiosk.service` en
  `~/.config/systemd/user/` (versionado en `systemd/`).
- Helper `bin/switch-profile.sh {main|kiosk}` que hace el swap atómico:
  lanza el `start` del nuevo servicio como **transient unit**
  (`systemd-run --user`) para que sobreviva al `stop` del actual
  (cuyo cgroup-kill mata todo). Espera 1.5s antes del start para que
  el deck USB se libere.
- Botón en CONF de cada app:
  - main: tecla **15** "Perfil Kiosko" (col 7 fila 1, debajo del gear).
  - kiosko: tecla **11** "Perfil Main" (sólo aparece si existe el
    helper, así no se renderiza en la Pi).
- Ambas apps atrapan SIGTERM para cerrar el deck limpio en `finally`.

Setup del servicio kiosko en dinamo:
```bash
cp systemd/streamdeb-kiosk.service ~/.config/systemd/user/
systemctl --user daemon-reload
# no se hace `enable` — sólo se lanza vía el botón
```

---

## 2) `awa_kiosk.py` — kiosko Raspberry Pi

Stream Deck XL en **Raspberry Pi 3 headless**. La Pi no tiene monitor;
el deck es la única interfaz. Dedicado a control de AWAhorro.

- OS: Raspberry Pi OS Lite 64-bit (Debian 13 trixie).
- Hostname: `awa`. Usuario: `jfqp` (en grupo `plugdev`).
- Servicio **system** (no user): `/etc/systemd/system/awa-kiosk.service`.
- Código en `/opt/streamdeb/`, venv en `/opt/streamdeb/.venv/`.

### Layout (página única + CONF)

```
Página AWA (default):
  Fila 0:  Ext   Ambas Tanque Inten Mix   Eco   Ráp   Pre        ← modos + lavaplatos
  Fila 1:  Estado Cuenta Modo  Aper. WiFi  Tank  Usuario Admin   ← estado API
  Fila 2:  1MIN  2MIN  3MIN  4MIN  5MIN   .     .     PingAPI
  Fila 3:  15MIN 30MIN 1HORA 2HORAS .     .    CONF    CERRAR

Página CONF:
  Fila 1:  Brillo+ Dim+  .    [Main]  .    .    .    Tema diurno
  Fila 2:  Brillo% Dim%  .    .       .    .    .    .
  Fila 3:  Brillo− Dim−  .    .       .    .    AWA  X (apagado)
```

`[Main]` (tecla 11) sólo se renderiza en dinamo (vuelve al perfil
main). En la Pi no aparece.

**Comportamientos:**

- **Brillo** y **Dim** funcionan en ambos temas (claro/oscuro).
- **Auto-redim 2s en dark**: tras pulsar apertura o CERRAR en tema
  oscuro, el deck atenúa a 0 al cabo de 2s (kiosko silencioso de
  noche). Cualquier toque despierta.
- **Ping al deck durante dim**: cada 1s un `set_brightness(0)`
  ping para detectar desconexiones USB sin notar.
- **CERRAR drained**: en light, sólo outline cuando ya está cerrada;
  rojo sólido cuando hay apertura activa. En dark, gris tenue cuando
  cerrada, rojo cuando abierta.

### Configuración (env vars en el .service)

```
STREAMDEB_API_HOST   (default http://192.168.18.10)
STREAMDEB_API_USER   (default Kiosko)
STREAMDEB_BRILLO     (default 75)
STREAMDEB_DIM        (default 1800)
```

### Aviso de hardware

La Stream Deck XL consume ~500 mA por USB. La Pi 3 con fuente débil
genera **subvoltaje** (visible como `Undervoltage detected!` en
`dmesg`) y el deck se re-enumera en bucle. Soluciones:

1. Fuente oficial Pi 5V 2.5A (o 5.1V 3A).
2. Hub USB con alimentación propia entre Pi y deck (recomendado).

### Provisión de la Pi (rápida, desde dinamo)

```bash
# 1) instalar deps
ssh jfqp@<pi> 'sudo apt install -y python3-venv libhidapi-libusb0 \
    libusb-1.0-0 libjpeg-dev zlib1g-dev libfreetype-dev rsync tzdata'

# 2) sincronizar repo a /opt/streamdeb
ssh jfqp@<pi> 'sudo mkdir -p /opt/streamdeb && sudo chown jfqp:jfqp /opt/streamdeb'
rsync -az --exclude='.venv' --exclude='.git' --exclude='__pycache__' \
    ./ jfqp@<pi>:/opt/streamdeb/

# 3) venv + deps Python
ssh jfqp@<pi> 'cd /opt/streamdeb && python3 -m venv .venv && \
    .venv/bin/pip install -r requirements.txt'

# 4) udev + servicio (en awa-kiosk.service usar User=jfqp)
ssh jfqp@<pi> 'sudo cp /opt/streamdeb/udev/50-streamdeck.rules /etc/udev/rules.d/ && \
    sudo udevadm control --reload-rules && sudo udevadm trigger'
ssh jfqp@<pi> 'sudo cp /opt/streamdeb/systemd/awa-kiosk.service /etc/systemd/system/ && \
    sudo systemctl daemon-reload && sudo systemctl enable --now awa-kiosk'
```

### Operación

```bash
ssh jfqp@<pi> 'sudo journalctl -u awa-kiosk -f'
ssh jfqp@<pi> 'sudo systemctl restart awa-kiosk'
```

---

## Estructura

```
streamdeb/
├── dashboard_pro.py                 # app PC dinamo (5 páginas)
├── awa_kiosk.py                     # app kiosko (Pi y perfil dinamo)
├── main.py                          # scaffold original (no usado)
├── API.md                           # API ESP32 AWAhorro
├── requirements.txt                 # streamdeck, Pillow
├── bin/switch-profile.sh            # swap main↔kiosko en dinamo
├── udev/50-streamdeck.rules         # acceso USB sin root (plugdev)
├── systemd/awa-kiosk.service        # servicio system para la Pi
├── systemd/streamdeb-kiosk.service  # servicio user kiosko en dinamo
└── .venv/                           # virtualenv local (solo dinamo)
```

## License

MIT
