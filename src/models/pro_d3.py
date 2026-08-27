"""Viam sensor model for the Profoto Pro-D3 studio flash over Bluetooth LE.

Registered as `rdk:component:sensor` (there is no `light` component in the RDK):
`get_readings` reports the current power (and other decoded state), and
`do_command` sets power. Reverse-engineered PUP protocol - see the `profoto`
package and `~/git/profoto-spike/FINDINGS.md`.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, ClassVar, Mapping, Optional, Sequence, Tuple

# Allow both `python src/main.py` (src on sys.path) and package-style imports.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from typing_extensions import Self
from viam.components.sensor import Sensor
from viam.logging import getLogger
from viam.proto.app.robot import ComponentConfig
from viam.proto.common import ResourceName
from viam.resource.base import ResourceBase
from viam.resource.easy_resource import EasyResource
from viam.resource.types import Model, ModelFamily
from viam.utils import ValueTypes, struct_to_dict

from profoto import protocol as proto
from profoto.session import ProfotoError, ProfotoSession

# Change-only data capture is a nice-to-have; guard the import so an older
# viam-sdk that lacks these helpers doesn't break the module.
try:
    from viam.errors import NoCaptureToStoreError
    from viam.utils import from_dm_from_extra

    _HAVE_DM_HELPERS = True
except Exception:  # pragma: no cover
    _HAVE_DM_HELPERS = False

LOGGER = getLogger(__name__)


class ProD3(Sensor, EasyResource):
    # Namespace note: `viam-soleng` matches the owner's other reusable modules.
    # To publish under a different namespace, change this triple AND meta.json.
    MODEL: ClassVar[Model] = Model(ModelFamily("viam-soleng", "profoto"), "pro-d3")

    @classmethod
    def new(
        cls, config: ComponentConfig, dependencies: Mapping[ResourceName, ResourceBase]
    ) -> Self:
        # EasyResource.new does not call reconfigure, and viam-server only calls
        # it on *later* config changes - so configure here or self._session
        # won't exist when the first get_readings/DoCommand arrives.
        instance = cls(config.name)
        instance.reconfigure(config, dependencies)
        return instance

    @classmethod
    def validate_config(
        cls, config: ComponentConfig
    ) -> Tuple[Sequence[str], Sequence[str]]:
        """This model owns its own BLE hardware, so it declares no dependencies."""
        attrs = struct_to_dict(config.attributes)

        address = attrs.get("address")
        if not address or not isinstance(address, str):
            raise ValueError(
                "`address` is required: the light's Bluetooth MAC "
                "(e.g. `38:39:8F:A4:ED:34` on Linux)"
            )

        head_id = attrs.get("head_id")
        if head_id is not None and (
            not isinstance(head_id, (int, float)) or isinstance(head_id, bool) or head_id < 0
        ):
            raise ValueError("`head_id` must be a non-negative integer")

        timeout = attrs.get("connect_timeout")
        if timeout is not None and (
            not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or timeout <= 0
        ):
            raise ValueError("`connect_timeout` must be a positive number of seconds")

        return [], []

    def reconfigure(
        self, config: ComponentConfig, dependencies: Mapping[ResourceName, ResourceBase]
    ):
        attrs = struct_to_dict(config.attributes)
        self._address: str = str(attrs["address"])
        self._head_id: int = int(attrs.get("head_id", 0))
        self._connect_timeout: float = float(attrs.get("connect_timeout", 15.0))
        self._last_readings: Optional[Mapping[str, Any]] = None

        # Tear down any previous session before replacing it (a stale connection
        # would hold the light's single central slot against the new instance).
        old = getattr(self, "_session", None)
        if old is not None:
            import asyncio

            try:
                asyncio.get_running_loop().create_task(old.close())
            except RuntimeError:
                pass  # no running loop (unlikely under viam-server); drop it

        # Lazy connect: the session opens the BLE link on first use, so
        # reconfigure never blocks on a multi-second BLE scan/connect.
        self._session = ProfotoSession(
            self._address,
            head_id=self._head_id,
            connect_timeout=self._connect_timeout,
            logger=self.logger,
        )
        self.logger.info(
            f"Pro-D3 configured for {self._address} (head {self._head_id})"
        )

    # ------------------------------------------------------------------
    # Sensor API
    # ------------------------------------------------------------------
    async def get_readings(
        self, *, extra: Optional[Mapping[str, Any]] = None, timeout: Optional[float] = None, **kwargs
    ) -> Mapping[str, ValueTypes]:
        try:
            settings = await self._session.request_state()
        except ProfotoError as exc:
            # Keep telemetry flowing with a health flag rather than erroring the
            # data collector; a transient BLE drop shouldn't stop the pipeline.
            self.logger.warning(f"Pro-D3 unreachable: {exc}")
            return {"connected": False, "error": str(exc)}

        power = proto.energy_from_settings(settings, self._head_id)
        readings: dict[str, ValueTypes] = {"connected": True, "head_id": self._head_id}
        if power is not None:
            readings["power"] = power
            readings["power_byte"] = int(round(power * 10))
        head = settings.get(802)  # HeadOnV2 [headId, on]
        if head is not None and len(head) >= 2:
            readings["head_on"] = bool(head[1])
        mode = settings.get(186)  # FlashMode
        if mode is not None and len(mode) >= 1:
            readings["flash_mode"] = int(mode[0])
        serial = settings.get(73)
        if serial is not None:
            readings["serial"] = proto.decode_string_value(serial)

        # Change-only capture: when the data manager is polling, skip storing a
        # row identical to the last one (a light idle at 7.4 writes one row, not
        # thousands). The control tab (no DM flag) always gets a fresh reading.
        if _HAVE_DM_HELPERS and from_dm_from_extra(extra):
            if readings == self._last_readings:
                raise NoCaptureToStoreError()
        self._last_readings = dict(readings)
        return readings

    # ------------------------------------------------------------------
    # DoCommand: set power
    # ------------------------------------------------------------------
    async def do_command(
        self,
        command: Mapping[str, ValueTypes],
        *,
        timeout: Optional[float] = None,
        **kwargs,
    ) -> Mapping[str, ValueTypes]:
        resp: dict[str, ValueTypes] = {}

        if "set_power" in command:
            arg = command["set_power"]
            value = arg.get("value") if isinstance(arg, Mapping) else arg
            if value is None:
                raise ValueError("`set_power` needs a number of f-stops, e.g. {\"set_power\": 5.0}")
            applied = await self._session.set_power(float(value))
            resp["set_power"] = {"power": applied}

        if "get_state" in command or "get_power" in command:
            resp["state"] = dict(await self.get_readings())

        if not resp:
            raise ValueError(
                "no recognized command; supported: set_power (f-stops "
                f"{proto.FSTOP_MIN}-{proto.FSTOP_MAX}), get_state"
            )
        return resp

    async def close(self):
        """Release the BLE link so a replacing instance can grab the light."""
        session = getattr(self, "_session", None)
        if session is not None:
            await session.close()
