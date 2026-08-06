"""shared_control.di_raster_scan_control: digital-input raster scan control."""

from instro.daq import InstroDAQ
from instro.daq.drivers import Keysight34980A
from instro.daq.types import Direction, Logic

from .constants import _log, _RESOURCE_34980A, _MUX_SLOT_34950A, _POLL_S_GENERAL, _STREAM_ID_DIO_TRAY


class diRasterScan():
    # Config
    RESOURCE = _RESOURCE_34980A

    MODULE_SLOT = _MUX_SLOT_34950A
    DIO_BANK = 201  # bank 2 -- where DIO is physically wired

    DI_INPUT_BITS = [2, 3, 4, 5, 6]

    # Aliases (used as channel/stream names when published)
    DI_INPUT_ALIAS = {b: f"di_{b}" for b in DI_INPUT_BITS}

    LOGIC_LEVEL_V = 2.5

    # Timing
    POLL_S = _POLL_S_GENERAL

    STREAM_ID = _STREAM_ID_DIO_TRAY

    log = _log

    def _line(self, bit: int) -> str:
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
        """Configure DI2..DI6 per the schematic pin map as digital inputs."""
        for b in self.DI_INPUT_BITS:
            daq.configure_digital_line(
                direction=Direction.INPUT,
                physical_channel=self._line(b),
                alias=self.DI_INPUT_ALIAS[b],
                logic=Logic.HIGH,
                logic_level=self.LOGIC_LEVEL_V,
            )
        self.log.info("configured: DI2-6 inputs")

    def read_inputs(self, daq) -> dict:
        """Read DI2..DI6 and return {alias: 0/1}."""
        states = {}
        for b in self.DI_INPUT_BITS:
            states[self.DI_INPUT_ALIAS[b]] = int(daq.read_digital_line(channel=self.DI_INPUT_ALIAS[b]).latest)
        return states
