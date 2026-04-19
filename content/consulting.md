---
title: "Consulting"
layout: "single"
summary: "Consulting and contract work for UAV, robotics, and embedded C++ teams. Navigation pipelines, flight control integration, and real-time video."
ShowToc: true
---

## Consulting for UAV and Robotics Teams

I help teams build and stabilize flight-critical C++ systems. If your codebase touches drones, navigation, or real-time video and something isn't working the way it should, I can probably help.

### What I Help With

- **Flight-critical C++23 systems** -- low-latency, zero-overhead, safety-constrained code for avionics and edge hardware
- **ROS 2 and PX4 integration** -- sensor fusion, custom airframes, EKF2 tuning, offboard control
- **GStreamer and Jetson pipelines** -- zero-copy video, shared memory, NVMM, latency debugging
- **CI, testing, and build infrastructure** -- Docker-based workflows, sanitizers, SITL, fuzz testing
- **Upstream bug-hunting** -- tracing intermittent failures in Eigen, rclcpp, PX4, MAVSDK, and friends back to specific commits, then landing the fix upstream so you stop having to carry it

### Case Studies

#### GPS-denied VTOL navigation — fiber-optic + monocular vision fusion

**The problem.** A tethered quad-tailsitter drone needed sub-meter position accuracy indoors and in GPS-denied environments. Magnetic compass was unreliable around steel; visual odometry alone drifted over multi-kilometre legs.

**What I did.** Designed and implemented a sensor fusion pipeline combining fiber-optic gyro rates with a monocular visual-inertial front-end, running as a custom PX4 estimator module plus a ROS 2 sensor-fusion node. Built 330+ integration tests, SITL-based CI, a fully Dockerized simulation stack, and the bring-up path from simulator to hardware.

**Outcome.** Sub-meter position accuracy over 3.3 km in PX4 SITL. Regressions get caught in CI before hardware time is wasted. [fiber-nav-sim →](/projects/fiber-nav-sim/)

*Stack:* C++23, PX4, ROS 2, Gazebo, Docker, GTest.

#### GStreamer shared-memory crashes on Jetson production pipeline

**The problem.** A multi-camera Jetson pipeline was crashing intermittently in the field. Symptoms: exit code 1 on clean shutdown, occasional use-after-free under load, file-descriptor leaks that eventually killed the process days into flight.

**What I did.** Reproduced every failure in minimal GStreamer pipelines, traced each through `shmsink` / `shmsrc` internals, and submitted four upstream fixes to freedesktop.org GitLab -- race condition, use-after-free, fd leak, and the exit-code bug. Also contributed [gst-nvmm-cpp](/projects/#systems--libraries), a zero-copy NVMM allocator + VIC transform plugin, so the in-house pipeline could eliminate the CPU↔GPU copies entirely.

**Outcome.** Four bugs fixed upstream; production pipeline stable. Writeups: [Anatomy of Four GStreamer Shared Memory Bugs](/posts/anatomy-of-gstreamer-shm-bugs/) and [Zero-Copy Video on Jetson](/posts/gst-nvmm-cpp-zero-copy-video-jetson/).

*Stack:* C++23, GStreamer, NVIDIA NVMM, CUDA, Jetson Xavier / Orin.

#### ROS 2 core performance -- O(N²) CallbackGroup

**The problem.** A bug report on `ros2/rclcpp` showed that creating 10,000 timers took 429 ms -- a quadratic blowup in the executor's entity tracking that hurt any team running many short-lived timers (scheduler, watchdog, per-object cadence control).

**What I did.** Traced the quadratic to `CallbackGroup::add_timer` doing a linear membership check on every insert. Rewrote the path to use an indexed lookup, added tests, and validated against the original reproducer. Separately, fixed a deadlock in `TimeSource::destroy_clock_sub` where the main thread held a lock while joining a thread that needed the same lock.

**Outcome.** 71× speedup on the 10,000-timer reproducer. Both patches open for upstream review. Full writeup: [Fixing O(N²) Entity Addition in ROS 2's CallbackGroup](/posts/fixing-quadratic-callback-group-rclcpp/).

*Stack:* C++17/20, rclcpp, ROS 2 Rolling, gtest.

#### PX4 SIH on production flight controllers

**The problem.** A team wanted hardware-in-the-loop testing on real Pixhawk boards -- without propellers, without a motion-capture rig, but with the actual flight controller running the same firmware it would fly. The pre-built PX4 firmware didn't include the SIH module, and a custom build was failing at flash time on a board without enough code space.

**What I did.** Built a custom PX4 with flash-trimming and module-level config tweaks so SIH fit on the target hardware. Wired fan-out MAVLink routing so one serial link feeds both the simulator and the ground station. Connected the whole stack to a Unity-based visualizer for realistic flight rehearsal.

**Outcome.** Hardware-in-the-loop setup running on a real Pixhawk with zero propellers. Team can rehearse missions on the bench end-to-end. Full walkthrough: [Running PX4 SIH on Real Hardware](/posts/px4-sih-on-hardware-custom-firmware-unity/).

*Stack:* PX4, NuttX, MAVLink, Unity, Docker, serial routing.

#### Eigen numerical-library upstream work

**The problem.** A safety-critical navigation stack was blocked on an Eigen bug where `TensorUInt128` division hit an infinite loop on overflow inputs. Separately, the team's linear-algebra hot path was bottlenecked on `HouseholderSequence::applyThisOnTheRight`, which used a BLAS-2 scalar inner loop.

**What I did.** Upstreamed 23 patches to Eigen across bug fixes and performance improvements: the uint128 infinite-loop fix, a `GCC 13 -Warray-bounds` false-positive suppression that was breaking our Jetson builds, a Modified Gram-Schmidt QR implementation for a use case where explicit `Q`/`R` matter, and a blocked BLAS-3 right-side Householder application. Blog-post series documents the reproducer, measurement, fix, and upstream review for each.

**Outcome.** Blockers cleared; fewer patches to carry locally. Selected writeups: [Modified Gram-Schmidt vs Householder QR benchmark](/posts/gram-schmidt-vs-householder-qr-benchmark/), [Upgrading Householder from BLAS-2 to BLAS-3](/posts/eigen-householder-blocked-right-side/), [Fixing uint128 division infinite loop](/posts/fixing-eigen-uint128-division-infinite-loop/).

*Stack:* C++17/20, Eigen, GCC, GitLab CI.

### How an Engagement Typically Works

1. **30-minute intro call** -- problem, constraints, what "done" looks like.
2. **Scoped proposal** -- fixed-price or day-rate, deliverables, timeline, code licensing.
3. **Work in your repo or mine** -- small PRs, tests first, no throw-it-over-the-wall handoffs.
4. **Closing handoff** -- writeup, runbook, and a short recorded walkthrough if it helps.

Short reproducers and bug-hunts can turn around in a few days. Larger integrations (new sensor fusion, SITL setup, full pipeline rewrite) typically run 2-8 weeks.

### Availability

Available for consulting and contract work -- remote or on-site. Based in Israel (UTC+2/+3), comfortable with EU/US time zones.

**Email:** [me@pavelguzenfeld.com](mailto:me@pavelguzenfeld.com) | **GitHub:** [PavelGuzenfeld](https://github.com/PavelGuzenfeld) | **LinkedIn:** [pavelguzenfeld](https://www.linkedin.com/in/pavelguzenfeld/)
