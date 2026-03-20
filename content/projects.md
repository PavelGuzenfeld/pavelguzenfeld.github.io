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

32 patches across 9 projects:

### Eigen

| MR | Description |
|----|-------------|
| [!2298](https://gitlab.com/libeigen/eigen/-/merge_requests/2298) | Fix most vexing parse in `SparseSparseProductWithPruning.h` |
| [!2299](https://gitlab.com/libeigen/eigen/-/merge_requests/2299) | Guard redundant `constexpr` static member redeclarations for C++17+ |
| [!2300](https://gitlab.com/libeigen/eigen/-/merge_requests/2300) | Fix `TensorUInt128` division infinite loop on overflow |
| [!2301](https://gitlab.com/libeigen/eigen/-/merge_requests/2301) | Remove trailing semicolon from `EIGEN_UNUSED_VARIABLE` macro |
| [!2306](https://gitlab.com/libeigen/eigen/-/merge_requests/2306) | Fix vectorized `erf` returning NaN at ±inf instead of ±1 |
| [!2307](https://gitlab.com/libeigen/eigen/-/merge_requests/2307) | Add coefficient-wise modulus operator (`%`) for `Array` |
| [!2308](https://gitlab.com/libeigen/eigen/-/merge_requests/2308) | Add mixed dense/skew-symmetric arithmetic operators |
| [!2309](https://gitlab.com/libeigen/eigen/-/merge_requests/2309) | Include `Scaling.h` in IterativeSolvers module |
| [!2310](https://gitlab.com/libeigen/eigen/-/merge_requests/2310) | Fix undefined behavior in `matrix_cwise` test for signed integers |
| [!2311](https://gitlab.com/libeigen/eigen/-/merge_requests/2311) | Fix GCC 13 `-Warray-bounds` warning in TensorContraction |

### dora-rs

| PR | Description |
|----|-------------|
| [#1403](https://github.com/dora-rs/dora/pull/1403) | Expose `node_id()` and `dataflow_id()` accessors |
| [#1428](https://github.com/dora-rs/dora/pull/1428) | Dynamic node initialization |
| [#1431](https://github.com/dora-rs/dora/pull/1431) | Zero-copy output API |
| [#1409](https://github.com/dora-rs/dora/pull/1409) | Event receive variants (timeout, non-blocking, drain) |
| [#1410](https://github.com/dora-rs/dora/pull/1410) | `close_outputs`, `NodeFailed` and `Reload` event types |
| [#1413](https://github.com/dora-rs/dora/pull/1413) | `node_config_json` and `dataflow_descriptor_json` |
| [#1414](https://github.com/dora-rs/dora/pull/1414) | Forward `InputClosed`/`Stop` events to C++ callbacks |
| [#1427](https://github.com/dora-rs/dora/pull/1427) | CLI progress bars for time-consuming operations |

### XGBoost

| PR | Description |
|----|-------------|
| [#12087](https://github.com/dmlc/xgboost/pull/12087) | Update competition winning solutions list |
| [#12089](https://github.com/dmlc/xgboost/pull/12089) | Handle indicator features in `trees_to_dataframe` |
| [#12094](https://github.com/dmlc/xgboost/pull/12094) | Fix `python -OO` crash by guarding `__doc__` assignments |
| [#12086](https://github.com/dmlc/xgboost/pull/12086) | Remove dead Python 2 guard and `sklearn.cross_validation` fallback |

### Other Projects

| Project | Description |
|---------|-------------|
| [OpenCV](https://github.com/opencv/opencv) | Fix Python bindings ([#28660](https://github.com/opencv/opencv/pull/28660)), clean up stale typing stubs ([#28665](https://github.com/opencv/opencv/pull/28665)) |
| [px4-ros2-interface-lib](https://github.com/Auterion/px4-ros2-interface-lib) | VTOL timeout fix ([#186](https://github.com/Auterion/px4-ros2-interface-lib/pull/186)), geodesic namespace fix ([#188](https://github.com/Auterion/px4-ros2-interface-lib/pull/188)), HomePositionSetter ([#189](https://github.com/Auterion/px4-ros2-interface-lib/pull/189)) |
| [concurrentqueue](https://github.com/cameron314/concurrentqueue) | Replace C-style casts ([#445](https://github.com/cameron314/concurrentqueue/pull/445)), document `try_enqueue` limit ([#446](https://github.com/cameron314/concurrentqueue/pull/446)) |
| [Fast-DDS](https://github.com/eProsima/Fast-DDS) | Missing `#include <cstdint>` ([#6332](https://github.com/eProsima/Fast-DDS/pull/6332)), XML parser null-deref fix ([#6333](https://github.com/eProsima/Fast-DDS/pull/6333)) |
| [Fast-DDS-docs](https://github.com/eProsima/Fast-DDS-docs) | Troubleshooting entry for libunwind/libgcc_s conflict ([#1234](https://github.com/eProsima/Fast-DDS-docs/pull/1234)) |
