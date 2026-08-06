# Hardware CI Rack 

In-house hardware continuous-integration rig for validating Nominal's drivers (benchtop / core / instro) against real instruments before they ship. Signals are routed device-to-device through a Keysight 34980A switch frame so any output can be measured by any input, and the whole rack is driven from Connect apps and instro scripts. There is also support for testing power supplies and electronic loads on this rack.

--- 
## What is the Rack?
The rack is organized into four trays:

- **DC Power Tray** - two isolated 24V domains (CTRL for automation/relays, LOAD for
  instruments), an NI-9472 relay interposer, and a USB-6002 health monitor.
- **PSU Tray** - BK 9115 + Keysight N5745A power supplies and a BK 8514B eLoad on a
  shared source bus, governed by a force-guided ARM relay interlock (one supply on
  the bus at a time, regardless of software).
- **DAQ Tray** - LabJack T4/T7/T8, NI USB-6421, NI cDAQ (9263 AO, 9204/9207 AI),
  NI-9401, and the Keysight 34980A (34923A mux + 34950A DIO).
- **Computer + Network Tray** - the control PC on two networks (corporate + isolated
  rack network).

To access the Hardware CI Rack follow the steps to remote access into the "Instrumentation Lab" computer through google remote desktop. This will allow you to be able to access all the hardware in the aformentioned racks. The ciRACK repo is in the desktop file of this computer - to open the connect app, either start connect, and choose the app.connect file from the Desktop/ciRACK/CI Rack Config/app.connect, or go to the folder following the same path, and double click on app.connect.

---
## Repo Layout

