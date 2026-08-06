"""shared_control.counter_34980a_control: 34980A built-in totalizer counter control."""

import pyvisa

from .constants import _log, _RESOURCE_34980A, _MUX_SLOT_34950A, _POLL_S_SLOW


class Counter34980aControl():
    RESOURCE = _RESOURCE_34980A

    MODULE_SLOT = _MUX_SLOT_34950A
    COUNTER_CHANNEL = f"{MODULE_SLOT}301"  # counter 1; use f"{MODULE_SLOT}302" for counter 2

    # Fixed input threshold, in volts. Per LabJack's own T-series datasheet
    # (Appendix A-2), CIO/EIO output impedance is 180 ohms (a fairly weak
    # driver) and their own worked example shows a 180 ohm load pulling the
    # output HIGH down to ~1.65V (vs. 3.3V unloaded) -- Output High Voltage
    # is only guaranteed down to 2.6V typical at 5mA and drops further under
    # heavier loading. Output LOW stays low regardless (0.01-0.75V across
    # the sinking range in that same table). NI's counter/PFI driver doesn't
    # sag like this under the same load, which is the real reason 5V TTL
    # (NI) clears a threshold that 3.3V CMOS (LabJack) may not -- it's a
    # drive-strength/loading difference, not just a nominal voltage one.
    # Dropped from 1.5V to 1.0V for more margin above LOW's worst case
    # (0.75V) while staying safely below even a badly-drooped HIGH like the
    # 1.65V worked example above.
    THRESHOLD_V = 1.0
    POLL_S = _POLL_S_SLOW

    log = _log

    def check_err(self, inst, context=""):
        err = inst.query("SYST:ERR?").strip()
        self.log.info(f"SYST:ERR? {context} -> {err}")
        return err.startswith("+0")

    def safe_query(self, inst, cmd):
        """Query with device-clear recovery so one timeout doesn't desync the session."""
        try:
            return inst.query(cmd).strip()
        except pyvisa.errors.VisaIOError as e:
            self.log.info(f"query {cmd!r} failed ({e}); sending device clear and retrying once")
            try:
                inst.clear()
            except Exception:
                pass
            return inst.query(cmd).strip()

    def configure(self, inst):
        """Select totalize mode on COUNTER_CHANNEL, zero it, and start counting."""
        # Select the totalize function on the counter channel.
        inst.write(f"COUN:FUNC TOT,(@{self.COUNTER_CHANNEL})")
        ok_func = self.check_err(inst, "after COUN:FUNC TOT")

        # Count rising edges.
        inst.write(f"COUN:SLOP POS,(@{self.COUNTER_CHANNEL})")
        self.check_err(inst, "after COUN:SLOP")

        # Gate source: INTernal so the counter free-runs after INITiate rather
        # than requiring an external gate edge. Param is {INTernal|EXTernal}
        # (NOT IMM). [SENSe:]COUNter:GATE:SOURce
        inst.write(f"COUN:GATE:SOUR INT,(@{self.COUNTER_CHANNEL})")
        self.check_err(inst, "after COUN:GATE:SOUR INT")

        # Gate polarity: INVerted so a LOW/floating external gate ENABLES
        # counting. The GATE H terminal is unwired; if the gate still applies
        # in totalize mode, NORMal polarity (count-while-high) would block all
        # counting -- exactly a permanent count=0. {NORMal|INVerted}
        # If you later tie GATE H physically high, switch this back to NORM.
        inst.write(f"COUN:GATE:POL INV,(@{self.COUNTER_CHANNEL})")
        self.check_err(inst, "after COUN:GATE:POL INV")

        # Read without resetting the count (monotonic). {READ|RRESet}
        inst.write(f"COUN:TOT:TYPE READ,(@{self.COUNTER_CHANNEL})")
        self.check_err(inst, "after COUN:TOT:TYPE READ")

        # Input threshold voltage (signal must cross this to register an edge).
        inst.write(f"COUN:THR:VOLT {self.THRESHOLD_V},(@{self.COUNTER_CHANNEL})")
        self.check_err(inst, "after COUN:THR:VOLT")

        # Read the threshold straight back from the instrument rather than
        # trusting that the write succeeded just because SYST:ERR? was clean --
        # a clamped/rounded value would still report no error but wouldn't
        # match what we asked for. Flag loudly if it doesn't match.
        readback = self.safe_query(inst, f"COUN:THR:VOLT? (@{self.COUNTER_CHANNEL})")
        try:
            readback_v = float(readback)
            if abs(readback_v - self.THRESHOLD_V) > 0.01:
                self.log.error(
                    f"Threshold readback mismatch: asked for {self.THRESHOLD_V}V, "
                    f"instrument reports {readback_v}V on channel {self.COUNTER_CHANNEL}. "
                    f"The card is NOT actually configured at the level we intended."
                )
            else:
                self.log.info(f"Threshold readback confirmed: {readback_v}V on channel {self.COUNTER_CHANNEL}.")
        except ValueError:
            self.log.info(f"unexpected COUN:THR:VOLT? response: {readback!r}")

        # Zero the accumulated count.
        inst.write(f"COUN:TOT:CLE:IMM (@{self.COUNTER_CHANNEL})")
        self.check_err(inst, "after COUN:TOT:CLE:IMM")

        # START the counter. With an internal gate, INITiate triggers counting
        # immediately. Without this, a correctly-configured totalizer reads 0.
        inst.write(f"COUN:INIT (@{self.COUNTER_CHANNEL})")
        self.check_err(inst, "after COUN:INIT")

        if not ok_func:
            raise RuntimeError(
                f"COUN:FUNC TOT was rejected on channel {self.COUNTER_CHANNEL} -- the module in "
                f"slot {self.MODULE_SLOT} likely doesn't support counting on this channel (wrong "
                f"module type, or the wrong channel number for a 34950A). The totalizer will read "
                f"0 forever until this succeeds -- check SYST:CTYP? above before re-running."
            )

    def read_count(self, inst):
        """Read the totalizer once. Returns an int count, or None if the response was unparseable."""
        resp = self.safe_query(inst, f"COUN:TOT:DATA? (@{self.COUNTER_CHANNEL})")
        try:
            return int(float(resp))
        except ValueError:
            self.log.info(f"unexpected totalizer response: {resp!r}")
            return None
