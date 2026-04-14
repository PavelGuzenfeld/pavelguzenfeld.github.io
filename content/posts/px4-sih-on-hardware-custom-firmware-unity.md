---
title: "Running PX4 SIH on Real Hardware: Custom Firmware for In-the-Loop Flight Simulation"
date: 2026-04-14
draft: false
tags: ["Unity", "Docker", "PX4", "SITL", "SIH", "MAVLink", "simulation", "headless", "integration-testing", "open-source"]
keywords: ["PX4 SIH custom firmware", "PX4 hardware in the loop", "mavlink-router PX4 serial", "PX4 SIH tailsitter Cube Orange", "PX4 simulator_sih Kconfig", "flash PX4 board_id mismatch", "pymavlink SIH flight test"]
cover:
  image: /images/posts/px4-sih-hardware.png
  alt: "PX4 SIH running on real flight controller hardware with Unity visualization"
categories: ["deep-dive"]
summary: "Getting PX4's Simulation-In-Hardware (SIH) module running on a production flight controller — discovering the firmware doesn't include SIH, building a custom PX4 with flash-trimming, fan-out routing serial MAVLink to both the simulator and ground station, and connecting it all to the Unity visualization pipeline."
ShowToc: true
---

## Context

This is the fifth post in a series about running a Unity simulation headless in Docker:

1. [Running Unity Headless in Docker with GPU Rendering and RTSP Streaming](/posts/headless-unity-docker-simulation/)
2. [From Magenta to Desert: Fixing Cross-Platform Unity Terrain Rendering](/posts/unity6-terrain-rendering-cross-platform-asset-bundles/)
3. [Natural Skies and Satellite Terrain in a Headless Unity Simulation](/posts/unity-headless-environment-satellite-terrain-sky/)
4. [Procedural Settlement: Generating 3D Buildings from OpenStreetMap](/posts/procedural-osm-terrain-buildings-entities-unity/)

Previously I drove the drone with Unity's internal `SimEntity` and `PrimitiveFlightController` — the simulation physics lived entirely inside Unity. Good enough for visualization, but it's not really flight testing. The whole point of this Unity rig is to be a visual front-end for a real autopilot running real flight stack code.

The goal for this post: make the autopilot fly the drone **inside my laptop**, with no external vehicle, no SITL container, no simulator process. Just the flight controller board running PX4 SIH (Simulation-In-Hardware), providing simulated sensor data to its own flight stack and flying simulated physics — all while Unity renders the aircraft.

```
┌──────────────────────────┐       ┌──────────────────────────┐
│  PX4 Hardware (Cube)     │       │  Unity Simulation        │
│  ┌────────────────────┐  │       │                          │
│  │ SIH physics        │  │       │  MavlinkEntity           │
│  │   ↓ simulated IMU  │  │       │    ↓ position            │
│  │ EKF2 → controllers │──┼─USB──►│  Visual model            │
│  │   ↓ setpoints      │  │MAVLink│    ↓ render              │
│  │ SIH physics        │  │       │  RTSP camera streams     │
│  └────────────────────┘  │       │                          │
└──────────────────────────┘       └──────────────────────────┘
```

## Problem 1: Your Firmware Probably Doesn't Have SIH

I connected to the board via pymavlink, checked `AUTOPILOT_VERSION`, and confirmed PX4 v1.17 was running. Then I tried to list SIH parameters:

```python
for p in ['SIH_MASS', 'SIH_IXX', 'SIH_GPS_USED']:
    m.mav.param_request_read_send(1, 1, p.encode(), -1)
    msg = m.recv_match(type='PARAM_VALUE', blocking=True, timeout=2)
    print(f'{p}: {"FOUND" if msg else "NOT FOUND"}')
```

Output:

```
SIH_MASS: NOT FOUND
SIH_IXX: NOT FOUND
SIH_GPS_USED: NOT FOUND
```

All missing. The board reports a valid PX4 version but the SIH module isn't compiled in.

This is the default state for most production flight controllers. SIH is only enabled in a handful of board configs — primarily dev boards meant for software testing. Production boards for Cube Orange, Pixhawk 4/5/6, Durandal and similar ship without SIH to save flash space for real-flight drivers.

