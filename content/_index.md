---
title: "Pavel Guzenfeld"
---

# I build the software that keeps drones in the air.

C++23 for flight-critical systems — navigation, computer vision, real-time video. The code that has to not crash at 400 feet.

## What I'm working on right now

Multi-camera streaming from a headless simulator. Training data doesn't come from the sky; it comes from a Docker container that renders three synchronised 1080p feeds at 30+ fps while simulating a drone flying over a city.

Started in Unity. The ecosystem for headless rendering in a container is quietly broken — three months of fighting GPU drivers, asset bundles, and license servers. Moved to [O3DE](/posts/o3de-performance-deep-dive-readback-bottleneck/) and hit an 18-millisecond wall in the frame-graph readback system. Moved to [Godot](/posts/godot-multi-camera-streaming-async-readback/), got three live RTP streams at 50 fps per camera by going deep into `RenderingDevice::texture_get_data_async`. That's the new reference stack.

Before that: a Householder-apply bottleneck and a uint128 division loop in [Eigen](/posts/eigen-householder-blocked-right-side/), and [PX4 Simulation-In-Hardware](/posts/px4-sih-on-hardware-custom-firmware-unity/) running on a production flight controller so the team could rehearse missions on the bench without propellers.

## The kind of problems I like

The ones that look like *"it just sometimes crashes."*

A GStreamer `shmsink` that exits clean but returns 1. A sensor-fusion filter that drifts after exactly 47 minutes. A Dragoon stuck against a cliff in StarCraft's pathing hack. These aren't bugs you solve with a stack trace — you solve them by building the tooling that makes the bug show itself twice.

I'm also drawn to the places where correctness and performance meet the ground truth of physics. A type-safe coordinate transform that compiles away to a `memcpy`. An integer predicate that returns the same answer on every compiler and every SIMD flag. Zero-copy video that survives a full flight without exhausting the kernel's descriptor table.

## Selected writing

- [**Game pathfinding algorithms, benchmarked**](/posts/game-pathfinding-algorithms-cpp23-benchmark/) — A\*, JPS, Theta\*, flow fields, visibility graphs, with StarCraft and Age of Empires as case studies.
- [**From Unity to Godot: 50 FPS multi-camera streaming**](/posts/godot-multi-camera-streaming-async-readback/) — the three-engine journey to a pipeline that actually ran.
- [**Fixing O(N²) entity addition in ROS 2's CallbackGroup**](/posts/fixing-quadratic-callback-group-rclcpp/) — 71× speedup on the 10,000-timer reproducer.
- [**Anatomy of four GStreamer shared-memory bugs**](/posts/anatomy-of-gstreamer-shm-bugs/) — race, use-after-free, fd leak, exit code. All upstream.
- [**Modified Gram-Schmidt vs Householder QR**](/posts/gram-schmidt-vs-householder-qr-benchmark/) — the benchmark that answered an Eigen maintainer's "why are you adding this?"
- [**Six Optiver-style C++ problems**](/posts/optiver-cpp-problems-order-books-dijkstra-dp/) — order books, Dijkstra with K free edges, lattice DP, AoS→SoA.

[Everything I've written →](/posts/)

## Working together

I take consulting engagements that look like the above — stabilising flight software, landing upstream fixes, building the CI that catches the next bug before a customer does. 64 patches merged into Eigen, MAVSDK, GStreamer, PX4, and rclcpp, so far.

[How that works →](/consulting/) · [About me →](/about/) · [me@pavelguzenfeld.com](mailto:me@pavelguzenfeld.com)
