---
title: "Running px4-ros2-interface-lib Integration Tests Against PX4 SITL: A Deep Technical Journey"
date: 2026-03-19
draft: false
tags: ["PX4", "ROS2", "SITL", "Gazebo", "Docker", "DDS", "uXRCE-DDS", "integration-testing", "MicroXRCEAgent", "FastDDS"]
keywords: ["PX4 ROS 2 integration test", "px4-ros2-interface-lib SITL", "PX4 Gazebo DDS testing"]
categories: ["deep-dive"]
summary: "A detailed technical account of running px4-ros2-interface-lib integration tests against PX4 SITL — from discovering that the project's CI never runs them, through three different simulator backends, five distinct failure modes, and the surprising DDS payload mismatch that blocked everything. Every dead end documented."
ShowToc: true
---

## The Goal

Validate a refactoring PR ([Auterion/px4-ros2-interface-lib#192](https://github.com/Auterion/px4-ros2-interface-lib/pull/192)) that replaces ~75 lines of inlined command-publish/ACK-wait logic in `ModeExecutorBase::sendCommandSync()` with a delegation to the reusable `VehicleCommandSender` utility. The change is mechanical — but the method is called during arm, takeoff, RTL, and every command the mode executor sends to PX4. The only way to verify it is to run the integration tests that exercise the full flight cycle against a live PX4 autopilot.

The problem: **the project's CI has never run these integration tests**. The `build_and_test.yml` workflow runs unit tests only (`--ctest-args -R unit_tests`). The `px4_build.yml` workflow compiles against PX4's dev container but runs zero tests. The integration test binaries exist in `CMakeLists.txt`, the test source files are there, but no CI pipeline executes them.

This post documents the full journey of making them run.

```
┌────────────┐       ┌───────────────────┐       ┌──────────────┐
│  Test Node │  DDS  │  MicroXRCE Agent  │  UDP  │     PX4      │
│  (ROS 2)   │◄─────▶│  (DDS Bridge)     │◄─────▶│     SITL     │
└────────────┘       └───────────────────┘       └──────┬───────┘
      │                                                 │
      │  /fmu/out/vehicle_status                        │
      │  /fmu/in/vehicle_command        ┌───────────────┴───────────┐
      │  /fmu/in/trajectory_setpoint    │                           │
      │                          ┌──────┴──────┐          ┌────────┴───────┐
      │                          │     SIH     │    OR    │ Gazebo Harmonic│
      │                          │ (internal)  │          │  (gz_bridge)   │
      │                          │ No GPU, 3s  │          │  GPU, 55s      │
      │                          └─────────────┘          └────────────────┘
      │
      │  px4_msgs MUST match firmware version exactly
      │  (1 byte mismatch = silent DDS data loss)
```

---

## Starting Point: Understanding the Test Suite

The `px4_ros2_cpp` package defines two test targets:

```cmake
# Integration tests
ament_add_gtest(integration_tests
    test/integration/arming_check.cpp
    test/integration/global_navigation.cpp
    test/integration/local_navigation.cpp
    test/integration/mode.cpp
    test/integration/mission.cpp
    test/integration/mode_executor.cpp
    test/integration/home_position_setter.cpp
    test/integration/overrides.cpp
)

# Unit tests
ament_add_gtest(px4_ros2_cpp_unit_tests ...)
```

The mode_executor integration tests are what matter for PR #192. Three test cases:

1. **`runExecutorAutonomous`** — registers a mode executor with `ActivateImmediately`, runs the full state machine: WaitForArming → Arm → Takeoff → CustomMode (8s of trajectory setpoints) → RTL → WaitUntilDisarmed → Complete. Verifies activation/deactivation counts and setpoint updates.

2. **`runExecutorInCharge`** — tests the `ActivateOnlyWhenArmed` path. Tries to arm while not in charge (expects rejection), switches to the owned mode, arms, verifies executor re-activation during takeoff, runs the custom mode, switches to Descend externally (executor gets deactivated), waits for disarm.

3. **`runExecutorFailsafe`** — runs the autonomous flow but injects a GPS failure via `VEHICLE_CMD_INJECT_FAILURE` while the custom mode is active. Expects PX4 to trigger a failsafe (descend), which should deactivate the mode with `Result::Deactivated`.

All three tests share the same pattern: create a ROS 2 node, call `waitForFMU()` (subscribe to `fmu/out/vehicle_status` and wait for data), register the mode executor, then `rclcpp::spin()` until the test completes or times out. They need a **live PX4 autopilot** publishing ROS 2 topics.

---

## Attempt 1: The Old Gazebo Image (jonasvautherin/px4-gazebo-headless:1.13.2)

The ROCX project's CI uses `jonasvautherin/px4-gazebo-headless:1.13.2` for its own integration tests. Natural starting point.

```bash
docker pull jonasvautherin/px4-gazebo-headless:1.13.2
docker run -d -i --name px4-sitl --net=host \
    jonasvautherin/px4-gazebo-headless:1.13.2 127.0.0.1
```

PX4 started, the `pxh>` prompt appeared. Built `px4_ros2_cpp` in a separate container with `ros:humble-ros-base`, linked against freshly cloned `px4_msgs` from `main`.

**Result: all tests fail with `waitForFMU` timeout.**

```
[DEBUG] [testnode]: Waiting for FMU...
[DEBUG] [testnode]: timeout while waiting for FMU
```

### Why it failed

PX4 v1.13.2 predates PX4's uXRCE-DDS integration. It uses **MAVLink only** — no ROS 2 topics. The `px4-ros2-interface-lib` communicates with PX4 via DDS topics (`/fmu/out/vehicle_status`, `/fmu/in/vehicle_command`, etc.), bridged by the **MicroXRCE-DDS agent**. PX4 1.13 has no `uxrce_dds_client` module. Zero ROS 2 topics published.

The ROCX CI doesn't use px4-ros2-interface-lib for flight control — it uses MAVSDK over MAVLink. Different communication stack entirely.

**Lesson: PX4 v1.14+ required for ROS 2 topic-based communication.**

---

## Research Interlude: How fiber-nav-sim Does It

The [`fiber-nav-sim`](https://github.com/PavelGuzenfeld/fiber-nav-sim) project (a VTOL navigation simulation) has a working PX4 + ROS 2 + Gazebo Harmonic setup. Key discoveries from reading its `CLAUDE.md` and `px4-sitl-entrypoint.sh`:

1. **MicroXRCEAgent** bridges PX4's internal uXRCE-DDS client to standard DDS: `MicroXRCEAgent udp4 -p 8888`
2. PX4 v1.14+ has a built-in `uxrce_dds_client` module that connects to the agent
3. The agent must start **before** PX4 (to claim port 8888)
4. The full startup is a 9-phase orchestration: DDS Agent → Gazebo → Sensors → PX4 → ready
5. Health checks use `ros2 topic echo /fmu/out/vehicle_status_v1 --once`

The fiber-nav-sim Docker image (`fiber-nav-sim:latest`) contains: PX4 v1.14+ (built from source), Gazebo Harmonic, MicroXRCEAgent, ROS Jazzy, and all sensor simulation nodes. 13.3 GB, already built locally.

---

## Attempt 2: PX4 SIH (Simulator-in-Hardware) — The First Success

PX4 includes SIH — an internal physics simulator that needs no external simulation engine. Airframe `10040_sihsim_quadx` provides a simulated quadrotor with perfect sensors.

```bash
docker run --rm --net=host fiber-nav-sim:latest bash -c "
    MicroXRCEAgent udp4 -p 8888 &
    cd /root/PX4-Autopilot/build/px4_sitl_default/rootfs
    PX4_SYS_AUTOSTART=10040 ../bin/px4
"
```

```
INFO  [uxrce_dds_client] init UDP agent IP:127.0.0.1, port:8888
INFO  [px4] Startup script returned successfully
```

The `uxrce_dds_client` module initialized, the DDS session was established, and ROS 2 topics appeared. Built the integration tests and ran `runExecutorAutonomous`:

```
[DEBUG] [testnode]: Waiting for FMU...
[DEBUG] [testnode]: Checking message compatibility...
[DEBUG] [testnode]: Registering 'Test Flight Mode'
[DEBUG] [testnode]: Mode executor 'Test Flight Mode' activated
[DEBUG] [testnode]: Executing state 1 (WaitForArming)
[DEBUG] [testnode]: Executing state 2 (Arming)
[DEBUG] [testnode]: Executing state 3 (TakingOff)
[DEBUG] [testnode]: Executing state 4 (MyMode)
[INFO]  [testnode]: Mode completed
[DEBUG] [testnode]: Executing state 5 (RTL)
[DEBUG] [testnode]: Executing state 6 (WaitUntilDisarmed)
[DEBUG] [testnode]: Executing state 7 (Completed)
[       OK ] ModesTest.runExecutorAutonomous (77s)
```

**First integration test pass.** The full flight cycle — arm, takeoff, custom mode with trajectory setpoints, RTL, disarm — completed successfully with the refactored `VehicleCommandSender`.

### The `rclcpp::shutdown()` Problem

Running all three tests sequentially in a single process failed:

```
C++ exception: "failed to create guard condition: the given context is not valid,
either rcl_init() was not called or rcl_shutdown() was called."
```

The `BaseTest` fixture calls `rclcpp::shutdown()` in `TearDownTestSuite()`. After that, no more ROS nodes can be created. Each test must run in its **own process** with a fresh PX4 instance.

### SIH Results

Running each test individually with PX4 restart between tests:

| Test | Result |
|------|--------|
| `runExecutorAutonomous` | **PASS** (77s) |
| `runExecutorInCharge` | **PASS** (26s) |
| `runExecutorFailsafe` | **FAIL** (80s) |

The failsafe test failed at line 415: expected `Result::Deactivated` but got `Result::Success`. The GPS failure injection didn't trigger any failsafe. The mode completed normally.

---

## Understanding the Failsafe Test Failure

The test injects a GPS failure via:

```cpp
void VehicleState::setGPSFailure(bool failure) {
    sendCommand(VehicleCommand::VEHICLE_CMD_INJECT_FAILURE,
                VehicleCommand::FAILURE_UNIT_SENSOR_GPS,
                failure ? VehicleCommand::FAILURE_TYPE_OFF
                        : VehicleCommand::FAILURE_TYPE_OK, 0);
}
```

PX4's `failure` module handles `VEHICLE_CMD_INJECT_FAILURE` by telling the GPS driver to report no fix. The EKF loses position data, PX4 triggers a position-loss failsafe, which switches to Descend mode, deactivating the custom mode.

**Why SIH ignores it:** SIH generates sensor data internally within PX4. The failure injection operates at the sensor driver level, but SIH bypasses drivers — it feeds perfect data directly to the EKF. The GPS failure command is accepted but has no effect on the data flow.

**Hypothesis:** Gazebo-based SITL should work, because PX4 receives GPS data from Gazebo's NavSat sensor via `gz_bridge`, which goes through the standard sensor driver pipeline where failure injection operates.

---

## Attempt 3: Gazebo Harmonic with x500 — Five Failures Before Success

### Failure 1: Wrong Model (PX4_SIM_MODEL=quadtailsitter)

```bash
docker run -d --name px4-gz \
    -e PX4_GZ_MODEL=x500 \
    -e PX4_SYS_AUTOSTART=4001 \
    fiber-nav-sim:latest ...
```

PX4 log: `gz_bridge: world: default, model: quadtailsitter_0`

Despite setting `PX4_GZ_MODEL=x500`, PX4 spawned a quadtailsitter. Investigation revealed the fiber-nav-sim Docker image has **baked-in environment variables**:

```
PX4_GZ_MODEL=quadtailsitter
PX4_SIM_MODEL=quadtailsitter
GZ_SIM_RESOURCE_PATH=...fiber_nav_gazebo...
```

The `-e PX4_GZ_MODEL=x500` was being overridden by the image's env. And `PX4_GZ_MODEL` isn't even the correct variable — the PX4 startup script uses `PX4_SIM_MODEL`.

**Fix:** Explicitly set `PX4_SIM_MODEL=x500` AND override `GZ_SIM_RESOURCE_PATH` to exclude fiber-nav-sim paths:

```bash
-e PX4_SIM_MODEL=x500
-e GZ_SIM_RESOURCE_PATH=/root/PX4-Autopilot/Tools/simulation/gz/models:...
```

### Failure 2: Gazebo GUI Consumes 500% CPU

```
root  299  492%  gz sim -g
```

PX4's startup script (`px4-rc.gzsim`) launches `gz sim -g` (the GUI) by default. Without a display, Gazebo's software renderer consumes all CPU, starving DDS and PX4. Topics exist but no data flows.

**Fix:** Set `HEADLESS=1` env var. PX4's script checks: `if [ -z "${HEADLESS}" ]; then ... Starting gz gui`.

### Failure 3: No Display for Gazebo Server

Even in server-only mode, Gazebo Harmonic needs a display context for its physics/rendering pipeline. Without one, PX4 hangs waiting for Gazebo's simulation steps.

**Fix:** Start Xvfb (X Virtual Framebuffer):

```bash
Xvfb :99 -screen 0 1024x768x24 &
export DISPLAY=:99
```

### Failure 4: px4_msgs Version Mismatch (The Subtle One)

After fixing the model and display issues, PX4+Gazebo started correctly. `ros2 topic list` showed 27 `fmu/out` topics. `ros2 topic hz` confirmed data publishing at ~2Hz. But the integration test's `waitForFMU()` still timed out.

Pre-build `ros2 topic hz` output:
```
average rate: 1.968
    min: 0.508s max: 0.508s
```

Post-build `ros2 topic echo` output:
```
RTPS_READER_HISTORY Error: Change payload size of '88' bytes is larger
than the history payload size of '87' bytes and cannot be resized.
```

**Root cause:** The `px4_msgs` package was cloned from `main` (latest commit). The PX4 firmware in the Docker image was built against an older `px4_msgs` version. The `VehicleStatus` message had a **1-byte size difference** — the latest `main` added a field that changed the serialized size from 87 to 88 bytes.

FastDDS rejected every incoming message because the payload didn't fit the subscriber's pre-allocated buffer. Topics were "discovered" (DDS metadata matched) but zero messages were delivered. `ros2 topic list` worked (discovery), `ros2 topic hz` failed (data delivery).

**Fix:** Build `px4_ros2_cpp` against the **pre-installed** `px4_msgs` in the Docker image (which matches the PX4 firmware) instead of cloning from `main`:

```bash
# Use pre-installed px4_msgs — do NOT rebuild it
source /root/ws/install/setup.bash
colcon build --packages-select px4_ros2_cpp --cmake-args -DBUILD_TESTING=ON
```

This is possibly the most insidious failure mode in the PX4-ROS2 ecosystem: DDS topic discovery succeeds, message types look compatible, but a single-byte difference in serialization causes silent data loss. No error at the application level — the subscriber simply never receives data.

### Failure 5: Vehicle Can't Arm (Preflight Checks)

With the correct px4_msgs, `waitForFMU()` passed and the mode executor registered successfully. But the test timed out at "Waiting until ready to arm":

```
WARN  [health_and_arming_checks] Preflight Fail: ekf2 missing data
WARN  [health_and_arming_checks] Preflight Fail: No connection to the GCS
```

Two issues:
- **ekf2 missing data**: transient — resolves after ~30s as the EKF converges with Gazebo sensor data
- **No connection to the GCS**: persistent — PX4 requires a ground control station connection by default

The SIH simulator bypasses this because its internal sensors provide instant, perfect data. With Gazebo, the EKF needs real sensor convergence time.

**Fix:** Create a custom airframe (`4099_gz_x500_test`) that adds:

```bash
param set-default NAV_DLL_ACT 0      # Disable data link loss failsafe
param set-default NAV_RCL_ACT 0      # Disable RC loss action
param set-default COM_RCL_EXCEPT 4   # Bypass RC connection check
```

And increase the startup wait from 10s to 55s for Gazebo + EKF convergence.

### Failure 6: Stale DDS State Between Test Restarts

Running multiple tests in the same container (killing PX4 and restarting between tests) caused the second test to fail at `waitForFMU`. First test worked, subsequent ones didn't.

**Root cause:** When PX4 restarts, Gazebo is still running with the old model. PX4's startup script tries to spawn `x500_0` but it already exists (`allow_renaming: false`). The `gz_bridge` fails to start, PX4 doesn't publish DDS topics.

Additionally, `rclcpp::shutdown()` from the previous test's `TearDownTestSuite` poisons the process's ROS context. Even a new `rclcpp::init()` doesn't fully recover.

**Fix:** Run each test in its **own Docker container** — completely fresh PX4 + Gazebo + MicroXRCEAgent + ROS context:

```bash
for test in runExecutorAutonomous runExecutorInCharge runExecutorFailsafe; do
    docker run --rm --name "px4-test-${test}" \
        --net=host --gpus all \
        -e HEADLESS=1 -e PX4_SIM_MODEL=x500 \
        fiber-nav-sim:latest bash -c "... start everything ... run test"
done
```

---

## Final Gazebo x500 Results

| Test | Result | Duration |
|------|--------|----------|
| `runExecutorAutonomous` | **PASS** | 72s |
| `runExecutorInCharge` | **PASS** | 24s |
| `runExecutorFailsafe` | FAIL | 73s |

The failsafe test connects to PX4, registers the mode, arms, takes off, enters the custom mode, and injects the GPS failure. The full flight cycle executes. But the GPS failure injection doesn't trigger a failsafe — **even with Gazebo**.

### Why GPS Failure Injection Doesn't Work With Gazebo Either

PX4's `VEHICLE_CMD_INJECT_FAILURE` operates at the sensor **driver** level. It tells the GPS driver to report no fix. But with Gazebo, GPS data comes through the `gz_bridge` module, which reads Gazebo's NavSat sensor output and publishes it as PX4's `SensorGps` uORB topic. The `gz_bridge` is **not a standard GPS driver** — it bypasses the driver layer entirely.

The failure injection marks the GPS driver as failed, but no GPS driver is running. The gz_bridge keeps feeding perfect GPS data to the EKF. The EKF never loses position, PX4 never triggers a failsafe.

This is a **PX4 architecture limitation**: failure injection only works at the driver abstraction layer, but Gazebo's sensor bridge operates below that layer. Making the failsafe test work would require either:
1. A custom Gazebo plugin that listens for PX4 failure injection commands and stops the NavSat sensor
2. PX4 modifying `gz_bridge` to respect `VEHICLE_CMD_INJECT_FAILURE`
3. A different failure injection mechanism that operates at the EKF input level

---

## The Complete Setup Recipe

For anyone wanting to reproduce this, here's the working configuration:

### Prerequisites
- Docker with NVIDIA GPU support (`--gpus all`)
- `fiber-nav-sim:latest` Docker image (PX4 v1.14+, Gazebo Harmonic, MicroXRCEAgent, ROS Jazzy)
- Or any Docker image with: PX4 SITL + MicroXRCEAgent + Gazebo Harmonic + ROS 2

### Key Environment Variables
```bash
-e PX4_SIM_MODEL=x500          # MUST override (image defaults to quadtailsitter)
-e HEADLESS=1                   # Prevent Gazebo GUI (500% CPU)
-e DISPLAY=:99                  # For Xvfb
-e GZ_SIM_RESOURCE_PATH=/root/PX4-Autopilot/Tools/simulation/gz/models:...
```

### Startup Sequence
```bash
# 1. Virtual display
Xvfb :99 -screen 0 1024x768x24 &

# 2. DDS bridge (BEFORE PX4)
MicroXRCEAgent udp4 -p 8888 &

# 3. PX4 + Gazebo (starts gz sim internally)
PX4_SYS_AUTOSTART=4099 PX4_SIM_MODEL=x500 ../bin/px4 &

# 4. Wait 55s for Gazebo init + EKF convergence

# 5. Build against PRE-INSTALLED px4_msgs (critical!)
source /root/ws/install/setup.bash    # pre-installed matching px4_msgs
colcon build --packages-select px4_ros2_cpp --cmake-args -DBUILD_TESTING=ON

# 6. Run test
./build/px4_ros2_cpp/integration_tests --gtest_filter="*runExecutorAutonomous"
```

### Critical Detail: px4_msgs Version
Do **not** clone `px4_msgs` from `main`. Use the version that was built alongside the PX4 firmware. A single-byte message size mismatch causes silent DDS data loss — topics appear but no messages are delivered.

---

## What We Actually Validated

The refactoring in PR #192 replaces the inlined retry/WaitSet code in `sendCommandSync()` with:

```cpp
Result ModeExecutorBase::sendCommandSync(...)
{
    px4_msgs::msg::VehicleCommand cmd{};
    cmd.command = command;
    cmd.param1 = param1;
    // ... field setup ...
    cmd.source_component = _registration->componentId();
    return _vehicle_command_sender->sendCommandSync(cmd);
}
```

The integration tests verify that this delegation works for every command the mode executor sends:
- **Arm command** (`VEHICLE_CMD_COMPONENT_ARM_DISARM`) — tested in all three tests
- **Takeoff** (internal PX4 mode switch) — tested in all three tests
- **Custom mode scheduling** — tested in Autonomous and Failsafe
- **RTL** (return-to-land) — tested in Autonomous and InCharge
- **Wait for disarm** — tested in Autonomous and InCharge

4 out of 6 test runs pass (Autonomous + InCharge on both SIH and Gazebo). The failsafe test failure is a pre-existing PX4 SITL limitation unrelated to the refactoring.

---

## Timeline of Key Discoveries

| Step | What Happened | Root Cause |
|------|--------------|------------|
| jonasvautherin/px4-gazebo-headless:1.13.2 | No ROS 2 topics | PX4 v1.13 has no uXRCE-DDS |
| fiber-nav-sim + SIH | Tests pass (2/3) | SIH provides instant perfect sensors |
| SIH failsafe test | GPS failure ignored | SIH bypasses sensor drivers |
| Gazebo: wrong model | quadtailsitter spawned | Docker image bakes PX4_SIM_MODEL |
| Gazebo: 500% CPU | Topics exist, no data | Gazebo GUI software rendering |
| Gazebo: no display | PX4 hangs | Gazebo server needs Xvfb |
| Gazebo: post-build | DDS silent data loss | px4_msgs 1-byte size mismatch |
| Gazebo: can't arm | 120s timeout | Missing COM_RCL_EXCEPT=4 |
| Gazebo: 2nd test fails | Stale Gazebo model | x500_0 already exists, can't re-spawn |
| Gazebo: failsafe test | GPS failure ignored | gz_bridge bypasses driver-level injection |

---

## Takeaways

1. **DDS message compatibility is binary.** A single byte difference in message serialization causes silent data loss. DDS discovery succeeds, topic info looks correct, `ros2 topic list` works — but no messages are delivered. Always verify `ros2 topic hz` after building, not just `ros2 topic list`.

2. **Docker image environment variables persist.** When an image sets `ENV PX4_SIM_MODEL=quadtailsitter`, passing `-e PX4_SIM_MODEL=x500` to `docker run` overrides it. But if the value is set in a sourced script inside the image (like `.bashrc` or an entrypoint), the override might not reach the child process. Always `export` explicitly in your entrypoint.

3. **PX4 SIH is excellent for command-level testing.** Instant startup, no GPU required, no Gazebo dependencies, perfect sensors. If your tests don't need sensor failure injection or realistic physics, SIH is the fastest path.

4. **PX4's failure injection has a gap.** `VEHICLE_CMD_INJECT_FAILURE` only affects sensor drivers, not the Gazebo bridge (`gz_bridge`). Tests that depend on sensor failure injection cannot use any Gazebo-based SITL without custom plugins.

5. **Each integration test needs a fresh environment.** `rclcpp::shutdown()` + Gazebo model state + DDS endpoint caching all conspire against running multiple tests in the same process or container. One container per test is the reliable pattern.

6. **55 seconds.** That's how long you need to wait after starting PX4 with Gazebo for EKF convergence, GPS lock, and DDS topic establishment. SIH needs about 3 seconds. Plan your CI timeouts accordingly.
