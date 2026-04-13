---
title: "About"
layout: "single"
summary: "UAV software engineer specializing in C++23 avionics, navigation, and computer-vision pipelines. 103 patches merged across Eigen, ROS 2, GStreamer, PX4, MAVSDK, and Fast-DDS."
ShowToc: false
---

## Who I Am

I'm a drone avionics software engineer building safety-critical systems for autonomous flight. I design the software that runs on UAV avionics -- navigation, computer vision pipelines, and flight control integration -- where every line of code has to earn its place on hardware that can't afford to fail.

I got into this field because I wanted to write software that interacts with the physical world under real constraints -- not just latency SLAs, but actual physics. Drones don't get to retry a failed request.

## What I Work With

- **Languages:** C++23, Python
- **Domains:** Drone avionics, navigation, computer vision, edge computing
- **Frameworks:** ROS 2, PX4, GStreamer, Gazebo
- **Hardware:** NVIDIA Jetson (Xavier, Orin), Pixhawk
- **Infrastructure:** CMake, Docker, GitHub Actions, Linux

## What I Care About

I'm drawn to problems at the boundary between correctness and performance -- type-safe APIs that compile away to nothing, zero-copy pipelines, and deterministic behavior on constrained hardware. I'd rather spend a day getting the abstraction right than ship something that "works for now."

## Open Source Contributions

103 patches merged across 15 projects. I contribute upstream to the tools I depend on -- not because it looks good, but because I hit bugs and want them fixed.

**Eigen** -- 24 MRs: [Householder BLAS-3 right-side application](/posts/eigen-householder-blocked-right-side/), [Gram-Schmidt QR implementation](/posts/gram-schmidt-vs-householder-qr-benchmark/), [uint128 division infinite loop fix](/posts/fixing-eigen-uint128-division-infinite-loop/), [AutoDiffScalar fill regression](/posts/eigen-autodiff-fill-regression/), [GCC false-positive suppression](/posts/fixing-gcc-false-positives-in-eigen/), [stableNorm code review fix](/posts/eigen-stablenorm-gram-schmidt/), [Doxygen .inc extension mapping](/posts/debugging-doxygen-inc-extension-mapping-eigen/)

**ROS 2** -- 4 PRs: [O(N²) → O(N) CallbackGroup fix (71x speedup)](/posts/fixing-quadratic-callback-group-rclcpp/), deadlock fix in TimeSource, and more. Full writeup: [Contributing to ROS 2 -- A Practical Guide](/posts/contributing-to-ros2-a-practical-guide/)

**GStreamer** -- 7 MRs: [Four shared memory bugs (race condition, use-after-free, fd leak, exit code)](/posts/anatomy-of-gstreamer-shm-bugs/), [shmsink exit code fix](/posts/fixing-gstreamer-shmsink-exit-code-bug/), [gst-nvmm-cpp zero-copy Jetson plugin](/posts/gst-nvmm-cpp-zero-copy-video-jetson/)

**PX4-Autopilot** -- 7 PRs: DDS reconnection, MAVLink signing analysis, mission resume bugs. Detailed in [PX4 Troubleshooting Guide](/posts/px4-autopilot-troubleshooting-debugging-testing-guide/)

**MAVSDK** -- 11 PRs: telemetry timestamps, geofence download, HOME_POSITION, mocap fixes, mission test race conditions

**Fast-DDS** -- 7 PRs: data races, infinite loop, null-deref, missing includes. Related: [DDS Content Filter String Params Bug](/posts/dds-content-filter-string-params-ros2/)

**Other:** [XGBoost](https://github.com/dmlc/xgboost) (10 PRs), [OpenCV](https://github.com/opencv/opencv), [dora-rs](https://github.com/dora-rs/dora) (9 PRs), [concurrentqueue](https://github.com/cameron314/concurrentqueue), [px4-ros2-interface-lib](https://github.com/Auterion/px4-ros2-lib)

## Projects

- [behavior-tree-lite](/projects/behavior-tree-lite/) -- C++23 header-only behavior tree with compile-time DSL, zero heap allocation, 10x smaller binary than BehaviorTree.CPP
- [strong-types](/projects/strong-types/) -- Compile-time type safety for C++ primitives with SI units and dimensional analysis
- [l2-hybrid-protocol](/projects/l2-hybrid-protocol/) -- Low-latency Layer 2 raw socket protocol for drone telemetry
- [fiber-nav-sim](/projects/fiber-nav-sim/) -- GPS-denied VTOL navigation simulator with PX4 + Gazebo + ROS 2

## Get in Touch

Available for [consulting and contract work](/consulting/) -- remote or on-site.

**Email:** [me@pavelguzenfeld.com](mailto:me@pavelguzenfeld.com) | **GitHub:** [PavelGuzenfeld](https://github.com/PavelGuzenfeld) | **LinkedIn:** [pavelguzenfeld](https://www.linkedin.com/in/pavelguzenfeld/) | **X:** [@PavelGuzenfeld](https://x.com/PavelGuzenfeld)
