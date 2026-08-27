# viam-profoto

A Viam module to **read and set the flash power of a Profoto Pro-D3** studio
light over Bluetooth LE.

- **Model:** `viam-soleng:profoto:pro-d3` (API `rdk:component:sensor`)
- `get_readings` reports current power (f-stops) and other decoded state.
- `do_command({"set_power": 1.2})` sets the power.

There is no `light` component in the RDK, so this is a `sensor`: it gets both a
`Readings` collector (for logging power to Viam data) and `DoCommand` (for
control). Firing is **not** exposed — the Pro-D3 has no BLE trigger; it fires
over its 3.5 mm sync port / the Air radio.

## Requirements

- A Linux (or macOS) host with Bluetooth. On Linux: BlueZ with `bluetoothd`
  running. If viam-server runs as root, `org.bluez` access is unrestricted and
  the light needs no pairing.
- The light's Bluetooth address. On Linux this is a MAC (e.g.
  `38:39:8F:A4:ED:34`); find it with `bluetoothctl scan on` (look for
  `Pro-D3 <serial>`). On macOS it's a per-host UUID instead.
- The light: **Settings → Bluetooth → ON**, and it accepts **one central at a
  time** — quit the Profoto app / Control Desktop so they don't hold it.

## Configure

```json
{
  "name": "flash",
  "api": "rdk:component:sensor",
  "model": "viam-soleng:profoto:pro-d3",
  "attributes": {
    "address": "38:39:8F:A4:ED:34",
    "head_id": 0,
    "connect_timeout": 15
  }
}
```

| attribute | required | default | meaning |
|---|---|---|---|
| `address` | yes | — | the light's BLE MAC (Linux) or per-host UUID (macOS) |
| `head_id` | no | `0` | which head to address (Pro-D3 is single-head: 0) |
| `connect_timeout` | no | `15` | seconds to wait for a BLE connect |

## Use

Set power (f-stops, 0.1–10.0) from the Control tab or a client:

```json
{ "set_power": 5.0 }
```

Read power: the component's readings show `power` (f-stops), `power_byte`,
`head_on`, `flash_mode`, `serial`, and `connected`. Enable data capture on
`get_readings` to log power to Viam data — identical consecutive readings are
skipped, so an idle light writes one row, not thousands.

## Protocol & safety

The PUP protocol was reverse-engineered from the Profoto Control Android app and
verified against a physical Pro-D3 — see `~/git/profoto-spike/FINDINGS.md`. The
module only ever writes to the PUP command characteristic and the device-name
(registration) characteristic; it **never** touches the firmware/DFU service.

Reverse-engineered, so a Profoto firmware update may change it. Also note that
*lowering* power on a D-series can dump energy through the tube (a light-emitting
event); *raising* power just charges the capacitor.

## Develop

```bash
python3 -m venv venv && ./venv/bin/pip install -r requirements.txt pytest
./venv/bin/python -m pytest tests/ -v   # codec tests, no hardware needed
```

Before publishing: set `visibility` and `url` in `meta.json`, and change the
`viam-soleng` namespace (in `meta.json` and `src/models/pro_d3.py`) if you want a
different owner.
