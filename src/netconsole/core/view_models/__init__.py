"""ViewModels for the unified state architecture.

ViewModels are pure **data-mapping** layers — they call
:func:`compute_state` from the state engine and populate row dicts
with the result.  They never recompute thresholds or contain
``if/else`` status logic.
"""

from netconsole.core.view_models.fit_ap_view_model import FITAPViewModel
from netconsole.core.view_models.trackside_view_model import TracksideViewModel
from netconsole.core.view_models.device_detail_view_model import DeviceDetailViewModel

__all__ = ["FITAPViewModel", "TracksideViewModel", "DeviceDetailViewModel"]
