"""shared_control.psu_control: unified bench source control (PSUs + eLoad + interlock)."""

from instro.psu import InstroPSU
from instro.psu.drivers import BK9115, KeysightN5700
from instro.eload import InstroELoad
from instro.eload.drivers import BK85XXB
from instro.eload.types import LoadMode
from instro.lib.exceptions import FeatureNotSupportedError

from .constants import _log


class PSUControl():
    """Unified control for every regulated current-capable bench source on
    this rack -- the two PSUs (BK9115, Keysight N5745A) and the BK 8514B
    eLoad -- combined into ONE class per request, replacing what used to be
    four separate classes (the old PSUControl/DCPSUControl, N5745AControl,
    PSUInterlockControl, ELoadControl). The name PSUControl predates the
    eLoad merge and is kept so btop_dc_psu.py's existing import keeps
    working -- read "PSU" here loosely as "one of the rack's interlocked
    bench sources," not literally "power supply only."

    One instance = one physical device, built via one of the three factory
    classmethods below (bk9115(), n5745a(), eload_8514b()) rather than
    __init__ directly, since each device's config (VISA resource, default
    setpoint, etc.) differs. PSU instances (kind=KIND_PSU) wrap InstroPSU
    (BK9115/KeysightN5700 drivers, both single-channel -- confirmed from
    source); the eLoad instance (kind=KIND_ELOAD) wraps InstroELoad
    (BK85XXB driver). These two instro base classes expose DIFFERENT
    methods for conceptually the same operations (set_voltage/
    set_current_limit/output_enable vs set_mode/set_level/output_enable),
    so configure()/read_channel() branch on self.kind rather than
    pretending the two are identical.

    Also owns the shared Phoenix Contact relay current safety ceiling
    (SAFE_CURRENT_CEILING_A) and a generic mutual-exclusion interlock
    (selected()/apply_selection()) -- see their own docstrings below.

    IMPORTANT physical-safety note on the interlock: apply_selection()
    works on any group of instances you pass it. On THIS rig, all three
    devices (BK9115, N5745A, eLoad) go in the SAME group and are fully
    mutually exclusive -- exactly one of the three may ever be driving/
    drawing at a time (see btop_dc_psu.py, which interlocks all three).
    An earlier version of this docstring assumed a PSU + eLoad running
    together (source + sink) was the normal case and should be exempt from
    the interlock -- that assumption was wrong for this rig; all three are
    interlocked here.
    """

    KIND_PSU = "psu"
    KIND_ELOAD = "eload"

    # --- shared relay current safety ceiling ------------------------------
    # The rack's Phoenix Contact relays are rated for 5A. Every current-
    # related setpoint (PSU current_limit_a, eLoad CC-mode level) is
    # checked against SAFE_CURRENT_CEILING_A before being written -- raises
    # ValueError rather than silently clamping (a silent clamp could mask a
    # real test-config mistake; a loud failure can't). 5A is the relays'
    # absolute rating, not a target operating point -- derating by 20%
    # (4A) leaves headroom for overshoot/measurement error/transients
    # before ever reaching the relays' actual limit. Lower it further for
    # more margin; don't raise it above the relay rating.
    PHOENIX_RELAY_MAX_CURRENT_A = 5.0
    SAFE_CURRENT_CEILING_A = 4.0

    # Stream id for any driver script that wants to publish an instance's
    # read_channel() output to Connect via client.stream(STREAM_ID, ...,
    # name=f"{instance.name}_voltage"/f"{instance.name}_current") -- same
    # "class owns STREAM_ID, script owns the actual client.stream() call"
    # split as doDriveControl/diRasterScan/MultiCounterControl above.
    STREAM_ID = "psu_tray"

    log = _log

    def __init__(self, *, kind, cb_id, name, driver_cls, visa_resource, channel=1,
                 voltage_setpoint_v=None, current_limit_a=None,
                 mode=None, level=None, current_read_length=5):
        if kind not in (self.KIND_PSU, self.KIND_ELOAD):
            raise ValueError(f"unknown kind {kind!r}; expected {self.KIND_PSU!r} or {self.KIND_ELOAD!r}")
        self.kind = kind
        self.cb_id = cb_id            # checkbox app-value id, used by apply_selection()
        self.name = name
        self.driver_cls = driver_cls
        self.visa_resource = visa_resource
        self.channel = channel
        self.voltage_setpoint_v = voltage_setpoint_v
        self.current_limit_a = current_limit_a
        self.mode = mode
        self.level = level
        self.current_read_length = current_read_length
        self.voltage_channel_name = f"{name}.ch{channel}.voltage"
        self.current_channel_name = f"{name}.ch{channel}.current"

    # ---- factory classmethods for the three real devices on this rack ----
    @classmethod
    def bk9115(cls):
        """B&K Precision 9115 bench PSU (single-channel). Fixes two real
        bugs found in the original btop_dc_psu.py script this was ported
        from: it never called psu.start() before psu.get_channel()
        (Instrument.get_channel() unconditionally raises RuntimeError
        without a running background daemon -- open() alone does NOT
        start it), and it passed num_channels=2 to a single-channel-only
        driver (every BK9115 method calls _check_channel(), which raises
        ValueError for anything but channel=1).

        visa_resource confirmed directly against the connected unit
        (USB0::0xFFFF::0x9115::800422020766920015::INSTR -> "BK PRECISION,
        9115, 800422020766920015, 0.02-0.02") -- this replaces the
        original loose script's resource string
        (USB0::0xF4EC::0x1430::SPD3XJGQ806726::INSTR), which was for a
        DIFFERENT serial and never actually matched grabVisaIDN/
        idn_output.txt's confirmed BK9115 (serial 800422020766920015)."""
        return cls(
            kind=cls.KIND_PSU,
            cb_id="dev_select_bk9115",
            name="myPSU",
            driver_cls=BK9115,
            visa_resource="USB0::0xFFFF::0x9115::800422020766920015::INSTR",
            voltage_setpoint_v=12.0,
            current_limit_a=0.5,
        )

    @classmethod
    def n5745a(cls):
        """Keysight N5745A bench PSU (single-channel), via instro's
        KeysightN5700 driver (an N5700-series compatibility driver that
        talks the TDK Lambda Genesys SCPI dialect -- confirmed from
        source). visa_resource confirmed directly against the connected
        unit (USB0::0x0957::0x0807::US25D3814E::INSTR -> "Agilent
        Technologies,N5745A,US25D3814E,A.01.08,REV:B"), matching
        grabVisaIDN/idn_output.txt's serial (US25D3814E)."""
        return cls(
            kind=cls.KIND_PSU,
            cb_id="dev_select_n5745a",
            name="n5745a",
            driver_cls=KeysightN5700,
            visa_resource="USB0::0x0957::0x0807::US25D3814E::INSTR",
            voltage_setpoint_v=12.0,
            current_limit_a=0.5,
        )

    @classmethod
    def eload_8514b(cls):
        """B&K Precision 8514B electronic load, via instro's BK85XXB
        driver -- specifically hardware-validated by instro against the
        8514B (confirmed from source). visa_resource confirmed directly
        against the connected unit (ASRL4::INSTR -> "B&K Precision, 8514B,
        803328011797140029, 1.57"), matching grabVisaIDN/idn_output.txt's
        serial (803328011797140029) -- it's a serial/RS232 connection
        (ASRL), same connection type as the instro driver's own worked
        example ("ASRL19::INSTR")."""
        return cls(
            kind=cls.KIND_ELOAD,
            cb_id="dev_select_eload_8514b",
            name="eload_8514b",
            driver_cls=BK85XXB,
            visa_resource="ASRL4::INSTR",
            mode=LoadMode.CC,
            level=1.0,
        )

    # --- eLoad mode-select checkboxes (only meaningful for kind=KIND_ELOAD,
    # same single-select-checkbox idiom as selected()/apply_selection()
    # below -- must match the ids in app.connect) --------------------------
    CB_MODE_CC = "eload_mode_cc"
    CB_MODE_CV = "eload_mode_cv"
    CB_MODE_CR = "eload_mode_cr"
    CB_MODE_CP = "eload_mode_cp"
    MODE_CHECKBOX_ORDER = [CB_MODE_CC, CB_MODE_CV, CB_MODE_CR, CB_MODE_CP]
    MODE_BY_CHECKBOX = {
        CB_MODE_CC: LoadMode.CC,
        CB_MODE_CV: LoadMode.CV,
        CB_MODE_CR: LoadMode.CR,
        CB_MODE_CP: LoadMode.CP,
    }

    # --- eLoad level text boxes (one per mode, since each mode's level is a
    # different physical quantity -- A/V/Ohm/W) and their reasonable caps
    # for THIS rig -- must match the ids in app.connect. These are NOT the
    # 8514B's own hardware limits (it accepts up to 120V/240A/1500W per its
    # datasheet, and CR down to 0.05 Ohm) -- they're deliberately tighter,
    # because the actual sources on this rig (BK9115, N5745A) are never run
    # above the N5745A's own 30V hardware ceiling, and current is already
    # capped at SAFE_CURRENT_CEILING_A by the Phoenix Contact relay limit
    # above. Keeping the eLoad's caps consistent with what this rig's PSUs
    # can actually deliver means a fat-fingered UI value can't command the
    # load to try to sink far more than any connected source here could
    # ever supply.
    LEVEL_FIELD_CC = "eload_level_cc"
    LEVEL_FIELD_CV = "eload_level_cv"
    LEVEL_FIELD_CR = "eload_level_cr"
    LEVEL_FIELD_CP = "eload_level_cp"
    LEVEL_FIELD_BY_MODE = {
        LoadMode.CC: LEVEL_FIELD_CC,
        LoadMode.CV: LEVEL_FIELD_CV,
        LoadMode.CR: LEVEL_FIELD_CR,
        LoadMode.CP: LEVEL_FIELD_CP,
    }
    ELOAD_CV_MAX_V = 30.0        # >= N5745A's own 30V hardware max; BK9115 tops out at 80V but is never run that high here
    ELOAD_CR_MIN_OHM = 0.1       # a hair above the 8514B's own low-range CR floor (0.05 Ohm)
    ELOAD_CR_MAX_OHM = 1000.0    # generous headroom for light-load/high-Z tests, well under the 8514B's own 7.5kOhm high-range ceiling
    ELOAD_CP_MAX_W = ELOAD_CV_MAX_V * SAFE_CURRENT_CEILING_A   # 120W: the most this rig's relay-limited current times its max PSU voltage could ever actually deliver
    # (min, max, unit) per mode -- used both to validate a UI value and to
    # build a clear error message. CC's max intentionally equals
    # SAFE_CURRENT_CEILING_A so a UI-entered CC level can never exceed the
    # same relay-safety ceiling _enforce_relay_safe_current() enforces
    # again (belt-and-suspenders) inside _configure_eload().
    LEVEL_RANGE_BY_MODE = {
        LoadMode.CC: (0.0, SAFE_CURRENT_CEILING_A, "A"),
        LoadMode.CV: (0.0, ELOAD_CV_MAX_V, "V"),
        LoadMode.CR: (ELOAD_CR_MIN_OHM, ELOAD_CR_MAX_OHM, "Ohm"),
        LoadMode.CP: (0.0, ELOAD_CP_MAX_W, "W"),
    }

    def selected_level(self, client, mode=None) -> float:
        """eLoad only: read the text field for `mode` (or self.mode if not
        given -- same optional-explicit-mode idiom as callers needing to
        avoid the stale-self.mode ordering bug documented in
        btop_dc_psu.py), parse it as a float, and validate it against
        LEVEL_RANGE_BY_MODE -- raises ValueError (loud, not a silent clamp
        -- same philosophy as _enforce_relay_safe_current) if the field is
        non-numeric or outside this rig's reasonable cap for that mode.
        Falls back to self.level (this instance's factory default) if the
        field is blank/None, so a headless caller without Connect wired up
        still gets a sane value."""
        mode = self.mode if mode is None else mode
        field_id = self.LEVEL_FIELD_BY_MODE[mode]
        raw = client.get_value(field_id)
        if raw in (None, ""):
            return self.level
        try:
            value = float(raw)
        except (TypeError, ValueError):
            raise ValueError(f"{field_id}: {raw!r} is not a valid number")
        self._enforce_level_range(mode, value, field_id)
        return value

    def selected_mode(self, client) -> LoadMode:
        """eLoad only: return the LoadMode for whichever mode checkbox is
        checked (first if several, same warn-and-pick-first idiom as
        selected() below), or self.mode (this instance's default) if none
        are checked -- so headless/no-UI callers still get a sane mode."""
        checked = [cid for cid in self.MODE_CHECKBOX_ORDER if client.get_value(cid)]
        if not checked:
            return self.mode
        if len(checked) > 1:
            self.log.info(f"WARNING: multiple eLoad modes checked {checked}; "
                          f"using first ({checked[0]})")
        return self.MODE_BY_CHECKBOX[checked[0]]

    # ---- construction/session ---------------------------------------------
    def create_instrument(self):
        """Construct the underlying InstroPSU/InstroELoad instance. Caller
        still must call .open() then .start() before configure()/
        read_channel() -- kept separate (like every DAQ class's
        _create_daq() elsewhere in this file) so callers control ordering
        and can wrap shutdown() in a try/finally."""
        if self.kind == self.KIND_PSU:
            return InstroPSU(
                name=self.name,
                driver=self.driver_cls(visa_resource=self.visa_resource),
                num_channels=1,   # every PSU driver used here is single-channel
            )
        return InstroELoad(
            name=self.name,
            driver=self.driver_cls(visa_resource=self.visa_resource),
        )

    # ---- configure/read/safe_off/shutdown (branch on self.kind) -----------
    def configure(self, instrument, voltage_v=None, current_limit_a=None,
                  mode=None, level=None):
        """Configure and enable this device. PSU args (voltage_v,
        current_limit_a) are ignored for an eLoad instance, and eLoad args
        (mode, level) are ignored for a PSU instance."""
        if self.kind == self.KIND_PSU:
            self._configure_psu(instrument, voltage_v, current_limit_a)
        else:
            self._configure_eload(instrument, mode, level)

    def _configure_psu(self, psu, voltage_v, current_limit_a):
        """Set the current limit BEFORE voltage (so a stale/too-high limit
        is never briefly in effect at the new voltage), then enable
        output. Checks current_limit_a against SAFE_CURRENT_CEILING_A
        first -- raises ValueError rather than silently clamping. Also
        attempts to arm this PSU's own hardware OCP as a backstop (see
        _try_enable_hardware_ocp) -- not every driver supports it."""
        channel = self.channel
        voltage_v = self.voltage_setpoint_v if voltage_v is None else voltage_v
        current_limit_a = self.current_limit_a if current_limit_a is None else current_limit_a

        self._enforce_relay_safe_current(current_limit_a, f"{self.name}.configure current_limit_a")

        psu.set_current_limit(current_limit_a, channel=channel)
        self._try_enable_hardware_ocp(psu, current_limit_a, channel)
        psu.set_voltage(voltage_v, channel=channel)
        psu.output_enable(True, channel=channel)
        self.log.info(f"{self.name} ch{channel}: {voltage_v}V, {current_limit_a}A limit, output ON")

    def _configure_eload(self, eload, mode, level):
        """Set mode BEFORE level -- InstroELoad.set_level()/set_range()
        raise ValueError if no mode has been set yet (confirmed from
        source) -- then enable the input draw. In CC mode, level IS the
        current the load will sink in amperes, checked against
        SAFE_CURRENT_CEILING_A -- raises ValueError rather than silently
        clamping. CV/CP/CR modes don't expose the drawn current as a
        direct parameter here (it depends on the source's own voltage/
        resistance) -- protection there comes from the SOURCE PSU's own
        current_limit_a, already capped by _configure_psu() above."""
        channel = self.channel
        mode = self.mode if mode is None else mode
        level = self.level if level is None else level

        if mode is LoadMode.CC:
            self._enforce_relay_safe_current(level, f"{self.name}.configure level (CC mode)")
        else:
            self._enforce_level_range(mode, level, f"{self.name}.configure level ({mode.value} mode)")

        eload.set_mode(mode, channel=channel)
        eload.set_level(level, channel=channel)
        eload.output_enable(True, channel=channel)
        self.log.info(f"{self.name} ch{channel}: mode={mode.value}, level={level}, input ON")

    def read_channel(self, instrument):
        """One voltage sample (blocks for a fresh sample from the
        background daemon) and the last current_read_length current
        samples (returns immediately with whatever's already buffered) --
        same shape for both PSU and eLoad instances (both extend the same
        Instrument base, confirmed from source).

        Returns (voltage: float, current: list[float]) -- unwrapped from
        the Measurement objects get_channel() actually returns (confirmed
        from instro.lib.publishers.channel_buffer.DequeInMemoryPublisher.
        get(), which packages values as
        Measurement(channel_data={channel_name: [...]})). An earlier
        version of this method returned the raw Measurement objects
        instead -- harmless for a bare print() (which just prints its
        repr), but broken for anything that needs an actual number, like
        client.stream()."""
        voltage_measurement = instrument.get_channel(
            channel_name=self.voltage_channel_name, length=1, wait_for_new_samples=True)
        current_measurement = instrument.get_channel(
            channel_name=self.current_channel_name, length=self.current_read_length,
            wait_for_new_samples=False)
        voltage = float(voltage_measurement.channel_data[self.voltage_channel_name][-1])
        current = [float(v) for v in current_measurement.channel_data[self.current_channel_name]]
        return voltage, current

    def safe_off(self, instrument):
        """Disable output/input draw. Always call this before shutdown()
        so the device isn't left powered/drawing if the script exits
        unexpectedly."""
        try:
            instrument.output_enable(False, channel=self.channel)
        except Exception:
            pass

    def shutdown(self, instrument):
        """Stop the background sampling daemon and close the VISA
        session."""
        try:
            instrument.stop()
        except Exception:
            pass
        try:
            instrument.close()
        except Exception:
            pass

    # ---- shared relay current safety ceiling ------------------------------
    def _enforce_relay_safe_current(self, requested_a, context):
        """Raise ValueError if `requested_a` risks exceeding the rack's
        Phoenix Contact relay rating (see SAFE_CURRENT_CEILING_A's comment
        above for the ceiling's derivation). `context` is prepended to the
        error so it's obvious which call site tripped it."""
        if requested_a > self.SAFE_CURRENT_CEILING_A:
            raise ValueError(
                f"{context}: requested {requested_a}A exceeds the software safety "
                f"ceiling of {self.SAFE_CURRENT_CEILING_A}A (derated from the Phoenix "
                f"Contact relays' {self.PHOENIX_RELAY_MAX_CURRENT_A}A rating) -- refusing "
                f"to configure a level that could damage the relays. Lower the "
                f"requested current, or if you're certain this specific circuit "
                f"never routes through those relays, change SAFE_CURRENT_CEILING_A "
                f"deliberately rather than bypassing this check at the call site."
            )

    def _enforce_level_range(self, mode, level, context):
        """Raise ValueError if `level` falls outside this rig's reasonable
        cap for `mode` (LEVEL_RANGE_BY_MODE) -- same loud-not-silent
        philosophy as _enforce_relay_safe_current, which handles CC mode
        specifically (it's about the Phoenix Contact relay rating, not a
        generic UI-input cap)."""
        min_v, max_v, unit = self.LEVEL_RANGE_BY_MODE[mode]
        if not (min_v <= level <= max_v):
            raise ValueError(
                f"{context}: {level}{unit} is outside this rig's reasonable "
                f"cap of {min_v}-{max_v}{unit} for {mode.value} mode -- "
                f"refusing to configure. Adjust the requested level, or if "
                f"you're certain a wider range is safe for this specific "
                f"test, change LEVEL_RANGE_BY_MODE deliberately rather than "
                f"bypassing this check."
            )

    def _try_enable_hardware_ocp(self, psu, level_a, channel):
        """Best-effort: arm this PSU's own hardware overcurrent protection
        as a backstop behind the software ceiling above. Not every driver
        supports this -- BK9115 supports neither a settable OCP level nor
        an OCP enable (confirmed from source: both raise
        FeatureNotSupportedError); KeysightN5700/TDKLambdaGenesys supports
        enabling OCP but not setting its trip level (confirmed from
        source). Logs and continues rather than failing configure() over a
        hardware feature the specific model doesn't have -- the software
        ceiling above is enforced either way."""
        try:
            psu.set_overcurrent_protection_level(level_a, channel=channel)
            self.log.info(f"Hardware OCP level set to {level_a}A on channel {channel}.")
        except FeatureNotSupportedError:
            self.log.info("This PSU's driver has no settable OCP level -- relying on the "
                          "software current-limit ceiling + set_current_limit() only.")
        except Exception as e:
            self.log.info(f"Unexpected error setting hardware OCP level: {e}")

        try:
            psu.set_overcurrent_protection_enabled(True, channel=channel)
            self.log.info(f"Hardware OCP enabled on channel {channel}.")
        except FeatureNotSupportedError:
            self.log.info("This PSU's driver has no OCP enable at all.")
        except Exception as e:
            self.log.info(f"Unexpected error enabling hardware OCP: {e}")

    # ---- interlock across an arbitrary group of instances ------------------
    @classmethod
    def selected(cls, client, group):
        """Return whichever instance in `group` has its checkbox checked
        (first if several, warning and picking the first -- same idiom as
        MultiCounterControl.selected_checkbox() elsewhere in this file), or
        None if none are checked."""
        checked = [dev for dev in group if client.get_value(dev.cb_id)]
        if not checked:
            return None
        if len(checked) > 1:
            cls.log.info(f"WARNING: multiple devices checked "
                         f"({[d.cb_id for d in checked]}); using first ({checked[0].cb_id})")
        return checked[0]

    @classmethod
    def apply_selection(cls, client, group, sessions, state):
        """Read the checkbox group and, ONLY if the selection changed since
        the last call (tracked in state['last_selected'] -- same "small
        dict this call owns" idiom every continuous headless_tests/*.py
        test uses), enforce it: every OTHER device in `group` gets
        safe_off() BEFORE the newly-selected device gets configure()'d
        (break-before-make), so there's never a moment where two devices in
        the SAME group are both enabled. `sessions` maps each device
        instance -> its already open()+start()'d instrument. Safe to call
        every poll; a no-op once the current selection has already been
        applied. Returns the selected device instance (or None).

        IMPORTANT: only put devices in the SAME `group` call that must
        never run together (see class docstring's physical-safety note --
        e.g. the two PSUs, but NOT a PSU + the eLoad, which normally run
        together on purpose)."""
        selected = cls.selected(client, group)
        if selected is state.get("last_selected", "__unset__"):
            return selected

        prev_name = getattr(state.get("last_selected"), "name", state.get("last_selected"))
        new_name = getattr(selected, "name", None)
        cls.log.info(f"Device selection changed: {prev_name!r} -> {new_name!r}")

        for dev in group:
            if dev is not selected:
                dev.safe_off(sessions[dev])
        if selected is not None:
            selected.configure(sessions[selected])

        state["last_selected"] = selected
        return selected
