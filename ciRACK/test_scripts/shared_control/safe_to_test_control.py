"""shared_control.safe_to_test_control: relay-safety watcher control."""

from .constants import _log


class SafeToTestControl():
    """Read-only 'safe to test' WATCHER for the rack, derived from the six
    Phoenix Contact relay control lines on the health-monitor USB-6002
    (Connect stream id 'health_monitor_daq', channels
    dc_panel_daq/port0/line0-5 -- see
    'CI Rack Config/health-monitor-usb-6002.ni-daqmx.ni-daqmx.json').

    Deliberately does NOT open its own instro/NI-DAQmx session on that
    device: the USB-6002 is already exclusively owned by Connect's own
    built-in NI-DAQmx device connector (there is no instro-based Python
    script touching it anywhere in this repo -- confirmed). A second,
    competing session on the same physical device would risk a DAQmx
    resource conflict. Instead this reads the SAME already-published
    telemetry via connect_python's client.get_channel_values() -- a read
    of Connect's own stream buffer, not new hardware I/O -- so there's
    nothing to conflict with.

    Per rig convention: safe to test only if EVERY monitored relay line
    currently reads 0 (all six de-energized); ANY line reading 1 means NOT
    safe. If the stream hasn't published anything yet, or is missing any
    one of the monitored channels, this fails SAFE -- treats the unknown
    state as NOT safe rather than assuming the best -- same loud-refuse,
    don't-silently-assume philosophy as PSUControl's
    _enforce_relay_safe_current()/_enforce_level_range() above.

    IMPORTANT: this is a standalone MONITOR only -- it does not gate or
    control any other script on this rig (an earlier version wired it into
    PSUControl.apply_selection() as a hard interlock; that was reverted).
    Run it alongside whatever else is active via its own driver script
    (btop_safe_to_test.py), which streams a boolean indicator and pops up
    a Connect notification on every safe<->unsafe transition."""

    HEALTH_MONITOR_STREAM_ID = "health_monitor_daq"
    RELAY_LINE_CHANNELS = [
        "dc_panel_daq/port0/line0",
        "dc_panel_daq/port0/line1",
        "dc_panel_daq/port0/line2",
        "dc_panel_daq/port0/line3",
        "dc_panel_daq/port0/line4",
        "dc_panel_daq/port0/line5",
    ]

    # Stream id this watcher's own driver script (btop_safe_to_test.py)
    # publishes the safe_to_test boolean indicator to -- distinct from
    # HEALTH_MONITOR_STREAM_ID above, which is only ever READ from.
    STREAM_ID = "safe_to_test"

    log = _log

    def is_safe(self, client) -> bool:
        """NAND all RELAY_LINE_CHANNELS together: True only if every one of
        them currently reads 0 (falsy). Returns False (fail-safe) if the
        health-monitor stream has never published data at all, or if any
        individual monitored channel has no value yet -- an unknown relay
        state is never treated as safe. Reports EVERY missing/energized
        channel in one log line (not just the first one found), so a
        stuck-unsafe state is diagnosable from the log alone -- e.g. if a
        specific line was never wired up as an actual input and never
        publishes, that's immediately visible instead of only showing up
        one channel at a time across repeated runs."""
        values = client.get_channel_values(self.HEALTH_MONITOR_STREAM_ID, channels=self.RELAY_LINE_CHANNELS)
        if not values:
            self.log.info(f"{self.HEALTH_MONITOR_STREAM_ID}: no data yet at all -- "
                           f"treating as NOT safe to test")
            return False

        missing = [ch for ch in self.RELAY_LINE_CHANNELS if ch not in values]
        if missing:
            self.log.info(
                f"{self.HEALTH_MONITOR_STREAM_ID}: no value yet for {missing} -- "
                f"treating as NOT safe to test. If this list never changes across repeated "
                f"runs, those specific channel(s) are likely never actually publishing "
                f"(e.g. not wired as inputs, or not enabled in the device config) -- "
                f"double check '{self.HEALTH_MONITOR_STREAM_ID}' picks up all of "
                f"{self.RELAY_LINE_CHANNELS}."
            )
            return False

        energized = [ch for ch in self.RELAY_LINE_CHANNELS if bool(values[ch]["value"])]
        if energized:
            self.log.info(f"NOT safe to test -- energized relay line(s): {energized}")
            return False
        return True
