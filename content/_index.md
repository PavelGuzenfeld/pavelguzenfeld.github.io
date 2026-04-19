---
title: "Home"
---

## What I Do

I build the software that keeps drones in the air. From avionics integration to computer vision pipelines — every line of code runs on hardware where failure isn't an option.

**C++23** for zero-overhead abstractions. **ROS 2** for distributed systems. **PX4** for flight control. All running on edge hardware under tight constraints.

---

## Featured Projects

### [behavior-tree-lite](/projects/behavior-tree-lite/)
Header-only C++23 behavior tree with a **compile-time DSL**. Zero heap allocation, flattened execution, and 10x smaller binary than BehaviorTree.CPP.

### [strong-types](/projects/strong-types/)
Type-safe C++ primitives that catch unit and coordinate mix-ups **at compile time**. Fuzz-tested. Because `meters` and `feet` should never silently convert.

### [l2-hybrid-protocol](/projects/l2-hybrid-protocol/)
Custom Layer 2 network protocol that beats raw UDP latency for drone telemetry.

### [fiber-nav-sim](/projects/fiber-nav-sim/)
Full VTOL navigation simulation — PX4 + Gazebo + ROS 2. Test your flight code before it leaves the ground.

[See all projects &rarr;](/projects/)

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
- **ROS 2** `rclcpp`/`ros2cli` — O(N²) → O(N) CallbackGroup (71x speedup), deadlock fix, `--content-filter` in `ros2 topic` (3 PRs under review)
- **Fast-DDS** — 7 PRs under review: data races, infinite loop, null-deref, missing includes

---

## Tech Stack

`C++23` `CMake` `ROS 2` `PX4` `Gazebo` `GStreamer` `Docker` `GitHub Actions` `Python` `Linux`

