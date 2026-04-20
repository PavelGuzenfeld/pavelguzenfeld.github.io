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

## Setting Up SIH: The Airframe ID

After flashing the custom firmware, SIH params exist but SIH isn't running yet — the airframe determines what modules start at boot. The naming convention assumes `1100` is the SIH tailsitter, but that's wrong. Listing actual ROMFS airframes via MAVLink shell:

```
ls /etc/init.d/airframes
...
1001_rc_quad_x.hil
1101_rc_plane_sih.hil
1102_tailsitter_duo_sih.hil
1103_standard_vtol_sih.hil
...
```

Airframe **1102** is the SIH tailsitter (not 1100). Setting the wrong ID silently does nothing — PX4 boots into a broken state where no airframe init runs.

```python
# Correct: SIH Tailsitter Duo
set_int('SYS_AUTOSTART', 1102)
```

## The `set-default` Trap

The airframe script `1102_tailsitter_duo_sih.hil` contains the critical line:

```bash
# set SYS_HITL to 2 to start the SIH and avoid sensors startup
param set-default SYS_HITL 2
```

**`param set-default` only sets the value if the parameter is at its current default.** If `SYS_HITL` was previously set to 0 (or anything else) by a prior config or boot, the `set-default` is a no-op. The SIH module never starts, the drone has no simulated sensors, nothing works — and there's no error message.

Fix: force-set every param from the airframe script via MAVLink `PARAM_SET`:

```python
# Replay the entire 1102 script — forcing every value
set_int('SYS_HITL', 2)             # the critical flag
set_int('SIH_VEHICLE_TYPE', 2)     # tailsitter
set_int('CA_AIRFRAME', 4)          # Tailsitter VTOL
set_int('CA_ROTOR_COUNT', 2)       # duo
set_int('VT_MOT_COUNT', 2)
set_int('VT_TYPE', 0)
set_int('MAV_TYPE', 19)
# ... all the motor positions, servo configs, physics params, etc.
```

Symptoms of this bug that took hours to track down: arm succeeds, takeoff commanded, mode switches to TAKEOFF, but AGL stays at 0m forever. Control allocator reports `CA_ROTOR_COUNT=0` — no motors are configured, so there's nothing to command.

## The Counter-Rotating Motor Bug

With the airframe fully configured, the drone lifts off but immediately **tumbles on the Z axis** — spinning wildly around the yaw axis. Cause: the airframe script sets both motors with the same torque direction:

```bash
param set-default CA_ROTOR0_KM -0.05
param set-default CA_ROTOR1_KM -0.05
```

A tailsitter duo has two motors that must counter-rotate so yaw torques cancel. Same `KM` on both motors means both propellers produce yaw in the same direction — the vehicle spins uncontrollably.

Fix: opposite signs.

```python
set_float('CA_ROTOR0_KM',  0.05)  # CW
set_float('CA_ROTOR1_KM', -0.05)  # CCW
```

This might be a bug in the v1.16.1 SIH tailsitter script, or it's intentionally wrong so you have to set real motor directions yourself. Either way — check `KM` signs when adding any multi-rotor SIH airframe.

## Tuning for Stable Hover

Even with physics engaging and yaw balanced, the tailsitter oscillates in altitude. Default SIH params for the duo:

```
SIH_MASS    = 0.2 kg
SIH_T_MAX   = 2.0 N  (per motor → 4 N total)
SIH_IXX     = 0.00354
SIH_IYY     = 0.000625
SIH_IZZ     = 0.00300
```

With 0.2 kg × 9.81 = 1.96 N weight and 4 N max thrust, the thrust-to-weight ratio is only 2:1. That's too tight for stable altitude hold — the controller saturates trying to hover. Bumping `SIH_T_MAX` to 5 N per motor gives 5:1 T/W and much better hover authority.

The control gains also need to match the tiny inertias. The defaults (MC_PITCH_P=6.5, MC_PITCHRATE_P=0.15) are tuned for larger vehicles. For a 0.2 kg tailsitter I used:

```
MC_PITCH_P         = 5.0
MC_ROLL_P          = 5.0
MC_PITCHRATE_P     = 0.08
MC_ROLLRATE_P      = 0.08
MPC_THR_HOVER      = 0.4
MPC_TKO_SPEED      = 0.5
```

With this, the drone climbs smoothly to the target altitude and holds ±0.5 m in simulated wind. Not competition-grade but fully functional for integration testing.

## Locating SIH Home

The default SIH home is Zurich (47.397, 8.546, 489 m). To match a different geographic origin for the visualization:

```python
set_float('SIH_LOC_LAT0', <your_lat>)
set_float('SIH_LOC_LON0', <your_lon>)
set_float('SIH_LOC_H0',   <your_alt>)
```

Save and reboot. Next `GPS_RAW_INT` arrives at the configured location.

## Router Reliability

