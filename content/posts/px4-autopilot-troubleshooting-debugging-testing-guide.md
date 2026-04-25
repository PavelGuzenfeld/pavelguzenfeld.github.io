---
title: 'PX4 Autopilot: A Practitioner''s Guide to Troubleshooting, Debugging, Building,
  and Testing'
date: 2026-03-22
draft: false
tags:
- PX4
- C++
- NuttX
- debugging
- Docker
- SITL
- uXRCE-DDS
- MAVLink
- ASan
- TSan
- integration-testing
- open-source
keywords:
- PX4 Docker build guide
- PX4 SITL debugging
- PX4 uXRCE-DDS troubleshooting
cover:
  image: /images/posts/px4-guide.png
  alt: 'PX4 Autopilot: A Practitioner''s Guide'
categories:
- deep-dive
summary: Everything I learned contributing 6 PRs to PX4-Autopilot in a single session
  — from Docker-based builds and sanitizer workflows, through uXRCE-DDS session debugging
  and MAVLink signing analysis, to SITL integration testing. Real bugs, real fixes,
  real build output.
ShowToc: true
audio:
  pronunciation:
    PX4: P X four
    PX4-Autopilot: P X four autopilot
    NuttX: nuts X
    NXP: N X P
    Pixhawk: pix hawk
    Kinetis: Kinetis
    STM32: S T M thirty two
    STM32H7: S T M thirty two H seven
    ESP32: E S P thirty two
    RPI: R P I
    io_timer: I O timer
    io_timer.c: I O timer dot C
    uORB: you orb
    uXRCE-DDS: micro X R C E D D S
    DDS: D D S
    Fast-DDS: fast D D S
    MicroXRCEAgent: micro X R C E agent
    Micro-XRCE-DDS-Agent: micro X R C E D D S agent
    Micro XRCE-DDS Agent: micro X R C E D D S agent
    ASan: A san
    TSan: T san
    PX4_ASAN: P X four A san
    PX4_TSAN: P X four T san
    PX4_SIM_MODEL: P X four sim model
    AddressSanitizer: address sanitizer
    ThreadSanitizer: thread sanitizer
    rcS: R C S
    px4_sitl_default: P X four sittle default
    SITL: sittle
    SIH: S I H
    SYS_HITL: sys hit L
    SYS_AUTOSTART: sys auto start
    ros2cli: ross two C L I
    ROS2: ross two
    ROS 2: ross two
    MAVLink: mav link
    MAV_SIGN_CFG: mav sign C F G
    PROTO_SIGN_OPTIONAL: proto sign optional
    PROTO_SIGN_NON_USB: proto sign non U S B
    PROTO_SIGN_ALWAYS: proto sign always
    accept_unsigned: accept unsigned
    SETUP_SIGNING: setup signing
    VEHICLE_CMD_INJECT_FAILURE: vehicle command inject failure
    FAILURE_UNIT_SENSOR_GPS: failure unit sensor G P S
    EKF2: E K F two
    vehicle_thrust_setpoint: vehicle thrust setpoint
    Werror: W error
    Werror=unused-variable: W error unused variable
    Werror=unused-function: W error unused function
    rolling: rolling
    TimeSource: time source
    destroy_clock_sub: destroy clock sub
    dds_topics.yaml: D D S topics dot yaml
    dds_topics.h.em: D D S topics dot H dot E M
    generate_dds_topics.py: generate D D S topics dot pie
    uxrce_dds_client: micro X R C E D D S client
    UxrceddsClient::run: micro X R C E D D S client run
    setupSession: setup session
    deleteSession: delete session
    checkConnectivity: check connectivity
    px4_poll: P X four poll
    uxr_run_session: U X R run session
    uxr_sync_session: U X R sync session
    on_pong_flag: on pong flag
    EmPy: em pie
    ROMFS: rom F S
    PARAM_SET: param set
    PARAM_VALUE: param value
    AUTOPILOT_VERSION: autopilot version
    DCO: D C O
    astyle: A style
    DShot: D shot
    S32K1xx: S thirty two K one X X
    S32K3xx: S thirty two K three X X
    GitHub: git hub