```
ciRACK/
├── CI_RACK.drawio              # Rack wiring/schematic diagram (draw.io)
├── CI Rack Config/             # Nominal Connect app + native device configs
│   ├── app.connect             # Connect app layout: tabs, panes, plots, script controls
│   ├── T4_config.labjack.json  # LabJack T4 native device channel config
│   ├── T7_config.labjack.json  # LabJack T7 native device channel config
│   ├── T8_config.labjack.json  # LabJack T8 native device channel config
│   ├── cdaqMODs.ni-daqmx.json          # NI cDAQ module channel config
│   ├── usb6421.ni-daqmx.json           # NI USB-6421 channel config
│   ├── relay_control.ni-daqmx.json     # Relay control channel config
│   └── health-monitor-usb-6002.ni-daqmx.ni-daqmx.json  # Health-monitor USB-6002 (relay-control lines) config
│
├── test_scripts/                # All Python test/control scripts run from Connect
│   ├── shared_control/           # Shared *Control classes -- used by BOTH Connect scripts and headless_tests/
│   │   ├── __init__.py            # Re-exports all 8 classes (from shared_control import X)
│   │   ├── constants.py           # Shared logger + deduped constants (VISA resource, mux/module slots, poll rates, stream ids)
│   │   ├── psu_control.py         # PSUControl -- interlocked BK9115/N5745A/eLoad control
│   │   ├── ain_ao_control.py      # AIN_AOControl -- analog in/out mux routing
│   │   ├── fgen_diff_control.py   # FGEN_DIFFControl -- FGEN differential sweep
│   │   ├── di_raster_scan_control.py  # diRasterScan -- digital input raster scan
│   │   ├── do_drive_control.py    # doDriveControl -- digital output drive (DO0/TB_D_OUT)
│   │   ├── counter_34980a_control.py  # Counter34980aControl -- 34980A built-in totalizer
│   │   ├── multi_counter_control.py   # MultiCounterControl -- multi-device pulse counter
│   │   └── safe_to_test_control.py    # SafeToTestControl -- relay-safety watcher
│   │
│   ├── btop_dc_psu.py            # Connect script: PSUControl
│   ├── btop_AIN_AOControl.py     # Connect script: AIN_AOControl
│   ├── btop_fgen_diff_control.py # Connect script: FGEN_DIFFControl
│   ├── di_raster_scan.py         # Connect script: diRasterScan
│   ├── do_send_output.py         # Connect script: doDriveControl
│   ├── DAQ_counter.py            # Connect script: MultiCounterControl
│   ├── 34980a_counter.py         # Connect script: Counter34980aControl
│   ├── btop_safe_to_test.py      # Connect script: SafeToTestControl (standalone watcher)
│   ├── clk_off_all.py            # Utility: force CLK output off across the rack
│   ├── diag_relay_state.py       # Utility: diagnostic relay-state dump
│   ├── list_ni_devices.py        # Utility: list connected NI DAQmx devices
│   │
│   ├── headless_rack_control.py          # Standalone (no-Connect) test orchestrator
│   ├── headless_rack_control.config.json # Config for the headless orchestrator
│   └── headless_tests/           # Per-test modules run by headless_rack_control.py
│       ├── __init__.py           # Shared module interface (TEST_ID/KIND/run/teardown)
│       ├── safe_to_test.py       # Runs FIRST -- direct NI-DAQmx relay-safety check (no Connect needed)
│       ├── do_drive.py
│       ├── di_raster_scan.py
│       ├── ain_ao_loopback.py
│       ├── ain_ao_route.py
│       ├── fgen_sweep.py
│       ├── psu_control.py        # Round-robins BK9115 -> N5745A -> eLoad automatically
│       ├── mux_rig.py            # Shared SW_AO_MUX wiring table (fgen_sweep + ain_ao_route)
│       ├── counter_totalize.py   # Present but NOT wired into TEST_MODULES (unused currently)
│       └── multi_counter_clk.py  # Present but NOT wired into TEST_MODULES (unused currently)
│
├── grabVisaIDN/                  # Standalone VISA *IDN? query helpers
│   ├── idnFile.py
│   └── idnRS232.py
│
└── testRackSoft/                 # Dev tooling (Claude agents/skills, SCPI CodeQL queries)
```
---
> **Do NOT commit `.venv/`** - it's gitignored. A committed venv previously broke the
> repo (a 176 MB binary exceeded GitHub's 100 MB limit). Create your own (below).
--- 

##  Getting Started

### Prerequisites
If starting on a completely new test rack computer, be sure to download the following packages to be able to use instro, and connect appropiately: nidaqmx, labjack-ljm, instro, pyvisa, and pyserial. These packages can all be added to via the connect app. Next, clone and set up the the repository, by running:
```bash
git clone https://github.com/nominal-io/ciRACK.git
```

### Sanity check - enumerate instruments
 
Connects to the first USB VISA resource it finds, prompts you for a `device name`, sends `*IDN?`, and appends `device_name, idn_string` to `idn_output.txt`.

Notes:
- If more than one USB instrument is connected, it grabs whichever one `list_resources()` returns first - unplug others if you need a specific device.
- Currently hardcoded with SPD3303X-E-specific serial settings (`\n` termination, 5s timeout) even though it's used across many different instrument models (see `idn_output.txt` for the variety already logged) - works fine for `*IDN?` generically, just don't assume the termination settings are tuned per-device.
- If the query times out, the script's own reminder applies: physically power-cycle the Siglent supply's USB port (a known freeze that a software retry won't fix).

### Usage

```bash
cd grabVisaIDN

# USB / VISA instruments
python idnFile.py

# RS-232 / serial instruments
python idnRS232.py
```
---

## Instrument map (VISA / addresses)

<!-- FILL IN / VERIFY at the rack - these are the values established during bring-up -->

| Instrument | Resource / address | Notes |
|---|---|---|
| Keysight 34980A frame | `USB0::0x0957::0x0507::MY44001757::INSTR` | Confirmed - used identically across 5 classes in `btop_test_suite.py`; matches `idn_output.txt` (`...34980A,MY44001757,...`) |
| Keysight N5745A PSU | `USB0::0x0957::0x0807::US25D3814E::INSTR` | Confirmed - `PSUControl.n5745a()`; matches `idn_output.txt` serial `US25D3814E` |
| BK eLoad (8514B) | `ASRL4::INSTR` | **Corrected** - this is a serial/RS-232 (ASRL) connection, not USB. The address in the draft table was actually the BK 9115's. Confirmed via `PSUControl.eload_8514b()`; matches `idn_output.txt` serial `803328011797140029` |
| BK 9115 PSU | `USB0::0xFFFF::0x9115::800422020766920015::INSTR` | USB. Confirmed via `PSUControl.bk9115()`; matches `idn_output.txt` |
| LabJack T4 / T7 / T8 | serials `440020473 / 470041016 / 480011030` | Confirmed via `MultiCounterControl.LABJACKS`, via LJM |
| NI USB-6421 | `Dev1` (DAQmx) | Confirmed via `usb6421.ni-daqmx.json` - all AI channels configured `terminal_config: rse` (single-ended) |
| NI cDAQ | `cDAQ1Mod1` = NI 9263 (AO) · `cDAQ1Mod2` = NI 9204 (AI) · `cDAQ1Mod3` = NI 9207 (AI) · `cDAQ1Mod4` = NI 9401 (DIO) | Confirmed via `cdaqMODs.ni-daqmx.json` - exact module-to-slot mapping |

---
## Running the tests

### Via the Connect app (manual)
1. Load `CI Rack Config/app.connect`.
2. Load the device configs (health monitor USB-6002 + relay control NI-9170) and
   start streaming.
3. Run **safe-to-test** first (see below).
4. Use the per-tab controls (checkboxes + port lists) to run each test.

### Test cases
| Test | What it does |
|---|---|
| Analog In/Out | Each AO routed onto COM on keysight switch, read back by every AI |
| FGEN | One source fanned to two tied channels (4021/4022) |
| DIFF | AO driven across the TB_AO_DIF+/- pair into a differential input |
| Loopback | A device's own AO wired back to its AI, bypassing the mux |
| Digital I/O | 34950A patterns at varying bit widths read by each DAQ |
| Counter In (DAQ→SW) | DAQ pulse train totalized by the 34950A |
| Counter Out (SW→DAQ) | 34950A CLK counted by each DAQ |
| PSU Tray | Control/sense of BK 9115, N5745A, BK 8514B eLoad |
| DC Power Tray | Sense of Phoenix contact relays to check for safe to test | 
---
## Safe-to-test procedure

**Always run before any test actuates hardware.** Reads the USB-6002 health monitor
and confirms the rack is in a known-good state.

- Each supply's on-state line reads **LOW** (NO contact closes when operational →
  a HIGH means the feeding breaker tripped).
- If anything is off, **halt** - do not toggle blind.

---
## Headless (Config Based) Testing

## headless_rack_control.config.json

Config file for `headless_rack_control.py` - the standalone (no Connect app) test orchestrator. It's read once at startup from the same directory as the script (`headless_rack_control.config.json`, next to `headless_rack_control.py`), with a couple of retries on read errors since this file gets synced onto the actual test machine and can occasionally be read mid-sync (see the JSON-parsing retry logic in `_read_config_json`).

### Fields

| Field | Type | Default if omitted | Notes |
|---|---|---|---|
| `dataset_rid` | string or `null` | none - a fresh dataset is created each run | Set this to reuse the same Nominal Core dataset across runs instead of creating a new one every time. |
| `dataset_name` | string | `"Hardware CI RACK stream"` | Display name for the dataset (only used when `dataset_rid` is omitted). |
| `asset_rid` | string or `null` | none - data still streams, just not organized under a Run/Asset | The one persistent Asset every test's Run gets tied to. |
| `drivers` | `"all"` or list | - (required, but `"all"` is fine) | Which drivers are enabled. Valid values: `keysight_34980a`, `labjack`, `ni_daqmx`. |
| `tests` | `"all"` or list | - (required, but `"all"` is fine) | Which tests to run, and in this fixed order: `do_drive`, `di_raster_scan`, `ain_ao_loopback`, `ain_ao_route`, `fgen_sweep`. |
| `test_duration_s` | number | `60.0` | How long each *continuous* test runs before moving to the next. Doesn't apply to `do_drive` (one-shot, runs to its own natural completion). |

`"all"` for `drivers`/`tests` also accepts any string starting with "all" case-insensitively (e.g. `"All Supported Drivers"`). A list is validated strictly - an unrecognized id raises an error rather than being silently skipped. 


**Heads up:** This script is currently still in test - more test need to be added to btop_test_suite.py and the headless scripts, including a safe-to-test script and psu control. 

### Current repo config

```json
{
    "dataset_rid": "ri.catalog.cerulean-staging.dataset.4db6e212-c5ce-4c76-993c-90c95561477f",
    "dataset_name": "Hardware CI RACK stream",
    "asset_rid": "ri.scout.cerulean-staging.asset.18bde477-8abc-4bc1-818c-f16bdb08819d",
    "drivers": "all",
    "tests": "all"
}
```
**NOTE:** Make sure tosend all data to the same dataset and asset - all runs show be recorded to core. The headless script has been set up this way in case seperate datasets need to be made, but in general datasets and asset rid's should remain constant.

### Running

```bash
cd test_scripts
python headless_rack_control.py
```

Prints the dataset/Run URLs as it goes, then runs each enabled test strictly one at a time, start to finish, before moving to the next - nothing interleaves. 

### Steps to adding more tests
1. Create `headless_tests/my_new_test.py` implementing the interface above. Follow an existing file as a template: `do_drive.py`/`di_raster_scan.py` if your test uses the shared 34980A `daq`, or `psu_control.py`/`safe_to_test.py` if it opens its own independent hardware session instead.
2. If `REQUIRED_DRIVER` isn't one of the existing driver ids (`keysight_34980a`, `labjack`, `ni_daqmx`, `psu`), add the new id to `ALL_DRIVERS` in `headless_rack_control.py`.
3. In `headless_rack_control.py`, add your module to the `from headless_tests import (...)` block.
4. Add it to the `TEST_MODULES` list, in whatever position reflects the run order you want — order matters, since tests run strictly one at a time, start to finish, never interleaved (`safe_to_test` is first for exactly this reason).


---
## Known Issues & Gotchas
hese cost real debugging time - read before you repeat them.

- **34923A wire mode.** Card must be 2-wire to match the terminal block. `WIRE:MODE` SCPI was rejected on this firmware; set it via the **front panel** (select slot -> Module → 2-Wire) then **power cycle**. Verify with `SYST:CTYP? 4` (want `34923A`, not `34923A-1W`).
- **NI AI terminal config.** The mux outputs are **single-ended** - set NI AI tasks to **RSE** (not Differential), or you get a ~-5V offset pedestal. Differential mode is only for the DIFF test.
- **Floating-common bias.** COM-High floats to ~1.4V when nothing drives it; a 100kΩ–1MΩ bleed from COM-High to TB_AGND defines the node. This resistor is already placed between COM-HIGH and COM-LOW.
- **`.venv` in git.** Never commit it (see repo layout note).
- more to come!
---

## Relevant Notion Documents
- [A Comprehensive Guide on the Control of the Hardware CI Rack](https://app.notion.com/p/nmnl/A-Comprehensive-Guide-on-the-Control-of-the-Hardware-CI-Rack-3a49462a2d2e80498a39f9c6cc0d0e56?source=copy_link)
- [Office Dogfood Display Setup](https://app.notion.com/p/Office-Dogfood-Display-Setup-2f79462a2d2e802f83fee157fc26c7cc?source=copy_link)
- [Hardware Test Rack V1 - Continued](https://app.notion.com/p/nmnl/Hardware-Test-Rack-V1-Continued-3869462a2d2e805eaacad93402f4b415?source=copy_link)
- [Hardware Test Rack v1](https://app.notion.com/p/nmnl/Hardware-Test-Rack-v1-3829462a2d2e80d7b44fea0d90174f80?source=copy_link)
