---
title: "Pavel Guzenfeld"
---

# I write C++ for drones.

Flight controllers, sensor fusion, video pipelines — the code that can't afford a second chance.

## What I'm up to now

I'm building a simulator for drone training data. Three camera feeds, 1080p each, streaming out of a Docker container in sync, at thirty frames a second, rendering a simulated city.

Unity was the obvious choice. It fought me for three months — driver stacks, asset bundles, license servers, the usual story for anyone trying to run Unity headless.

So I tried [O3DE](/posts/o3de-performance-deep-dive-readback-bottleneck/). That's a newer engine from Amazon. I hit a hard eighteen-millisecond wall in the way it moves rendered frames back to the CPU.

So I tried [Godot](/posts/godot-multi-camera-streaming-async-readback/). That one worked. Eventually. Along the way I learned more about its renderer than I'd have chosen to.

Before this thread, I spent a lot of time [patching Eigen](/posts/eigen-householder-blocked-right-side/), the linear-algebra library most C++ math code sits on top of. And I got [PX4's built-in simulator](/posts/px4-sih-on-hardware-custom-firmware-unity/) to run on a real flight controller, so the team could rehearse whole missions with the actual firmware on the bench — without propellers.

## The kind of bugs I like

The ones people describe as *"it just sometimes crashes."*

A program that exits cleanly but returns an error code. A filter that works fine for exactly 47 minutes and then drifts. A unit in a game that gets wedged against a wall because the pathfinder has an edge case nobody thought about.

You don't solve these with a stack trace. You solve them by building the tools that make the bug show itself on demand. That part I find satisfying.

## A few posts worth reading

- [**Game pathfinding, benchmarked**](/posts/game-pathfinding-algorithms-cpp23-benchmark/) — A\*, jump-point search, Theta\*, flow fields. StarCraft and Age of Empires as case studies.
- [**Three game engines, one streaming pipeline**](/posts/godot-multi-camera-streaming-async-readback/) — the full path from Unity through O3DE to a working Godot stack.
- [**Making ROS 2 timers 71× faster**](/posts/fixing-quadratic-callback-group-rclcpp/) — a quadratic bug hiding in the middle of the executor.
- [**Four GStreamer shared-memory bugs**](/posts/anatomy-of-gstreamer-shm-bugs/) — including the one where clean shutdown returned error code 1.
- [**Gram-Schmidt vs Householder QR**](/posts/gram-schmidt-vs-householder-qr-benchmark/) — the benchmark that answered an Eigen maintainer's *"why would we add this?"*

[Everything I've written →](/posts/)

## Working together

I take consulting work that looks like the above — making broken drone software less broken, landing fixes in open-source libraries, building the automated tests that catch the next bug before a customer does.

[How that works →](/consulting/) · [About me →](/about/) · [me@pavelguzenfeld.com](mailto:me@pavelguzenfeld.com)
