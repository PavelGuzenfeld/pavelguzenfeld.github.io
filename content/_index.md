---
title: "Pavel Guzenfeld"
---

# Drone software, mostly.

Video pipelines, system-testing infrastructure, and bug-hunting in the libraries drone stacks depend on. Not a flight-control engineer and not writing sensor-fusion algorithms — I'm the person you want when your CI keeps falling over, your headless simulator won't boot in Docker, or a GStreamer pipeline is returning exit code 1 and nobody can explain it.

## What I'm on right now

A system-testing setup for a drone stack. Same scenario every run — same flight path, same timing, same camera inputs — executed in CI and closing the loop all the way through to the video output, so the whole pipeline gets exercised instead of just the parts you can cheaply mock.

The hard part is the video. Three 1080p camera streams out of a simulator, synchronized, at thirty frames a second, inside a Docker container, on shared CI hardware.

Unity was the first try. It fought me for three months — driver stacks, asset bundles, license servers, the usual story for anyone trying to run Unity without a display.

So I tried [O3DE](/posts/o3de-performance-deep-dive-readback-bottleneck/). I hit an eighteen-millisecond wall in how it moves frames from the GPU to the CPU.

So I tried [Godot](/posts/godot-multi-camera-streaming-async-readback/). That worked. Eventually. Along the way I learned more about its renderer than I'd have picked to.

The pipeline now replays the exact same scenario every night, with video, and posts pass/fail to the PR.

## The kind of bugs I like

The boring ones.

A GStreamer pipeline that exits cleanly but returns error code 1 — so the launch script thinks the run failed. A Docker build that passes on my laptop and fails on the CI runner because libunwind is a different major version. An Eigen header that breaks on GCC 13 with a warning the code didn't deserve. A build on a Jetson Xavier that fails differently on every retry.

Nothing dramatic. I just like finding why something's off by one.

## A few posts worth reading

- [**Three game engines, one streaming pipeline**](/posts/godot-multi-camera-streaming-async-readback/) — the full path from Unity through O3DE to a working Godot stack.
- [**Four GStreamer shared-memory bugs**](/posts/anatomy-of-gstreamer-shm-bugs/) — race, use-after-free, fd leak, and that exit-code-1 mystery.
- [**Making ROS 2 timers 71× faster**](/posts/fixing-quadratic-callback-group-rclcpp/) — a quadratic bug in the middle of the executor.
- [**Running PX4 SIH on real hardware**](/posts/px4-sih-on-hardware-custom-firmware-unity/) — custom firmware, fan-out MAVLink, Unity for visualization.
- [**Fixing a CI pipeline on a Jetson Xavier**](/posts/fixing-ci-pipeline-arm-jetson-docker/) — the slow slog to a green ARM-in-Docker build.

[Everything I've written →](/posts/)

## Working together

Consulting on the above — video pipelines, headless simulation, CI for embedded drone stacks, and upstream bug-hunts in GStreamer, ROS 2, PX4, and Eigen. Not the right person if you need a navigation or sensor-fusion specialist.

[How that works →](/consulting/) · [About me →](/about/) · [me@pavelguzenfeld.com](mailto:me@pavelguzenfeld.com)
