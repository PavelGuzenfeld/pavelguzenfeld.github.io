---
title: "Consulting"
layout: "single"
summary: "Freelance C++ for drones and robotics. Flight-critical code, navigation pipelines, video on Jetson, and upstream fixes that actually land."
ShowToc: false
---

## Consulting

I work on the video, testing, and bug-hunting side of drone software. If your CI keeps failing, your headless simulator won't run in Docker, a GStreamer pipeline is flaking once a week, or a library you depend on has a bug nobody's gotten around to fixing — that's where I'm useful.

Not the right person if you need a navigation or sensor-fusion engineer. Those jobs need people who write Kalman filters for a living and I don't.

### What I'll do for you

- **Video pipelines on Jetson and in headless simulators.** GStreamer, NVMM, zero-copy, multi-camera synchronization, RTP and RTSP streaming.
- **System-testing setups for drone stacks.** Reproducible scenarios that run in CI, closing the loop all the way through to video so the whole pipeline gets exercised on every PR.
- **Chasing intermittent bugs in the infrastructure layer.** The ones that show up once every few days, in CI but not locally, or only on one Jetson and not another.
- **Landing upstream fixes in the libraries you already depend on.** 64 patches merged so far across Eigen, GStreamer, MAVSDK, PX4, and rclcpp. I know the review culture and when to push.

### Things I've done lately

**GStreamer on the Jetson, four bugs deep.** A multi-camera pipeline was crashing intermittently — exit code 1 on clean shutdown, fd leaks that killed long-running processes, a use-after-free that surfaced once a month under load, and a data race on teardown. Reproduced each in a minimal pipeline, traced them to specific GStreamer internals, landed all four fixes upstream at freedesktop.org. While I was in there I also wrote [gst-nvmm-cpp](/projects/#systems--libraries) — a zero-copy NVMM allocator and VIC transform element so the pipeline could stop copying 1080p frames across the CPU↔GPU boundary. [Writeup →](/posts/anatomy-of-gstreamer-shm-bugs/)

**A streaming simulator that runs in CI.** The goal was three synchronized 1080p camera feeds out of a headless renderer in a Docker container, at 30+ fps, so a drone stack's video pipeline could be exercised end-to-end on every PR. Tried Unity (three months of headless-in-Docker pain), [O3DE](/posts/o3de-performance-deep-dive-readback-bottleneck/) (hit an 18 ms wall in the frame-graph readback), finally [Godot](/posts/godot-multi-camera-streaming-async-readback/). Landed a working pipeline with `RenderingDevice::texture_get_data_async` as the primitive.

**rclcpp got 71× faster.** A bug report on ROS 2's executor showed that creating 10,000 timers took 429 ms — `CallbackGroup::add_timer` was doing a linear membership check on every insert, a clean quadratic. Rewrote with an indexed lookup, added tests, fixed a separate `TimeSource` deadlock on the way out. [Writeup →](/posts/fixing-quadratic-callback-group-rclcpp/)

**PX4 SIH on a real flight controller.** A team wanted hardware-in-the-loop on the actual Pixhawk, propellers off. Default firmware didn't include SIH, and rolling a custom build blew the code-space limit. Trimmed modules to fit, fanned out MAVLink so one serial link fed both the simulator and ground station, wired a Unity visualizer for realistic mission rehearsal. [Walkthrough →](/posts/px4-sih-on-hardware-custom-firmware-unity/)

**Eigen, 23 patches merged.** A project we depended on was blocked on an infinite loop in `TensorUInt128::operator/`. Fixed it. Then a GCC 13 `-Warray-bounds` false positive that was breaking Jetson builds. Fixed that. Then a BLAS-2 bottleneck in `HouseholderSequence`'s right-side apply — wrote a blocked BLAS-3 version. All merged upstream. [Selected writeups](/posts/gram-schmidt-vs-householder-qr-benchmark/).

**A CI pipeline on a Jetson Xavier, fifteen failures to green.** ARM-in-Docker builds failing differently on every retry — libunwind versions, apt mirrors timing out, Docker layer caches going stale, one test that needed `/dev/kvm` and another that didn't. Worked through each until the build was reliable. [Writeup →](/posts/fixing-ci-pipeline-arm-jetson-docker/)

### How it works

Thirty-minute call to figure out if I can actually help. Scoped proposal — fixed price or day rate, whichever fits. I work in your repo or mine, small PRs, tests before the fix. Writeup and a short walkthrough at the end so the knowledge stays with the team.

Short reproducer-then-fix work turns around in a few days. Larger engagements — a new sensor fusion path, full SITL bring-up, rebuilding CI from scratch — usually run two to eight weeks.

### Availability

Remote or on-site. Based in Israel (UTC+2/+3), comfortable across EU and US time zones.

**[me@pavelguzenfeld.com](mailto:me@pavelguzenfeld.com)** · [GitHub](https://github.com/PavelGuzenfeld) · [LinkedIn](https://www.linkedin.com/in/pavelguzenfeld/)
