"""shared_control.constants: the shared logger and values reused identically
across multiple *Control classes in this package, factored out to one place
so there's exactly one spot to update each. Every class keeps its own
existing public attribute name (RESOURCE, RESOURCE_34980A, MUX_SLOT, ...)
since other scripts reference those directly (e.g. DAQ_counter.py reads
counter.RESOURCE_34980A) -- only the right-hand-side value is shared here,
so nothing outside this package needs to change."""

# connect_python only exists inside Connect's own bundled Python venv -- it's
# injected when Connect itself runs a script, not something pip-installable
# or available to headless_rack_control.py (plain system Python, no Connect
# runtime). Try it first so scripts run through Connect keep using its real
# logger (shows up in Connect's own log viewer); fall back to the stdlib
# logging module so the exact same classes still work headless.
#
# Logger name is hardcoded to "btop_test_suite" (rather than __name__, which
# would now resolve to "shared_control.constants") so every class's log
# output keeps showing up under the exact same source name it did before
# this package split -- nothing about what appears in Connect's log viewer
# changes just because the code moved files.
try:
    import connect_python
    _log = connect_python.get_logger("btop_test_suite")
except ImportError:
    import logging
    _log = logging.getLogger("btop_test_suite")


_RESOURCE_34980A = "USB0::0x0957::0x0507::MY44001757::INSTR"   # confirmed 34980A frame (grabVisaIDN/idn_output.txt)
_MUX_SLOT_34923A = 4   # slot holding the 34923A mux/switch module (SW_AO_MUX) -- shared by FGEN_DIFFControl and AIN_AOControl
_MUX_SLOT_34950A = 8   # slot holding the 34950A DIO/counter module -- shared by diRasterScan, doDriveControl, and Counter34980aControl
_POLL_S_GENERAL = 0.20   # poll interval shared by diRasterScan and doDriveControl (both drive/read the 34950A DIO banks)
_POLL_S_SLOW = 0.5   # poll interval shared by Counter34980aControl and MultiCounterControl
_STREAM_ID_DIO_TRAY = "dio_tray"   # shared by diRasterScan, doDriveControl, and MultiCounterControl
_STREAM_ID_DAQ_TRAY = "daq_tray"   # shared by FGEN_DIFFControl and AIN_AOControl
