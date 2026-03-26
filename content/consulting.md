---
title: "Consulting"
layout: "single"
summary: "Consulting and contract work for UAV, robotics, and embedded C++ teams. Navigation pipelines, flight control integration, and real-time video."
ShowToc: false
---

## Consulting for UAV and Robotics Teams

I help teams build and stabilize flight-critical C++ systems. If your codebase touches drones, navigation, or real-time video and something isn't working the way it should, I can probably help.

### What I Help With

- **Flight-critical C++23 systems** -- low-latency, zero-overhead, safety-constrained code for avionics and edge hardware
- **ROS 2 and PX4 integration** -- sensor fusion, custom airframes, EKF2 tuning, offboard control
- **GStreamer and Jetson pipelines** -- zero-copy video, shared memory, NVMM, latency debugging
- **CI, testing, and build infrastructure** -- Docker-based workflows, sanitizers, SITL, fuzz testing

### Example Engagements

**GPS-denied VTOL navigation** -- Designed and implemented a fiber optic + monocular vision fusion algorithm for a tethered quad-tailsitter drone. Sub-meter position accuracy over 3.3km in PX4 SITL. 330+ tests, fully Dockerized.

**GStreamer shared memory bugs on Jetson** -- Found and fixed four upstream bugs in GStreamer shmsink/shmsrc (race condition, use-after-free, fd leak, exit code). Patches submitted to freedesktop.org GitLab.

**ROS 2 core performance** -- Fixed O(N^2) entity addition in rclcpp CallbackGroup (71x speedup) and a deadlock in TimeSource. Both merged upstream.

### Availability

Available for consulting and contract work -- remote or on-site.

**Email:** [me@pavelguzenfeld.com](mailto:me@pavelguzenfeld.com) | **GitHub:** [PavelGuzenfeld](https://github.com/PavelGuzenfeld) | **LinkedIn:** [pavelguzenfeld](https://www.linkedin.com/in/pavelguzenfeld/)