You cannot enable SIH with parameters alone. It has to be **compiled into the firmware binary**.

## Problem 2: Identifying Your Board

Before flashing anything, you need the correct firmware. PX4's `.px4` files are board-specific — the bootloader verifies the board_id before accepting the upload.

```python
m.mav.command_long_send(1, 1,
    mavlink.MAV_CMD_REQUEST_MESSAGE, 0,
    mavlink.MAVLINK_MSG_ID_AUTOPILOT_VERSION, 0, 0, 0, 0, 0, 0)
msg = m.recv_match(type='AUTOPILOT_VERSION', blocking=True, timeout=5)
print(f'board_version: {msg.board_version}')
print(f'vendor:product: 0x{msg.vendor_id:04x}:0x{msg.product_id:04x}')
```

Output:

```
board_version: 4118
vendor:product: 0x2dae:0x1016
```

Board version 4118 doesn't match any Pixhawk 6X build in the v1.16.1 release. To map it correctly, I downloaded every `.px4` file from the release and parsed the embedded JSON:

```bash
for url in $(curl -s "https://api.github.com/repos/PX4/PX4-Autopilot/releases/tags/v1.16.1" \
              | grep -o '"browser_download_url": "[^"]*_default\.px4"' \
              | grep -o 'https://[^"]*'); do
  name=$(basename "$url")
  curl -sL --range 0-1024 -o "$name" "$url"
  bid=$(grep -o '"board_id": [0-9]*' "$name" | head -1)
  echo "$name: $bid"
done
```

Board_id 140 turned out to be `cubepilot_cubeorange_default.px4` — a Cube Orange, not a Pixhawk 6X as I'd assumed from the form factor.

Key takeaway: **don't guess the board from the enclosure**. The VID:PID and board_version are authoritative.

## Problem 3: The Stock Firmware Still Doesn't Have SIH

After flashing the stock `cubepilot_cubeorange_default.px4`, SIH params were *still* NOT FOUND. The Cube Orange default config doesn't enable SIH either.

At this point there are three options:

1. **Switch to SITL** — run PX4 in Docker with full software simulation. No hardware in the loop.
2. **Build custom firmware** with SIH explicitly enabled.
3. **Accept reality** — this board can't SIH. Use its real sensors or drop to pure-software simulation.

I chose (2) because the whole point was to exercise the real flight stack binary on the real MCU.

## Building PX4 With SIH Enabled

PX4 uses Kconfig for module selection. SIH's config key is:

```kconfig
menuconfig MODULES_SIMULATION_SIMULATOR_SIH
    bool "simulator_sih"
    default n
    select MODULES_SIMULATION_PWM_OUT_SIM
    select MODULES_SIMULATION_SENSOR_BARO_SIM
    select MODULES_SIMULATION_SENSOR_GPS_SIM
    select MODULES_SIMULATION_SENSOR_MAG_SIM
```

So enabling SIH automatically pulls in simulated barometer, GPS, and magnetometer.

I cloned the repo, edited the board config:

```bash
git clone --depth 1 --branch v1.16.1 --recursive \
  https://github.com/PX4/PX4-Autopilot.git

# Add SIH to Cube Orange default config
cat >> boards/cubepilot/cubeorange/default.px4board << 'EOF'
CONFIG_MODULES_SIMULATION_SIMULATOR_SIH=y
CONFIG_MODULES_SIMULATION_PWM_OUT_SIM=y
CONFIG_MODULES_SIMULATION_SENSOR_BARO_SIM=y
CONFIG_MODULES_SIMULATION_SENSOR_GPS_SIM=y
CONFIG_MODULES_SIMULATION_SENSOR_MAG_SIM=y
EOF
```

Then built in PX4's official Docker image:

```bash
docker run --rm -v $PWD:/src -w /src px4io/px4-dev-nuttx-focal:latest \
  bash -c "git config --global --add safe.directory '*' && \
           make cubepilot_cubeorange_default"
```

First build failed with:

