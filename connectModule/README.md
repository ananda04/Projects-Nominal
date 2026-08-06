# Connect Serial-to-Ethernet Node

Standalone hardware adapter that bridges legacy test rack equipment (RS-232 / SCPI) to the Nominal Connect ecosystem via Ethernet. By running an embedded instance of Connect Engine directly on the node, it offloads driver execution and enables a no-code setup for test instrumentation.

## Implementation & Demo

The final implementation was scaled to run on a Raspberry Pi Compute platform running Linux. This preserved full Rust standard library (`std`) support, dynamic driver loading, and rapid SSH deployment without requiring a re-architecture of Connect Engine.

* Demo Video: https://youtu.be/hmSoeRTddCs?si=SxnHFOz03OIot3RP

## Key Hardware Specifications

* Power Input: 9–30V DC via 2-pin screw terminals (Buck converter rated up to 60V for potential future PoE support).
* Serial Interface: Male DB9 connector supporting RS-232 levels via MAX3232 transceiver.
* Network Interface: 100 Mbps RJ45 Ethernet using a W5500 SPI controller.
* Compute & Storage: Raspberry Pi Zero 2 W (Quad-core ARM Cortex-A53) with MicroSD for local OS and logging.

## Circuit Summary

* Power Subsystem: 9–30V DC input -> 4-60V Buck Converter (5V output) -> AMS1117-3.3 LDO (3.3V rail for level shifters and PHY).
* Serial Communication: DB9 RS-232 (+/-15V) converted to 3.3V logic via MAX3232 transceiver to Pi UART.
* Network Subsystem: W5500 IC offloads TCP/IP processing over SPI to the Pi, outputting via an integrated magnetics RJ45 jack.

## Software & Workflow

1. Stack: Raspberry Pi OS (Linux) running Connect Engine (compiled in Rust) integrated with Nominal Data Link for telemetry and commanding.
2. Setup: Connect DB9 to target instrument, attach Ethernet, and apply 9–30V DC power.
3. Usage: Locate node in Nominal Connect UI, configure instrument protocol, and control hardware without custom code.

