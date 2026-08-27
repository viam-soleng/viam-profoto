# viam-soleng:profoto:pro-d3

A `rdk:component:sensor` that reads and sets the flash power of a **Profoto
Pro-D3** studio light over Bluetooth LE.

## Configuration

```json
{
  "address": "38:39:8F:A4:ED:34",
  "head_id": 0,
  "connect_timeout": 15
}
```

| attribute | type | default | description |
|---|---|---|---|
| `address` | string | required | BLE MAC (Linux) or CoreBluetooth per-host UUID (macOS) of the light |
| `head_id` | int | `0` | head to address; the Pro-D3 is single-head |
| `connect_timeout` | number | `15` | seconds to wait for a BLE connect |

## DoCommand

| command | example | effect |
|---|---|---|
| `set_power` | `{"set_power": 5.0}` or `{"set_power": {"value": 5.0}}` | Set power to 5.0 f-stops (0.1–10.0, 0.1 steps). Waits for the light's ACK; raises on NACK/timeout. |
| `get_state` | `{"get_state": {}}` | Return the same fields as `get_readings`. |

`set_power` returns `{"set_power": {"power": 5.0}}` with the applied value.

## Readings (`get_readings`)

| key | type | meaning |
|---|---|---|
| `connected` | bool | whether the BLE session is up |
| `power` | number | current power in f-stops (e.g. `1.2`) |
| `power_byte` | int | raw energy byte (`power * 10`) |
| `head_on` | bool | head on/off |
| `flash_mode` | int | flash mode (ECO/BOOST/FREEZE encoding) |
| `serial` | string | the unit serial |
| `error` | string | present only when `connected` is false |

Consecutive identical readings are dropped during data capture
(`NoCaptureToStoreError`), so logging an idle light is cheap.

## How it works

The Pro-D3 speaks Profoto's undocumented **PUP** protocol over BLE. On connect
the module registers itself (writes `"Profoto Client"` to the device-name
characteristic — the light ignores unregistered clients), then requests state
with a zero-payload prologue. Power is set with the `MxEnergyV2` message
(`[counter, 0x23, 0x03, headId, round(fstop*10)]`) and confirmed by the light's
ACK. The scaling `byte = f-stop × 10` and the whole handshake were verified on a
real unit. Full derivation: `~/git/profoto-spike/FINDINGS.md`.

## Caveats

- **Reverse-engineered.** Verified against firmware as reported under the light's
  Settings → About; a Profoto firmware update may break it.
- **One central at a time.** While this module holds the light, the Profoto app
  can't, and vice-versa.
- **No firing.** The Pro-D3 has no BLE trigger; fire it via the sync port (e.g. a
  Viam `board` GPIO through an optocoupler).
- **Energy dumping.** Lowering power on a D-series can flash the tube to dump
  energy; raising power just charges. Keep that in mind for unattended use.
