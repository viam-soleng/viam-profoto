import asyncio

from viam.module.module import Module

# Importing the model registers it with the Viam resource registry.
from models.pro_d3 import ProD3  # noqa: F401


if __name__ == "__main__":
    asyncio.run(Module.run_from_registry())
