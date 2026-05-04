# AWAhorro — API HTTP del ESP32 Base

Documento de referencia de los endpoints HTTP expuestos por el firmware de
`AWAhorro_Base`. Pensado para integraciones externas (apps móviles, Home
Assistant, Node-RED, otro microcontrolador, etc.).

- **Host:** IP del ESP32 Base en la red local (visible por DHCP / mDNS).
- **Auth:** ninguna (red local). Cualquier petición a `/api/comando` activa el
  flag `adminLock` que bloquea la UI del cliente hasta que un admin la libere.
- **Encoding:** UTF-8.

---

## `POST /api/comando`

Endpoint principal de control. Body **JSON** obligatorio.

`Content-Type: application/json`

Todos los `action` (excepto `estado`) activan `g_adminLock`.

### 1. Abrir válvula N minutos

Rango válido: **1 – 120** minutos (máx 2h por seguridad).

**Request**
```json
{"action":"open","minutes":5,"user":"API"}
```

**Response 200**
```json
{"ok":true,"estado":"Abierta","minutos":5}
```

**Errores**
```json
{"ok":false,"error":"minutes 1-120 (max 2h)"}
```

---

### 2. Cerrar y cancelar secuencia

**Request**
```json
{"action":"close"}
```

**Response 200**
```json
{"ok":true,"estado":"Cerrada"}
```

---

### 3. Cambiar fuente de agua

`mode`: `1` = Externa · `2` = Ambas · `3` = Tanque

**Request**
```json
{"action":"mode","mode":2}
```

**Response 200**
```json
{"ok":true,"modo":2}
```

**Errores**
```json
{"ok":false,"error":"mode 1-3"}
```

---

### 4. Programa lavaplatos

`program`: `intensivo` · `mix` · `eco` · `rapido` · `prelavado`

| Programa  | Ventanas | Duración | Descripción     |
|-----------|----------|----------|-----------------|
| intensivo | 2        | 7800 s   | Intensivo 70 °C |
| mix       | 2        | 6000 s   | Mix 65 °C       |
| eco       | 2        | 12600 s  | Eco 50 °C       |
| rapido    | 2        | 3600 s   | Rápido 1h 65 °C |
| prelavado | 1        | 480 s    | Prelavado       |

**Request**
```json
{"action":"sequence","program":"intensivo"}
```

**Response 200**
```json
{"ok":true,"programa":"intensivo"}
```

**Errores**
```json
{"ok":false,"error":"programa desconocido"}
```

---

### 5. Estado actual

**Request**
```json
{"action":"estado"}
```

**Response 200** — mismo payload que `GET /estado` (ver abajo).

---

### Errores comunes de `/api/comando`

| HTTP | Body                                                           |
|------|----------------------------------------------------------------|
| 400  | `{"ok":false,"error":"body JSON requerido"}`                   |
| 400  | `{"ok":false,"error":"JSON invalido"}`                         |
| 400  | `{"ok":false,"error":"action desconocida"}`                    |

---

## `GET /estado`

Snapshot completo del sistema. `Content-Type: application/json`.

**Response 200**
```json
{
  "estado": "Cerrada",
  "contador": 12,
  "acumuladoA": "00:15:30",
  "acumuladoC": "10:42:11",
  "tiempoTotal": "10:57:41",
  "hora": "14:23:05",
  "usuario": "ADMJimmy (5min-API)",
  "cuenta": "00:04:32",
  "segundos": 272,
  "initial_seconds": 300,
  "admin": false,
  "modo": 2,
  "modoNombre": "Ambas",
  "tanqueAbierto": false,
  "tanqueListo": true,
  "wifiSSID": "MiRed",
  "wifiRSSI": -62,
  "wifiSignal": 3,
  "tankOnline": true,
  "tankRSSI": -55,
  "tankSignal": 4,
  "tankLastSeen": 2,
  "seqActive": false,
  "seqWindow": 1,
  "seqTotal": 0,
  "seqProgName": "",
  "seqElapsedSec": 0,
  "seqTotalSec": 0,
  "adminLocked": false
}
```

### Diccionario de campos

