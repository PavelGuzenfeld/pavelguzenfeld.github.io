---
title: "Connecting PX4 SITL to a Headless Unity Simulation in Docker: A 60-Hour Debugging Odyssey"
date: 2026-03-21
draft: false
tags: ["PX4", "Unity", "Docker", "MAVLink", "SITL", "Vulkan", "simulation", "TCP", "debugging", "DevOps"]
keywords: ["PX4 Unity Docker simulation", "Unity headless PX4 SITL", "MAVLink Unity Docker"]
categories: ["deep-dive"]
summary: "A three-day odyssey connecting PX4 flight controller to a GPU-rendered Unity drone simulation running headless inside Docker — through licensing labyrinths, shader abysses, coordinate system riddles, native library dragons, and a TCP protocol twist ending nobody expected."
ShowToc: true
---

> *"It started with a simple question: can we run a Windows-only Unity drone simulation in a Linux Docker container, stream its cameras via RTSP, and connect a PX4 flight controller to it?"*
>
> *Three days, 40+ commits, and approximately 60 hours of debugging later, the answer is yes. This is the story of how we got there.*

If you haven't read the [first part of this journey](/posts/headless-unity-docker-simulation/), start there — it covers the Docker foundation, the Unity licensing labyrinth, and the initial RTSP streaming pipeline. This post picks up where that one ends and follows the thread all the way to a working PX4 SITL integration.

---

## Act I: The Ordinary World

We had a working Docker pipeline — GPU passthrough, volume mounts, and the same [container-based testing patterns](/posts/fixing-ci-pipeline-arm-jetson-docker/) that work on everything from Jetson Xaviers to cloud GPUs:

```
┌─────────────────────────────────────────────────────┐
│  Docker Container (nvidia/vulkan, RTX 3060)         │
│                                                     │
│  Xvfb (:99) → Unity (-batchmode, Vulkan)            │
│       ↓              ↓            ↓                 │
│    HeadCamera    BodyCamera    REST API              │
│       ↓              ↓         (:4900)              │
│    FFmpeg H264   FFmpeg H264                        │
│       ↓              ↓                              │
│    mediamtx RTSP server (:8554)                     │
│       ↓              ↓                              │
│    /HeadCamera   /BodyCamera                        │
└─────────────────────────────────────────────────────┘
         ↓              ↓
    GStreamer clients (display)
```

The simulation ran. Cameras streamed. But the cameras showed gray pixels or terrain contours without color. And most importantly — there was no flight controller connected. The drone just sat there, frozen in digital amber.

