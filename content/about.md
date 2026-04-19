---
title: "About"
layout: "single"
summary: "UAV software engineer specializing in C++23 avionics, navigation, and computer-vision pipelines. 64 patches merged across Eigen, GStreamer, MAVSDK, PX4, ROS 2, XGBoost, OpenCV, and other upstream projects."
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

**64 patches merged across 11 upstream projects, with 17 more open for review.** I contribute upstream to the tools I depend on -- not because it looks good, but because I hit bugs and want them fixed. Numbers below are live GitHub/GitLab counts as of April 2026.

**[Eigen](https://gitlab.com/libeigen/eigen)** -- 23 merged MRs: [Householder BLAS-3 right-side application](/posts/eigen-householder-blocked-right-side/), [Gram-Schmidt QR implementation](/posts/gram-schmidt-vs-householder-qr-benchmark/), [uint128 division infinite loop fix](/posts/fixing-eigen-uint128-division-infinite-loop/), [AutoDiffScalar fill regression](/posts/eigen-autodiff-fill-regression/), [GCC false-positive suppression](/posts/fixing-gcc-false-positives-in-eigen/), [stableNorm code review fix](/posts/eigen-stablenorm-gram-schmidt/), [Doxygen .inc extension mapping](/posts/debugging-doxygen-inc-extension-mapping-eigen/)

**[MAVSDK](https://github.com/mavlink/MAVSDK)** -- 14 merged PRs (10 on `MAVSDK`, 4 on `MAVSDK-Proto`): telemetry timestamps, geofence download, HOME_POSITION, mocap fixes, mission test race conditions

**[GStreamer](https://gitlab.freedesktop.org/gstreamer/gstreamer)** -- 6 merged MRs: [Four shared memory bugs (race condition, use-after-free, fd leak, exit code)](/posts/anatomy-of-gstreamer-shm-bugs/), [shmsink exit code fix](/posts/fixing-gstreamer-shmsink-exit-code-bug/), [gst-nvmm-cpp zero-copy Jetson plugin](/posts/gst-nvmm-cpp-zero-copy-video-jetson/) (2 more open for review)

**[XGBoost](https://github.com/dmlc/xgboost)** -- 5 merged PRs

**[PX4-Autopilot](https://github.com/PX4/PX4-Autopilot)** -- 4 merged PRs: DDS reconnection, MAVLink signing analysis, mission resume bugs. Detailed in [PX4 Troubleshooting Guide](/posts/px4-autopilot-troubleshooting-debugging-testing-guide/)

**[px4-ros2-interface-lib](https://github.com/Auterion/px4-ros2-interface-lib)** -- 4 merged PRs (Auterion)

**[dora-rs](https://github.com/dora-rs/dora)** -- 3 merged PRs

**[OpenCV](https://github.com/opencv/opencv)** -- 2 merged PRs · **[concurrentqueue](https://github.com/cameron314/concurrentqueue)** -- 2 merged PRs · **[ros2/geometry2](https://github.com/ros2/geometry2)** -- 1 merged PR: `StaticCache::getData()` on empty cache

**ROS 2 ecosystem** -- 4 PRs submitted, 1 merged (geometry2), 3 open on `rclcpp` and `ros2cli`: [O(N²) → O(N) CallbackGroup fix (71x speedup)](/posts/fixing-quadratic-callback-group-rclcpp/), deadlock fix in `TimeSource`, content-filter support in `ros2 topic`. Full writeup: [Contributing to ROS 2 -- A Practical Guide](/posts/contributing-to-ros2-a-practical-guide/)

**[Fast-DDS](https://github.com/eProsima/Fast-DDS)** -- 7 PRs open for review: data races, infinite loop, null-deref, missing includes, content-filter string params. Related: [DDS Content Filter String Params Bug](/posts/dds-content-filter-string-params-ros2/)

## Projects

- [behavior-tree-lite](/projects/behavior-tree-lite/) -- C++23 header-only behavior tree with compile-time DSL, zero heap allocation, 10x smaller binary than BehaviorTree.CPP
- [strong-types](/projects/strong-types/) -- Compile-time type safety for C++ primitives with SI units and dimensional analysis
- [l2-hybrid-protocol](/projects/l2-hybrid-protocol/) -- Low-latency Layer 2 raw socket protocol for drone telemetry
- [fiber-nav-sim](/projects/fiber-nav-sim/) -- GPS-denied VTOL navigation simulator with PX4 + Gazebo + ROS 2

## Get in Touch

Available for [consulting and contract work](/consulting/) -- remote or on-site.

**Email:** [me@pavelguzenfeld.com](mailto:me@pavelguzenfeld.com) | **GitHub:** [PavelGuzenfeld](https://github.com/PavelGuzenfeld) | **LinkedIn:** [pavelguzenfeld](https://www.linkedin.com/in/pavelguzenfeld/) | **X:** [@PavelGuzenfeld](https://x.com/PavelGuzenfeld)