```
region `FLASH' overflowed by 25344 bytes
```

The Cube Orange flash is already near full with standard modules. Adding SIH pushed it over.

### Trimming Modules for Flash Space

Disabled modules I could live without for a simulation-focused build:

```
CONFIG_DRIVERS_UAVCAN=y               →  disable  (~15KB)
CONFIG_MODULES_UXRCE_DDS_CLIENT=y     →  disable
CONFIG_DRIVERS_GNSS_SEPTENTRIO=y      →  disable
CONFIG_DRIVERS_IRLOCK=y               →  disable
CONFIG_DRIVERS_PCA9685_PWM_OUT=y      →  disable
CONFIG_MODULES_TEMPERATURE_COMPENSATION=y → disable
```

A `sed -i 's/^CONFIG_DRIVERS_UAVCAN=y/# &/'` style pass over the board config, one-liner per module to strip. The simulator doesn't need CAN peripherals or DDS bridges.

After trimming, rebuild succeeded:

```
[1151/1153] Linking CXX executable cubepilot_cubeorange_default.elf
[1152/1153] Generating cubepilot_cubeorange_default.bin
[1153/1153] Creating cubepilot_cubeorange_default.px4
```

Firmware size: 1.6MB. Fits comfortably now.

## Flashing Without QGroundControl

QGC is great if you have a display and mouse. For headless deployments or scripting, use PX4's `px_uploader.py`:

```bash
# Trigger bootloader via MAVLink first
python3 -c "
from pymavlink import mavutil
m = mavutil.mavlink_connection('udpout:127.0.0.1:14550',
    source_system=255, source_component=190)
m.mav.heartbeat_send(6, 8, 192, 0, 4, 3)
m.wait_heartbeat(timeout=10)
m.mav.command_long_send(m.target_system, m.target_component,
    mavutil.mavlink.MAV_CMD_PREFLIGHT_REBOOT_SHUTDOWN, 0,
    3, 0, 0, 0, 0, 0, 0)  # param1=3: reboot to bootloader
"

# Immediately run uploader (bootloader only waits ~5s)
python3 px_uploader.py --port /dev/ttyACM0 cubepilot_cubeorange_default.px4
```

Expected output:

```
Waiting for bootloader...
Found board id: 140,0 bootloader protocol revision 5
Loaded firmware for board id: 140,0 size: 1943164 bytes (98.83%)
Erase  : [====================] 100.0%
Program: [====================] 100.0%
Verify : [====================] 100.0%
Rebooting. Elapsed Time 30.847
```

**Backup your params first.** Flashing wipes everything. I used pymavlink to dump all 1151 params to JSON before touching the bootloader:

```python
m.mav.param_request_list_send(target_sys, target_comp)
params = {}
while time.time() - start < 60:
    msg = m.recv_match(type='PARAM_VALUE', blocking=True, timeout=1)
    if msg is None: continue
    name = msg.param_id.rstrip('\x00')
    params[name] = {'value': float(msg.param_value), 'type': int(msg.param_type)}
    if msg.param_index == msg.param_count - 1:
        break
```

If the flash goes wrong, these restore the vehicle-specific tuning. They probably won't all apply cleanly on the new firmware (some params may not exist, some may have different types), but it's a much better starting point than defaults.

## Routing MAVLink to Multiple Consumers

The PX4 USB serial port is a single pipe. But you want three things talking to the autopilot:

- **The Unity simulation** — consumes position/attitude to drive the visual model
- **pymavlink or MAVSDK** — sends commands (arm, takeoff, waypoints)
- **Optionally QGC** — for inspection

Solution: run `mavlink-router` as a broker. Serial input, multiple UDP/TCP endpoints out.

```ini
# main.conf
[General]
TcpServerPort = 5760
ReportStats = false

[UartEndpoint pixhawk]
Device = /dev/ttyACM0
Baud = 115200

[UdpEndpoint unity]
Mode = Normal
Address = 127.0.0.1
Port = 14540

[UdpEndpoint control]
Mode = Eavesdropping
Address = 127.0.0.1
Port = 14550
```

Run it in Docker so you don't need to install it on the host:

```bash
docker run -d --name mavlink-router --network host \
  --device=/dev/ttyACM0:/dev/ttyACM0 \
  -v $PWD/main.conf:/etc/mavlink-router/main.conf \
  mavlink-router mavlink-routerd
