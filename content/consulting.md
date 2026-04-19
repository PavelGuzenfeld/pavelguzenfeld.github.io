---
title: "Consulting"
layout: "single"
summary: "Freelance C++ for drones and robotics. Flight-critical code, navigation pipelines, video on Jetson, and upstream fixes that actually land."
ShowToc: false
---

## Consulting

I work freelance on UAV and robotics C++ codebases. If your drone software is misbehaving and nobody on the team can quite explain why, or you need someone to land a feature upstream and actually get it reviewed — that's what I do.

### What I'll do for you

- **Chase down intermittent crashes in flight controllers and video pipelines.** If it shows up once every few days in the field, I'll reproduce it on the bench.
- **Build the thing when no one else has time.** Custom PX4 modules, ROS 2 executors, GStreamer plugins, sensor fusion code. Written tight, tested, handed back with a writeup.
- **Unstick stuck upstream contributions.** I've landed 64 patches across Eigen, PX4, MAVSDK, GStreamer, rclcpp, and friends. I know the maintainers, the review culture, when to wait, and when to push.
- **Set up the CI that actually catches the bug before it ships.** Sanitizers on by default, SITL in Docker, fuzz targets for the predicates that matter.

### Things I've done lately

**A VTOL that flies indoors.** A tethered quad-tailsitter needed sub-meter position accuracy in a GPS-denied environment. Magnetic compass was useless near steel, plain VIO drifted over the 3-km legs. I built a fusion front-end combining fiber-optic gyro rates with monocular vision, running as a custom PX4 estimator module plus a ROS 2 fusion node. The whole stack runs in Docker against PX4 SITL, 330+ tests gating every PR. Result: under one meter of drift at 3.3 km. [fiber-nav-sim →](/projects/fiber-nav-sim/)

**GStreamer was crashing on the Jetson.** Four different flavours of failure — exit code 1 on clean shutdown, fd leaks that killed processes after days of uptime, a use-after-free that surfaced once a month under memory pressure, and a data race on teardown. I reproduced each, traced it to specific internals, and landed all four fixes upstream at freedesktop.org. While there I also wrote [gst-nvmm-cpp](/projects/#systems--libraries) — a zero-copy NVMM allocator and VIC transform so we could stop copying 1080p frames across the CPU↔GPU boundary.

**rclcpp got 71× faster.** Someone reported that creating 10,000 timers took 429 ms. That's quadratic, and it was: `CallbackGroup::add_timer` did a linear membership check on every insert. I rewrote it with an indexed lookup, added the tests that should have been there, and threw in a fix for a separate deadlock in `TimeSource` on the way out. [Full writeup →](/posts/fixing-quadratic-callback-group-rclcpp/)

**PX4 SIH on a real flight controller.** The team wanted hardware-in-the-loop testing on the actual Pixhawk, without propellers. Default firmware didn't include SIH, and rolling a custom build blew the code-space limit. I trimmed modules until it fit, fanned out MAVLink so one serial link fed both the simulator and the ground station, and hooked the stack to a Unity visualiser for realistic mission rehearsal. [Walkthrough →](/posts/px4-sih-on-hardware-custom-firmware-unity/)

**Eigen, 23 patches.** A navigation stack hit an infinite loop inside `TensorUInt128::operator/`. Fixed it. Then the GCC 13 `-Warray-bounds` false positive that was breaking our Jetson builds. Fixed that. Then noticed `HouseholderSequence`'s right-side apply was bottlenecked on a BLAS-2 inner loop, wrote a blocked BLAS-3 version. 23 patches merged upstream, each with a writeup: [Gram-Schmidt vs Householder](/posts/gram-schmidt-vs-householder-qr-benchmark/), [BLAS-3 upgrade](/posts/eigen-householder-blocked-right-side/), [uint128 infinite-loop fix](/posts/fixing-eigen-uint128-division-infinite-loop/).

### How it works

Thirty-minute call to figure out if I can actually help. Scoped proposal — fixed price or day rate, whichever fits. I work in your repo or mine, small PRs, tests before the fix. Writeup and a short walkthrough at the end so the knowledge stays with the team.

Short reproducer-then-fix work turns around in a few days. Larger engagements — a new sensor fusion path, full SITL bring-up, rebuilding CI from scratch — usually run two to eight weeks.

### Availability

Remote or on-site. Based in Israel (UTC+2/+3), comfortable across EU and US time zones.

**[me@pavelguzenfeld.com](mailto:me@pavelguzenfeld.com)** · [GitHub](https://github.com/PavelGuzenfeld) · [LinkedIn](https://www.linkedin.com/in/pavelguzenfeld/)
