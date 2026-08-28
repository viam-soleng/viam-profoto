"""PUP wire protocol for the Profoto Pro-D3 over Bluetooth LE.

Pure functions and constants only - no BLE, no Viam - so every byte here is
unit-testable against real captured frames (see tests/test_protocol.py).

The protocol was reverse-engineered from the Profoto Control Android app
(`com.profoto.freke` 1.4.2) and verified against a physical Pro-D3.

Frame format (writes, to CHAR_WRITE):
    [counter:1][opcode:2 little-endian][payload...]
There is no checksum and no length prefix on the write side.

Receive framing (notifications on CHAR_NOTIFY) is an AllSettingsV2 container:
    [counter:1][124 (0x7C 0x00)][ entry, entry, ... ]
    entry = [len:1][opcode:2 LE][value:(len-2) bytes]   # len counts opcode+value
Command replies are tiny frames: [counter][01 00] = ACK, [counter][02 00] = NACK,
each carrying the acked/nacked message's counter as its 1-byte payload.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

# --- GATT identity --------------------------------------------------------
SERVICE_PUP = "bbd75314-ddaa-4b61-a7df-c6eedb79c152"
CHAR_WRITE = "64ecef4f-4408-4565-b017-f254e64462db"   # write-without-response (h28)
CHAR_NOTIFY = "049e2ea9-516a-420b-99f9-b28619f965aa"  # notify (h30)
CHAR_NAME = "c655ad5a-f991-4ce6-8aaf-10803359b587"    # DeviceName - client registration

# The firmware/DFU service. NEVER write to it: this light takes firmware over BLE
# and a stray write here could brick a 750 Ws unit. The session refuses it.
SERVICE_FIRMWARE = "df2c4df7-aa27-490b-8cff-0148ba13f07c"

# Identity string the app writes to CHAR_NAME on connect to register itself; the
# light stays silent to unregistered clients.
CLIENT_NAME = "Profoto Client"

# --- opcodes --------------------------------------------------------------
OP_ACK = 1
OP_NACK = 2
OP_MXENERGY = 18          # legacy single-head power (NACK'd by the Pro-D3)
OP_PROLOGUE = 27          # zero-payload "send me your state" bootstrap
OP_MXENERGY_V2 = 803      # per-head power [headId, energyByte] - the Pro-D3 form
OP_ALLSETTINGS_V2 = 124   # container opcode for the notify-side state dump

# Displayed f-stop range on the Pro-D3 ruler (0.1 EV steps). The exact bounds
# come from MxEnergyConstraint at runtime; these are the documented defaults and
# also what we validate against before sending. An out-of-range value the light
# rejects still surfaces as a NACK.
FSTOP_MIN = 0.1
FSTOP_MAX = 10.0
FSTOP_STEP = 0.1

COUNTER_MODULUS = 240     # PupMsgCounter cycles 0..239


def next_counter(counter: int) -> int:
    """Advance the PupMsgCounter exactly as the app does: (n + 1) % 240."""
    return (counter + 1) % COUNTER_MODULUS


def fstop_to_byte(fstop: float) -> int:
    """Convert a displayed f-stop (e.g. 1.2) to the on-wire energy byte (12).

    Verified on-device: byte = round(fstop * 10), so 0.7 -> 7, 1.2 -> 12,
    10.0 -> 100. Raises ValueError outside the ruler range.
    """
    if not isinstance(fstop, (int, float)) or isinstance(fstop, bool):
        raise ValueError("`power` must be a number of f-stops")
    if fstop < FSTOP_MIN or fstop > FSTOP_MAX:
        raise ValueError(
            f"`power` {fstop} out of range {FSTOP_MIN}-{FSTOP_MAX} f-stops"
        )
    return int(round(fstop * 10))


def byte_to_fstop(byte: int) -> float:
    """Inverse of fstop_to_byte: energy byte -> displayed f-stop."""
    return round(byte / 10.0, 1)


def _frame(counter: int, opcode: int, payload: bytes = b"") -> bytes:
    """Build a write frame: [counter][opcode:2 LE][payload]."""
    return bytes([counter & 0xFF, opcode & 0xFF, (opcode >> 8) & 0xFF]) + payload


def encode_prologue(counter: int) -> bytes:
    """The state-request bootstrap: opcode 27, no payload -> [ctr, 1B, 00]."""
    return _frame(counter, OP_PROLOGUE)


def encode_set_power_v2(counter: int, fstop: float, head_id: int = 0) -> bytes:
    """MxEnergyV2 set for one head: [ctr, 23, 03, headId, round(fstop*10)]."""
    return _frame(counter, OP_MXENERGY_V2, bytes([head_id & 0xFF, fstop_to_byte(fstop)]))


def encode_registration() -> bytes:
    """The client-name bytes written (with response) to CHAR_NAME on connect."""
    return CLIENT_NAME.encode("utf-8")


def classify_reply(frame: bytes) -> Optional[Tuple[str, int]]:
    """Recognise a command reply frame.

    Returns ("ACK"|"NACK", acked_counter) for a reply, or None for anything
    else (e.g. an AllSettingsV2 container).
    """
    if len(frame) >= 4 and frame[1] == OP_ACK and frame[2] == 0x00:
        return ("ACK", frame[3])
    if len(frame) >= 4 and frame[1] == OP_NACK and frame[2] == 0x00:
        return ("NACK", frame[3])
    return None


def parse_allsettings(frame: bytes) -> Dict[int, bytes]:
    """Parse an AllSettingsV2 container into {opcode: value_bytes}.

    Returns an empty dict for frames that are not opcode-124 containers
    (including the empty terminator frame). Later entries win if an opcode
    repeats within one frame.
    """
    out: Dict[int, bytes] = {}
    if len(frame) < 3 or frame[1] != OP_ALLSETTINGS_V2 or frame[2] != 0x00:
        return out
    i = 3
    n = len(frame)
    while i < n:
        length = frame[i]
        if length < 2 or i + 1 + length > n:
            break  # truncated / terminator padding
        opcode = frame[i + 1] | (frame[i + 2] << 8)
        value = frame[i + 3 : i + 1 + length]
        out[opcode] = value
        i += 1 + length
    return out


def decode_string_value(value: bytes) -> str:
    """Decode a PUP string field: [strlen:1][utf-8 chars]."""
    if not value:
        return ""
    length = value[0]
    return value[1 : 1 + length].decode("utf-8", "replace")


def energy_from_settings(settings: Dict[int, bytes], head_id: int = 0) -> Optional[float]:
    """Extract the displayed f-stop for a head from a parsed settings dict.

    Prefers MxEnergyV2 (op 803, [headId, byte]); falls back to legacy
    MxEnergy (op 18, [byte]). Returns None if neither is present.
    """
    v2 = settings.get(OP_MXENERGY_V2)
    if v2 is not None and len(v2) >= 2 and v2[0] == head_id:
        return byte_to_fstop(v2[1])
    v1 = settings.get(OP_MXENERGY)
    if v1 is not None and len(v1) >= 1:
        return byte_to_fstop(v1[0])
    return None
