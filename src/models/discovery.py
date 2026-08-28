"""Viam discovery service for Profoto Pro-D3 lights over Bluetooth LE.

Scans for BLE advertisers whose name starts with "Pro-D3" and returns a
ComponentConfig for each one, pre-filled with the light's address so the
user can add it to their machine with no manual lookup.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import ClassVar, List, Mapping, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from google.protobuf import struct_pb2
from typing_extensions import Self
from viam.logging import getLogger
from viam.proto.app.robot import ComponentConfig
from viam.proto.common import ResourceName
from viam.resource.base import ResourceBase
from viam.resource.easy_resource import EasyResource
from viam.resource.types import Model, ModelFamily
from viam.services.discovery import Discovery
from viam.utils import ValueTypes, struct_to_dict

try:
    from bleak import BleakScanner

    _BLEAK_AVAILABLE = True
except Exception:
    BleakScanner = None  # type: ignore
    _BLEAK_AVAILABLE = False

LOGGER = getLogger(__name__)

SCAN_TIMEOUT_DEFAULT = 10.0
SENSOR_API = "rdk:component:sensor"
SENSOR_MODEL = "viam-soleng:profoto:pro-d3"


class ProfotoDiscovery(Discovery, EasyResource):
    MODEL: ClassVar[Model] = Model(
        ModelFamily("viam-soleng", "profoto"), "ble-discovery"
    )

    _scan_timeout: float

    @classmethod
    def new(
        cls,
        config: ComponentConfig,
        dependencies: Mapping[ResourceName, ResourceBase],
    ) -> Self:
        instance = cls(config.name)
        instance.reconfigure(config, dependencies)
        return instance

    @classmethod
    def validate_config(
        cls, config: ComponentConfig
    ) -> Tuple[Sequence[str], Sequence[str]]:
        attrs = struct_to_dict(config.attributes)
        timeout = attrs.get("scan_timeout")
        if timeout is not None and (
            not isinstance(timeout, (int, float))
            or isinstance(timeout, bool)
            or timeout <= 0
        ):
            raise ValueError("`scan_timeout` must be a positive number of seconds")
        return [], []

    def reconfigure(
        self, config: ComponentConfig, dependencies: Mapping[ResourceName, ResourceBase]
    ):
        attrs = struct_to_dict(config.attributes)
        self._scan_timeout = float(attrs.get("scan_timeout", SCAN_TIMEOUT_DEFAULT))

    async def discover_resources(
        self,
        *,
        extra: Optional[Mapping[str, ValueTypes]] = None,
        timeout: Optional[float] = None,
    ) -> List[ComponentConfig]:
        if not _BLEAK_AVAILABLE:
            LOGGER.warning("bleak is not installed; BLE discovery unavailable")
            return []

        scan_timeout = self._scan_timeout
        if timeout is not None:
            scan_timeout = min(scan_timeout, timeout - 1.0)
            if scan_timeout <= 0:
                scan_timeout = self._scan_timeout

        LOGGER.info(f"scanning for Pro-D3 lights ({scan_timeout:.0f}s)...")
        found = await BleakScanner.discover(
            timeout=scan_timeout, return_adv=True
        )

        configs: List[ComponentConfig] = []
        for device, adv in found.values():
            name = adv.local_name or device.name or ""
            if not name.startswith("Pro-D3"):
                continue

            serial = name.replace("Pro-D3 ", "").strip()
            resource_name = f"flash-{serial}" if serial else "flash"

            attrs = struct_pb2.Struct()
            attrs.update({"address": device.address})

            configs.append(
                ComponentConfig(
                    name=resource_name,
                    api=SENSOR_API,
                    model=SENSOR_MODEL,
                    namespace="viam-soleng",
                    attributes=attrs,
                )
            )
            LOGGER.info(
                f"discovered {name} at {device.address} (rssi {adv.rssi})"
            )

        LOGGER.info(f"discovery complete: {len(configs)} light(s) found")
        return configs