The quest: connect [PX4](https://px4.io/) — an open-source flight controller — to this containerized simulation so the drone could actually fly, and the cameras would show a real flight perspective.

This quest would take us through five distinct underworlds, each with its own guardian and puzzle.

---

## Act II: The Coordinate System Riddle

### The Call

The first mystery: why was the camera output always the same gray image regardless of where we placed the drone?

We changed the entity's GPS altitude from 200m to 300m to 500m. The camera feed didn't change. Not a single pixel.

### The Descent

Deep investigation into the simulation's source code revealed the coordinate conversion system — a flat-earth approximation in `ManagedCoordinateConverter.cs`:

```
Unity X = (longitude_diff × π/180) × 6,366,707.02 × cos(home_latitude)
Unity Z = (latitude_diff × π/180) × 6,366,707.02
Unity Y = altitude   ← ABSOLUTE, not relative to HomePoint
```

The critical insight: altitude is passed through **directly** as Unity's Y coordinate. An entity at GPS altitude 300m appears at Unity Y=300, regardless of the HomePoint altitude.

But the real dragon was hiding elsewhere.

### The Dragon: MavLinkVehicleReflector

```csharp
// This runs EVERY FRAME
private void Update()
{
    if (_ctrl == null) return;
    VehicleState state = _ctrl.Vehicle.GetVehicleState();
    Vector3 local = new Vector3(state.LocalEst.Pos.Y, -state.LocalEst.Pos.Z, state.LocalEst.Pos.X);
    transform.position = localOrigin + local;  // Overwrites position!
}
```

Without a MAVLink connection, `GetVehicleState()` returns all zeros. Every frame, the entity position is reset to `(0, 0, 0)` — **below the terrain**. The initial GPS position from `SetInitialGeodLocation()` is immediately overwritten.

### The Fix

```csharp
private bool _hasReceivedPosition = false;

// Don't override until we have real MAVLink data
if (!_hasReceivedPosition)
{
    if (local.sqrMagnitude < 0.001f && !_globalOriginSet)
        return; // Preserve initial GPS position
    _hasReceivedPosition = true;
}
```

With this fix, switching to `SimEntity` (which doesn't have the reflector) confirmed: the drone model appeared in the camera at the correct altitude. The camera was attached to the entity all along — we just couldn't see it because the entity was underground.

---

## Act III: The Terrain Shader Abyss

### The Problem

Even with correct positioning, the terrain rendered as flat gray geometry — elevation contours visible but no satellite imagery or colors.

### The Investigation

The terrain asset bundles from the team's file server were built with `BuildTarget.StandaloneWindows`. Their shaders included only DirectX variants:

```
WARNING: Shader Did you use #pragma only_renderers and omit this platform?
```

On Linux with Vulkan, every material fell back to the default gray Standard shader.

### Attempts That Failed

1. **Custom VertexColor shader** — compiled in Editor but didn't render at runtime in the player build, even when added to "Always Included Shaders"
2. **Unlit/Texture shader** — texture reference didn't survive the asset bundle → player loading pipeline in Unity 2019.4 batch mode
3. **Embedded terrain in main scene** — same texture serialization issue
4. **Rebuilding terrain from UMFTDI project** — the terrain builder project existed but needed raw MFT source data from an unreachable server

### What We Learned

Unity 2019.4's built-in rendering pipeline on Linux/Vulkan has fundamental limitations with shader compilation for asset bundles built in batch mode. The terrain geometry loads and renders correctly — the issue is purely about material/texture binding.

This remains an open item. The proper fix is rebuilding the original terrain with `StandaloneLinux64` from the team's UMFTDI terrain builder project — a one-dropdown-change in the wizard, if someone has access to the raw terrain source data.

---

## Act IV: The PX4 SITL Integration — Five Sub-Bosses

### Sub-Boss 1: The Entity Generator

The simulation has multiple entity types:
- `SimEntity` — static, no flight controller
- `MavlinkEntity` — receives MAVLink position (client mode)
- `MatrixRemoteDrone` — acts as PX4 SITL simulator (server mode, TCP 4560)

`MatrixRemoteDrone` failed silently. No logs, no errors. Investigation revealed:

1. `UdpRemoteEntity.StartServer(9400)` returned false (UDP port binding issue in Docker)
2. This prevented `SetMovementSettings()` from ever running
3. TCP 4560 never opened

And separately: `SimpleIMU`, `SimpleBarometer`, `SimpleMagnetometer` classes referenced in the config **don't exist** in the codebase. Only `SimpleGPS` exists. The sensor initialization returned false, causing the entire `SetPlayerSettings` chain to fail.

**The fix**: Created `PX4Entity` — a simplified entity that extends `Entity` directly (skipping `UdpRemoteEntity`), only requires `SimpleGPS`, and initializes `RemoteMavlinkFlightController` for TCP 4560.

A debugging lesson: `Debug.Log` is **stripped from Release builds**. We only discovered the entity failures after switching to `Debug.LogError` which is never stripped.

### Sub-Boss 2: The Native Library Dragon

With `PX4Entity`, TCP 4560 opened. PX4 SITL connected. The initial `SendHilSensor` returned `True`. PX4 responded with `HIL_ACTUATOR_CONTROLS`. Victory seemed close.

Then the simulation loop failed. Every `MavLinkNode.SendMessage` call returned `false`. 500 retries — all failed.

We checked:
- Struct sizes: `Marshal.SizeOf<mavlink_hil_sensor_t>() = 64` — **matches native expectations**
- Connection state: `sitlNode null=False, connected=True` — connected
- Incoming messages: PX4 kept sending `HIL_ACTUATOR_CONTROLS (#93)` — connection alive

The native `libMavLinkComWrapper.so` was the suspect. We found the source code in the `the mavlinkcomwrapper project` repo. The `SendMessage` implementation:

```cpp
MavLinkMessage mavmsg = utils::mavlink::EncodeMessage(msg, msgId, static_cast<uint8_t>(length));
conn->_ptr->sendMessage(mavmsg);
```

No validation, no size check — just memcpy and send. The library should work. But it didn't.

### Sub-Boss 3: The Raw TCP Approach

Bypassing the native library entirely, we wrote `RawMavLinkSender.cs` — a pure .NET `TcpClient`-based MAVLink v2 message sender with manual CRC computation:

```csharp
packet[0] = 0xFD; // MAVLink v2 start
packet[1] = (byte)len;
// ... header fields ...
ushort crc = CrcCalculate(packet, 1, len + 9);
crc = CrcAccumulate(GetCrcExtra(msgId), crc);
```

Same result: first sends succeeded, then failed at send #36-42. `IOException: The socket has been shut down.`

### Sub-Boss 4: The TCP Buffer Red Herring

We added a dedicated read thread to drain PX4's responses. Still failed. We disabled the Subscribe callback. Still failed. We tried connection-level vs node-level sends. Still failed.

Every test showed the same pattern: ~40 successful sends, then permanent failure. The TCP connection was being closed by the remote end.

### Sub-Boss 5: The Twist Ending

```
=== PX4 FULL ===
INFO  [px4] Startup script returned successfully
pxh> Exiting NOW.
EXIT_CODE=0
```

PX4 was **exiting**. Not crashing. Not rejecting our data. Just... finishing its startup script and shutting down cleanly. The `none_iris` model runs PX4's init script and exits — there's no foreground process to keep it alive.

Every "failure" we debugged — the native library, the CRC, the TCP buffer, the lockstep protocol — was a red herring. The connection worked perfectly for exactly as long as PX4 was running (~800ms of startup), then PX4 exited and closed the socket.

**The fix**: One flag.

```bash
build/px4_sitl_default/bin/px4 ... -d  # daemon mode
```

The `-d` flag keeps PX4 running after the init script completes. This lesson applies universally to [PX4 SITL deployments](/posts/px4-ros2-integration-testing-sitl-gazebo/) — and if the TCP 4560 complexity seems excessive, the [SIH approach](/posts/px4-ros-integration-tests-gazebo-to-sih-migration/) avoids external simulators entirely by running physics inside PX4 itself.

---

## Act V: The Return

With the `-d` flag:

```
[PX4Entity] Raw send #1: sensor=True, gps=True
[PX4Entity] Raw send #50: sensor=True, gps=True — running stable
```

```
INFO  [vehicle_air_data] BARO switch from #0 -> #1
INFO  [tone_alarm] home set
```

PX4 received our simulated sensor data. It switched to the barometer we provided. It set the home position from our GPS coordinates. Both containers ran stable for minutes.

The full architecture:

```
┌──────────────────────────────────────────────────────────────┐
│  Docker Container (nvidia/vulkan, RTX 3060)                  │
│                                                              │
│  ┌──────────────────────────────────────────────────┐        │
│  │  Unity 2019.4 (-batchmode, Vulkan rendering)     │        │
│  │                                                  │        │
│  │  PX4Entity                                       │        │
│  │  ├── MavLinkVehicleReflector (position updates)  │        │
│  │  ├── RawMavLinkSender (TCP 4560)                 │        │
│  │  │   ├── HIL_SENSOR (IMU, baro, mag) @ 50Hz      │        │
│  │  │   └── HIL_GPS (position) @ 50Hz               │        │
│  │  ├── HeadCamera → FFmpeg → RTSP /HeadCamera       │        │
│  │  └── BodyCamera → FFmpeg → RTSP /BodyCamera       │        │
│  └──────────────────────────────────────────────────┘        │
│                                                              │
│  Xvfb (:99) │ mediamtx (:8554) │ REST API (:4900)           │
└──────────────┼──────────────────┼────────────────────────────┘
               │                  │
    ┌──────────┼──────────┐  ┌────┴──────────┐
    │  PX4 SITL (Docker)  │  │  GStreamer     │
    │  TCP → :4560        │  │  RTSP client   │
    │  -d (daemon mode)   │  │  protocols=tcp │
    │  none_iris model    │  └───────────────┘
    │                     │
    │  Receives:          │
    │  - HIL_SENSOR       │
    │  - HIL_GPS          │
    │  Sends back:        │
    │  - HIL_ACTUATOR_    │
    │    CONTROLS          │
    │  - HEARTBEAT        │
    └─────────────────────┘
```

---

## The Lessons

### 1. The Simplest Explanation Is Usually Right

We spent hours debugging native library internals, CRC computations, struct marshaling, and TCP buffer management. The root cause was that PX4 was exiting. A process lifecycle issue, not a protocol issue. Always check `EXIT_CODE` first.

### 2. Debug.Log Is Stripped in Release Builds

Unity strips `Debug.Log` calls in non-Development builds. Use `Debug.LogError` for diagnostics that must survive to production. We lost hours because entity initialization failures were completely silent.

### 3. The Entity That Overrides Position Every Frame

If your game entity uses a network reflector that sets `transform.position` every frame, it will override any initial position. Guard with a "has received real data" flag.

### 4. Type.GetType() Works... Until It Doesn't

Unity's `Type.GetType("ClassName")` works in Editor but can fail silently in builds if the assembly context is different. Always handle the null case with a visible error.

### 5. Test One Thing at a Time

When we switched from `MavlinkEntity` to `SimEntity`, the drone model immediately appeared. That single change proved the camera system worked — the problem was entity positioning. Isolate variables ruthlessly.

---

## What's Still Open

1. **Terrain satellite texture** — needs the original terrain asset bundle rebuilt with `StandaloneLinux64` from the UMFTDI project
2. **Dynamic flight** — PX4 receives our sensor data but the mock data is static (hover). Real flight requires updating sensor values based on Unity physics
3. **1080p cameras with terrain** — Vulkan segfaults under heavy async GPU readback load at 1080p. Stable at 720p25
4. **Native `MavLinkComWrapper` fix** — the native library's `SendMessage` fails after the first call. Our `RawMavLinkSender` works around it, but the native lib should be rebuilt from `the mavlinkcomwrapper project`

---

## Timeline

| Day | Hours | What Happened |
|-----|-------|---------------|
| 1 | 20h | Docker foundation, licensing labyrinth, Unity build, RTSP streaming |
| 2 | 20h | Terrain debugging, coordinate system, shader investigation, MavlinkEntity fix |
| 3 | 20h | PX4Entity creation, native library debugging, RawMavLinkSender, the `-d` flag revelation |

Total: ~60 hours across three days. The `-d` flag that fixed everything took 1 second to add.

---

*Every great debugging story ends the same way: the fix is embarrassingly simple, and the journey to find it teaches you more about the system than any documentation ever could.*
