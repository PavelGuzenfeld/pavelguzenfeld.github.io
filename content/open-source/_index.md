---
title: "Open Source"
layout: "single"
summary: "Open-source systems, libraries, and upstream contributions."
ShowToc: true
TocOpen: true
aliases:
  - /projects/
---

## Systems & Libraries

| Project | What it does |
|---------|-------------|
| [strong-types](https://github.com/PavelGuzenfeld/strong-types) | Type-safe C++ primitives with SI units, dimensional analysis, and fuzz testing — prevent unit/coordinate mix-ups at compile time |
| [behavior-tree-lite](https://github.com/PavelGuzenfeld/behavior-tree-lite) | Header-only C++23 behavior tree with compile-time DSL and zero-overhead flattened execution |
| [l2-hybrid-protocol](https://github.com/PavelGuzenfeld/l2-hybrid-protocol) | Custom L2 network protocol — lower latency than raw UDP for real-time telemetry |
| [gst-nvmm-cpp](https://github.com/PavelGuzenfeld/gst-nvmm-cpp) | GStreamer plugins for zero-copy NVMM video on NVIDIA Jetson (Xavier, Orin) — allocator, VIC transform, shared-memory IPC |
| [immutable-data-embedder](https://github.com/PavelGuzenfeld/immutable-data-embedder) | Compile-time C++23 config parser — embed data as `constexpr` with zero runtime overhead |
| [ucoro](https://github.com/PavelGuzenfeld/ucoro) | Minimal C++ coroutine abstraction for async task orchestration |
| [gst-metadata](https://github.com/PavelGuzenfeld/gst-metadata) | Composable GStreamer metadata — type-safe, independent metadata types via CRTP |
| [safe-shm](https://github.com/PavelGuzenfeld/safe-shm) | Thread-safe shared memory with compile-time allocation |
| [image-shm-dblbuf](https://github.com/PavelGuzenfeld/image-shm-dblbuf) | Double-buffered shared memory optimized for video frames |
| [v4l2](https://github.com/PavelGuzenfeld/v4l2) | Video for Linux 2 based video source adapter in C++ |

## Navigation & Robotics

| Project | What it does |
|---------|-------------|
| [fiber-nav-sim](https://github.com/PavelGuzenfeld/fiber-nav-sim) | GPS-denied VTOL navigation — fiber optic + monocular vision fusion, PX4 + Gazebo + ROS 2 |
| [linalg3d](https://github.com/PavelGuzenfeld/linalg3d) | 3D linear algebra for flight path and attitude calculations |
| [image-to-body-math](https://github.com/PavelGuzenfeld/image-to-body-math) | Camera-to-body coordinate transforms — C++23 header-only + Python (nanobind, zero-copy NumPy) |
| [ros2-gst-meta](https://github.com/PavelGuzenfeld/ros2-gst-meta) | ROS 2 ↔ GStreamer metadata bridge for vision pipelines |
| [geoslice](https://github.com/PavelGuzenfeld/geoslice) | Geospatial terrain slicing utilities |

## DevOps & Tooling

| Project | What it does |
|---------|-------------|
| [standard](https://github.com/PavelGuzenfeld/standard) | Reusable GitHub Actions for C++/Python — diff-aware linting, SAST, sanitizers, fuzzing |
| [mcp-media-forge](https://github.com/PavelGuzenfeld/mcp-media-forge) | MCP server for generating presentations, diagrams, and charts from Markdown |
| [gemini-mcp](https://github.com/PavelGuzenfeld/gemini-mcp) | MCP server exposing Google Gemini as tools for Claude Code |
| [notebooklm-mcp](https://github.com/PavelGuzenfeld/notebooklm-mcp) | MCP server for Google NotebookLM — notebooks, sources, chat, artifacts, research |
| [ros2-alpine](https://github.com/PavelGuzenfeld/ros2-alpine) | Minimal ROS 2 on Alpine Linux — lightweight container for edge deployment |
| [ai-cpp-course](https://github.com/PavelGuzenfeld/ai-cpp-course) | C++ course intended for AI developers |

---

## Upstream Contributions

**64 patches merged across 11 projects, 17 open for review.** Statuses below are refreshed from live GitHub/GitLab APIs as of April 2026.

### Eigen — 21 merged, 1 open, 2 closed

| MR | Type | Description | Date | Status |
|----|------|-------------|------|--------|
| [!2298](https://gitlab.com/libeigen/eigen/-/merge_requests/2298) | bug | Fix most vexing parse in `SparseSparseProductWithPruning.h` | 2026-03-15 | merged |
| [!2299](https://gitlab.com/libeigen/eigen/-/merge_requests/2299) | fix | Guard redundant `constexpr` static member redeclarations for C++17+ | 2026-03-15 | merged |
| [!2300](https://gitlab.com/libeigen/eigen/-/merge_requests/2300) | bug | Fix `TensorUInt128` division infinite loop on overflow | 2026-03-15 | merged |
| [!2301](https://gitlab.com/libeigen/eigen/-/merge_requests/2301) | cleanup | Remove trailing semicolon from `EIGEN_UNUSED_VARIABLE` macro | 2026-03-15 | merged |
| [!2306](https://gitlab.com/libeigen/eigen/-/merge_requests/2306) | bug | Fix vectorized `erf` returning NaN at ±inf instead of ±1 | 2026-03-17 | merged |
| [!2307](https://gitlab.com/libeigen/eigen/-/merge_requests/2307) | feature | Add coefficient-wise modulus operator (`%`) for `Array` | 2026-03-17 | open |
| [!2308](https://gitlab.com/libeigen/eigen/-/merge_requests/2308) | feature | Add mixed dense/skew-symmetric arithmetic operators | 2026-03-17 | merged |
| [!2309](https://gitlab.com/libeigen/eigen/-/merge_requests/2309) | bug | Missing `Scaling.h` include in IterativeSolvers module | 2026-03-17 | merged |
| [!2310](https://gitlab.com/libeigen/eigen/-/merge_requests/2310) | bug | Fix undefined behavior in `matrix_cwise` test for signed integers | 2026-03-18 | merged |
| [!2311](https://gitlab.com/libeigen/eigen/-/merge_requests/2311) | fix | Fix GCC 13 `-Warray-bounds` false positive in TensorContraction | 2026-03-18 | merged |
| [!2312](https://gitlab.com/libeigen/eigen/-/merge_requests/2312) | bug | Fix `computeInverseAndDetWithCheck` for dynamic result matrices | 2026-03-19 | merged |
| [!2313](https://gitlab.com/libeigen/eigen/-/merge_requests/2313) | fix | Guard `eigen_fill_helper` on trivially copyable scalars | 2026-03-19 | merged |
| [!2316](https://gitlab.com/libeigen/eigen/-/merge_requests/2316) | test | Add C++20 `contiguous_range` tests for Eigen vectors | 2026-03-19 | merged |
| [!2317](https://gitlab.com/libeigen/eigen/-/merge_requests/2317) | test | Add blocking and vectorization boundary tests for LU and Cholesky | 2026-03-19 | merged |
| [!2322](https://gitlab.com/libeigen/eigen/-/merge_requests/2322) | refactor | Strip `lapacke.h` to only the declarations used by Eigen | 2026-03-20 | merged |
| [!2327](https://gitlab.com/libeigen/eigen/-/merge_requests/2327) | fix | Prefer SuiteSparse config-mode packages in CMake Find modules | 2026-03-20 | merged |
| [!2329](https://gitlab.com/libeigen/eigen/-/merge_requests/2329) | docs | Add Array relational operator docs and FetchContent CMake guide | 2026-03-20 | merged |
| [!2330](https://gitlab.com/libeigen/eigen/-/merge_requests/2330) | refactor | Inline `IndexedViewMethods.inc` into `DenseBase.h` | 2026-03-20 | merged |
| [!2331](https://gitlab.com/libeigen/eigen/-/merge_requests/2331) | feature | Add `hcat`/`vcat` DenseBase concatenation expressions | 2026-03-20 | merged |
| [!2335](https://gitlab.com/libeigen/eigen/-/merge_requests/2335) | bug | Fix dangling reference in `IndexedView` with expression indices | 2026-03-21 | merged |
| [!2336](https://gitlab.com/libeigen/eigen/-/merge_requests/2336) | feature | Add C++17 structured bindings support for fixed-size Matrix and Array | 2026-03-21 | merged |
| [!2337](https://gitlab.com/libeigen/eigen/-/merge_requests/2337) | feature | Add Modified Gram-Schmidt QR decomposition | 2026-03-21 | closed |
| [!2338](https://gitlab.com/libeigen/eigen/-/merge_requests/2338) | fix | Map `.inc` files to C++ in Doxygen extension mapping | 2026-03-21 | merged |
| [!2341](https://gitlab.com/libeigen/eigen/-/merge_requests/2341) | perf | Add blocked right-side application for HouseholderSequence | 2026-03-23 | closed |

### GStreamer — 5 merged, 1 open, 1 closed

| MR | Type | Description | Date | Status |
|----|------|-------------|------|--------|
| [!11101](https://gitlab.freedesktop.org/gstreamer/gstreamer/-/merge_requests/11101) | feature | Add NVMM allocator, buffer pool, and transform element for Jetson | 2026-03-23 | closed |
| [!11104](https://gitlab.freedesktop.org/gstreamer/gstreamer/-/merge_requests/11104) | fix | Fix typos in `gstcudacontext` | 2026-03-23 | merged |
| [!11105](https://gitlab.freedesktop.org/gstreamer/gstreamer/-/merge_requests/11105) | fix | Fix CONVET typo in format macro names | 2026-03-23 | merged |
| [!11106](https://gitlab.freedesktop.org/gstreamer/gstreamer/-/merge_requests/11106) | bug | Unchecked `CuMemFree`/`CuMemFreeAsync` return values | 2026-03-23 | merged |
| [!11109](https://gitlab.freedesktop.org/gstreamer/gstreamer/-/merge_requests/11109) | bug | shmsink returns exit code 1 on clean shutdown | 2026-03-24 | merged |
| [!11118](https://gitlab.freedesktop.org/gstreamer/gstreamer/-/merge_requests/11118) | bug | `GstShmAllocator` maxsize not rounded up to page size | 2026-03-24 | merged |
| [!11126](https://gitlab.freedesktop.org/gstreamer/gstreamer/-/merge_requests/11126) | test | Fix flaky `test_shm_live` timeout | 2026-03-24 | open |

### PX4-Autopilot — 4 merged, 2 open, 1 closed

| PR | Type | Description | Date | Status |
|----|------|-------------|------|--------|
| [#26836](https://github.com/PX4/PX4-Autopilot/pull/26836) | refactor | Migrate ROS integration tests from Gazebo Classic to SIH | 2026-03-20 | open |
| [#26845](https://github.com/PX4/PX4-Autopilot/pull/26845) | bug | `io_timer` timer_channel off-by-one (1-indexed instead of 0) | 2026-03-21 | merged |
| [#26846](https://github.com/PX4/PX4-Autopilot/pull/26846) | bug | uxrce_dds_client build fails with empty DDS subscriptions | 2026-03-21 | merged |
| [#26847](https://github.com/PX4/PX4-Autopilot/pull/26847) | security | Unsigned MAVLink messages accepted when signing key is missing | 2026-03-21 | closed |
| [#26848](https://github.com/PX4/PX4-Autopilot/pull/26848) | bug | uxrce_dds_client session fails to reconnect after agent restart | 2026-03-21 | merged |
| [#26853](https://github.com/PX4/PX4-Autopilot/pull/26853) | bug | Mission resume picks wrong waypoint when camera triggering is active | 2026-03-22 | merged |
| [#26854](https://github.com/PX4/PX4-Autopilot/pull/26854) | bug | False landed-state detection in OFFBOARD direct_actuator mode | 2026-03-22 | open |

### MAVSDK — 8 merged, 2 closed

| PR | Type | Description | Date | Status |
|----|------|-------------|------|--------|
| [#2800](https://github.com/mavlink/MAVSDK/pull/2800) | bug | System incorrectly set to disconnected on heartbeat timeout | 2026-03-16 | closed |
| [#2801](https://github.com/mavlink/MAVSDK/pull/2801) | feature | Add `timestamp_us` to Altitude and GroundTruth telemetry structs | 2026-03-21 | merged |
| [#2803](https://github.com/mavlink/MAVSDK/pull/2803) | feature | Implement `set_rate_rc` for ArduPilot via `SYS_STATUS` | 2026-03-21 | merged |
| [#2804](https://github.com/mavlink/MAVSDK/pull/2804) | feature | Implement `download_geofence` mirroring `download_mission` | 2026-03-21 | merged |
| [#2821](https://github.com/mavlink/MAVSDK/pull/2821) | bug | `mission_raw_server`: Fix crash on empty mission upload | 2026-03-29 | merged |
| [#2822](https://github.com/mavlink/MAVSDK/pull/2822) | fix | `log_streaming`: Guard ardupilotmega-specific messages with `#ifdef` | 2026-03-29 | merged |
| [#2823](https://github.com/mavlink/MAVSDK/pull/2823) | feature | telemetry: Use `REQUEST_DATA_STREAM` for ArduPilot `set_rate` | 2026-03-29 | closed |
| [#2827](https://github.com/mavlink/MAVSDK/pull/2827) | bug | mocap: Fix `MavFrame` enum sending wrong values on the wire | 2026-03-30 | merged |
| [#2828](https://github.com/mavlink/MAVSDK/pull/2828) | bug | system_tests: Fix race in mission tests by registering server before connections | 2026-03-30 | merged |
| [#2839](https://github.com/mavlink/MAVSDK/pull/2839) | feature | Expose full `HOME_POSITION` fields in `subscribe_home` | 2026-04-02 | merged |

### MAVSDK-Proto — 3 merged, 1 closed

| PR | Type | Description | Date | Status |
|----|------|-------------|------|--------|
| [#398](https://github.com/mavlink/MAVSDK-Proto/pull/398) | feature | Add `timestamp_us` to Altitude and GroundTruth messages | 2026-03-21 | merged |
| [#399](https://github.com/mavlink/MAVSDK-Proto/pull/399) | feature | Add `HomePosition` message with full `HOME_POSITION` fields | 2026-03-21 | merged |
| [#400](https://github.com/mavlink/MAVSDK-Proto/pull/400) | feature | Add `DownloadGeofence` RPC to geofence proto | 2026-03-21 | merged |
| [#401](https://github.com/mavlink/MAVSDK-Proto/pull/401) | feature | Add `HomePosition` message and timestamp fields to telemetry | 2026-03-27 | closed |

### dora-rs — 3 merged, 5 open, 1 closed

| PR | Type | Description | Date | Status |
|----|------|-------------|------|--------|
| [#1403](https://github.com/dora-rs/dora/pull/1403) | feature | Expose `node_id()` and `dataflow_id()` accessors | 2026-03-15 | merged |
| [#1409](https://github.com/dora-rs/dora/pull/1409) | feature | Event receive variants (timeout, non-blocking, drain) | 2026-03-16 | open |
| [#1410](https://github.com/dora-rs/dora/pull/1410) | feature | `close_outputs`, `NodeFailed` and `Reload` event types | 2026-03-16 | open |
| [#1413](https://github.com/dora-rs/dora/pull/1413) | feature | `node_config_json` and `dataflow_descriptor_json` accessors | 2026-03-16 | open |
| [#1414](https://github.com/dora-rs/dora/pull/1414) | bug | `InputClosed`/`Stop` events not forwarded to C++ callbacks | 2026-03-16 | open |
| [#1426](https://github.com/dora-rs/dora/pull/1426) | feature | CLI progress bars for time-consuming operations | 2026-03-17 | closed |
| [#1427](https://github.com/dora-rs/dora/pull/1427) | feature | CLI progress bars for time-consuming operations (v2) | 2026-03-17 | open |
| [#1428](https://github.com/dora-rs/dora/pull/1428) | feature | Dynamic node initialization | 2026-03-17 | merged |
| [#1431](https://github.com/dora-rs/dora/pull/1431) | feature | Zero-copy output API | 2026-03-17 | merged |

### XGBoost — 4 merged, 1 open, 5 closed

| PR | Type | Description | Date | Status |
|----|------|-------------|------|--------|
| [#12085](https://github.com/dmlc/xgboost/pull/12085) | bug | Import crash under `python -OO` (optimized bytecode) | 2026-03-15 | closed |
| [#12086](https://github.com/dmlc/xgboost/pull/12086) | cleanup | Dead Python 2 guard and `sklearn.cross_validation` fallback | 2026-03-15 | closed |
| [#12087](https://github.com/dmlc/xgboost/pull/12087) | docs | Update competition winning solutions list | 2026-03-15 | merged |
| [#12088](https://github.com/dmlc/xgboost/pull/12088) | feature | Warn when `xgb_model` booster type mismatches training config | 2026-03-15 | closed |
| [#12089](https://github.com/dmlc/xgboost/pull/12089) | bug | `trees_to_dataframe` mishandles indicator features | 2026-03-15 | merged |
| [#12093](https://github.com/dmlc/xgboost/pull/12093) | bug | Docstring assignments crash under `python -OO` | 2026-03-16 | closed |
| [#12094](https://github.com/dmlc/xgboost/pull/12094) | bug | `python -OO` crash from unguarded `__doc__` assignments | 2026-03-16 | merged |
| [#12110](https://github.com/dmlc/xgboost/pull/12110) | cleanup | Add specific error codes to all `type: ignore` comments | 2026-03-19 | merged |
| [#12111](https://github.com/dmlc/xgboost/pull/12111) | cleanup | Replace bare `Any` with specific types in sklearn helpers | 2026-03-19 | open |
| [#12112](https://github.com/dmlc/xgboost/pull/12112) | refactor | Consolidate version query scripts into shared Python module | 2026-03-19 | closed |

### ROS 2 — rclcpp, ros2cli, geometry2 — 1 merged, 3 open

| PR | Type | Description | Date | Status |
|----|------|-------------|------|--------|
| [rclcpp#3109](https://github.com/ros2/rclcpp/pull/3109) | perf | O(N²) entity addition in CallbackGroup — 71x speedup | 2026-03-21 | open |
| [rclcpp#3110](https://github.com/ros2/rclcpp/pull/3110) | bug | Deadlock in `TimeSource::destroy_clock_sub` | 2026-03-21 | open |
| [ros2cli#1213](https://github.com/ros2/ros2cli/pull/1213) | feature | Add `--content-filter` DDS filtering to `ros2 topic echo\|hz\|bw` | 2026-03-21 | open |
| [geometry2#908](https://github.com/ros2/geometry2/pull/908) | bug | `StaticCache::getData()` returns true on empty cache | 2026-03-21 | merged |

### Fast-DDS — 7 open

| PR | Type | Description | Date | Status |
|----|------|-------------|------|--------|
| [#6332](https://github.com/eProsima/Fast-DDS/pull/6332) | bug | Missing `#include <cstdint>` in DDSSQLFilter headers | 2026-03-15 | open |
| [#6333](https://github.com/eProsima/Fast-DDS/pull/6333) | bug | XML parser null-dereference on malformed config (2.6.x) | 2026-03-15 | open |
| [#6339](https://github.com/eProsima/Fast-DDS/pull/6339) | bug | Data race in TopicPayloadPool payload acquisition | 2026-03-21 | open |
| [#6341](https://github.com/eProsima/Fast-DDS/pull/6341) | bug | Double serialization of `type_information` in `ReaderProxyData` | 2026-03-21 | open |
| [#6342](https://github.com/eProsima/Fast-DDS/pull/6342) | bug | Data race on `has_been_removed` flag in `DataSharingPayloadPool` | 2026-03-21 | open |
| [#6343](https://github.com/eProsima/Fast-DDS/pull/6343) | bug | Infinite loop in VOLATILE `DataReader` `init_shared_segment` | 2026-03-21 | open |
| [#6344](https://github.com/eProsima/Fast-DDS/pull/6344) | bug | Race between Condition destruction and WaitSet iteration | 2026-03-21 | open |

### px4-ros2-interface-lib — 4 merged

| PR | Type | Description | Date | Status |
|----|------|-------------|------|--------|
| [#186](https://github.com/Auterion/px4-ros2-interface-lib/pull/186) | fix | VTOL status staleness timeout not configurable | 2026-03-15 | merged |
| [#188](https://github.com/Auterion/px4-ros2-interface-lib/pull/188) | bug | Missing topic namespace prefix in `MapProjection` | 2026-03-17 | merged |
| [#189](https://github.com/Auterion/px4-ros2-interface-lib/pull/189) | feature | Add `HomePositionSetter` utility | 2026-03-18 | merged |
| [#192](https://github.com/Auterion/px4-ros2-interface-lib/pull/192) | refactor | Use `VehicleCommandSender` in `sendCommandSync()` | 2026-03-19 | merged |

### OpenCV — 2 merged

| PR | Type | Description | Date | Status |
|----|------|-------------|------|--------|
| [#28660](https://github.com/opencv/opencv/pull/28660) | bug | Broken Python bindings | 2026-03-15 | merged |
| [#28665](https://github.com/opencv/opencv/pull/28665) | cleanup | Stale typing stubs | 2026-03-16 | merged |

### concurrentqueue — 2 merged

| PR | Type | Description | Date | Status |
|----|------|-------------|------|--------|
| [#445](https://github.com/cameron314/concurrentqueue/pull/445) | cleanup | Replace C-style casts with C++ casts | 2026-03-10 | merged |
| [#446](https://github.com/cameron314/concurrentqueue/pull/446) | docs | Document `try_enqueue` capacity limit | 2026-03-17 | merged |

### Fast-DDS-docs — 1 open

| PR | Type | Description | Date | Status |
|----|------|-------------|------|--------|
| [#1234](https://github.com/eProsima/Fast-DDS-docs/pull/1234) | docs | Troubleshooting entry for libunwind/libgcc_s conflict | 2026-03-15 | open |
