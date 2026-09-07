
"""Internal service entry points."""

# Phase 2D-A keeps the shadow runner available as an internal, opt-in entry
# without wiring it into the device.inventory.collect production flow.
from .interface_discovery_shadow import InterfaceDiscoveryShadowRunner

__all__ = ["InterfaceDiscoveryShadowRunner"]
