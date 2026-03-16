---
title: "Projects"
layout: "projects"
summary: "Open-source systems, libraries, and tools"
ShowToc: true
TocOpen: true
---

## Systems & Libraries

| Project | What it does |
|---------|-------------|
| [strong-types](https://github.com/PavelGuzenfeld/strong-types) | Type-safe C++ primitives with fuzz testing — prevent unit/coordinate mix-ups at compile time |
| [behavior-tree-lite](https://github.com/PavelGuzenfeld/behavior-tree-lite) | Header-only C++23 behavior tree with compile-time DSL and zero-overhead flattened execution |
| [l2-hybrid-protocol](https://github.com/PavelGuzenfeld/l2-hybrid-protocol) | Custom L2 network protocol — lower latency than raw UDP for real-time telemetry |
| [immutable-data-embedder](https://github.com/PavelGuzenfeld/immutable-data-embedder) | Compile-time C++23 config parser — embed data as `constexpr` with zero runtime overhead |
| [ucoro](https://github.com/PavelGuzenfeld/ucoro) | Minimal C++ coroutine abstraction for async task orchestration |
| [gst-metadata](https://github.com/PavelGuzenfeld/gst-metadata) | Composable GStreamer metadata — type-safe, independent metadata types via CRTP |
| [safe-shm](https://github.com/PavelGuzenfeld/safe-shm) | Thread-safe shared memory with compile-time allocation |
| [image-shm-dblbuf](https://github.com/PavelGuzenfeld/image-shm-dblbuf) | Double-buffered shared memory optimized for video frames |

## Navigation & Robotics

| Project | What it does |
|---------|-------------|
| [fiber-nav-sim](https://github.com/PavelGuzenfeld/fiber-nav-sim) | VTOL navigation simulation framework — PX4 + Gazebo + ROS 2 |
| [linalg3d](https://github.com/PavelGuzenfeld/linalg3d) | 3D linear algebra for flight path and attitude calculations |
| [image-to-body-math](https://github.com/PavelGuzenfeld/image-to-body-math) | Camera-to-body coordinate transforms — C++23 header-only + Python (nanobind, zero-copy NumPy) |
| [ros2-gst-meta](https://github.com/PavelGuzenfeld/ros2-gst-meta) | ROS 2 ↔ GStreamer metadata bridge for vision pipelines |

## DevOps & Tooling

| Project | What it does |
|---------|-------------|
| [standard](https://github.com/PavelGuzenfeld/standard) | Reusable GitHub Actions for C++/Python — diff-aware linting, SAST, sanitizers, fuzzing |
| [mcp-media-forge](https://github.com/PavelGuzenfeld/mcp-media-forge) | MCP server for generating presentations, diagrams, and charts from Markdown |
| [gemini-mcp](https://github.com/PavelGuzenfeld/gemini-mcp) | MCP server exposing Google Gemini as tools for Claude Code |
| [ros2-alpine](https://github.com/PavelGuzenfeld/ros2-alpine) | Minimal ROS 2 on Alpine Linux — lightweight container for edge deployment |

## Upstream Contributions

| Project | Contribution |
|---------|-------------|
| [Eigen](https://gitlab.com/libeigen/eigen) | Fixing vexing parse issues — 4 MRs merged, 6 more planned |
| [XGBoost](https://github.com/dmlc/xgboost) | Code quality improvements — 5 PRs submitted |
| [Fast-DDS](https://github.com/eProsima/Fast-DDS) | Build fixes and documentation — PRs #6332, #6333 |
| [OpenCV](https://github.com/opencv/opencv) | GAPI fixes — PR #28660 |
| [dora-rs](https://github.com/dora-rs/dora) | C++ API parity |
