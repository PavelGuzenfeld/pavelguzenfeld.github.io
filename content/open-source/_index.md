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

{{< projects section="Systems & Libraries" >}}

## Navigation & Robotics

{{< projects section="Navigation & Robotics" >}}

## DevOps & Tooling

{{< projects section="DevOps & Tooling" >}}

---

## Upstream Contributions

**121 patches merged across 13 projects, 13 open for review.** Statuses below are refreshed from live GitHub/GitLab APIs as of September 2026.

{{% details summary="Eigen — 23 merged, 3 open, 2 closed" %}}
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
| [!2350](https://gitlab.com/libeigen/eigen/-/merge_requests/2350) | feature | Add DGKS iterative reorthogonalization utility | 2026-03-28 | open |
| [!2357](https://gitlab.com/libeigen/eigen/-/merge_requests/2357) | fix | Fix private shadowing of protected base members in iterative solvers | 2026-03-29 | merged |
| [!2359](https://gitlab.com/libeigen/eigen/-/merge_requests/2359) | feature | Add polymorphic memory resource primitives for custom allocators | 2026-03-29 | open |
| [!2416](https://gitlab.com/libeigen/eigen/-/merge_requests/2416) | fix | Guard `SimplicialCholesky` `kEmpty` redeclaration for C++17+ | 2026-04-10 | merged |
{{% /details %}}

{{% details summary="GStreamer — 7 merged, 2 open, 1 closed" %}}
| MR | Type | Description | Date | Status |
|----|------|-------------|------|--------|
| [!11101](https://gitlab.freedesktop.org/gstreamer/gstreamer/-/merge_requests/11101) | feature | Add NVMM allocator, buffer pool, and transform element for Jetson | 2026-03-23 | closed |
| [!11104](https://gitlab.freedesktop.org/gstreamer/gstreamer/-/merge_requests/11104) | fix | Fix typos in `gstcudacontext` | 2026-03-23 | merged |
| [!11105](https://gitlab.freedesktop.org/gstreamer/gstreamer/-/merge_requests/11105) | fix | Fix CONVET typo in format macro names | 2026-03-23 | merged |
| [!11106](https://gitlab.freedesktop.org/gstreamer/gstreamer/-/merge_requests/11106) | bug | Unchecked `CuMemFree`/`CuMemFreeAsync` return values | 2026-03-23 | merged |
| [!11109](https://gitlab.freedesktop.org/gstreamer/gstreamer/-/merge_requests/11109) | bug | shmsink returns exit code 1 on clean shutdown | 2026-03-24 | merged |
| [!11118](https://gitlab.freedesktop.org/gstreamer/gstreamer/-/merge_requests/11118) | bug | `GstShmAllocator` maxsize not rounded up to page size | 2026-03-24 | merged |
| [!11126](https://gitlab.freedesktop.org/gstreamer/gstreamer/-/merge_requests/11126) | test | Fix flaky `test_shm_live` timeout | 2026-03-24 | open |
| [!11162](https://gitlab.freedesktop.org/gstreamer/gstreamer/-/merge_requests/11162) | fix | Fix `shmpipe` lockup from wrong buffer ack and fallback allocator | 2026-03-27 | merged |
| [!11182](https://gitlab.freedesktop.org/gstreamer/gstreamer/-/merge_requests/11182) | fix | Make `v4l2videoenc` output state caps writable before modification | 2026-03-29 | open |
{{% /details %}}

{{% details summary="PX4-Autopilot — 5 merged, 2 closed" %}}
| PR | Type | Description | Date | Status |
|----|------|-------------|------|--------|
| [#26836](https://github.com/PX4/PX4-Autopilot/pull/26836) | refactor | Migrate ROS integration tests from Gazebo Classic to SIH | 2026-03-20 | closed |
| [#26845](https://github.com/PX4/PX4-Autopilot/pull/26845) | bug | `io_timer` timer_channel off-by-one (1-indexed instead of 0) | 2026-03-21 | merged |
| [#26846](https://github.com/PX4/PX4-Autopilot/pull/26846) | bug | uxrce_dds_client build fails with empty DDS subscriptions | 2026-03-21 | merged |
| [#26847](https://github.com/PX4/PX4-Autopilot/pull/26847) | security | Unsigned MAVLink messages accepted when signing key is missing | 2026-03-21 | closed |
| [#26848](https://github.com/PX4/PX4-Autopilot/pull/26848) | bug | uxrce_dds_client session fails to reconnect after agent restart | 2026-03-21 | merged |
| [#26853](https://github.com/PX4/PX4-Autopilot/pull/26853) | bug | Mission resume picks wrong waypoint when camera triggering is active | 2026-03-22 | merged |
| [#26854](https://github.com/PX4/PX4-Autopilot/pull/26854) | bug | False landed-state detection in OFFBOARD direct_actuator mode | 2026-03-22 | merged |
{{% /details %}}

{{% details summary="MAVSDK — 10 merged, 3 closed" %}}
| PR | Type | Description | Date | Status |
|----|------|-------------|------|--------|
| [#2800](https://github.com/mavlink/MAVSDK/pull/2800) | bug | System incorrectly set to disconnected on heartbeat timeout | 2026-03-16 | closed |
| [#2801](https://github.com/mavlink/MAVSDK/pull/2801) | feature | Add `timestamp_us` to Altitude and GroundTruth telemetry structs | 2026-03-21 | merged |
| [#2802](https://github.com/mavlink/MAVSDK/pull/2802) | feature | Expose full `HOME_POSITION` fields in `subscribe_home` (superseded by #2839) | 2026-03-21 | closed |
| [#2803](https://github.com/mavlink/MAVSDK/pull/2803) | feature | Implement `set_rate_rc` for ArduPilot via `SYS_STATUS` | 2026-03-21 | merged |
| [#2804](https://github.com/mavlink/MAVSDK/pull/2804) | feature | Implement `download_geofence` mirroring `download_mission` | 2026-03-21 | merged |
| [#2821](https://github.com/mavlink/MAVSDK/pull/2821) | bug | `mission_raw_server`: Fix crash on empty mission upload | 2026-03-29 | merged |
| [#2822](https://github.com/mavlink/MAVSDK/pull/2822) | fix | `log_streaming`: Guard ardupilotmega-specific messages with `#ifdef` | 2026-03-29 | merged |
| [#2823](https://github.com/mavlink/MAVSDK/pull/2823) | feature | telemetry: Use `REQUEST_DATA_STREAM` for ArduPilot `set_rate` | 2026-03-29 | closed |
| [#2827](https://github.com/mavlink/MAVSDK/pull/2827) | bug | mocap: Fix `MavFrame` enum sending wrong values on the wire | 2026-03-30 | merged |
| [#2828](https://github.com/mavlink/MAVSDK/pull/2828) | bug | system_tests: Fix race in mission tests by registering server before connections | 2026-03-30 | merged |
| [#2839](https://github.com/mavlink/MAVSDK/pull/2839) | feature | Expose full `HOME_POSITION` fields in `subscribe_home` | 2026-04-02 | merged |
| [#2847](https://github.com/mavlink/MAVSDK/pull/2847) | test | Fix unit test working directory for file-dependent tests | 2026-04-06 | merged |
| [#2848](https://github.com/mavlink/MAVSDK/pull/2848) | bug | Fix data race in `MavlinkDirectImpl` callback teardown | 2026-04-06 | merged |
{{% /details %}}

{{% details summary="MAVSDK-Proto — 4 merged, 1 closed" %}}
| PR | Type | Description | Date | Status |
|----|------|-------------|------|--------|
| [#398](https://github.com/mavlink/MAVSDK-Proto/pull/398) | feature | Add `timestamp_us` to Altitude and GroundTruth messages | 2026-03-21 | merged |
| [#399](https://github.com/mavlink/MAVSDK-Proto/pull/399) | feature | Add `HomePosition` message with full `HOME_POSITION` fields | 2026-03-21 | merged |
| [#400](https://github.com/mavlink/MAVSDK-Proto/pull/400) | feature | Add `DownloadGeofence` RPC to geofence proto | 2026-03-21 | merged |
| [#401](https://github.com/mavlink/MAVSDK-Proto/pull/401) | feature | Add `HomePosition` message and timestamp fields to telemetry | 2026-03-27 | closed |
| [#405](https://github.com/mavlink/MAVSDK-Proto/pull/405) | refactor | Move `HomePosition` after `Quaternion` in telemetry proto | 2026-04-06 | merged |
{{% /details %}}

{{% details summary="dora-rs — 8 merged, 6 closed" %}}
| PR | Type | Description | Date | Status |
|----|------|-------------|------|--------|
| [#1403](https://github.com/dora-rs/dora/pull/1403) | feature | Expose `node_id()` and `dataflow_id()` accessors | 2026-03-15 | merged |
| [#1409](https://github.com/dora-rs/dora/pull/1409) | feature | Event receive variants (timeout, non-blocking, drain) | 2026-03-16 | closed |
| [#1410](https://github.com/dora-rs/dora/pull/1410) | feature | `close_outputs`, `NodeFailed` and `Reload` event types | 2026-03-16 | closed |
| [#1413](https://github.com/dora-rs/dora/pull/1413) | feature | `node_config_json` and `dataflow_descriptor_json` accessors | 2026-03-16 | closed |
| [#1414](https://github.com/dora-rs/dora/pull/1414) | bug | `InputClosed`/`Stop` events not forwarded to C++ callbacks | 2026-03-16 | closed |
| [#1426](https://github.com/dora-rs/dora/pull/1426) | feature | CLI progress bars for time-consuming operations | 2026-03-17 | closed |
| [#1427](https://github.com/dora-rs/dora/pull/1427) | feature | CLI progress bars for time-consuming operations (v2) | 2026-03-17 | closed |
| [#1428](https://github.com/dora-rs/dora/pull/1428) | feature | Dynamic node initialization | 2026-03-17 | merged |
| [#1431](https://github.com/dora-rs/dora/pull/1431) | feature | Zero-copy output API | 2026-03-17 | merged |
| [#1904](https://github.com/dora-rs/dora/pull/1904) | feature | C++ operator `on_input_parse_error` callback | 2026-05-21 | merged |
| [#1905](https://github.com/dora-rs/dora/pull/1905) | test | Tighten ws-cli-e2e assertions + node lifecycle E2E | 2026-05-21 | merged |
| [#1906](https://github.com/dora-rs/dora/pull/1906) | fix | Add root `pyproject.toml` workspace to Python dataflow template | 2026-05-21 | merged |
| [#1907](https://github.com/dora-rs/dora/pull/1907) | fix | Replace `expect` with contextual errors on stdout/stderr pipe capture | 2026-05-21 | merged |
| [#1908](https://github.com/dora-rs/dora/pull/1908) | feature | Async iteration support for `MockNode` + 3 async tests | 2026-05-21 | merged |
{{% /details %}}

{{% details summary="XGBoost — 5 merged, 6 closed" %}}
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
| [#12111](https://github.com/dmlc/xgboost/pull/12111) | cleanup | Replace bare `Any` with specific types in sklearn helpers | 2026-03-19 | closed |
| [#12112](https://github.com/dmlc/xgboost/pull/12112) | refactor | Consolidate version query scripts into shared Python module | 2026-03-19 | closed |
| [#12162](https://github.com/dmlc/xgboost/pull/12162) | bug | Backport #12094: guard `__doc__` assignments for `python -OO` | 2026-04-16 | merged |
{{% /details %}}

{{% details summary="ROS 2 — rclcpp, ros2cli, geometry2 — 1 merged, 3 open, 5 closed" %}}
| PR | Type | Description | Date | Status |
|----|------|-------------|------|--------|
| [rclcpp#3109](https://github.com/ros2/rclcpp/pull/3109) | perf | O(N²) entity addition in CallbackGroup — 71x speedup | 2026-03-21 | closed |
| [rclcpp#3110](https://github.com/ros2/rclcpp/pull/3110) | bug | Deadlock in `TimeSource::destroy_clock_sub` | 2026-03-21 | closed |
| [rclcpp#3166](https://github.com/ros2/rclcpp/pull/3166) | perf | O(N²) entity addition in CallbackGroup — resubmission of #3109 | 2026-06-06 | closed |
| [rclcpp#3167](https://github.com/ros2/rclcpp/pull/3167) | bug | Deadlock in `TimeSource::destroy_clock_sub` — resubmission of #3110 | 2026-06-06 | closed |
| [rclcpp#3168](https://github.com/ros2/rclcpp/pull/3168) | bug | `create_service()` compile failure from `can_be_nullptr` trait | 2026-06-06 | open |
| [rclcpp#3169](https://github.com/ros2/rclcpp/pull/3169) | feature | Report wait outcome from `SyncParametersClient::get_parameters` | 2026-06-06 | open |
| [rclcpp#3170](https://github.com/ros2/rclcpp/pull/3170) | bug | Bounds-check `EventHandlerBase::is_ready()` to fix out-of-bounds read | 2026-06-06 | closed |
| [ros2cli#1213](https://github.com/ros2/ros2cli/pull/1213) | feature | Add `--content-filter` DDS filtering to `ros2 topic echo\|hz\|bw` | 2026-03-21 | open |
| [geometry2#908](https://github.com/ros2/geometry2/pull/908) | bug | `StaticCache::getData()` returns true on empty cache | 2026-03-21 | merged |
{{% /details %}}

{{% details summary="Fast-DDS — 4 open, 5 closed" %}}
| PR | Type | Description | Date | Status |
|----|------|-------------|------|--------|
| [#6332](https://github.com/eProsima/Fast-DDS/pull/6332) | bug | Missing `#include <cstdint>` in DDSSQLFilter headers | 2026-03-15 | open |
| [#6333](https://github.com/eProsima/Fast-DDS/pull/6333) | bug | XML parser null-dereference on malformed config (2.6.x) | 2026-03-15 | open |
| [#6339](https://github.com/eProsima/Fast-DDS/pull/6339) | bug | Data race in TopicPayloadPool payload acquisition | 2026-03-21 | closed |
| [#6341](https://github.com/eProsima/Fast-DDS/pull/6341) | bug | Double serialization of `type_information` in `ReaderProxyData` | 2026-03-21 | closed |
| [#6342](https://github.com/eProsima/Fast-DDS/pull/6342) | bug | Data race on `has_been_removed` flag in `DataSharingPayloadPool` | 2026-03-21 | closed |
| [#6343](https://github.com/eProsima/Fast-DDS/pull/6343) | bug | Infinite loop in VOLATILE `DataReader` `init_shared_segment` | 2026-03-21 | closed |
| [#6344](https://github.com/eProsima/Fast-DDS/pull/6344) | bug | Race between Condition destruction and WaitSet iteration | 2026-03-21 | closed |
| [#6510](https://github.com/eProsima/Fast-DDS/pull/6510) | fix | Detach conditions from WaitSets before the vtable is rewritten | 2026-08-21 | open |
| [#6511](https://github.com/eProsima/Fast-DDS/pull/6511) | fix | Guard matched-status counters with the endpoint mutex | 2026-08-21 | open |
{{% /details %}}

{{% details summary="px4-ros2-interface-lib — 4 merged" %}}
| PR | Type | Description | Date | Status |
|----|------|-------------|------|--------|
| [#186](https://github.com/Auterion/px4-ros2-interface-lib/pull/186) | fix | VTOL status staleness timeout not configurable | 2026-03-15 | merged |
| [#188](https://github.com/Auterion/px4-ros2-interface-lib/pull/188) | bug | Missing topic namespace prefix in `MapProjection` | 2026-03-17 | merged |
| [#189](https://github.com/Auterion/px4-ros2-interface-lib/pull/189) | feature | Add `HomePositionSetter` utility | 2026-03-18 | merged |
| [#192](https://github.com/Auterion/px4-ros2-interface-lib/pull/192) | refactor | Use `VehicleCommandSender` in `sendCommandSync()` | 2026-03-19 | merged |
{{% /details %}}

{{% details summary="OpenCV — 2 merged" %}}
| PR | Type | Description | Date | Status |
|----|------|-------------|------|--------|
| [#28660](https://github.com/opencv/opencv/pull/28660) | bug | Broken Python bindings | 2026-03-15 | merged |
| [#28665](https://github.com/opencv/opencv/pull/28665) | cleanup | Stale typing stubs | 2026-03-16 | merged |
{{% /details %}}

{{% details summary="concurrentqueue — 2 merged" %}}
| PR | Type | Description | Date | Status |
|----|------|-------------|------|--------|
| [#445](https://github.com/cameron314/concurrentqueue/pull/445) | cleanup | Replace C-style casts with C++ casts | 2026-03-10 | merged |
| [#446](https://github.com/cameron314/concurrentqueue/pull/446) | docs | Document `try_enqueue` capacity limit | 2026-03-17 | merged |
{{% /details %}}

{{% details summary="boost/sml — 50 merged (1.2.0 released)" %}}
| PR | Type | Description | Date | Status |
|----|------|-------------|------|--------|
| [#661](https://github.com/boost-ext/sml/pull/661) | fix | Build with `-fno-exceptions` on GCC 14 | 2026-05-22 | merged |
| [#662](https://github.com/boost-ext/sml/pull/662) | bug | Ambiguous constructor when a substate machine has a virtual destructor | 2026-05-22 | merged |
| [#663](https://github.com/boost-ext/sml/pull/663) | bug | Deferred events not processed in a non-first orthogonal region | 2026-05-22 | merged |
| [#664](https://github.com/boost-ext/sml/pull/664) | fix | `-Wcast-align` in `queue_event` with over-aligned event types | 2026-05-22 | merged |
| [#665](https://github.com/boost-ext/sml/pull/665) | fix | `lock_guard` member order in `thread_safe` for clang-cl | 2026-05-23 | merged |
| [#666](https://github.com/boost-ext/sml/pull/666) | bug | UBSan false positives with captureless lambdas in C++20 | 2026-05-23 | merged |
| [#667](https://github.com/boost-ext/sml/pull/667) | bug | Submachine state not accessible as an action parameter (#659) | 2026-05-23 | merged |
| [#668](https://github.com/boost-ext/sml/pull/668) | bug | Template-depth explosion with large FSMs sharing dependency types (#639) | 2026-05-23 | merged |
| [#669](https://github.com/boost-ext/sml/pull/669) | bug | Uninitialized array in `constexpr` context (GCC 14) | 2026-05-23 | merged |
| [#670](https://github.com/boost-ext/sml/pull/670) | bug | Double-pop crash in `process_queued_events` (#465) | 2026-05-23 | merged |
| [#671](https://github.com/boost-ext/sml/pull/671) | bug | Queued events dispatched in a stale state with pending anonymous transitions (#542) | 2026-05-24 | merged |
| [#672](https://github.com/boost-ext/sml/pull/672) | fix | `-Wextra-semi` warning with `BOOST_SML_CFG_DISABLE_MIN_SIZE` (#519) | 2026-05-24 | merged |
| [#673](https://github.com/boost-ext/sml/pull/673) | bug | Null deref when a pointer dependency is passed as an lvalue to the sm ctor (#485) | 2026-05-24 | merged |
| [#674](https://github.com/boost-ext/sml/pull/674) | bug | Dangling reference in the `pool_type_impl<T&>` init constructor (#504) | 2026-05-23 | merged |
| [#675](https://github.com/boost-ext/sml/pull/675) | fix | Two-phase lookup + test assertion in the `pool_type_impl<T&>` fix (#504) | 2026-05-23 | merged |
| [#676](https://github.com/boost-ext/sml/pull/676) | fix | Resolve `-Wshadow` warnings across `sml.hpp` (#496) | 2026-05-24 | merged |
| [#677](https://github.com/boost-ext/sml/pull/677) | bug | `process_queue<std::queue>` compile error on GCC 9 / Clang 10 (#441) | 2026-05-24 | merged |
| [#678](https://github.com/boost-ext/sml/pull/678) | docs | Document the `operator,` two-MFP limitation; show the `wrap()` workaround (#389) | 2026-05-25 | merged |
| [#679](https://github.com/boost-ext/sml/pull/679) | bug | Non-copyable derived dependency passed as a base-class reference (#467) | 2026-05-25 | merged |
| [#680](https://github.com/boost-ext/sml/pull/680) | fix | Allow `final` classes as SM deps and SM classes (#483) | 2026-05-25 | merged |
| [#681](https://github.com/boost-ext/sml/pull/681) | bug | Guard taking `const State&` now sees live pool state (#530) | 2026-05-26 | merged |
| [#682](https://github.com/boost-ext/sml/pull/682) | bug | Prevent `operator&&`/`\|\|`/`!` from matching `integral_constant`-like types (#546) | 2026-05-26 | merged |
| [#683](https://github.com/boost-ext/sml/pull/683) | fix | Rename reserved `__BOOST_SML_*` macros and `args__` identifiers (#220) | 2026-05-27 | merged |
| [#684](https://github.com/boost-ext/sml/pull/684) | bug | Generic `on_entry<_>`/`on_exit<_>` suppressed by a sub-SM specific handler (#372) | 2026-05-26 | merged |
| [#686](https://github.com/boost-ext/sml/pull/686) | fix | Move `operator[]`/`operator/` SFINAE to a trailing return type for MSVC C++20 (#515) | 2026-05-27 | merged |
| [#687](https://github.com/boost-ext/sml/pull/687) | bug | `back::process<E>` from a sub-SM now routes to the root SM queue (#400) | 2026-05-27 | merged |
| [#688](https://github.com/boost-ext/sml/pull/688) | fix | Disable the zero-size-array min-size trick by default to fix UBSan violations (#249) | 2026-05-27 | merged |
| [#689](https://github.com/boost-ext/sml/pull/689) | ci | Codacy cppcheck config and project include paths | 2026-05-27 | merged |
| [#690](https://github.com/boost-ext/sml/pull/690) | feature | `sml::deps<Ts...>` policy for explicit pool dependencies (#437) | 2026-05-28 | merged |
| [#691](https://github.com/boost-ext/sml/pull/691) | test | Functional test for `sml::deps<Ts...>` (#437) | 2026-05-28 | merged |
| [#692](https://github.com/boost-ext/sml/pull/692) | fix | Replace `if constexpr` with C++14 tag-dispatch in `update_composite_states` (#684 regression) | 2026-05-28 | merged |
| [#694](https://github.com/boost-ext/sml/pull/694) | fix | Guard `test_constexpr` for C++17+; remove a duplicate `add_test` | 2026-05-28 | merged |
| [#697](https://github.com/boost-ext/sml/pull/697) | docs | Document pool mechanism design, `try_get` overload order, and bug history | 2026-05-28 | merged |
| [#698](https://github.com/boost-ext/sml/pull/698) | fix | `BOOST_SML_DETAIL_ZERO_SIZE_ARRAY` `static_assert` needs a message for C++14 | 2026-05-28 | merged |
| [#699](https://github.com/boost-ext/sml/pull/699) | build | Compile-error tests, CMake style/tidy targets, thin Makefile wrapper | 2026-05-28 | merged |
| [#700](https://github.com/boost-ext/sml/pull/700) | bug | Include `process(E{})` events in `events_t` so the queue can store them (#580) | 2026-05-29 | merged |
| [#701](https://github.com/boost-ext/sml/pull/701) | test | Regression tests for anonymous transitions in sub-SMs (#384, #544) | 2026-05-29 | merged |
| [#702](https://github.com/boost-ext/sml/pull/702) | bug | `any`-state wildcard fires when a composable sub-SM terminates (#622) | 2026-05-31 | merged |
| [#703](https://github.com/boost-ext/sml/pull/703) | docs | Document the `on_entry<_>` multi-TU limitation and dispatch priority (#565) | 2026-05-29 | merged |
| [#704](https://github.com/boost-ext/sml/pull/704) | bug | Skip `process_event` in `transitions_sub` when the event isn't in the sub-SM (#685) | 2026-05-30 | merged |
| [#705](https://github.com/boost-ext/sml/pull/705) | bug | Clear the sub-SM defer queue when a composite state is re-entered (#253) | 2026-05-30 | merged |
| [#707](https://github.com/boost-ext/sml/pull/707) | feature | `sm::flush_queue()` to drain the process queue from async handlers (#456) | 2026-05-31 | merged |
| [#706](https://github.com/boost-ext/sml/pull/706) | feature | `sml::make_action<Deps...>(f)` for template/constrained callable actions (#629) | 2026-06-01 | merged |
| [#708](https://github.com/boost-ext/sml/pull/708) | release | Release v1.2.0 — new API (`flush_queue`, `clear_defer`, `deps`, `make_action`), docs overhaul, verified Compiler Explorer links | 2026-05-31 | merged |
| [#709](https://github.com/boost-ext/sml/pull/709) | ci | Automate docs deploy + GitHub releases; fix dead badges and links | 2026-06-01 | merged |
| [#710](https://github.com/boost-ext/sml/pull/710) | docs | Fix 404 links and dead Run buttons; add examples and FAQ | 2026-06-02 | merged |
| [#712](https://github.com/boost-ext/sml/pull/712) | fix | Re-enable const lvalue reference dependency usage | 2026-06-04 | merged |
| [#713](https://github.com/boost-ext/sml/pull/713) | ci | Add ASan and UBSan to CI | 2026-06-10 | merged |
| [#714](https://github.com/boost-ext/sml/pull/714) | fix | Make `transition_sa` and `transition_sg` constructors constexpr | 2026-07-11 | merged |
| [#716](https://github.com/boost-ext/sml/pull/716) | fix | Make `transitions<aux::true_type>::execute` constexpr | 2026-08-09 | merged |
{{% /details %}}

{{% details summary="ast-grep/langs — 1 merged" %}}
| PR | Type | Description | Date | Status |
|----|------|-------------|------|--------|
| [#195](https://github.com/ast-grep/langs/pull/195) | feature | Add GDScript language package | 2026-09-10 | merged |
{{% /details %}}

{{% details summary="Fast-DDS-docs — 1 open" %}}
| PR | Type | Description | Date | Status |
|----|------|-------------|------|--------|
| [#1234](https://github.com/eProsima/Fast-DDS-docs/pull/1234) | docs | Troubleshooting entry for libunwind/libgcc_s conflict | 2026-03-15 | open |
{{% /details %}}
