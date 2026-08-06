"""psu_control: headless port of btop_dc_psu.py's interlocked bench-source
control (PSUControl -- BK9115, Keysight N5745A, BK 8514B eLoad). Opens its
own three dedicated instrument sessions (NOT the shared 34980A daq/inst this
orchestrator passes to every test -- this test simply ignores those two
params, same as PSUControl.create_instrument()/apply_selection() work
independent of any Keysight frame).

There's no Connect UI checkbox in headless mode to pick a device by hand, so
this round-robins through all three automatically -- one PSU at a time
(BK9115, then N5745A), then the eLoad last -- holding each for
HEADLESS_HOLD_S seconds before advancing, same round-robin-one-at-a-time
idiom as di_raster_scan.py's DI_STIMULUS_HOLD_PASSES. It stops (holds) once
it reaches the eLoad rather than wrapping back to BK9115 -- this is a single
walkthrough of all three devices, not an indefinite cycle."""

import time

from instro.eload.types import LoadMode

from shared_control import PSUControl

TEST_ID = "psu_control"
REQUIRED_DRIVER = "psu"
KIND = "continuous"

# Round-robin order: one PSU at a time, eLoad last.
DEVICE_ORDER = ["bk9115", "n5745a", "eload_8514b"]

# How long each device gets before advancing to the next -- see class
# docstring above. Pick something long enough to actually read a settled
# voltage/current for that device before moving on.
HEADLESS_HOLD_S = 10.0

# Only used once the eLoad becomes the active device -- same mode/level
# idea as PSUControl.selected_mode()/selected_level() in the Connect-app
# version, but fixed constants instead of reading a UI checkbox/text
# field. Validated against PSUControl.LEVEL_RANGE_BY_MODE the same way
# (_enforce_level_range/_enforce_relay_safe_current) the moment
# configure() is called below -- an out-of-range constant here raises
# ValueError loudly rather than silently clamping.
HEADLESS_ELOAD_MODE = LoadMode.CC
HEADLESS_ELOAD_LEVEL = 1.0


def run(daq, inst, publish, state):
    if "sessions" not in state:
        bk_ctl = PSUControl.bk9115()
        n5745a_ctl = PSUControl.n5745a()
        eload_ctl = PSUControl.eload_8514b()
        eload_ctl.mode = HEADLESS_ELOAD_MODE
        eload_ctl.level = HEADLESS_ELOAD_LEVEL

        group = [bk_ctl, n5745a_ctl, eload_ctl]
        by_name = {"bk9115": bk_ctl, "n5745a": n5745a_ctl, "eload_8514b": eload_ctl}

        sessions = {}
        for ctl in group:
            instrument = ctl.create_instrument()
            instrument.open()
            instrument.start()   # required before get_channel() -- see PSUControl.bk9115()'s docstring for why
            ctl.safe_off(instrument)   # make sure nothing is left enabled from a previous run
            sessions[ctl] = instrument

        state["group"] = group
        state["by_name"] = by_name
        state["sessions"] = sessions
        state["last_selected"] = "__unset__"   # sentinel so the first pass always acts

        # Round-robin bookkeeping: index into DEVICE_ORDER, and when we last
        # advanced (monotonic clock so a system clock change can't skip/
        # stall a hold early or late).
        state["index"] = 0
        state["last_advance"] = time.monotonic()

        PSUControl.log.info(
            f"psu_control (headless) ready. Round-robining {DEVICE_ORDER}, "
            f"{HEADLESS_HOLD_S}s each, stopping at the eLoad. "
            f"eLoad mode={HEADLESS_ELOAD_MODE.value}, level={HEADLESS_ELOAD_LEVEL}."
        )

    group = state["group"]
    sessions = state["sessions"]
    by_name = state["by_name"]

    # Advance to the next device every HEADLESS_HOLD_S seconds -- but stop
    # once we reach the last entry (the eLoad) rather than wrapping back to
    # the first PSU. One walkthrough per test slot, not an indefinite loop.
    now = time.monotonic()
    if state["index"] < len(DEVICE_ORDER) - 1 and now - state["last_advance"] >= HEADLESS_HOLD_S:
        state["index"] += 1
        state["last_advance"] = now

    selected_name = DEVICE_ORDER[state["index"]]
    selected = by_name[selected_name]

    # Same break-before-make interlock as PSUControl.apply_selection(), just
    # driven by the round-robin above instead of reading a Connect checkbox
    # -- every OTHER device gets safe_off() BEFORE the newly-selected device
    # gets configure()'d, so two devices in this group are never both
    # enabled at once. Only re-applied when the selection actually changes.
    if selected is not state["last_selected"]:
        prev_name = getattr(state["last_selected"], "name", state["last_selected"])
        new_name = getattr(selected, "name", None)
        PSUControl.log.info(f"psu_control (headless): device selection -> {prev_name!r} -> {new_name!r}")

        for ctl in group:
            if ctl is not selected:
                ctl.safe_off(sessions[ctl])
        selected.configure(sessions[selected])

        state["last_selected"] = selected

    # Every device is sensed every pass regardless of which one is
    # selected -- the two deselected devices will just read ~0V/0A since
    # their outputs are off (same as the Connect-app version).
    for ctl, instrument in sessions.items():
        voltage, current = ctl.read_channel(instrument)
        publish(
            {f"{ctl.name}_voltage": voltage, f"{ctl.name}_current": current[-1]},
            tags={"subsystem": "psu_control"},
        )


def teardown(state, daq, inst):
    if "sessions" not in state:
        return   # run() never got far enough to open anything -- nothing to tear down
    for ctl, instrument in state["sessions"].items():
        ctl.safe_off(instrument)
        ctl.shutdown(instrument)