---

## Context

PX4-Autopilot is the largest open autopilot codebase: 1,100+ open issues, 490 open PRs, C++17 on NuttX. I recently contributed fixes across the timer driver layer, uXRCE-DDS client, MAVLink signing, navigator, and land detector — touching 30+ files across 6 PRs. This post documents the debugging methodology, build infrastructure, and testing patterns that made it possible to work across that breadth in a single session.

This is not a tutorial. It's a reference for anyone about to touch PX4 internals and wondering: *how do I build this? how do I test this? how do I know I haven't broken something?*

```
PX4-Autopilot Architecture (simplified)

┌──────────────────────────────────────────────────────────────┐
│                        Applications                           │
│  ┌──────────┐ ┌──────────┐ ┌───────────┐ ┌───────────────┐  │
│  │Navigator │ │Commander │ │Flight Mode│ │ Land Detector │  │
│  │(missions)│ │(state m.)│ │ Manager   │ │(ground contact│  │
│  └─────┬────┘ └────┬─────┘ └─────┬─────┘ │ maybe_landed) │  │
│        │           │             │        └───────┬───────┘  │
│        └───────────┴─────────────┴────────────────┘          │
│                           │ uORB pub/sub                     │
├───────────────────────────┼──────────────────────────────────┤
│                     Middleware                                │
│  ┌──────────────┐  ┌─────┴──────┐  ┌───────────────────┐    │
│  │   MAVLink    │  │   uORB     │  │  uXRCE-DDS Client │    │
│  │  (GCS link)  │  │  (bus)     │  │  (ROS 2 bridge)   │    │
│  └──────────────┘  └────────────┘  └───────────────────┘    │
├──────────────────────────────────────────────────────────────┤
│                    Drivers / HAL                              │
│  ┌────────────┐ ┌────────────┐ ┌─────────────────────────┐  │
│  │  io_timer  │ │   dshot    │ │  PWM / LED / Capture    │  │
│  │ (STM32,NXP │ │ (bidirect.)│ │  (input_capture.c)      │  │
│  │  RPI,ESP32)│ │            │ │                         │  │
│  └────────────┘ └────────────┘ └─────────────────────────┘  │
├──────────────────────────────────────────────────────────────┤
│                    NuttX RTOS / POSIX                         │
└──────────────────────────────────────────────────────────────┘
```

---

## 1. The Docker Build Environment

PX4's CI uses Docker. You should too. Never install the toolchain locally — it's a moving target of ARM GCC versions, NuttX headers, and Python codegen tools. The canonical dev image is specified in `Tools/docker_run.sh`:

```bash
# Default image (check your branch — this changes per release)
PX4_DOCKER_REPO="px4io/px4-dev:v1.17.0-beta1"
```

### Building any target

```bash
# SITL (Linux, x86)
docker run --rm \
  --user="$(id -u):$(id -g)" \
  --env=CCACHE_DIR="$HOME/.ccache" \
  -v $HOME/.ccache:$HOME/.ccache:rw \
  -v "$(pwd):$(pwd):rw" \
  -w "$(pwd)" \
  px4io/px4-dev:v1.17.0-beta1 \
  /bin/bash -c "make px4_sitl_default -j$(nproc)"

# STM32 NuttX (Pixhawk 6X)
# Same command, different target
/bin/bash -c "make px4_fmu-v6x_default -j$(nproc)"

# NXP Kinetis (FMUK66)
/bin/bash -c "make nxp_fmuk66-v3_default -j$(nproc)"
```

Key details:
- **`--user`** avoids root-owned build artifacts that block subsequent builds
- **ccache** is critical — first build takes 5-10 minutes, incremental builds take seconds
- **No `-t` flag** — the Docker script uses `-it` but non-interactive builds fail with "not a TTY"
- The build produces `build/<target>/` with the binary, `.elf`, `.bin`, and `.px4` files

