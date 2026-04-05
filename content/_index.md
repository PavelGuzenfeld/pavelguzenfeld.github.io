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

103 patches across 15 projects. I contribute upstream to the tools I depend on:

- **Eigen** — 24 MRs: bug fixes, new operators, structured bindings, Gram-Schmidt QR
- **dora-rs** — 9 PRs: C++ API parity, zero-copy output, dynamic node init
- **XGBoost** — 10 PRs: `python -OO` crash fixes, type safety, dead code removal
- **PX4-Autopilot** — 7 PRs: DDS reconnection, MAVLink signing, mission resume bugs
- **GStreamer** — 7 MRs: NVMM Jetson plugins, shmsink bugs, CUDA memory checks
- **Fast-DDS** — 7 PRs: data races, infinite loop, null-deref, missing includes
- **MAVSDK** — 11 PRs: telemetry timestamps, geofence download, HOME_POSITION, mocap fixes, mission test races
- **ROS 2** — 4 PRs: O(N²) → O(N) CallbackGroup (71x speedup), deadlock fix
- **OpenCV**, **concurrentqueue**, **px4-ros2-interface-lib** — bug fixes and utilities

---

## Tech Stack

`C++23` `CMake` `ROS 2` `PX4` `Gazebo` `GStreamer` `Docker` `GitHub Actions` `Python` `Linux`

