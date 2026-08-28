import asyncio

from viam.module.module import Module

# Importing models registers them with the Viam resource registry.
from models.pro_d3 import ProD3  # noqa: F401
from models.discovery import ProfotoDiscovery  # noqa: F401


if __name__ == "__main__":
    asyncio.run(Module.run_from_registry())