```

### The "Eavesdropping vs Normal" Trap

Lost an hour here. mavlink-router has two UDP endpoint modes:

- **Normal** — the endpoint must send a MAVLink packet first before the router knows where to forward data. Good for a client that actively sends heartbeats.
- **Eavesdropping** — the router treats the endpoint as a UDP server and forwards every packet. Good for listeners that just want to receive.

Setting `Mode = Normal` on an endpoint that never sends anything (a pure listener) results in the router silently dropping packets to that endpoint. Symptoms: pymavlink `wait_heartbeat()` times out while the router logs show "N messages to unknown endpoints in the last 5 seconds."

For a pymavlink script that sends its own heartbeat first, `Normal` mode works and the client connects via `udpout://`. For a listener that should receive without sending, use `Eavesdropping`.

## Setting Up SIH

After flashing the custom firmware, SIH_* params exist but SIH isn't running yet — the airframe determines what modules start at boot. PX4 v1.16 includes a SIH tailsitter airframe at autostart ID 1100:

```python
m.mav.param_set_send(1, 1, b'SYS_AUTOSTART',
    struct.unpack('f', struct.pack('i', 1100))[0],
    mavlink.MAV_PARAM_TYPE_INT32)

# Save and reboot to apply
m.mav.command_long_send(1, 1, mavlink.MAV_CMD_PREFLIGHT_STORAGE,
    0, 1, -1, 0, 0, 0, 0, 0)
m.mav.command_long_send(1, 1, mavlink.MAV_CMD_PREFLIGHT_REBOOT_SHUTDOWN,
    0, 1, 0, 0, 0, 0, 0, 0)
```

After reboot, SIH runs. The simulated GPS reports the default SIH home (Zurich). To match the Unity simulation's geographic origin:

```python
m.mav.param_set_send(1, 1, b'SIH_LOC_LAT0', <your_lat>, mavlink.MAV_PARAM_TYPE_REAL32)
m.mav.param_set_send(1, 1, b'SIH_LOC_LON0', <your_lon>, mavlink.MAV_PARAM_TYPE_REAL32)
m.mav.param_set_send(1, 1, b'SIH_LOC_H0',   <your_alt>, mavlink.MAV_PARAM_TYPE_REAL32)
```

Then save + reboot again. Next `GPS_RAW_INT` should arrive at your chosen coordinates.

## What Works, What's Next

What this setup achieves:

- **Real PX4 binary running on real MCU** — same code path as a flight
- **Simulated sensors** generated by SIH physics on the same MCU
- **No host simulator process** — the laptop just handles visualization and MAVLink routing
- **Position data reaches Unity** via the MavlinkEntity + router — 3D model moves with PX4's state

What I haven't nailed down:

- **Mode engagement sequence**: arm succeeds, takeoff command is accepted (result=0), but the drone doesn't climb. The AUTO.TAKEOFF mode transition via `set_mode_send()` doesn't take effect cleanly. PX4 mode switching has specific base_mode+custom_mode encoding that pymavlink's high-level calls don't always handle correctly — next iteration needs raw `MAV_CMD_DO_SET_MODE` with the right bit pattern.

## Lessons

**Your production firmware probably lacks SIH.** Before spending hours debugging "why doesn't SIH work," query `SIH_T_MAX` or similar — if not found, the module isn't compiled in. Flashing won't help unless you build custom.

**Parse `.px4` files to find the right board.** The filename pattern (`cubepilot_cubeorange`, `px4_fmu-v6x`) doesn't always match what the hardware reports. `grep "board_id"` on the JSON gives ground truth.

**Backup params before flashing.** Every time. The backup might not be restorable perfectly, but a reference is better than none.

**mavlink-router is the right tool** for sharing serial MAVLink. Running it in Docker avoids the host install complexity. But learn its endpoint modes — Normal vs Eavesdropping — before wondering why no messages arrive.

**Trim modules aggressively** when building SIH-capable firmware for production boards. UAVCAN, optional GPS drivers, and DDS clients typically account for 20-40KB that you don't need in a simulation context.