During PX4 reboots (every airframe change), the USB serial drops and `mavlink-router` crashes with:

```
poll error for fd 4
Critical fd 4 got error, exiting
```

Run the router with `--restart always` so it automatically reconnects when the serial port reappears:

```bash
docker run -d --name mavlink-router --network host \
  --device=/dev/ttyACM0:/dev/ttyACM0 \
  --restart always \
  -v $PWD/main.conf:/etc/mavlink-router/main.conf \
  mavlink-router mavlink-routerd
```

Otherwise every param-set-and-reboot cycle requires manually restarting the router.

## Flying Around: Mission vs DO_REPOSITION

After getting stable hover, the next question was: can the drone actually fly a waypoint pattern? This exposed two more traps.

### Sandbox REST `/takeoff` Doesn't Talk to PX4

The Unity simulation exposes a local HTTP API for commanding entities (`POST /takeoff/0:0:1`, `POST /waypoint/action/...`). Those endpoints work for `SimEntity` vehicles with internal flight controllers. But for a `MavlinkEntity` driven by an external autopilot, the REST layer can't find a matching controller and logs:

```
Simple REST Server - Requested URL: /takeoff/0:0:1
Invoker: /takeoff/0:0:1
FlightController not found!
```

The command is silently swallowed. Nothing goes over MAVLink, nothing moves.

Fix: command the real autopilot directly via MAVLink. The Unity side is a pure visualizer for MavlinkEntity drones — it has no authority to command anything.

### Upload-and-Run Missions Get Stuck at WP0

First pattern I tried: upload a mission with a takeoff WP at index 0 plus N waypoints, then `SET_MODE` → AUTO.MISSION. The drone armed, took off, reached altitude... and hovered forever at WP0:

```
t=11.6s  WP current=0
t=22.6s  WP current=0
t=33.6s  WP current=0   ← still on takeoff WP after 22s
```

The AUTO.TAKEOFF command I'd issued before uploading the mission put the vehicle into its own takeoff state machine. Switching into AUTO.MISSION afterwards restarts mission execution from `current_seq=0` — which *is* the already-completed takeoff. Never advances to WP1.

Fix: skip the mission abstraction entirely and drive the vehicle with `DO_REPOSITION` commands.

```python
def goto(lat, lon, alt_asl):
    m.mav.command_int_send(
        m.target_system, m.target_component,
        mavlink.MAV_FRAME_GLOBAL,
        mavlink.MAV_CMD_DO_REPOSITION,
        0, 0,
        -1.0,          # speed: -1 = default
        1,             # bitmask: ground speed
        0,             # radius (ignored)
        float('nan'),  # yaw: leave as-is
        int(lat * 1e7),
        int(lon * 1e7),
        alt_asl,
    )

# Fly a box around home
for lat, lon in box:
    goto(lat, lon, home_alt + 30)
    wait_until_within(5, lat, lon)  # 5m threshold
```

`DO_REPOSITION` bypasses mission-state bookkeeping entirely. Each call is a single "go here" nudge to the position controller. The vehicle accepts it in LOITER/HOLD mode and the flight controller just flies there.

Also note: before issuing the first `DO_REPOSITION`, switch the vehicle to **AUTO.LOITER** (main=4 sub=3), NOT AUTO.MISSION. LOITER is the clean "accept external position commands" mode; MISSION fights with you.

### End-to-End: Arm → Takeoff → Box → RTL

Full working flight sequence:

1. `MAV_CMD_COMPONENT_ARM_DISARM` (param1=1)
2. `MAV_CMD_NAV_TAKEOFF` to `home_alt + 30`
3. Wait for AGL ≥ 25m
4. `MAV_CMD_DO_SET_MODE` → base=CUSTOM, main=4 (AUTO), sub=3 (LOITER)
5. For each waypoint: `MAV_CMD_DO_REPOSITION` (frame=GLOBAL, alt=ASL), then poll `GLOBAL_POSITION_INT` until within 5m
6. `MAV_CMD_NAV_RETURN_TO_LAUNCH`
7. Wait for `HEARTBEAT.base_mode & 128 == 0` (disarm = landed)

