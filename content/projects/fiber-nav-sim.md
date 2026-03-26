---
title: "fiber-nav-sim -- PX4 + Gazebo VTOL Navigation Simulator"
summary: "GPS-denied VTOL navigation simulator using fiber optic odometry and monocular vision fusion. PX4 SITL + Gazebo Harmonic + ROS 2 Jazzy. Sub-meter accuracy over 3.3km."
tags: ["C++", "ROS 2", "PX4", "Gazebo", "VTOL", "navigation", "drones", "simulation"]
---

## What It Is

A fully Dockerized ROS 2 Jazzy / Gazebo Harmonic simulation environment for GPS-denied VTOL navigation. A tethered quad-tailsitter drone navigates through tunnels and canyons using only a fiber optic cable spool sensor (scalar velocity) and a monocular camera (direction of motion).

## Results

### PX4 SITL -- Canyon Mission (3.3km, 10 minutes)

| Metric | Value |
|--------|-------|
| Mean position error | **0.85 m** |
| Max position error | 1.94 m |
| Drift rate | 0.06 m per 1000m |
| Speed RMSE (fusion vs GT) | 0.133 m/s |

### Long Distance (20km)

| Method | Position Error | vs IMU |
|--------|---------------|--------|
| **Fiber + Vision** | 952m (4.8%) | **12x better** |
| IMU-only | 11,979m (60%) | -- |

Key finding: fiber + vision drift is **linear** vs **quadratic** for IMU-only. Viable for GPS-denied long-distance navigation.

## Key Features

- **Full PX4 integration** -- custom airframe, EKF2 fusion, 7-state VTOL navigation mode
- **Real terrain** -- SRTM DEM heightmaps with satellite imagery (Negev desert 6x6km)
- **Cable dynamics** -- virtual fiber force model (drag, weight, friction, breakage) via Gazebo wrench
- **330+ tests** -- unit, integration, SITL benchmarks, terrain pipeline
- **One-command launch** -- fully Dockerized with GPU-accelerated Gazebo rendering

## Stack

`C++23` `ROS 2 Jazzy` `PX4 SITL` `Gazebo Harmonic` `Docker Compose`

[View on GitHub](https://github.com/PavelGuzenfeld/fiber-nav-sim)
