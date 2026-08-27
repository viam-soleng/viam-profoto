"""Async BLE session for the Profoto Pro-D3, built on bleak.

Owns the connection lifecycle and the PUP request/response choreography, but
holds no Viam types - so it can be exercised from a plain asyncio script. The
frame encoding/decoding lives entirely in `protocol.py`.

Connection model: lazy-connect and hold. The first read/write connects,
registers as "Profoto Client", and subscribes to notifications; subsequent calls
reuse the link and reconnect transparently if it drops. All GATT access is
serialized by an asyncio.Lock (the light accepts one central at a time and PUP is
strictly request/response).
"""

from __future__ import annotations

import asyncio
from typing import Dict, Optional

from . import protocol as p

# bleak is only needed at runtime on a host with BlueZ. Import it lazily so the
# module still loads (and can report a clean error) where bleak/BlueZ is absent,
# mirroring how the ptp model guards libgphoto2.
try:
    from bleak import BleakClient, BleakScanner  # type: ignore

    _BLEAK_IMPORT_ERROR: Optional[Exception] = None
except Exception as exc:  # pragma: no cover - depends on the host
    BleakClient = None  # type: ignore
    BleakScanner = None  # type: ignore
    _BLEAK_IMPORT_ERROR = exc


class ProfotoError(Exception):
    """Raised when the light rejects a command or can't be reached."""


class ProfotoSession:
    def __init__(
        self,
        address: str,
        *,
        head_id: int = 0,
        connect_timeout: float = 15.0,
        dump_timeout: float = 4.0,
        logger=None,
    ):
        self._address = address
        self._head_id = head_id
        self._connect_timeout = connect_timeout
        self._dump_timeout = dump_timeout
        self._log = logger

        self._client: Optional["BleakClient"] = None
        self._lock = asyncio.Lock()
        self._counter = 0

        # Latest decoded settings ({opcode: value_bytes}), updated from every
        # AllSettingsV2 notification.
        self._cache: Dict[int, bytes] = {}

        # In-flight command ACK/NACK matching (one command at a time under lock).
        self._ack_counter: Optional[int] = None
        self._ack_future: "Optional[asyncio.Future[bool]]" = None

        # End-of-dump signalling for request_state().
        self._dump_done: Optional[asyncio.Event] = None

    # ------------------------------------------------------------------
    # connection
    # ------------------------------------------------------------------
    def _debug(self, msg: str):
        if self._log is not None:
            self._log.debug(msg)

    def _guard_write_uuid(self, uuid: str):
        # Defensive: only ever write the PUP command char or the registration
        # char. Never the firmware/DFU service.
        if uuid.lower() not in (p.CHAR_WRITE.lower(), p.CHAR_NAME.lower()):
            raise ProfotoError(f"refusing to write to unexpected characteristic {uuid}")

    def _on_disconnect(self, _client):
        self._debug("Pro-D3 BLE link dropped")
        self._client = None

    def _handle_notify(self, _char, data: bytearray):
        frame = bytes(data)
        if len(frame) < 3:
            return
        reply = p.classify_reply(frame)
        if reply is not None:
            kind, acked = reply
            fut = self._ack_future
            if fut is not None and not fut.done() and acked == self._ack_counter:
                fut.set_result(kind == "ACK")
            return
        # Otherwise an AllSettingsV2 container (or its empty terminator).
        if frame[1] == p.OP_ALLSETTINGS_V2 and frame[2] == 0x00:
            settings = p.parse_allsettings(frame)
            if settings:
                self._cache.update(settings)
            elif self._dump_done is not None and self._cache:
                self._dump_done.set()

    async def _ensure_connected(self):
        if BleakClient is None:
            raise ProfotoError(
                "bleak is not installed / importable: "
                f"{_BLEAK_IMPORT_ERROR}. Install bleak and ensure BlueZ + "
                "bluetoothd are available."
            )
        if self._client is not None and self._client.is_connected:
            return
        self._debug(f"connecting to Pro-D3 at {self._address}")
        client = BleakClient(
            self._address,
            timeout=self._connect_timeout,
            disconnected_callback=self._on_disconnect,
        )
        await client.connect()
        await client.start_notify(p.CHAR_NOTIFY, self._handle_notify)
        # Register as a client - the light stays silent until this is written.
        self._guard_write_uuid(p.CHAR_NAME)
        await client.write_gatt_char(p.CHAR_NAME, p.encode_registration(), response=True)
        self._client = client
        self._debug("connected and registered as 'Profoto Client'")

    async def close(self):
        async with self._lock:
            client = self._client
            self._client = None
            if client is not None and client.is_connected:
                try:
                    await client.disconnect()
                except Exception as exc:  # pragma: no cover
                    self._debug(f"error during disconnect: {exc}")

    # ------------------------------------------------------------------
    # operations
    # ------------------------------------------------------------------
    def _next(self) -> int:
        self._counter = p.next_counter(self._counter)
        return self._counter

    async def request_state(self) -> Dict[int, bytes]:
        """Send the prologue and collect the light's full settings dump."""
        async with self._lock:
            await self._ensure_connected()
            self._dump_done = asyncio.Event()
            self._cache = {}
            await self._client.write_gatt_char(
                p.CHAR_WRITE, p.encode_prologue(self._next()), response=False
            )
            try:
                await asyncio.wait_for(self._dump_done.wait(), timeout=self._dump_timeout)
            except asyncio.TimeoutError:
                self._debug("state dump did not terminate cleanly; using what arrived")
            finally:
                self._dump_done = None
            return dict(self._cache)

    async def get_power(self) -> Optional[float]:
        """Return the current displayed f-stop for the configured head."""
        settings = await self.request_state()
        return p.energy_from_settings(settings, self._head_id)

    async def set_power(self, fstop: float) -> float:
        """Set flash power (f-stops) via MxEnergyV2 and wait for the ACK.

        Returns the applied f-stop. Raises ProfotoError on NACK or timeout.
        """
        frame = p.encode_set_power_v2(self._next(), fstop, self._head_id)  # validates range
        async with self._lock:
            await self._ensure_connected()
            loop = asyncio.get_running_loop()
            self._ack_counter = frame[0]
            self._ack_future = loop.create_future()
            self._guard_write_uuid(p.CHAR_WRITE)
            await self._client.write_gatt_char(p.CHAR_WRITE, frame, response=False)
            try:
                ok = await asyncio.wait_for(self._ack_future, timeout=3.0)
            except asyncio.TimeoutError:
                raise ProfotoError("no ACK from light after set_power (timed out)")
            finally:
                self._ack_future = None
                self._ack_counter = None
            if not ok:
                raise ProfotoError(f"light NACK'd set_power to {fstop}")
        return round(fstop, 1)

    async def scan_present(self, timeout: float = 8.0) -> bool:
        """Best-effort: is the configured address advertising right now?"""
        if BleakScanner is None:
            return False
        devices = await BleakScanner.discover(timeout=timeout)
        return any((d.address or "").upper() == self._address.upper() for d in devices)
