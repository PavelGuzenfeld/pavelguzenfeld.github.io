---
title: "Migrating PX4's ROS Integration Tests from Gazebo Classic to SIH"
date: 2026-03-20
draft: false
tags: ["PX4", "ROS2", "SITL", "SIH", "Docker", "CI/CD", "integration-testing", "open-source"]
categories: ["deep-dive"]
summary: "PX4's MAVSDK tests were migrated to SIH but the ROS integration tests were left behind on Gazebo Classic. This post documents the complete migration — the config changes, the CI pipeline surgery, the parameter name pitfall that silently broke GlobalPositionInterfaceTest, and how to reproduce the full 14-test suite locally in Docker."
ShowToc: true
---

## Background

PX4-Autopilot's CI runs two families of integration tests against a Software-In-The-Loop (SITL) simulator:

1. **MAVSDK tests** — communicate with PX4 over MAVLink via [MAVSDK](https://mavsdk.mavlink.io/)
2. **ROS integration tests** — communicate with PX4 over DDS via [px4-ros2-interface-lib](https://github.com/Auterion/px4-ros2-interface-lib)

Both historically depended on **Gazebo Classic** as the external physics simulator. [PR #26032](https://github.com/PX4/PX4-Autopilot/pull/26032) migrated the MAVSDK tests to PX4's built-in **SIH** (Simulator-In-Hardware) simulator, eliminating the Gazebo dependency for those tests. But the ROS integration tests were left untouched — still pulling in Gazebo Classic packages, still building `sitl_gazebo-classic`, still running against the `iris` airframe.

This post documents the migration of those ROS integration tests to SIH: [PR #26836](https://github.com/PX4/PX4-Autopilot/pull/26836).

If you're not familiar with SIH or why it's a better fit for CI than Gazebo, I covered the tradeoffs in [a previous post](/posts/px4-ros2-integration-testing-sitl-gazebo/). The short version: SIH is PX4's internal physics simulator — no external process, no GPU, instant startup, deterministic sensors. It's ideal for testing flight logic and communication layers where realistic sensor noise isn't the point.

---

## What PR #26032 Established (The Pattern to Follow)

Before writing any code, I studied how the MAVSDK migration was done. PR #26032 (by @MaEtUgR, @julianoes, @mrpollo) introduced a `sih-sitl.json` config for the MAVSDK tests:

```json
{
    "mode": "sitl",
    "model_prefix": "sihsim_",
    "mavlink_connection": "udpin://0.0.0.0:14540",
    "tests": [
        {
            "model": "quadx",
            "test_filter": "[multicopter],[offboard],[offboard_attitude]",
            "timeout_min": 10
        }
    ]
}
```

Key patterns:
- **No `"simulator"` field** — SIH doesn't use an external simulator process
- **`"model_prefix": "sihsim_"`** — maps to PX4 airframe `10040_sihsim_quadx`
- **`"model": "quadx"`** instead of `"iris"` — SIH's quadrotor model
- **No `"vehicle"` field** — removed in the PR #26032 refactor

The shared `test_runner.py` was also updated to use `config.get('simulator')` instead of `config['simulator']`, making the simulator field optional. But this change was only applied in `mavsdk_test_runner.py` — `ros_test_runner.py` was left using the old `config['simulator']` accessor, which would crash with a `KeyError` if no simulator was configured.

---

## The Three Files

The migration touched three files:

### 1. `test/ros_tests/config.json` — The Test Configuration

**Before** (Gazebo Classic):
```json
{
    "mode": "sitl",
    "simulator": "gazebo",
    "model_prefix": "gazebo-classic_",
    "tests": [
        {
            "model": "iris",
            "vehicle": "iris",
            "test_filter": "ModesTest.*",
            "timeout_min": 10
        },
        {
            "model": "iris",
            "vehicle": "iris",
            "test_filter": "GlobalPositionInterfaceTest.*",
            "timeout_min": 10,
            "env": {
                "PX4_PARAM_EKF2_AGP_CTRL": 1
            }
        }
    ]
}
```

**After** (SIH):
```json
{
    "mode": "sitl",
    "model_prefix": "sihsim_",
    "mavlink_connection": "udpin://0.0.0.0:14540",
    "tests": [
        {
            "model": "quadx",
            "test_filter": "ModesTest.*",
            "timeout_min": 10
        },
        {
            "model": "quadx",
            "test_filter": "LocalPositionInterfaceTest.*",
            "timeout_min": 10,
            "env": {
                "PX4_PARAM_EKF2_EV_CTRL": 15
            }
        },
        {
            "model": "quadx",
            "test_filter": "GlobalPositionInterfaceTest.*",
            "timeout_min": 10,
            "env": {
                "PX4_PARAM_EKF2_AGP_CTRL": 1
            }
        }
    ]
}
```

Changes:
- Removed `"simulator": "gazebo"` — SIH is internal, no external sim
- Changed `model_prefix` from `"gazebo-classic_"` to `"sihsim_"`
- Changed model from `"iris"` to `"quadx"`
- Removed `"vehicle"` fields (follows PR #26032 pattern)
- Kept `EKF2_AGP_CTRL` as the parameter name (more on this below)

### 2. `test/ros_test_runner.py` — The Test Runner

The `is_everything_ready()` function had a hard dependency on the `simulator` config key:

```python
# Before — crashes with KeyError if 'simulator' not in config
if config['simulator'] == 'gazebo':
    if is_running('gzserver'):
        ...

# After — safely handles missing key
if config.get('simulator') == 'gazebo':
    if is_running('gzserver'):
        ...
```

Also updated the error message for a missing PX4 binary — the old message referenced `make px4_sitl gazebo`, which is Gazebo-specific:

```python
# Before
print("PX4 SITL is not built\n"
      "run `DONT_RUN=1 make px4_sitl gazebo` or "
      "`DONT_RUN=1 make px4_sitl_default gazebo`")

# After
print("PX4 SITL is not built\n"
      "run `make px4_sitl_default`")
```

### 3. `.github/workflows/ros_integration_tests.yml` — The CI Pipeline

This is where the biggest savings come from. Three steps removed:

**Removed: "Install gazebo"**
```yaml
# ~2 minutes of apt install gazebo11 libgazebo11-dev gstreamer1.0-plugins-*
- name: Install gazebo
  run: |
    apt update && apt install -y gazebo11 libgazebo11-dev ...
```

**Removed: "Build SITL Gazebo"**
```yaml
# ~3 minutes to compile the Gazebo Classic plugin
- name: Build SITL Gazebo
  run: make px4_sitl_default sitl_gazebo-classic
- name: ccache post-run sitl_gazebo-classic
  run: ccache -s
```

**Updated: test model**
```yaml
# Before
test/ros_test_runner.py --verbose --model iris --upload --force-color

# After
test/ros_test_runner.py --verbose --model quadx --upload --force-color
```

The `make px4_sitl_default` step stays — it builds PX4 itself, which includes the SIH module. No additional build target needed.

---

## The EKF2 Parameter Name Trap

The original plan called for updating the `GlobalPositionInterfaceTest` environment from `EKF2_AGP_CTRL` to `EKF2_AGP0_ID` + `EKF2_AGP0_CTRL`, based on what appeared to be the newer parameter naming convention. This was wrong.

On first test run, PX4 printed:

```
ERROR [param] Parameter EKF2_AGP0_CTRL not found.
ERROR [param] Parameter EKF2_AGP0_ID not found.
```

The `GlobalPositionInterfaceTest.fuseAll` test failed because the EKF2 aux global position fusion was never enabled — the parameters simply didn't exist.

Checking the actual PX4 source (`src/modules/ekf2/params_aux_global_position.yaml`):

```yaml
EKF2_AGP_CTRL:
    # Aux Global Position fusion control bitmask
    ...
```

The parameter is `EKF2_AGP_CTRL` — no `0` suffix, no separate `_ID` parameter. The `EKF2_AGP0_*` naming was from a future refactor that hasn't landed yet. The fix was simply keeping the original parameter name.

This is the kind of mistake that's invisible in code review — the parameter name looks plausible, the YAML parses fine, the CI workflow is valid. The only way to catch it is to run the actual tests against PX4.

---

## The px4-ros2-interface-lib Compatibility Issue

The ROS integration test CI workflow clones `px4-ros2-interface-lib` from `main`:

```yaml
git clone --recursive https://github.com/Auterion/px4-ros2-interface-lib.git
```

Between when the `maetugr/sih-ci` branch was created and when this PR was opened, the interface library's `main` branch added support for a new `AuxGlobalPosition` message type ([PR #180](https://github.com/Auterion/px4-ros2-interface-lib/pull/180)). This message doesn't exist in the PX4 branch yet:

```
fatal error: px4_msgs/msg/aux_global_position.hpp: No such file or directory
```

The colcon build failed trying to compile `global_position_measurement_interface.cpp`, which `#include`s the header generated from a message definition that doesn't exist in this PX4 branch's `msg/` directory.

This is a variant of the DDS message compatibility problem I documented in the [previous post](/posts/px4-ros2-integration-testing-sitl-gazebo/#failure-4-px4_msgs-version-mismatch-the-subtle-one) — except this time it's a compile-time failure rather than a silent runtime data loss. The fix was pinning the interface library to the last compatible commit:

```yaml
git clone --recursive https://github.com/Auterion/px4-ros2-interface-lib.git
cd px4-ros2-interface-lib
# Pin to last version compatible with this branch's px4_msgs (before AuxGlobalPosition)
git checkout e0c9d19
cd ..
```

---

## Local Reproduction in Docker

Here's how to reproduce the full test suite locally. The CI uses `px4io/px4-dev-ros2-galactic:2021-09-08` — a container with ROS 2 Galactic, colcon, and PX4 build tooling pre-installed.

### Step 1: Clone and set up

```bash
git clone --branch pavelgu/ros-integration-sih \
    https://github.com/PavelGuzenfeld/PX4-Autopilot.git
cd PX4-Autopilot
git submodule update --init --recursive
```

### Step 2: Start a persistent container

```bash
docker run --name px4-ros-test --privileged \
    -v $(pwd):/src/PX4-Autopilot:rw \
    -w /src/PX4-Autopilot \
    -d px4io/px4-dev-ros2-galactic:2021-09-08 \
    sleep infinity
```

### Step 3: Build everything inside the container

```bash
docker exec px4-ros-test bash -c '
set -e
git config --global --add safe.directory "*"

# Update ROS keys
sudo rm -f /etc/apt/sources.list.d/ros2.list
sudo curl -sSL https://raw.githubusercontent.com/ros/rosdistro/master/ros.key \
    -o /usr/share/keyrings/ros-archive-keyring.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/ros-archive-keyring.gpg] \
    http://packages.ros.org/ros2/ubuntu $(. /etc/os-release && echo $UBUNTU_CODENAME) main" \
    | sudo tee /etc/apt/sources.list.d/ros2.list > /dev/null

# Build micro-xrce-dds-agent
cd /opt
git clone --recursive https://github.com/eProsima/Micro-XRCE-DDS-Agent.git
cd Micro-XRCE-DDS-Agent
git checkout v2.2.1
sed -i "s/_fastdds_tag 2.8.x/_fastdds_tag 2.8.2/g" CMakeLists.txt
mkdir -p build && cd build
cmake .. && make -j$(nproc)

# Build px4-ros2-interface-lib (pinned to compatible version)
PX4_DIR="/src/PX4-Autopilot"
. /opt/ros/galactic/setup.bash
mkdir -p /opt/px4_ws/src && cd /opt/px4_ws/src
git clone --recursive https://github.com/Auterion/px4-ros2-interface-lib.git
cd px4-ros2-interface-lib && git checkout e0c9d19 && cd ..
touch px4-ros2-interface-lib/px4_ros2_py/COLCON_IGNORE || true
touch px4-ros2-interface-lib/examples/python/COLCON_IGNORE || true
cd ..
"${PX4_DIR}/Tools/copy_to_ros_ws.sh" "$(pwd)"
rm -rf src/translation_node src/px4_msgs_old
colcon build --symlink-install

# Build PX4 SITL
cd "$PX4_DIR"
make px4_sitl_default
'
```

This takes roughly 15-20 minutes. The longest steps are `colcon build` (~4 min for px4_msgs code generation) and `make px4_sitl_default` (~5 min).

### Step 4: Run the tests

```bash
docker exec px4-ros-test bash -c '
cd /src/PX4-Autopilot
. /opt/px4_ws/install/setup.bash
/opt/Micro-XRCE-DDS-Agent/build/MicroXRCEAgent udp4 localhost -p 8888 -v 0 &
test/ros_test_runner.py --verbose --model quadx --force-color
'
```

### Expected results

```
Results:
  - quadx:
     - 'ModesTest.denyArming': succeeded
     - 'ModesTest.runModeTests': succeeded
     - 'ModesTest.runMission': succeeded
     - 'ModesTest.runExecutorAutonomous': succeeded
     - 'ModesTest.runExecutorInCharge': succeeded
     - 'ModesTest.runExecutorFailsafe': succeeded
     - 'ModesTest.runExecutorOverrides': succeeded
  - quadx:
     - 'LocalPositionInterfaceTest.fuseEvPos': succeeded
     - 'LocalPositionInterfaceTest.fuseEvVel': succeeded
     - 'LocalPositionInterfaceTest.fuseEvYaw': succeeded
     - 'LocalPositionInterfaceTest.fuseAll': succeeded
  - quadx:
     - 'GlobalPositionInterfaceTest.fuseAll': succeeded
Overall result: PASS
```

14/14 tests pass. Each test starts a fresh PX4 SIH instance, runs the integration test binary via gtest, and tears down. Total runtime is approximately 3 minutes for all 14 test cases — compare that to Gazebo Classic, which needed ~2 minutes just to install packages plus ~3 minutes to build the Gazebo plugin before any tests ran.

---

## What Stays the Same

A few things were intentionally left untouched:

- **Container image** (`px4io/px4-dev-ros2-galactic:2021-09-08`): Updating to a newer ROS distro is orthogonal to the SIH migration. The current image has ROS 2 Galactic and all the build tooling needed.

- **Test structure**: The `ros_test_runner.py` orchestrator, the `TesterInterfaceRos` class, the `MicroXrceAgent` lifecycle management — all unchanged. Only the `is_everything_ready()` guard and the error message were modified.

- **Gazebo codepaths in `ros_test_runner.py`**: The `if config.get('simulator') == 'gazebo':` guard still exists. If someone later creates a Gazebo-based ROS test config, the gzserver/gzclient process checks will still work. The migration doesn't delete Gazebo support, it just stops depending on it by default.

---

## Commit History

The final PR contains four commits:

1. **`ros_integration_tests: migrate from Gazebo Classic to SIH`** — the core migration: config.json, ros_test_runner.py, CI workflow
2. **`ros_tests: fix EKF2 aux global position parameter name`** — `EKF2_AGP0_CTRL` → `EKF2_AGP_CTRL`
3. **`ros_integration_tests: pin px4-ros2-interface-lib to compatible version`** — pin to `e0c9d19` to avoid `AuxGlobalPosition` build failure

Commits 2-3 were discovered by running the tests, not by code review. This is exactly why the [previous post's](/posts/px4-ros2-integration-testing-sitl-gazebo/#takeaways) first takeaway matters: you can't validate a PX4 integration change without actually running against a live autopilot.

---

## Takeaways

1. **SIH eliminates entire CI steps.** The Gazebo Classic pipeline needed: apt install (~2 min), Gazebo plugin build (~3 min), and a GPU-capable runner. SIH needs none of that. `make px4_sitl_default` already builds the SIH module. Net CI time savings: ~5 minutes per run plus cheaper runners.

2. **Parameter names are not guessable.** `EKF2_AGP0_CTRL` looks like a reasonable next-generation name for `EKF2_AGP_CTRL`, but it doesn't exist. Always grep the source (`src/modules/ekf2/params_*.yaml`) for the actual parameter definition rather than guessing from convention.

3. **Interface library version must match the PX4 message definitions.** The `px4-ros2-interface-lib` and PX4's `msg/` directory must be in sync. When they drift apart — whether by a single byte at runtime ([DDS silent data loss](/posts/px4-ros2-integration-testing-sitl-gazebo/#failure-4-px4_msgs-version-mismatch-the-subtle-one)) or by a missing message at compile time — things break. Pin the interface library version or build from the same commit.

4. **`config.get()` vs `config[]` matters.** A Python `dict['missing_key']` raises `KeyError`; `dict.get('missing_key')` returns `None`. When a config field becomes optional (as `simulator` did when SIH was introduced), every accessor must be updated. The MAVSDK runner was fixed in PR #26032; the ROS runner was forgotten.
