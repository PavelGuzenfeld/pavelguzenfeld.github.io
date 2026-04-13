# pavelguzenfeld.com

Personal website and technical blog. Built with [Hugo](https://gohugo.io/) + [PaperMod](https://github.com/adityatelange/hugo-PaperMod), deployed via GitHub Pages.

**Live site:** [pavelguzenfeld.com](https://pavelguzenfeld.com/)

---

## About

I'm a UAV & robotics software engineer specializing in C++23 avionics, navigation pipelines, and computer-vision systems for drones. I contribute upstream to the tools I depend on -- 103 patches across 15 projects including [Eigen](https://gitlab.com/libeigen/eigen), [ROS 2](https://github.com/ros2/rclcpp), [GStreamer](https://gitlab.freedesktop.org/gstreamer/gstreamer), [PX4](https://github.com/PX4/PX4-Autopilot), [Fast-DDS](https://github.com/eProsima/Fast-DDS), and [MAVSDK](https://github.com/mavlink/MAVSDK).

Available for [consulting and contract work](https://pavelguzenfeld.com/consulting/).

---

## Blog Posts

### C++ & Linear Algebra

- [Five Optiver-Style C++ Problems: Order Books, Dijkstra, and DP](https://pavelguzenfeld.com/posts/optiver-cpp-problems-order-books-dijkstra-dp/)
- [Modified Gram-Schmidt vs Householder QR: A Performance Showdown in Eigen](https://pavelguzenfeld.com/posts/gram-schmidt-vs-householder-qr-benchmark/)
- [Upgrading Eigen's Householder Right-Side Application from BLAS-2 to BLAS-3](https://pavelguzenfeld.com/posts/eigen-householder-blocked-right-side/)
- [Why You Should Use stableNorm() Instead of norm()](https://pavelguzenfeld.com/posts/eigen-stablenorm-gram-schmidt/)
- [Fixing an Infinite Loop in Eigen's 128-bit Integer Division](https://pavelguzenfeld.com/posts/fixing-eigen-uint128-division-infinite-loop/)
- [How GCC's std::fill_n Silently Regressed Eigen's AutoDiffScalar](https://pavelguzenfeld.com/posts/eigen-autodiff-fill-regression/)
- [Fixing GCC False-Positive Warnings in Eigen](https://pavelguzenfeld.com/posts/fixing-gcc-false-positives-in-eigen/)
- [Debugging Doxygen: How .inc Files Break C++ Documentation](https://pavelguzenfeld.com/posts/debugging-doxygen-inc-extension-mapping-eigen/)

### ROS 2 & DDS

- [Contributing to ROS 2 -- A Practical Guide from Four Accepted PRs](https://pavelguzenfeld.com/posts/contributing-to-ros2-a-practical-guide/)
- [Fixing O(N squared) Entity Addition in ROS 2's CallbackGroup](https://pavelguzenfeld.com/posts/fixing-quadratic-callback-group-rclcpp/)
- [Why DDS Content Filter Parameters Silently Fail for Strings in ROS 2](https://pavelguzenfeld.com/posts/dds-content-filter-string-params-ros2/)

### GStreamer & Video

- [Anatomy of Four GStreamer Shared Memory Bugs](https://pavelguzenfeld.com/posts/anatomy-of-gstreamer-shm-bugs/)
- [Fixing a GStreamer Bug: Why shmsink Always Exits with Code 1](https://pavelguzenfeld.com/posts/fixing-gstreamer-shmsink-exit-code-bug/)
- [Zero-Copy Video on Jetson: Building gst-nvmm-cpp](https://pavelguzenfeld.com/posts/gst-nvmm-cpp-zero-copy-video-jetson/)

### PX4 & Drone Simulation

- [PX4 Autopilot: A Practitioner's Guide to Troubleshooting, Debugging, and Testing](https://pavelguzenfeld.com/posts/px4-autopilot-troubleshooting-debugging-testing-guide/)
- [Scripted Hardware Testing for PX4](https://pavelguzenfeld.com/posts/scripted-hardware-testing-px4/)
- [Running PX4 ROS 2 Integration Tests Against SITL](https://pavelguzenfeld.com/posts/px4-ros2-integration-testing-sitl-gazebo/)
- [Migrating PX4's ROS Integration Tests from Gazebo to SIH](https://pavelguzenfeld.com/posts/px4-ros-integration-tests-gazebo-to-sih-migration/)

### Unity & Simulation

- [Running Unity Headless in Docker with GPU, RTSP, and MAVLink](https://pavelguzenfeld.com/posts/headless-unity-docker-simulation/)
- [Connecting PX4 SITL to Headless Unity in Docker](https://pavelguzenfeld.com/posts/unity-px4-sitl-docker-debugging-odyssey/)
- [From Magenta to Desert: Fixing Cross-Platform Unity Terrain Rendering](https://pavelguzenfeld.com/posts/unity6-terrain-rendering-cross-platform-asset-bundles/)
- [Natural Skies and Satellite Terrain in a Headless Unity Simulation](https://pavelguzenfeld.com/posts/unity-headless-environment-satellite-terrain-sky/)
- [From 21 to 25 FPS: Profiling a Headless Unity Pipeline](https://pavelguzenfeld.com/posts/unity-headless-fps-optimization-pipeline/)
- [The Satellite Tile Hunt: From 15m Blobs to 13cm Resolution](https://pavelguzenfeld.com/posts/satellite-terrain-tile-hunt-air-gapped-simulation/)

### Linux & DevOps

- [Fixing a CI Pipeline on Jetson Xavier -- 15 Failures to Green](https://pavelguzenfeld.com/posts/fixing-ci-pipeline-arm-jetson-docker/)
- [Persistent SMB Shares on Linux](https://pavelguzenfeld.com/posts/persistent-smb-mount-linux/)
- [Linux Multi-Monitor Setup with xrandr](https://pavelguzenfeld.com/posts/linux-multi-monitor-screen-configuration/)

---

## Open Source Projects

- [behavior-tree-lite](https://pavelguzenfeld.com/projects/behavior-tree-lite/) -- C++23 header-only behavior tree with compile-time DSL
- [strong-types](https://pavelguzenfeld.com/projects/strong-types/) -- Compile-time type safety for C++ primitives with SI units
- [l2-hybrid-protocol](https://pavelguzenfeld.com/projects/l2-hybrid-protocol/) -- Low-latency Layer 2 protocol for drone telemetry
- [fiber-nav-sim](https://pavelguzenfeld.com/projects/fiber-nav-sim/) -- PX4 + Gazebo VTOL navigation simulator

---

## Tech Stack

`C++23` `CMake` `ROS 2` `PX4` `Gazebo` `GStreamer` `NVIDIA Jetson` `Docker` `GitHub Actions` `Python` `Linux`

---

## Contact

**Email:** [me@pavelguzenfeld.com](mailto:me@pavelguzenfeld.com) |
**GitHub:** [PavelGuzenfeld](https://github.com/PavelGuzenfeld) |
**LinkedIn:** [pavelguzenfeld](https://www.linkedin.com/in/pavelguzenfeld/) |
**X:** [@PavelGuzenfeld](https://x.com/PavelGuzenfeld)