### Why you need multiple targets

PX4 supports STM32, NXP (Kinetis, S32K1xx, S32K3xx), RPI, and ESP32. Each platform has its own:
- Timer driver (`io_timer.c`)
- GPIO abstraction
- DShot implementation
- LED PWM driver
- Input capture driver

When I refactored `timer_io_channels[].timer_channel` from 1-indexed to 0-indexed ([PR #26845](https://github.com/PX4/PX4-Autopilot/pull/26845)), I had to touch 20 files across all platforms. Building only SITL would have missed NuttX-specific compilation errors. The minimum set:

```bash
make px4_sitl_default      # Covers POSIX, common code
make px4_fmu-v6x_default   # Covers STM32
make nxp_fmuk66-v3_default # Covers NXP Kinetis
```

---

## 2. Sanitizers: ASan and TSan

PX4 supports AddressSanitizer and ThreadSanitizer via environment variables:

```bash
# ASan build
docker run --rm ... \
  --env=PX4_ASAN=1 \
  /bin/bash -c "make px4_sitl_default -j$(nproc)"

# TSan build
docker run --rm ... \
  --env=PX4_TSAN=1 \
  /bin/bash -c "make clean && make px4_sitl_default -j$(nproc)"
```

The `clean` before TSan is important — ASan and TSan are incompatible, and mixing object files from different sanitizer builds produces link errors or false positives.

These environment variables are passed through `Tools/docker_run.sh` and consumed by the CMake build system. The compiler flags added are:

- **ASan**: `-O1 -g3 -fsanitize=address -fno-omit-frame-pointer -fno-common -fno-optimize-sibling-calls`
- **TSan**: `-O1 -g3 -fsanitize=thread`

### When to use which

| Sanitizer | Catches | Use when |
|-----------|---------|----------|
| ASan | Buffer overflows, use-after-free, double-free, stack overflow | Touching array indexing, buffer management, memory lifecycle |
| TSan | Data races, lock-order violations, thread leaks | Touching shared state between modules (uORB, DDS session) |

For the timer_channel refactor, ASan was essential — the original 1-indexed code had potential underflow bugs when `timer_channel - 1` was applied to an unguarded zero value. ASan on the SITL build would catch any array-out-of-bounds at runtime.

---

## 3. Unit Tests

```bash
docker run --rm ... \
  /bin/bash -c "make tests -j$(nproc)"
```

This builds the SITL binary plus all test binaries, then runs CTest. On current main, expect ~154 tests:

```
100% tests passed, 0 tests failed out of 154
Total Test time (real) =  45.45 sec
```

The tests cover:
- Math libraries (matrix, quaternion, search algorithms)
- Data structures (IntrusiveQueue, IntrusiveSortedList)
- System primitives (hrt, dataman, parameters, perf counters)
- uORB messaging
- Sensor processing (IMU filtering, RC tests)
- Module-specific tests (controllib, lightware laser)

What the tests **don't** cover: anything requiring a running simulator, actual sensor data, or multi-module interaction. For that, you need SITL integration tests.

---

## 4. Code Style Enforcement

PX4 uses astyle. The CI will reject your PR if style checks fail:

```bash
docker run --rm ... \
  /bin/bash -c "./Tools/astyle/check_code_style_all.sh --fix"
```

The `--fix` flag auto-formats. Run this before committing. Common gotchas:
- Tab vs space mixing (PX4 uses tabs for indentation in C files)
- Brace placement
- Pointer/reference alignment

The style check only examines PX4 source files, not submodules or generated code.

---

## 5. The Code Generation Pipeline: uXRCE-DDS Topics

The uXRCE-DDS client's C++ code is partially generated from `dds_topics.yaml`. Understanding this pipeline is essential for debugging DDS build issues.

```
dds_topics.yaml          (topic definitions: publications, subscriptions)
       │
       ▼
generate_dds_topics.py   (Python: processes YAML, runs EmPy templating)
       │
       ▼
dds_topics.h.em          (EmPy template: C++ with @[for]/@[if] directives)
       │
       ▼
dds_topics.h             (generated C++ header: structs, callbacks, init code)
       │
       ▼
uxrce_dds_client.cpp     (includes generated header, runs the session loop)
```

### What goes wrong

When I fixed [#26799](https://github.com/PX4/PX4-Autopilot/pull/26846) (build fails with all DDS subscriptions commented out), the failure chain was:

1. **Python KeyError**: `generate_dds_topics.py` used `msg_map['subscriptions']` instead of `msg_map.get('subscriptions')`. When the YAML key was absent entirely, the script crashed.

2. **Unused variable error**: The generated `dds_topics.h` unconditionally declared `const int64_t time_offset_us = session->time_offset / 1000;` — used only inside subscription callback code. With zero subscriptions, the variable was unused, and `-Werror=unused-variable` promoted it to a build error.

3. **Unused function error**: `create_data_reader()` in `utilities.hpp` was `static` and only called from generated subscription code. With zero subscriptions, it became unused → `-Werror=unused-function`.

The fix required changes at three levels: the Python generator (use `.get()`), the EmPy template (conditional guards), and the utility header (`__attribute__((unused))`).

**Lesson**: When debugging PX4 build failures, check whether the error is in generated code. If so, trace back through the generation pipeline — the fix is usually in the template or generator, not the generated output.

---

## 6. Debugging uXRCE-DDS Session Lifecycle

The uXRCE-DDS client is the most reliability-sensitive module in PX4 for anyone running a companion computer. Its architecture:

```
┌───────────────────────────────────────────────────────────────┐
│                    UxrceddsClient::run()                       │
│                                                               │
│  ┌─────────────────────────────────────────────────────────┐  │
│  │  OUTER LOOP: while (!should_exit())                     │  │
│  │                                                         │  │
│  │  ┌──────────────────────────────────────────────────┐   │  │
│  │  │  SETUP LOOP: while (!should_exit())              │   │  │
│  │  │    init()          ← open transport (serial/UDP) │   │  │
│  │  │    setupSession()  ← ping, create session,       │   │  │
│  │  │                      create participant,          │   │  │
│  │  │                      time sync, init pubs/subs   │   │  │
│  │  │    break if _connected                           │   │  │
│  │  └──────────────────────────────────────────────────┘   │  │
│  │                                                         │  │
│  │  resetConnectivityCounters()                            │  │
│  │                                                         │  │
│  │  ┌──────────────────────────────────────────────────┐   │  │
│  │  │  MAIN LOOP: while (!should_exit() && _connected) │   │  │
│  │  │    px4_poll(uORB fds)     ← wait for topic data  │   │  │
│  │  │    _subs->update()        ← serialize & send     │   │  │
│  │  │    uxr_run_session()      ← process incoming     │   │  │
│  │  │    process_replies()      ← handle requests      │   │  │
│  │  │    uxr_sync_session()     ← time sync            │   │  │
│  │  │    checkConnectivity()    ← ping monitoring      │   │  │
│  │  └──────────────────────────────────────────────────┘   │  │
│  │                                                         │  │
│  │  deleteSession()  ← cleanup for retry                   │  │
│  └─────────────────────────────────────────────────────────┘  │
└───────────────────────────────────────────────────────────────┘
```

### The reconnection bug (#26022)

When the Micro XRCE-DDS Agent is restarted (e.g., via systemd), PX4 stays "Running, disconnected" forever. Three bugs prevented reconnection:

**Bug 1: `session.on_pong_flag` never reset**

```cpp
// In the main loop:
if (session.on_pong_flag == 1) {
    _had_ping_reply = true;
    // BUG: flag was never reset to 0!
}
```

After the first successful pong, `on_pong_flag` stayed 1 forever. The connectivity checker always saw `_had_ping_reply = true`, so the 3-missed-pings disconnection condition could never trigger. The agent could be dead for hours and PX4 would never notice.

**Fix**: One line — `session.on_pong_flag = 0;`

**Bug 2: `_subs->reset()` never called**

`SendTopicsSubs::reset()` exists — it unsubscribes uORB file descriptors and resets data writers. But `deleteSession()` never called it. On reconnection, stale uORB fds from the previous session persisted, causing the new session's publishers to malfunction.

**Bug 3: `_connected` not reset in `deleteSession()`**

Minor but important for clean state transitions.

### Verifying the fix in Docker SITL

I wrote a test script that runs inside Docker:

```bash
# 1. Build PX4 SITL
make px4_sitl_default -j$(nproc)

# 2. Build MicroXRCEAgent from source (not in dev image)
git clone --depth 1 https://github.com/eProsima/Micro-XRCE-DDS-Agent.git
cd Micro-XRCE-DDS-Agent && mkdir build && cd build
cmake .. -DCMAKE_BUILD_TYPE=Release && make -j$(nproc)

# 3. Start PX4 headless (no Gazebo needed)
PX4_SIM_MODEL=none build/px4_sitl_default/bin/px4 \
    build/px4_sitl_default/etc -s etc/init.d-posix/rcS -d &

# 4. Start agent, verify connection
MicroXRCEAgent udp4 -p 8888 &
# Wait for: "synchronized with time offset"
# Wait for: "successfully created ... data writer"

# 5. Kill agent
kill -9 $AGENT_PID

# 6. Verify disconnect detection
# Wait for: "No ping response, disconnecting"
# Wait for: "session disconnected, attempting to reconnect..."

# 7. Restart agent
MicroXRCEAgent udp4 -p 8888 &

# 8. Verify reconnection
# Wait for new: "synchronized with time offset"
# Wait for new: "successfully created ... data writer"
```

The actual test output from Docker:

```
=== Test 1: Start agent, verify connection ===
  PASS: Client connected to agent
    INFO  [uxrce_dds_client] synchronized with time offset 1774156926591857us
    INFO  [uxrce_dds_client] successfully created rt/fmu/out/register_ext_component_reply_v1

=== Test 2: Kill agent, verify disconnect detection ===
  PASS: Disconnect detected
    ERROR [uxrce_dds_client] No ping response, disconnecting
    INFO  [uxrce_dds_client] session disconnected, attempting to reconnect...

=== Test 3: Verify reconnect attempt message ===
  PASS: Reconnect attempt logged

=== Test 4: Restart agent, verify reconnection ===
  PASS: Client reconnected to new agent
    INFO  [uxrce_dds_client] synchronized with time offset 1774156926944585us

Results: 4 passed, 0 failed
```

**Key insight**: You don't need Gazebo for uXRCE-DDS testing. `PX4_SIM_MODEL=none` runs PX4 headless — it starts all modules including `uxrce_dds_client` without any simulator. The agent communicates over UDP localhost. This makes the test fast (~60 seconds total) and Docker-friendly.

---

## 7. Analyzing Safety-Critical Code: The Land Detector

The multicopter land detector implements a three-stage state machine:

```
                    ┌──────────────┐
                    │   IN FLIGHT  │
                    └──────┬───────┘
                           │ low throttle + no vertical movement
                           │ + close to ground (or skipped)
                           │ + commanded descent (if climb rate controlled)
                           ▼
                    ┌──────────────┐
                    │GROUND CONTACT│  (1/3 second hysteresis)
                    └──────┬───────┘
                           │ minimum thrust + no rotation
                           │ + no freefall + ground_contact
                           ▼
                    ┌──────────────┐
                    │ MAYBE LANDED │  (1/3 second hysteresis)
                    └──────┬───────┘
                           │ all conditions maintained
                           ▼
                    ┌──────────────┐
                    │    LANDED    │  (1/3 second hysteresis)
                    └──────────────┘
```

Each transition requires its conditions to hold for a hysteresis period (default 1/3 second, extended to 1 second when distance-to-ground is observable but currently invalid).

### The false landed-state bug (#26839)

When using OFFBOARD mode with `direct_actuator` control (companion sends motor commands directly), the land detector could falsely declare "landed" mid-flight. The causal chain:

1. `control_mode.cpp` had no `direct_actuator` branch → `flag_control_climb_rate_enabled` stayed false
2. Without climb rate control, the land detector used permissive manual-throttle thresholds
3. In `direct_actuator` mode, PX4's controllers don't publish `vehicle_thrust_setpoint` → the land detector read stale zero-initialized data
4. Stale zero thrust always satisfies "low throttle" and "minimum thrust"
5. With `dist_bottom_valid=false`, the close-to-ground check was skipped
6. Result: `ground_contact` → `maybe_landed` → `landed` while still airborne

The fix was three-pronged:
- Add the missing `direct_actuator` branch in `control_mode.cpp`
- Track `vehicle_thrust_setpoint` freshness (only use it if published within the last second)
- Guard both thrust-dependent checks with the validity flag

**Lesson**: Safety-critical code paths need to handle the "data not available" case explicitly. A zero-initialized value and a genuine zero-thrust command are indistinguishable without a freshness check. The correct default when data is unavailable is "don't trigger" — not "assume worst case."

---

## 8. MAVLink Signing: Silent Security Failures

MAVLink 2 supports message signing — SHA-256 HMAC over each message. PX4's implementation stores a 32-byte key + 8-byte timestamp in `/mavlink/mavlink-signing-key.bin`. The `MAV_SIGN_CFG` parameter controls signing mode:

| Value | Mode | Behavior |
|-------|------|----------|
| 0 | `PROTO_SIGN_OPTIONAL` | Accept all messages |
| 1 | `PROTO_SIGN_NON_USB` | Require signing except on USB |
| 2 | `PROTO_SIGN_ALWAYS` | Require signing on all channels |

### The silent failure (#26813)

When `MAV_SIGN_CFG` was set to require signing but no valid key was available (missing file, all-zero key), `accept_unsigned()` had this logic:

```cpp
// BEFORE (buggy):
if (!_is_signing_initialized) {
    return true;  // Accept ALL messages when key is missing!
}
```

This silently disabled signing — the exact opposite of safe behavior. An operator who configured signing had no indication it was non-functional.

The fix:

```cpp
// AFTER:
if (sign_mode == PROTO_SIGN_OPTIONAL) {
    return true;  // Signing not required, accept all
}

if (!_is_signing_initialized) {
    // Signing configured but key missing — only allow USB
    // (so SETUP_SIGNING can still provision the key)
    return is_usb_uart;
}
```

Plus logging at every signing lifecycle event: key load success/failure, SETUP_SIGNING updates, write errors.

**Lesson**: Security features that fail silently are worse than no security at all — they create a false sense of protection. When a security configuration is active but cannot be enforced, the system should log loudly and fail closed (reject), not fail open (accept).

---

## 9. The Contribution Workflow

### PR title format

PX4's CI enforces conventional commits with mandatory scope:

```
type(scope): description

# Valid:
fix(uxrce_dds_client): fix session reconnection after agent restart
refactor(io_timer): make timer_io_channels[].timer_channel 0-indexed

# Invalid (will fail CI):
refactor: make timer_io_channels[].timer_channel 0-indexed  ← missing scope
fix stuff                                                    ← no type, no scope
```

Valid types: `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`, `build`, `ci`, `chore`, `revert`.

### Commit message

PX4 requires `Signed-off-by` (DCO). Use `git commit -s` or add it manually:

```
Signed-off-by: Your Name <your@email.com>
```

### The full pre-PR checklist

```bash
# 1. Build SITL
make px4_sitl_default -j$(nproc)

# 2. Build at least one NuttX target
make px4_fmu-v6x_default -j$(nproc)

# 3. Run all unit tests
make tests -j$(nproc)

# 4. Code style
./Tools/astyle/check_code_style_all.sh --fix

# 5. ASan build (if touching memory-sensitive code)
PX4_ASAN=1 make px4_sitl_default -j$(nproc)

# 6. TSan build (if touching concurrent code)
make clean && PX4_TSAN=1 make px4_sitl_default -j$(nproc)
```

All of these run in Docker. No local toolchain required.

---

## 10. Patterns and Anti-Patterns

### Things that worked

- **Reading the code before proposing changes.** The timer_channel refactor touched 20 files across 6 platforms. The explore agent found all 51 instances of `timer_channel - 1` before I changed a single line.

- **Building multiple targets.** STM32 and NXP have completely different timer driver implementations. A SITL-only build would have missed compilation errors in platform-specific code.

- **Testing reconnection end-to-end in Docker SITL.** The pong flag bug would have been invisible in a unit test — it only manifests after a real session lifecycle (connect → agent death → reconnection attempt).

- **Checking how existing call sites work.** For the mission resume bug, all 4 call sites of `getPreviousPositionItems()` were audited. 3 of 4 passed the index directly. The buggy one was the outlier.

### Things to watch for

- **Generated code errors.** When a build fails in a file under `build/`, trace back to the template/generator.

- **Stale build artifacts.** ASan and TSan builds are incompatible. Always `make clean` when switching sanitizers.

- **Docker user mismatch.** If you build as root inside Docker, then try to build as your user, you'll get permission errors on `FETCH_HEAD` and build directories. Always use `--user="$(id -u):$(id -g)"`.

- **The `-Werror` wall.** PX4 compiles with `-Werror`. Unused variables, unused functions, and format string mismatches are all hard errors. This catches real bugs (the DDS subscription fix) but also means you can't leave debugging printf's in your code.

- **Platform-specific Channel enums.** STM32 `Timer::Channel` starts at 1 (was 1, now 0). NXP starts at 0. ESP32 starts at 0. RPI starts at 1 (was 1, now 0). Each platform's `initIOTimerChannel()` converts differently. Don't assume consistency.

---

## Summary of Contributions

| PR | Issue | Area | Files | Key Technique |
|----|-------|------|-------|---------------|
| [#26845](https://github.com/PX4/PX4-Autopilot/pull/26845) | #26747 | io_timer 0-indexing | 20 | Multi-platform build verification |
| [#26846](https://github.com/PX4/PX4-Autopilot/pull/26846) | #26799 | DDS empty subscriptions | 3 | Code generation pipeline tracing |
| [#26847](https://github.com/PX4/PX4-Autopilot/pull/26847) | #26813 | MAVLink signing | 1 | Security audit of accept_unsigned() |
| [#26848](https://github.com/PX4/PX4-Autopilot/pull/26848) | #26022 | uXRCE-DDS reconnect | 1 | SITL integration test in Docker |
| [#26853](https://github.com/PX4/PX4-Autopilot/pull/26853) | #26795 | Mission resume camera | 1 | Call-site consistency audit |
| [#26854](https://github.com/PX4/PX4-Autopilot/pull/26854) | #26839 | Landed-state detection | 3 | State machine + data freshness analysis |

Every fix was built on STM32 + SITL, tested with `make tests` (154/154), verified with `check_code_style_all.sh`, and where applicable built with ASan and TSan. The uXRCE-DDS reconnection fix was additionally verified end-to-end in Docker SITL with a live MicroXRCEAgent.

The common thread across all six: **read the code, build on all affected platforms, test in Docker, verify the fix doesn't break the thing you didn't change.**

---

**Related:**
- [Running px4-ros2-interface-lib Integration Tests Against PX4 SITL](/posts/px4-ros2-integration-testing-sitl-gazebo/)
- [Migrating PX4's ROS Integration Tests from Gazebo Classic to SIH](/posts/px4-ros-integration-tests-gazebo-to-sih-migration/)
- [fiber-nav-sim project](/open-source/fiber-nav-sim/)