| Campo             | Tipo     | Descripción                                                |
|-------------------|----------|------------------------------------------------------------|
| `estado`          | string   | `"Abierta"` / `"Cerrada"`                                  |
| `contador`        | int      | Nº de aperturas desde boot                                 |
| `acumuladoA`      | string   | Tiempo total abierta `HH:MM:SS`                            |
| `acumuladoC`      | string   | Tiempo total cerrada `HH:MM:SS`                            |
| `tiempoTotal`     | string   | Tiempo total monitorizado                                  |
| `hora`            | string   | Hora local actual `HH:MM:SS`                               |
| `usuario`         | string   | Último usuario y acción: `"ADMJimmy (5min-API)"`           |
| `cuenta`          | string   | Si abierta: tiempo transcurrido. Si cerrada: countdown     |
| `segundos`        | int      | Countdown en segundos                                      |
| `initial_seconds` | int      | Valor inicial del countdown                                |
| `admin`           | bool     | Sesión admin activa                                        |
| `modo`            | int      | `1`=Ext · `2`=Ambas · `3`=Tanque                           |
| `modoNombre`      | string   | Nombre legible del modo                                    |
| `tanqueAbierto`   | bool     | Válvula del tanque abierta                                 |
| `tanqueListo`     | bool     | Tanque listo para usarse                                   |
| `wifiSSID`        | string   | SSID al que está conectado el Base                         |
| `wifiRSSI`        | int      | RSSI WiFi en dBm                                           |
| `wifiSignal`      | int      | Barras 0–4                                                 |
| `tankOnline`      | bool     | Tanque visible vía ESP-NOW                                 |
| `tankRSSI`        | int      | RSSI ESP-NOW del tanque                                    |
| `tankSignal`      | int      | Barras 0–4                                                 |
| `tankLastSeen`    | int      | Segundos desde última trama del tanque                     |
| `seqActive`       | bool     | Secuencia lavaplatos en curso                              |
| `seqWindow`       | int      | Ventana actual (1-based)                                   |
| `seqTotal`        | int      | Total de ventanas del programa                             |
| `seqProgName`     | string   | Nombre del programa en curso                               |
| `seqElapsedSec`   | int      | Segundos transcurridos de la secuencia                     |
| `seqTotalSec`     | int      | Duración total programada                                  |
| `adminLocked`     | bool     | Cliente bloqueado por acción admin/API                     |

---

## `GET /api/macs`

Devuelve las MACs configuradas del sistema.

**Response 200**
```json
{
  "baseMac": "AA:BB:CC:DD:EE:FF",
  "tankMac": "11:22:33:44:55:66",
  "remoteMacs": [
    "AA:11:22:33:44:55",
    "BB:11:22:33:44:55",
    "",
    ""
  ]
}
```

`remoteMacs` siempre tiene 4 slots. String vacío = slot sin asignar.

---

## `POST /api/macs`

Actualiza MACs del tanque y/o mandos. **Form-urlencoded** (no JSON).

`Content-Type: application/x-www-form-urlencoded`

**Campos** (todos opcionales — solo se actualizan los enviados):

| Campo         | Formato            | Notas                              |
|---------------|--------------------|------------------------------------|
| `tankMac`     | `AA:BB:CC:DD:EE:FF`| MAC del ESP32 del tanque           |
| `remoteMac0`  | `AA:BB:CC:DD:EE:FF`| Mando físico 1. Vacío borra slot.  |
| `remoteMac1`  | idem               | Mando físico 2                     |
| `remoteMac2`  | idem               | Mando físico 3                     |
| `remoteMac3`  | idem               | Mando físico 4                     |

**Response 200**
```json
{"ok":true}
```

**Errores**
```json
{"error":"tankMac invalida"}
{"error":"remoteMac2 invalida"}
```

---

## `POST /api/modo`

Cambia la fuente de agua. **Form-urlencoded**.

| Campo     | Tipo   | Obligatorio | Descripción                       |
|-----------|--------|-------------|-----------------------------------|
| `modo`    | int    | sí          | `1`=Ext · `2`=Ambas · `3`=Tanque  |
| `usuario` | string | no          | Usuario que ejecuta el cambio     |

**Response 200**
```json
{"ok":true}
```

**Errores**
```json
{"error":"Falta modo"}
{"error":"Modo invalido"}
```

---

## Ejemplos `curl`

```bash
BASE=http://192.168.1.50

# Abrir 30 min como usuario "Casa"
curl -X POST $BASE/api/comando \
  -H "Content-Type: application/json" \
  -d '{"action":"open","minutes":30,"user":"Casa"}'

# Cerrar
curl -X POST $BASE/api/comando \
  -H "Content-Type: application/json" \
  -d '{"action":"close"}'

# Cambiar a fuente "Ambas"
curl -X POST $BASE/api/comando \
  -H "Content-Type: application/json" \
  -d '{"action":"mode","mode":2}'

# Lanzar programa lavaplatos eco
curl -X POST $BASE/api/comando \
  -H "Content-Type: application/json" \
  -d '{"action":"sequence","program":"eco"}'

# Estado
curl $BASE/estado

# MACs
curl $BASE/api/macs

# Asignar MAC del tanque
curl -X POST $BASE/api/macs \
  --data-urlencode "tankMac=11:22:33:44:55:66"

# Borrar slot del mando 3
curl -X POST $BASE/api/macs --data-urlencode "remoteMac2="
```

---

## Notas de implementación

- **Bloqueo admin (`adminLock`)**: cualquier comando vía `/api/comando` (excepto
  `estado`) bloquea la UI de cliente del Base. Una integración externa que
  haga polling cada N segundos con `estado` no causa bloqueo.
- **Polling**: `GET /estado` es liviano; un intervalo de 1–2 s es razonable
  desde una sola UI. Para varios consumidores conviene cachear.
- **Usuario**: el campo `user` en `/api/comando` se prefija automáticamente
  con `ADM` en backend (`"ADM" + user`). Aparece luego en `usuario` de
  `/estado`.
- **MACs vacías**: en `POST /api/macs`, enviar el campo con valor vacío borra
  el slot (queda `FF:FF:FF:FF:FF:FF` internamente, mostrado como `""` en GET).
- **Endpoints legacy** (HTML form, no API): `POST /toggle`, `POST /sequencia`.
  Se mantienen para la UI web embebida; preferir `/api/comando` desde
  integraciones externas.
