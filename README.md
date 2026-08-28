# viam-profoto

A Viam module to **read and set the flash power of a Profoto Pro-D3** studio
light over Bluetooth LE. Includes automatic discovery of lights on your network.

## Requirements

- A Linux (or macOS) host with Bluetooth. On Linux: BlueZ with `bluetoothd`
  running.
- The light: **Settings -> Bluetooth -> ON**. The light accepts **one central at
  a time** — quit the Profoto app / Control Desktop so they don't hold it.

## Install

Add the module from the [Viam registry](https://app.viam.com/module/viam-soleng/profoto):

1. In your machine's config, go to **Modules** and add `viam-soleng:profoto`.
2. Add the **discovery service** (`viam-soleng:profoto:ble-discovery`, API
   `rdk:service:discovery`) — it scans for nearby Pro-D3 lights over BLE and
   suggests component configurations automatically.
3. Add a **sensor component** for each light, using the model
   `viam-soleng:profoto:pro-d3` (API `rdk:component:sensor`).

## Configure

### Discovery service (optional)

```json
{
  "name": "profoto-discovery",
  "api": "rdk:service:discovery",
  "model": "viam-soleng:profoto:ble-discovery",
  "attributes": {
    "scan_timeout": 10
  }
}
```

| attribute | required | default | meaning |
|---|---|---|---|
| `scan_timeout` | no | `10` | seconds to scan for BLE advertisers |

### Sensor component

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

If you don't know the light's address, add the discovery service first — it will
find it for you. On Linux you can also run `bluetoothctl scan on` and look for
`Pro-D3 <serial>`.

## Use

**Set power** (f-stops, 0.1–10.0) from the Control tab or a client:

```json
{ "set_power": 5.0 }
```

**Read power:** the component's readings show `power` (f-stops), `power_byte`,
`head_on`, `flash_mode`, `serial`, and `connected`. Enable data capture on
`get_readings` to log power to Viam data — identical consecutive readings are
skipped automatically.

## Caveats

- **One central at a time.** While this module holds the light, the Profoto app
  can't connect, and vice-versa.
- **No firing.** The Pro-D3 has no BLE trigger; fire it via the sync port or Air
  radio.
- **Reverse-engineered protocol.** A Profoto firmware update may change it.
