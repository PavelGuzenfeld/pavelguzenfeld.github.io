---
title: "Pavel Guzenfeld"
---

# Drone software mostly. Trying to stop them from falling out of the sky.

C++, a lot of navigation and video, some sensor fusion. The day-to-day is chasing the bugs that only show up once a drone's been flying for an hour.

## What I'm on right now

A training simulator. You can't crash a thousand real drones to teach a vision model what a power line looks like, so we render fake cities in a container and stream three synchronized 1080p camera feeds out of it, at thirty frames a second.

Unity was the obvious choice. It fought me for three months — driver stacks, asset bundles, license servers, the usual story for anyone trying to run Unity without a display.

So I tried [O3DE](/posts/o3de-performance-deep-dive-readback-bottleneck/). I hit an eighteen-millisecond wall in the way it moves frames from the GPU back to the CPU.

So I tried [Godot](/posts/godot-multi-camera-streaming-async-readback/). That worked. Eventually. Along the way I learned more about its renderer than I'd have picked to.

Same goal underneath all of it: let the team practice the risky manoeuvres on a laptop, not a real airframe.

## The kind of bugs I like

The ones that only bite in flight.

A sensor-fusion filter that works fine for exactly 47 minutes and then drifts. A GStreamer pipeline that exits cleanly but returns error code 1 — so the launch script assumes the run failed. A unit in a video game stuck against a wall because the pathfinder has an edge case nobody thought about (yes, that ships in real games, and in real drone planners too).

You don't catch these with a stack trace. You catch them by building the tools that force the bug to show itself on the bench. That's the part I find satisfying.

## A few posts worth reading

- [**Game pathfinding, benchmarked**](/posts/game-pathfinding-algorithms-cpp23-benchmark/) — A\*, jump-point search, Theta\*, flow fields. StarCraft and Age of Empires as case studies.
- [**Three game engines, one streaming pipeline**](/posts/godot-multi-camera-streaming-async-readback/) — the full path from Unity through O3DE to a working Godot stack.
- [**Making ROS 2 timers 71× faster**](/posts/fixing-quadratic-callback-group-rclcpp/) — a quadratic bug hiding in the middle of the executor.
- [**Four GStreamer shared-memory bugs**](/posts/anatomy-of-gstreamer-shm-bugs/) — including the one where clean shutdown returned error code 1.
- [**Gram-Schmidt vs Householder QR**](/posts/gram-schmidt-vs-householder-qr-benchmark/) — the benchmark that answered an Eigen maintainer's *"why would we add this?"*

[Everything I've written →](/posts/)

## Working together

Consulting on the above — making broken drone software less broken, landing upstream fixes in Eigen, PX4, GStreamer, rclcpp, and the rest, and building the automated tests that catch the next bug before the drone leaves the ground.

[How that works →](/consulting/) · [About me →](/about/) · [me@pavelguzenfeld.com](mailto:me@pavelguzenfeld.com)
