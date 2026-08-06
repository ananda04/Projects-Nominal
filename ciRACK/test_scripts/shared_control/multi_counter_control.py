"""shared_control.multi_counter_control: multi-device pulse counter control."""

import time
from datetime import datetime

from .constants import _log, _RESOURCE_34980A, _POLL_S_SLOW, _STREAM_ID_DIO_TRAY


class MultiCounterControl():
    POLL_S = _POLL_S_SLOW

    # Stream the 34980A CLK output ON/OFF state to Connect for plotting.
    STREAM_ID = _STREAM_ID_DIO_TRAY
    CLK_STATE_NAME = "clk_state"

    # --- 34980A CLK output (edge source) ---------------------------------------
    RESOURCE_34980A = _RESOURCE_34980A
    CLK_SLOT = 8
    CLK_FREQ_HZ = 1000   # clock output frequency

    # Fixed output logic level. LabJacks (T4/T7/T8) are NOT 5V tolerant on
    # their digital inputs, so this stays at the LabJack-safe 3.3V for all
    # sources (including cDAQ/USB-6421, which read 3.3V TTL fine).
    CLK_LEVEL_V = 3.3    # logic "1" output voltage level

    CB_CLK = "clk_enable"

    # --- Checkbox app-value IDs (must match the ids in app.connect) -------------
    CB_T4 = "count_t4"
    CB_T7 = "count_t7"
    CB_T8 = "count_t8"
    CB_USB6421 = "count_usb6421"
    CB_CDAQ = "count_cdaq"

    # --- LabJack config ---------------------------------------------------------
    # CIO2 == DIO18 on T4/T7. Index 8 ("Interrupt Counter") is NOT valid on
    # DIO18 for any of these models -- its capable-pin list is DIO4-9 (T4),
    # DIO0/1/2/3/6/7 (T7), DIO0-15 (T8). Using it here caused LJM error 2553
    # EF_PIN_TYPE_MISMATCH on the T4 (and would fail the same way on T7/T8).
    # Index 7 ("High-Speed Counter") is the correct feature for DIO18/CIO2: it
    # needs no clock-source setup, and DIO18 IS in its capable-pin list for the
    # T4 (shared with async-serial, unused here) and T7 ("always available").
    # See LabJack's DIO-EF table:
    # https://support.labjack.com/docs/13-2-dio-extended-features-t-series-datasheet
    # and https://support.labjack.com/docs/configuring-reading-a-counter
    #
    # T8 exception: the T8's index-7 capable list is DIO6/7/8/10/13/14/15 --
    # DIO18 is not in it (nor in index 8's 0-15 range), so the T8 cannot
    # hardware-count on CIO2/DIO18 at all (confirmed on real hardware: LJM
    # error 2550 EF_DIO_HAS_NO_TNC_FEATURES). Requires a physical rewire of
    # the T8's sense line to a capable pin -- DIO6 (FIO6) is used here since
    # it's free elsewhere in this project and valid for index 7. Move the
    # signal on the rack from the T8's CIO2 terminal to its FIO6 terminal to
    # match. LJ_DIO_OVERRIDES lets a device use a different pin than the
    # LJ_DIO default without touching count_labjack's shared logic.
    LJ_DIO = 18
    LJ_EF_INDEX = 7
    LJ_DIO_OVERRIDES = {
        CB_T8: 6,   # T8 rewired to FIO6/DIO6 -- see note above
    }
    LABJACKS = {
        CB_T4: ("T4", "440020473"),
        CB_T7: ("T7", "470041016"),
        CB_T8: ("T8", "480011030"),
    }

    # --- NI DAQmx config --------------------------------------------------------
    # CountEdges counter task: (counter_channel, source_terminal)
    NI_DEVICES = {
        CB_USB6421: ("Dev1/ctr0", "/Dev1/PFI... (DIO2)"),   # source terminal string below
        CB_CDAQ: ("cDAQ1Mod4/ctr0", "cDAQ1Mod4 (DIO5)"),
    }

    NI_SOURCE = {
        CB_USB6421: "/Dev1/PFI2",
        CB_CDAQ: "/cDAQ1Mod4/PFI5",
    }

    log = _log

    def __init__(self):
        self._clk_state = {"on": False}

    def stream_clk(self, client):
        client.stream(self.STREAM_ID, datetime.now(), 1.0 if self._clk_state["on"] else 0.0,
                      name=self.CLK_STATE_NAME)

    def clk_on(self, inst):
        inst.write(f"SOUR:MOD:CLOC:FREQ {self.CLK_FREQ_HZ},{self.CLK_SLOT}")
        self.check_err_visa(inst, "after CLK FREQ")
        inst.write(f"SOUR:MOD:CLOC:LEV {self.CLK_LEVEL_V},{self.CLK_SLOT}")
        self.check_err_visa(inst, "after CLK LEV")
        # Real mnemonic is SOURce:MODule:CLOCk:STATe -- "CLOC ON" alone (no
        # :STATe) isn't a valid command per the Keysight 34980A Programmer's
        # Reference and was silently doing nothing.
        inst.write(f"SOUR:MOD:CLOC:STAT ON,{self.CLK_SLOT}")
        self.check_err_visa(inst, "after CLK STATe ON")

    def clk_off(self, inst):
        try:
            inst.write(f"SOUR:MOD:CLOC:STAT OFF,{self.CLK_SLOT}")
        except Exception:
            pass

    def check_err_visa(self, inst, context=""):
        err = inst.query("SYST:ERR?").strip()
        self.log.info(f"SYST:ERR? {context} -> {err}")
        return err.startswith("+0")

    def selected_checkbox(self, client):
        """Return the single selected checkbox id (first if several), or None."""
        order = [self.CB_T4, self.CB_T7, self.CB_T8, self.CB_USB6421, self.CB_CDAQ]
        checked = [cid for cid in order if client.get_value(cid)]
        if not checked:
            return None
        if len(checked) > 1:
            self.log.info(f"WARNING: multiple devices checked {checked}; using first ({checked[0]})")
        return checked[0]

    # -------------------------------------------------------------------
    # LabJack counting
    # -------------------------------------------------------------------
    def count_labjack(self, client, cb_id):
        from labjack import ljm

        dev_type, serial = self.LABJACKS[cb_id]
        dio = self.LJ_DIO_OVERRIDES.get(cb_id, self.LJ_DIO)
        handle = ljm.openS(dev_type, "ANY", serial)
        try:
            info = ljm.getHandleInfo(handle)
            self.log.info(f"Opened LabJack {dev_type} (serial {serial}); counting DIO{dio}")

            # Configure DIO-EF edge counter on this device's counting line.
            ljm.eWriteName(handle, f"DIO{dio}_EF_ENABLE", 0)     # disable to (re)configure
            ljm.eWriteName(handle, f"DIO{dio}_EF_INDEX", self.LJ_EF_INDEX)  # 7 = high-speed counter
            ljm.eWriteName(handle, f"DIO{dio}_EF_ENABLE", 1)     # enable

            self.log.info(f"Ready. Counting rising edges on LabJack DIO{dio}.")
            last = None
            while True:
                if self.selected_checkbox(client) != cb_id:
                    self.log.info("Selection changed; stopping LabJack counter.")
                    return
                count = int(ljm.eReadName(handle, f"DIO{dio}_EF_READ_A"))
                if count != last:
                    self.log.info(f"count = {count}")
                    last = count
                self.stream_clk(client)
                time.sleep(self.POLL_S)
        finally:
            try:
                ljm.eWriteName(handle, f"DIO{dio}_EF_ENABLE", 0)
            except Exception:
                pass
            ljm.close(handle)

    # -------------------------------------------------------------------
    # NI DAQmx counting (USB-6421 and cDAQ-9401 share this path)
    # -------------------------------------------------------------------
    def count_nidaqmx(self, client, cb_id):
        import nidaqmx
        from nidaqmx.constants import Edge, CountDirection

        counter_chan, _label = self.NI_DEVICES[cb_id]
        source_term = self.NI_SOURCE[cb_id]

        with nidaqmx.Task() as task:
            task.ci_channels.add_ci_count_edges_chan(
                counter_chan,
                edge=Edge.RISING,
                initial_count=0,
                count_direction=CountDirection.COUNT_UP,
            )

            task.ci_channels[0].ci_count_edges_term = source_term

            task.start()
            self.log.info(f"Ready. Counting rising edges on {counter_chan} (source {source_term}).")
            last = None
            try:
                while True:
                    if self.selected_checkbox(client) != cb_id:
                        self.log.info("Selection changed; stopping NI counter.")
                        return
                    count = int(task.read())
                    if count != last:
                        self.log.info(f"count = {count}")
                        last = count
                    self.stream_clk(client)
                    time.sleep(self.POLL_S)
            finally:
                task.stop()
