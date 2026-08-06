"""safe_to_test: headless port of btop_safe_to_test.py's relay-safety
watcher (see shared_control/safe_to_test_control.py's SafeToTestControl for
the full design rationale and the Connect-app version's docstring).

The Connect-app version reads Connect's own already-published
health-monitor telemetry via client.get_channel_values() -- deliberately
not opening a competing NI-DAQmx session, since Connect's own device
connector normally owns the USB-6002 (device name 'dc_panel_daq', confirmed
via list_ni_devices.py) exclusively.

Headless mode runs fully standalone with no Connect app running at all, so
there's no competing session to avoid here -- this version opens its own
direct NI-DAQmx digital-input read of the same six lines (port0/line0-5)
instead, via instro's NIDAQDriver (same pattern do_drive.py/
di_raster_scan.py use for their own NI listener/stimulus rigs). Reuses
SafeToTestControl's shared project logger so both the headless and
Connect-app versions log under the identical source name -- only the
actual data source differs.

NOTE: Connect's own device config
('CI Rack Config/health-monitor-usb-6002.ni-daqmx.ni-daqmx.json') has
port0/line0-5 configured as DigitalOutput -- these are relay CONTROL
lines (they command the six Phoenix Contact relays), not sense lines
reading some other external signal. With Connect not running, nothing
here is fighting over write ownership, so a plain digital-INPUT read is
safe and reads back whatever's currently present on those six pins -- but
that also means this is only as meaningful as whatever actually holds/
drives those lines while Connect itself isn't active. Worth confirming on
real hardware that this still reflects the real relay state the way you
expect during a Connect-less run."""

from instro.daq import InstroDAQ
from instro.daq.drivers.ni import NIDAQDriver
from instro.daq.types import Direction, Logic

from shared_control import SafeToTestControl

TEST_ID = "safe_to_test"
REQUIRED_DRIVER = "ni_daqmx"
KIND = "continuous"

DEVICE_NAME = "dc_panel_daq"   # confirmed via list_ni_devices.py on the real rig
RELAY_LINE_BITS = [0, 1, 2, 3, 4, 5]   # port0/line0-5 -- matches SafeToTestControl.RELAY_LINE_CHANNELS
RELAY_LINE_ALIASES = [f"relay_line{b}" for b in RELAY_LINE_BITS]

log = SafeToTestControl.log   # same shared project logger as every other *Control class


def _is_safe(daq_health) -> bool:
    """Same NAND-all-six-lines logic as SafeToTestControl.is_safe() --
    True only if every monitored line currently reads 0 -- just reading a
    direct DI task here instead of Connect's published telemetry."""
    energized = [
        alias for alias in RELAY_LINE_ALIASES
        if bool(daq_health.read_digital_line(channel=alias).latest)
    ]
    if energized:
        log.info(f"NOT safe to test -- energized relay line(s): {energized}")
        return False
    return True


def run(daq, inst, publish, state):
    if "daq_health" not in state:
        daq_health = InstroDAQ(name=DEVICE_NAME, driver=NIDAQDriver(device_id=DEVICE_NAME))
        daq_health.open()
        for bit, alias in zip(RELAY_LINE_BITS, RELAY_LINE_ALIASES):
            daq_health.configure_digital_line(
                direction=Direction.INPUT,
                physical_channel=f"{DEVICE_NAME}/port0/line{bit}",
                alias=alias,
                logic=Logic.HIGH,
            )
        state["daq_health"] = daq_health
        # None (not True/False) so the very first pass always logs the
        # starting state -- same idiom as btop_safe_to_test.py's last_safe.
        state["last_safe"] = None
        log.info(f"safe_to_test (headless) ready -- monitoring {RELAY_LINE_ALIASES} on {DEVICE_NAME!r}.")

    daq_health = state["daq_health"]
    is_safe = _is_safe(daq_health)
    publish({"safe_to_test": 1.0 if is_safe else 0.0}, tags={"subsystem": "safe_to_test"})

    if is_safe != state["last_safe"]:
        if is_safe:
            log.info("Safe to test -- all relay lines clear.")
        else:
            log.info("NOT safe to test -- a relay line is energized.")
        state["last_safe"] = is_safe


def teardown(state, daq, inst):
    if "daq_health" not in state:
        return   # run() never got far enough to open anything -- nothing to tear down
    try:
        state["daq_health"].close()
    except Exception:
        pass