A ~110m × 110m box at 30m AGL with four corners + return-to-home took about 2 minutes end-to-end. Altitude drifted up to ~50m during reposition (the tailsitter's position controller is still coarse on the vertical axis) but the horizontal track was clean.

### Param Drift on Reboot

Worth calling out: after a PX4 reboot — even with the custom firmware and correct airframe 1102 loaded — several of the airframe-init params had reverted:

```
CA_AIRFRAME     = 0       ← should be 4 (tailsitter)
CA_ROTOR1_KM    = 0.05    ← should be -0.05 (counter-rotate)
CA_ROTOR1_PY    = 0.0     ← should be -0.2 (left-motor geometry)
SIH_T_MAX       = 2.0     ← should be 5.0 for T/W=5:1
```

Same `set-default` trap as before: airframe scripts replay on boot but silently skip any param that already has a non-default value in the EEPROM. The fix is the same — force-set every airframe param via `PARAM_SET` at every session, or make it part of a bring-up script that always runs before the first arm attempt.

## What Works Now

End-to-end working path:

- PX4 binary runs on real Cube Orange hardware
- Custom firmware includes SIH module + VTOL attitude controller
- Airframe 1102 configures tailsitter duo + control allocator
- `SYS_HITL=2` activates the SIH simulation
- SIH produces simulated GPS, IMU, baro, mag
- EKF2 fuses simulated data → state estimate
- Flight controller commands motors → SIH physics integrates
- MAVLink telemetry flows through router → Unity visualization
- Unity drone model tracks the PX4-reported position
- `DO_REPOSITION` waypoints produce actual lateral motion; box pattern + RTL flies to completion

Autonomous takeoff, hover at altitude, `HOLD` mode station-keeping, multi-waypoint flight, and return-to-launch all work.

## Lessons

**Your production firmware probably lacks SIH.** Before spending hours debugging "why doesn't SIH work," query `SIH_T_MAX` or similar — if not found, the module isn't compiled in. Flashing won't help unless you build custom.

**Parse `.px4` files to find the right board.** The filename pattern (`cubepilot_cubeorange`, `px4_fmu-v6x`) doesn't always match what the hardware reports. `grep "board_id"` on the JSON gives ground truth.

**Backup params before flashing.** Every time. The backup might not be restorable perfectly, but a reference is better than none.

**mavlink-router is the right tool** for sharing serial MAVLink. Running it in Docker avoids the host install complexity. But learn its endpoint modes — Normal vs Eavesdropping — before wondering why no messages arrive.

**Trim modules aggressively** when building SIH-capable firmware for production boards. UAVCAN, optional GPS drivers, and DDS clients typically account for 20-40KB that you don't need in a simulation context.

**List the actual airframes in your firmware.** Don't assume documented airframe IDs exist in your build. `ls /etc/init.d/airframes` over MAVLink shell is the source of truth. ID 1100 in v1.16.1 is `rc_quad_x` (regular sensors), not SIH — the SIH tailsitter is 1102.

**`param set-default` is treacherous.** Airframe scripts use it so values can be user-overridable, but when you flash a board that previously had different values, the script silently fails to configure anything. Force-replay every airframe param via explicit MAVLink `PARAM_SET` calls instead of trusting the script's `set-default` lines.

**Check `CA_ROTOR_COUNT` after airframe init.** If it's 0, the control allocator has no motor config — arm will pass but no thrust will ever output. Single best signal for whether the airframe actually loaded.

**Verify counter-rotating motors.** For any multi-rotor with an even number of motors, opposing motors must have opposite `CA_ROTOR_KM` signs or the vehicle tumbles on yaw. Some SIH example scripts ship with both motors same-sign. Symptoms: drone lifts off and spins around Z uncontrollably within 1-2 seconds.

**Tailsitter hover needs 4:1 T/W minimum.** The default `SIH_T_MAX=2.0` with 0.2 kg mass gives only 2:1 — good luck holding altitude. Bumping to 5 N per motor (5:1 total) makes altitude hold behave.

**Run the router with `--restart always`.** Every PX4 reboot (which happens each time you change airframe or key params) drops the USB serial and crashes the router. Without auto-restart, every reboot cycle requires manual intervention.

**Don't use mission upload for simple waypoint flight with an active takeoff.** PX4's mission state machine re-executes from `current_seq=0` whenever you switch into AUTO.MISSION. If the WP0 is a takeoff command that already completed, the vehicle hovers forever. `MAV_CMD_DO_REPOSITION` in AUTO.LOITER mode is the right primitive for scripted "fly here, then fly there" — no mission upload, no sequencing pitfalls, just direct position commands.

**Visualization REST APIs can't command an external autopilot.** Sandbox's `/takeoff` and `/waypoint/action` endpoints work for its internal physics entities. A MavLink-backed entity has no local flight controller for the REST layer to invoke — the command fails with a cryptic `FlightController not found!` and nothing moves. Treat the visualizer as read-only for external autopilots; command the autopilot directly via MAVLink.

**Tailsitter visual orientation needs special handling.** Standard NED→Unity attitude conversion assumes the body x-axis points horizontally forward (as in multirotors). Tailsitters break this assumption — body x points UP during hover. Trying to apply PX4's full attitude quaternion to the visual model results in upside-down or sideways rendering during hover. The pragmatic fix: only apply yaw from PX4 attitude, keep the model in its default hover pose for pitch/roll. This loses fidelity but avoids confusing visuals. The proper fix requires a NED→Unity quaternion conversion that accounts for the tailsitter's body-frame convention — non-trivial and best done with a coordinate-frame diagram in front of you.
