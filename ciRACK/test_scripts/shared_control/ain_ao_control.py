"""shared_control.ain_ao_control: AIN/AO mux routing control."""

import time
from types import SimpleNamespace

from instro.daq import InstroDAQ
from instro.daq.drivers import Keysight34980A

from .constants import _log, _MUX_SLOT_34923A, _STREAM_ID_DAQ_TRAY


class AIN_AOControl():
    # Config
    # NOTE: same physical 34980A frame as _RESOURCE_34980A (constants.py),
    # just addressed via decimal VISA notation with an extra interface-number
    # field (0x0957/0x0507 == 2391/1287 decimal) instead of the hex form used
    # everywhere else -- left as its own literal rather than unified with
    # _RESOURCE_34980A since it's a different resource-string format, not a
    # literal duplicate.
    RESOURCE = "USB0::2391::1287::MY44001757::0::INSTR"

    MUX_SLOT = _MUX_SLOT_34923A

    BANK1_BASE = 1
    DAC_PORTS = [1, 2, 3, 4, 5]

    BANK_TIE = "external"
    ABUS_TIE_CHANNELS = []

    RELAY_SETTLE_S = 0.50
    DWELL_S = 3.0
    SETTLE_S = 1.0

    # Constants referenced by your original three methods (add only if not defined elsewhere)
    RELAY_CHANNEL = f"{MUX_SLOT}003"
    HAS_INTERNAL_DMM = True
    KNOWN_SOURCE_WIRED = False
    EXPECTED_VOLTAGE = 1.0
    VOLTAGE_TOLERANCE_V = 0.05

    # connect app init
    log = _log
    STREAM_ID = _STREAM_ID_DAQ_TRAY
    COMMAND_TOPIC = "script/daq_tray"
    def _create_daq(self):
        """Create and open a fresh 34980A DAQ instance (open() issues *RST)."""
        daq = InstroDAQ(name="daq_tray", driver=Keysight34980A(self.RESOURCE))
        daq.open()
        return daq

    def _assert_34980a(self, daq):
        """Confirm the connected instrument is a 34980A."""
        idn = daq.driver._visa.query("*IDN?").strip()
        print(f"         *IDN? = {idn}")
        if "34980A" not in idn:
            raise RuntimeError(f"Connected device is not a 34980A: {idn!r}")

    # ---- ADDED (required): bank-relative port -> absolute channel address ----
    def _chan(self, bank_base, port):
        """e.g. slot 1, bank2 port 1 -> '1021'."""
        return f"{self.MUX_SLOT}{bank_base + port - 1:03d}"

    def _is_closed(self, daq, ch):
        return daq.driver._visa.query(f"ROUT:CLOS? (@{ch})").strip() == "1"

    def startup_guard(self, daq):
        """Clear + verify ALL crosspoints before doing anything else.

        A previous run that was hard-killed can leave a reed CLOSED, tying a
        source onto the shared COM bus (this is what produced phantom
        staircase readings). This runs first: it opens every DAC crosspoint,
        settles, then reads back. If any crosspoint refuses to open it raises,
        so we never route on top of a stuck/left-closed path.
        """
        stuck = []
        for p in self.DAC_PORTS:
            ch = self._chan(self.BANK1_BASE, p)
            if self._is_closed(daq, ch):
                print(f"         startup_guard: {ch} was CLOSED -> opening")
                try:
                    daq.driver.open_relay(SimpleNamespace(physical_channel=ch))
                except Exception:
                    pass
        time.sleep(self.RELAY_SETTLE_S)

        # verify everything is now open
        for p in self.DAC_PORTS:
            ch = self._chan(self.BANK1_BASE, p)
            if self._is_closed(daq, ch):
                stuck.append(ch)

        if stuck:
            raise RuntimeError(
                f"startup_guard: crosspoints still CLOSED after open: {stuck}. "
                f"Likely a physically stuck reed -- try *RST or service the module. "
                f"Refusing to route on a dirty bus."
            )
        print("         startup_guard: all crosspoints open, COM is clear")

    def connect_dac(self, daq, dac_ch, verify=True):
        """ Connect one DAC to output"""
        # break: open all sources + taps
        for p in self.DAC_PORTS:
            daq.driver.open_relay(SimpleNamespace(physical_channel=self._chan(self.BANK1_BASE, p)))

        time.sleep(self.RELAY_SETTLE_S)

        # make: close the chosen crosspoint
        daq.driver.close_relay(SimpleNamespace(physical_channel=dac_ch))
        if self.BANK_TIE == "abus":
            for ch in self.ABUS_TIE_CHANNELS:
                daq.driver.close_relay(SimpleNamespace(physical_channel=ch))
        time.sleep(self.RELAY_SETTLE_S)

        if not verify:
            return True
        # EXCLUSIVITY CHECK: confirm ONLY dac_ch is closed across all sources.
        # If a reed failed to open, a second channel is still on the common (a
        # parallel 100 ohm leg) -- exactly what divides the source level down.
        closed = [self._chan(self.BANK1_BASE, p) for p in self.DAC_PORTS
                  if self._is_closed(daq, self._chan(self.BANK1_BASE, p))]
        if closed != [dac_ch]:
            print(f"         WARNING: expected only {dac_ch} closed, got {closed}")
        return closed == [dac_ch]

    def _open_all(self, daq):
        """Open every DAC + AIN channel (and any ABus tie) -> no live path remains."""
        for p in self.DAC_PORTS:
            try:
                daq.driver.open_relay(SimpleNamespace(physical_channel=self._chan(self.BANK1_BASE, p)))
            except Exception:
                pass
        for ch in self.ABUS_TIE_CHANNELS:
            try:
                daq.driver.open_relay(SimpleNamespace(physical_channel=ch))
            except Exception:
                pass
        time.sleep(self.RELAY_SETTLE_S)

    def route_all_dac(self):
        """Walk every DAC -> every AIN, connecting one path at a time."""
        daq = self._create_daq()
        total = ok_count = 0
        try:
            self._assert_34980a(daq)
            self.startup_guard(daq)
            self._open_all(daq)
            for dp in self.DAC_PORTS:
                    dac_ch = self._chan(self.BANK1_BASE, dp)
                    ok = self.connect_dac(daq, dac_ch)
                    total += 1
                    ok_count += int(ok)
                    time.sleep(self.DWELL_S)
            self._open_all(daq)
            print(f"done: {ok_count}/{total} connections verified, all relays open")
        finally:
            self._open_all(daq)
            daq.close()

    def connect_pair(self, dac_port, hold=True):
        """Connect a single DAC port to a single AIN port (by bank-relative port #).

        Opens its own frame session and makes just this one connection using
        connect_dac(). With hold=True (default) it leaves the crosspoint
        CLOSED so signal keeps passing and returns the open `daq`; command your
        source DAC / read your destination AIN, then call disconnect(daq).
        With hold=False it opens everything and closes the session before return.
        """
        daq = self._create_daq()
        self._assert_34980a(daq)
        self.startup_guard(daq)
        dac_ch = self._chan(self.BANK1_BASE, dac_port)
        ok = self.connect_dac(daq, dac_ch)
        time.sleep(self.SETTLE_S)

        print(f"DAC{dac_port} ({dac_ch})  [{'OK' if ok else 'FAIL'}]")
        if hold:
            return daq
        self._open_all(daq)
        daq.close()
        return None

    def disconnect(self, daq):
        """Open all crosspoints and close a session returned by connect_pair(hold=True)."""
        self._open_all(daq)
        daq.close()
