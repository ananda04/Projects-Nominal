"""shared_control.do_drive_control: digital-output drive control (DO0/TB_D_OUT)."""

from instro.daq import InstroDAQ
from instro.daq.drivers import Keysight34980A
from instro.daq.types import Direction, Logic

from .constants import _log, _RESOURCE_34980A, _MUX_SLOT_34950A, _POLL_S_GENERAL, _STREAM_ID_DIO_TRAY


class doDriveControl():
    # Config
    RESOURCE = _RESOURCE_34980A

    MODULE_SLOT = _MUX_SLOT_34950A
    DIO_BANK = 201  # bank 2 -- where DIO is physically wired

    DO_DRIVE_BIT = 7  # pin 7 on bank 2 -- confirmed physical wiring for TB_D_OUT

    # Aliases (used as channel/stream names when published)
    DO_DRIVE_ALIAS = "do_drive"

    # Timing
    POLL_S = _POLL_S_GENERAL

    STREAM_ID = _STREAM_ID_DIO_TRAY

    # UI app-value IDs (set these as the ID on the matching Form widgets in Connect)
    DRIVE_LEVEL_ID = "drive_level"

    DRIVE_LEVEL_DEFAULT = 0

    log = _log

    def _line(self, bit: int) -> str:
        """Keysight physical channel string for a single DIO line, e.g. '8101/0'."""
        return f"{self.MODULE_SLOT}{self.DIO_BANK}/{bit}"

    def _create_daq(self):
        """Create and open a fresh 34980A DAQ instance."""
        daq = InstroDAQ(name="dio_tray", driver=Keysight34980A(self.RESOURCE))
        daq.open()
        return daq

    def _assert_34980a(self, daq):
        idn = daq.driver._visa.query("*IDN?").strip()
        self.log.info(f"*IDN? = {idn}")
        if "34980A" not in idn:
            raise RuntimeError(f"Connected device is not a 34980A: {idn!r}")

    def configure_all(self, daq):
        """Configure DO0 per the schematic pin map as a digital output.

        DO0 -> output (drive the DAQs)
        """
        daq.configure_digital_line(
            direction=Direction.OUTPUT,
            physical_channel=self._line(self.DO_DRIVE_BIT),
            alias=self.DO_DRIVE_ALIAS,
            logic=Logic.HIGH,
        )
        # Start in a known-safe state: output low.
        daq.write_digital_line(channel=self.DO_DRIVE_ALIAS, data=0)
        self.log.info("configured: DO0 drive")

    def set_drive(self, daq, level: int):
        """Drive DO0 (TB_D_OUT) high or low to the DAQ modules."""
        daq.write_digital_line(channel=self.DO_DRIVE_ALIAS, data=1 if level else 0)

    def safe_off(self, daq):
        """Drive the output low."""
        try:
            daq.write_digital_line(channel=self.DO_DRIVE_ALIAS, data=0)
        except Exception:
            pass
