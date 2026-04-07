---
title: "Scripted Hardware Testing for PX4 — MAVLink Shell, Docker, and pymavlink"
date: 2026-04-07
draft: false
tags: ["PX4", "MAVLink", "Docker", "Python", "hardware-testing", "pymavlink", "embedded", "CI"]
keywords: ["PX4 hardware testing", "MAVLink shell scripting", "pymavlink serial control", "PX4 firmware verification", "CubeOrange testing", "Docker embedded testing"]
cover:
  image: /images/posts/px4-hardware-testing.png
  alt: "Scripted Hardware Testing for PX4"
categories: ["deep-dive"]
summary: "How to script PX4 hardware verification using pymavlink's SERIAL_CONTROL protocol over a USB connection — download CI firmware, flash from the command line, and run NSH commands programmatically. No QGroundControl required."
ShowToc: true
---

## The Problem

You've submitted a PR to PX4-Autopilot. CI builds pass. SITL tests pass. A reviewer asks: *"Did you test this on real hardware?"*

The standard answer is to open QGroundControl, flash the firmware, open the MAVLink console, type commands manually, and eyeball the results. That works, but it doesn't scale, it's not reproducible, and it's not something you can run from a CI pipeline or a shell script.

I recently needed to verify that a [timer register refactor](https://github.com/PX4/PX4-Autopilot/pull/26845) — changing `timer_io_channels[].timer_channel` from 1-indexed to 0-indexed across 25 files — didn't break PWM output on an STM32H7 board. The reviewer specifically flagged the CubeOrange (H7-based) as the "most broken" target. SITL can't catch register-level off-by-one errors. I needed real hardware, and I needed it scripted.

This post walks through the entire process: downloading firmware from GitHub Actions, flashing over USB, and running NSH commands — all from the command line, all scriptable.

---

## What You Need

- A PX4-compatible flight controller connected via USB (I'm using a CubeOrange)
- Docker (for building firmware, though we'll also show how to skip the build entirely)
- Python 3 with `pymavlink` and `pyserial`
- `px4_uploader.py` from the PX4-Autopilot tree

```bash
pip3 install pymavlink pyserial
```

---

## Step 1: Get the Firmware

You have two options: build it yourself or download it from CI.

### Option A: Download from GitHub Actions

Every PX4 pull request builds firmware for all supported boards. You can download the exact binary that CI produced:

```bash
# Find the artifact ID for your board
gh api repos/PX4/PX4-Autopilot/actions/runs/<RUN_ID>/artifacts \
  --jq '.artifacts[] | select(.name == "px4_nuttx-cubepilot_build_artifacts") | .id'

# Download and extract
gh api repos/PX4/PX4-Autopilot/actions/artifacts/<ARTIFACT_ID>/zip \
  > /tmp/cubepilot_artifacts.zip
unzip -o /tmp/cubepilot_artifacts.zip cubepilot_cubeorange_default.px4 -d /tmp/
```

This is the safest approach — you're testing the exact same binary that CI built, with the exact same toolchain. No "works on my machine" ambiguity.

### Option B: Build in Docker

If you need to build from source (e.g., testing local changes), use PX4's Docker image:

```bash
docker run --rm \
  -v $(pwd):/src -w /src \
  px4io/px4-dev:v1.17.0-beta1 \
  make cubepilot_cubeorange_default
```

**Watch out for NuttX Kconfig paths.** If you've previously built locally, the `apps/Kconfig` files may have your host's absolute paths baked in (`/home/user/PX4-Autopilot/...`). Inside Docker, the repo is mounted at `/src`, so these paths won't resolve. Fix them:

```bash
docker run --rm -v $(pwd):/src -w /src px4io/px4-dev:v1.17.0-beta1 bash -c '
  find platforms/nuttx/NuttX/apps -name Kconfig \
    -exec grep -l "/home/" {} \; | while read f; do
    sed -i "s|/home/.*/PX4-Autopilot|/src|g" "$f"
  done
  make cubepilot_cubeorange_default
'
```

---

## Step 2: Flash Over USB

Verify the board is connected:

```bash
$ lsusb | grep -i cube
Bus 003 Device 016: ID 2dae:1016 CubePilot CubeOrange

$ ls /dev/ttyACM*
/dev/ttyACM0
```

Flash using `px4_uploader.py` (note the `4` — it's `px4_uploader.py`, not `px_uploader.py`):

```bash
python3 Tools/px4_uploader.py --port /dev/ttyACM0 /tmp/cubepilot_cubeorange_default.px4
```

Output:

```
Found board 140,0 protocol v5 on /dev/ttyACM0
Firmware: board_id=140, revision=0
Size: 1923820 bytes (97.9%)
Serial: 0049001e3230511634353730
Chip: STM32H743/753
Uploaded in 30s
```

### Flashing from Docker

If you want to keep everything containerized, pass the device into the container:

```bash
docker run --rm \
  --device=/dev/ttyACM0 \
  -v $(pwd):/src -w /src \
  px4io/px4-dev:v1.17.0-beta1 \
  python3 Tools/px4_uploader.py --port /dev/ttyACM0 /tmp/firmware.px4
```

---

## Step 3: Run NSH Commands via MAVLink Shell

This is where it gets interesting. PX4 exposes an NSH shell over MAVLink's `SERIAL_CONTROL` message. QGroundControl uses this for its built-in console. We can do the same thing programmatically.

### Why Not Just Open the Serial Port Directly?

The USB port on most PX4 boards runs MAVLink, not a raw serial console. If you `cat /dev/ttyACM0`, you'll see binary garbage — that's MAVLink packets. The NSH shell is tunneled *inside* the MAVLink stream via `SERIAL_CONTROL` messages with device type `SERIAL_CONTROL_DEV_SHELL`.

### The Script

```python
from pymavlink import mavutil
import time

def connect(port="/dev/ttyACM0", baud=57600):
    mav = mavutil.mavlink_connection(port, baud=baud)
    mav.wait_heartbeat(timeout=10)
    print(f"Connected to system {mav.target_system}")
    return mav

def nsh_command(mav, cmd, timeout=3):
    """Send a command to the PX4 NSH shell and return the output."""
    cmd_bytes = (cmd + "\n").encode("utf-8")

    for i in range(0, len(cmd_bytes), 70):
        chunk = cmd_bytes[i:i+70]
        padding = b"\x00" * (70 - len(chunk))
        mav.mav.serial_control_send(
            10,    # SERIAL_CONTROL_DEV_SHELL
            6,     # RESPOND | EXCLUSIVE
            0, 0,
            len(chunk),
            chunk + padding
        )

    time.sleep(0.5)
    result = b""
    end_time = time.time() + timeout

    while time.time() < end_time:
        msg = mav.recv_match(type="SERIAL_CONTROL", timeout=0.5)
        if msg:
            result += bytes(msg.data[:msg.count])
        elif result:
            break

    return result.decode(errors="ignore")
```

Key details:

- **Device type 10** is `SERIAL_CONTROL_DEV_SHELL` — the MAVLink NSH tunnel
- **Flags 6** is `SERIAL_CONTROL_FLAG_RESPOND | SERIAL_CONTROL_FLAG_EXCLUSIVE` — tells PX4 to send output back and give us exclusive access
- **70-byte chunks** — the `SERIAL_CONTROL` message has a fixed 70-byte data field; longer commands need to be split
- **Polling for output** — PX4 sends responses as separate `SERIAL_CONTROL` messages; we poll until we stop receiving

### Initializing the Shell

The first call should be an empty command to wake up the shell:

```python
mav = connect()
nsh_command(mav, "")  # Wake up NSH
time.sleep(0.5)
```

---

## Step 4: Verify Your Changes

Now you can run any PX4 command and inspect the output programmatically:

```python
# Check firmware version
print(nsh_command(mav, "ver all"))
# HW arch: CUBEPILOT_CUBEORANGE
# PX4 version: 1.17.0
# Build datetime: Apr 7 2026 11:58:40

# Set an airframe to activate PWM outputs
nsh_command(mav, "param set SYS_AUTOSTART 4001")

# Start the PWM output module
nsh_command(mav, "pwm_out start")

# Check PWM channel status
output = nsh_command(mav, "pwm_out status")
print(output)
# Channel  0: func:   0, value: 1000.00, min: 1100, max: 1900
# Channel  1: func:   0, value: 1000.00, min: 1100, max: 1900
# ...
# Timer 1: rate: 400 channels: 4 5

# Check actuator outputs
print(nsh_command(mav, "listener actuator_outputs 0"))
```

For my timer refactor PR, the key validation was:
1. `pwm_out` starts without errors (no OOB array access from wrong timer_channel values)
2. All channels report correct min/max values (correct CCR register addressing)
3. Timer-to-channel mapping is correct (channels 4, 5 on Timer 1)

All passed on the CubeOrange — the same H7 board the reviewer flagged as potentially broken.

---

## Putting It All Together: Docker End-to-End

Here's the complete flow in a single Docker command — connect, run commands, print results:

```bash
docker run --rm \
  --device=/dev/ttyACM0 \
  -v $(pwd):/src -w /src \
  px4io/px4-dev:v1.17.0-beta1 \
  bash -c '
pip3 install pymavlink pyserial --quiet 2>/dev/null
python3 -c "
from pymavlink import mavutil
import time

mav = mavutil.mavlink_connection(\"/dev/ttyACM0\", baud=57600)
mav.wait_heartbeat(timeout=10)
print(\"Connected to system\", mav.target_system)

def nsh_command(mav, cmd, timeout=3):
    cmd_bytes = (cmd + chr(10)).encode(\"utf-8\")
    for i in range(0, len(cmd_bytes), 70):
        chunk = cmd_bytes[i:i+70]
        padding = b\"\x00\" * (70 - len(chunk))
        mav.mav.serial_control_send(10, 6, 0, 0, len(chunk), chunk + padding)
    time.sleep(0.5)
    result = b\"\"
    end_time = time.time() + timeout
    while time.time() < end_time:
        msg = mav.recv_match(type=\"SERIAL_CONTROL\", timeout=0.5)
        if msg:
            result += bytes(msg.data[:msg.count])
        elif result:
            break
    return result.decode(errors=\"ignore\")

nsh_command(mav, \"\")
time.sleep(0.5)

print(\"=== Firmware ===\")
print(nsh_command(mav, \"ver all\"))

print(\"=== PWM Output ===\")
nsh_command(mav, \"param set SYS_AUTOSTART 4001\")
nsh_command(mav, \"pwm_out start\")
print(nsh_command(mav, \"pwm_out status\", timeout=5))
"'
```

No GUI. No manual steps. Fully reproducible.

---

## Tips and Gotchas

### The USB port speaks MAVLink, not serial

Don't try to open `/dev/ttyACM0` with `picocom` or `screen` expecting a shell — you'll get binary garbage. Use the MAVLink shell tunnel described above.

### `px4_uploader.py` vs `px_uploader.py`

The script is called `px4_uploader.py` (with a `4`). Tab completion will happily offer you `px_mkfw.py`, `px_process_airframes.py`, and other scripts that are not what you want.

### SITL can't catch register-level bugs

SITL simulates the flight controller logic but not the hardware registers. If your change affects timer channel indexing, DMA base addresses, or CCR register offsets, it will pass SITL and fail on hardware. There's no substitute for a real board.

### NuttX Kconfig host path contamination

If you've ever run `make` locally (outside Docker), NuttX generates `Kconfig` files with your host's absolute paths baked in. These break when you later try to build in Docker where the repo is mounted at `/src`. The fix is to `sed` the paths or regenerate with `mkkconfig.sh`.

### Downloading CI artifacts requires `gh` auth

The `gh api` commands for downloading artifacts require you to be authenticated with the GitHub CLI. Run `gh auth login` once if you haven't already.

---

## What This Enables

This approach isn't just for one-off verification. Once you have scripted hardware access, you can:

- **Run hardware regression tests in CI** if you have boards connected to runners
- **Compare behavior across firmware versions** by flashing different builds and diffing the output
- **Automate parameter sweeps** — set a parameter, read a sensor, repeat
- **Build a hardware test matrix** — flash the same firmware to multiple boards and compare results

The MAVLink `SERIAL_CONTROL` protocol gives you full NSH access — anything you can do in QGroundControl's MAVLink console, you can do in a script.

---

## References

- [MAVLink SERIAL_CONTROL message](https://mavlink.io/en/messages/common.html#SERIAL_CONTROL)
- [PX4 MAVLink Shell](https://docs.px4.io/main/en/debug/mavlink_shell.html)
- [PX4 Firmware Upload](https://docs.px4.io/main/en/dev_setup/building_px4.html#uploading-firmware-flashing-the-board)
- [PR #26845: io_timer 0-indexed refactor](https://github.com/PX4/PX4-Autopilot/pull/26845) — the PR that motivated this workflow
