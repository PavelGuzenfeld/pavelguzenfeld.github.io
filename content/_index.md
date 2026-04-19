---
title: "Home"
---

## Featured Projects

- [**behavior-tree-lite**](/projects/behavior-tree-lite/) — header-only C++23 behavior tree with a compile-time DSL. Zero heap allocation, 10× smaller binary than BehaviorTree.CPP.
- [**strong-types**](/projects/strong-types/) — compile-time type safety for C++ primitives with SI units. Fuzz-tested. No more silent `meters` → `feet` conversions.
- [**l2-hybrid-protocol**](/projects/l2-hybrid-protocol/) — custom Layer 2 network protocol that beats raw UDP latency for drone telemetry.
- [**fiber-nav-sim**](/projects/fiber-nav-sim/) — VTOL navigation simulation with PX4 + Gazebo + ROS 2. Fiber-optic + monocular vision fusion tested over 3.3 km in SITL.

[See all projects →](/projects/)

---

## Open Source Contributions

**64 patches merged across 11 upstream projects, 17 more open for review.** I contribute upstream to the tools I depend on:

- **Eigen** — 23 merged MRs: Householder BLAS-3, Gram-Schmidt QR, uint128 division, AutoDiffScalar, stableNorm, GCC false-positives
- **MAVSDK** — 14 merged PRs (MAVSDK + MAVSDK-Proto): telemetry timestamps, geofence download, HOME_POSITION, mocap fixes
- **GStreamer** — 6 merged MRs: shmsink exit code, GstShmAllocator page alignment, CUDA memory checks, NVMM Jetson
- **XGBoost** — 5 merged PRs: `python -OO` crash fixes, type safety, dead code removal
- **PX4-Autopilot** — 4 merged PRs: DDS reconnection, MAVLink signing, mission resume bugs
- **px4-ros2-interface-lib** — 4 merged PRs (Auterion): VTOL timeout config, `HomePositionSetter`, namespace fixes
- **dora-rs** — 3 merged PRs: dynamic node init, zero-copy output, progress bars
- **OpenCV** (2), **concurrentqueue** (2), **ros2/geometry2** (1) — targeted upstream fixes
- **ROS 2** `rclcpp`/`ros2cli` — O(N²) → O(N) CallbackGroup (71× speedup), deadlock fix, `--content-filter` in `ros2 topic` (3 PRs under review)
- **Fast-DDS** — 7 PRs under review: data races, infinite loop, null-deref, missing includes

[Full list with per-PR status →](/projects/#upstream-contributions)

---

## Tech Stack

`C++23` `CMake` `ROS 2` `PX4` `Gazebo` `GStreamer` `Docker` `GitHub Actions` `Python` `Linux`
