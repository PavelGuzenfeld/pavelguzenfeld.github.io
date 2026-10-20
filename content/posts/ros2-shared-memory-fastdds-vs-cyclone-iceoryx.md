---
title: 'ROS 2 Shared Memory, Measured: Fast DDS SHM and Data-Sharing vs Cyclone DDS + iceoryx'
date: 2026-10-20
draft: false
cover:
  image: /images/posts/ros2-shared-memory-fastdds-vs-cyclone-iceoryx.png
  alt: 'Same-host ROS 2 Jazzy latency for 1 KB to 4 MB messages: Fast DDS UDP, SHM and data-sharing vs Cyclone DDS with iceoryx'
tags:
- ROS2
- DDS
- Fast-DDS
- shared-memory
- zero-copy
- benchmarking
- performance
- Docker
keywords:
- ROS 2 shared memory benchmark
- Fast DDS data sharing ROS 2
- Fast DDS SHM segment_size 512 KB
- Cyclone DDS iceoryx ROS 2 Jazzy
- ROS_DISABLE_LOANED_MESSAGES
- borrow_loaned_message latency
- ROS 2 zero copy large messages
- FASTRTPS_DEFAULT_PROFILES_FILE
categories:
- deep-dive
summary: I benchmarked same-host ROS 2 Jazzy pub/sub latency for 1 KB, 1 MB and 4 MB
  messages across six transport setups. Cyclone DDS + iceoryx with loaned messages
  moved 4 MB at an 83 µs median. Getting there took two settings nobody turns on by
  default, and the Fast DDS defaults fall over above 512 KB.
ShowToc: true
audio:
  pronunciation:
    ROS 2: ross two
    ROS2: ross two
    DDS: D D S
    Fast DDS: fast D D S
    Fast-DDS: fast D D S
    Cyclone DDS: cyclone D D S
    iceoryx: ice oryx
    RouDi: roo dee
    rmw: R M W
    rclcpp: R C L C P P
    SHM: shared memory
    UDP: U D P
    µs: microseconds
---

## Why I measured this

I had two old notes on ROS 2 shared memory. One was a Fast DDS XML profile with data-sharing turned on. The other was a "use Cyclone DDS with iceoryx" recipe. Both promised lower latency for big messages. Neither had a number in it.

So I built a small pub/sub pair, ran it on ROS 2 Jazzy in Docker, and measured six transport setups at 1 KB, 1 MB and 4 MB.

## The setup

- **Host:** Intel i7-12700H (20 threads), Linux 7.0, Docker 29.9, everything in one container per run.
- **ROS:** `ros:jazzy-ros-base`, `rmw_fastrtps_cpp` 8.4.4 on Fast DDS 2.14.7, `rmw_cyclonedds_cpp` 2.2.4 on Cyclone DDS 0.10.5 with iceoryx 2.0.6.
- **Traffic:** one publisher process, one subscriber process, 100 Hz, reliable QoS, `KEEP_LAST(16)`. 50 warm-up messages, then 500 measured ones. Each case was run once.
- **Latency:** the publisher writes `steady_clock` nanoseconds into the message right before `publish()`. The subscriber reads the clock first thing in its callback. Both processes share the same monotonic clock, so the difference is end to end: serialization, transport, the executor waking up, deserialization.

There are four message types. Three are fixed size, so they're plain memory that can be loaned:

```text
# Fixed1K.msg / Fixed1M.msg / Fixed4M.msg
uint64 stamp_ns
uint8[1024] data        # 1048576 / 4194304 in the other two
```

The fourth is unbounded, like `sensor_msgs/Image`:

```text
# Dyn.msg
uint64 stamp_ns
uint8[] data
```

There are two publish modes:

- **copy:** `publish(const Msg&)`. This is what most code does.
- **loan:** `borrow_loaned_message()`, write the stamp, then `publish(std::move(loaned))`. One catch for honesty: in loan mode I don't write the 4 MB payload, only the stamp. A real camera driver would fill the buffer, so treat the loan numbers as the transport floor.

The six setups:

| Name | What it is |
|---|---|
| `fastdds-udp` | Fast DDS, UDPv4 only, data-sharing off |
| `fastdds-default` | Fast DDS, no XML at all |
| `fastdds-shm64` | Fast DDS, SHM transport with a 64 MB segment |
| `fastdds-datasharing` | Fast DDS, my old note's profile: UDP transport + data-sharing `AUTOMATIC` |
| `cyclone-udp` | Cyclone DDS, defaults |
| `cyclone-iox` | Cyclone DDS, `SharedMemory` enabled, iceoryx RouDi running |

## The first trap: Jazzy disables subscriber loans

My first Cyclone + iceoryx run looked like nothing changed. 4 MB took about 3 ms either way. The publisher reported `can_loan_messages() == true`, but the subscription said `false`.

I traced through `rmw_cyclonedds` and Cyclone's reader code. The iceoryx subscriber was being created fine. The "no" came from rcl. Jazzy turns subscriber-side loans off unless you opt in, and rclcpp tells you so once you set the variable:

```text
[WARN] [bench_sub]: Loaned messages are only safe with const ref subscription callbacks.
If you are using any other kind of subscriptions, set the ROS_DISABLE_LOANED_MESSAGES
environment variable to 1 (the default).
```

So by default, a loaned publish still lands in a freshly allocated message on the subscriber side, and every byte gets copied. To get real zero-copy on Jazzy you need both of these:

```bash
export ROS_DISABLE_LOANED_MESSAGES=0
```

```cpp
node->create_subscription<Msg>("bench", qos, [&](const Msg & m) { /* ... */ });
```

The callback has to take a `const Msg&`. A `SharedPtr` or by-value callback isn't safe with loans. Here's the 4 MB fixed message on Cyclone + iceoryx, measured before I knew this:

| Subscriber loans | p50 (µs) | p99 (µs) |
|---|---:|---:|
| off (Jazzy default) | 2990 | 5010 |
| on | 63 | 102 |

That was a 50-message smoke test. The full runs below all use loan mode with `ROS_DISABLE_LOANED_MESSAGES=0`. Copy mode leaves it at the default.

## Results

### 4 MB, median latency

The bars use a log scale, one `#` per 1/12 of a decade above 10 µs. The numbers are p50 in µs.

```text
fastdds-udp          fixed copy  |#####################################     12066
fastdds-udp          fixed loan  |#####################################     11093
fastdds-udp          dyn copy    |#####################################     12165
fastdds-default      fixed copy  |##############################             2936
fastdds-default      fixed loan  |####################################      10601
fastdds-default      dyn copy    |#############################              2652
fastdds-shm64        fixed copy  |###########################                1621
fastdds-shm64        fixed loan  |#####################                       521
fastdds-shm64        dyn copy    |##########################                 1407
fastdds-datasharing  fixed copy  |########################                   1058
fastdds-datasharing  fixed loan  |##############                              147
fastdds-datasharing  dyn copy    |#####################################     12177
cyclone-udp          fixed copy  |##############################             3087
cyclone-udp          fixed loan  |#############################              2419
cyclone-udp          dyn copy    |#############################              2476
cyclone-iox          fixed copy  |###############################            3535
cyclone-iox          fixed loan  |###########                                  83
cyclone-iox          dyn copy    |##############################             3348
```

`cyclone-udp` can't loan, so its "loan" row is just a second copy run.

### Full table

The loan column shows which side actually got a loan: `pub+sub`, only `pub`, or `no`. All times are in µs, n = 500 for every row except one 4 MB `fastdds-default` loan run, which got 498.

| Setup | Size | Mode | Loan | min | p50 | p99 |
|---|---|---|---|---:|---:|---:|
| fastdds-udp | 1 KB | copy | pub | 77 | 164 | 285 |
| fastdds-udp | 1 KB | loan | pub+sub | 40 | 153 | 248 |
| fastdds-udp | 1 MB | copy | pub | 479 | 10979 | 21522 |
| fastdds-udp | 1 MB | loan | pub+sub | 233 | 10892 | 50726 |
| fastdds-udp | 4 MB | copy | pub | 1664 | 12066 | 22886 |
| fastdds-udp | 4 MB | loan | pub+sub | 663 | 11093 | 51157 |
| fastdds-udp | 4 MB dyn | copy | no | 1685 | 12165 | 23621 |
| fastdds-default | 1 KB | copy | pub | 55 | 152 | 259 |
| fastdds-default | 1 KB | loan | pub+sub | 47 | 155 | 292 |
| fastdds-default | 1 MB | copy | pub | 312 | 537 | 11086 |
| fastdds-default | 1 MB | loan | pub+sub | 132 | 361 | 30932 |
| fastdds-default | 4 MB | copy | pub | 1066 | 2936 | 12986 |
| fastdds-default | 4 MB | loan | pub+sub | 432 | 10601 | 70911 |
| fastdds-default | 4 MB dyn | copy | no | 1143 | 2653 | 22028 |
| fastdds-shm64 | 1 KB | copy | pub | 35 | 124 | 247 |
| fastdds-shm64 | 1 KB | loan | pub+sub | 24 | 102 | 237 |
| fastdds-shm64 | 1 MB | copy | pub | 283 | 464 | 1187 |
| fastdds-shm64 | 1 MB | loan | pub+sub | 128 | 260 | 758 |
| fastdds-shm64 | 4 MB | copy | pub | 948 | 1621 | 4470 |
| fastdds-shm64 | 4 MB | loan | pub+sub | 374 | 521 | 1084 |
| fastdds-shm64 | 4 MB dyn | copy | no | 1017 | 1407 | 2468 |
| fastdds-datasharing | 1 KB | copy | pub | 38 | 192 | 346 |
| fastdds-datasharing | 1 KB | loan | pub+sub | 29 | 139 | 356 |
| fastdds-datasharing | 1 MB | copy | pub | 197 | 373 | 594 |
| fastdds-datasharing | 1 MB | loan | pub+sub | 44 | 142 | 283 |
| fastdds-datasharing | 4 MB | copy | pub | 687 | 1058 | 1537 |
| fastdds-datasharing | 4 MB | loan | pub+sub | 33 | 147 | 299 |
| fastdds-datasharing | 4 MB dyn | copy | no | 1330 | 12177 | 43668 |
| cyclone-udp | 1 KB | copy | no | 28 | 93 | 168 |
| cyclone-udp | 1 KB | loan | no | 21 | 98 | 199 |
| cyclone-udp | 1 MB | copy | no | 435 | 821 | 1436 |
| cyclone-udp | 1 MB | loan | no | 419 | 824 | 2326 |
| cyclone-udp | 4 MB | copy | no | 2128 | 3087 | 17129 |
| cyclone-udp | 4 MB | loan | no | 2014 | 2419 | 6598 |
| cyclone-udp | 4 MB dyn | copy | no | 1906 | 2477 | 6901 |
| cyclone-iox | 1 KB | copy | pub | 15 | 74 | 184 |
| cyclone-iox | 1 KB | loan | pub+sub | 8 | 59 | 195 |
| cyclone-iox | 1 MB | copy | pub | 561 | 906 | 1280 |
| cyclone-iox | 1 MB | loan | pub+sub | 19 | 64 | 176 |
| cyclone-iox | 4 MB | copy | pub | 2275 | 3535 | 5392 |
| cyclone-iox | 4 MB | loan | pub+sub | 18 | 83 | 208 |
| cyclone-iox | 4 MB dyn | copy | no | 2391 | 3348 | 4665 |

## What the numbers say

**At 1 KB, nothing matters.** Every setup sits between 59 and 192 µs median. That's executor wake-up and scheduling, not the transport.

**iceoryx only pays off with loans on both ends.** `cyclone-iox` in copy mode is as slow as plain UDP at 4 MB: 3.5 ms against 3.1 ms. Turn on loans and the median drops to 83 µs, flat across 1 MB and 4 MB. That flat line is the whole point of zero-copy. The size stops mattering.

**Fast DDS out of the box falls over above 512 KB.** With no XML, the 1 MB and 4 MB tails jump to 11, 21, 31 ms and beyond. The 4 MB loan median is 10.6 ms. The jumps come in steps of about 10 ms, which looks like reliable-protocol recovery, not slow copying. The [Fast DDS 2.14 docs](https://fast-dds.docs.eprosima.com/en/2.14.x/fastdds/transport/shared_memory/shared_memory.html) list the default SHM `segment_size` as 512 KB. With the segment raised to 64 MB, the steps went away: 4 MB loan p99 dropped from 70.9 ms to 1.1 ms.

```xml
<transport_descriptor>
    <transport_id>shm_big</transport_id>
    <type>SHM</type>
    <segment_size>67108864</segment_size>
</transport_descriptor>
```

**UDP-only Fast DDS is the worst case for big messages.** It sits around 11–12 ms median at 1 MB and up, with the same 10 ms step pattern.

**Data-sharing is fast, and my old profile was a trap.** The profile from my note turns off the builtin transports and keeps only UDPv4, then turns on data-sharing:

```xml
<participant profile_name="participant_profile_ros2" is_default_profile="true">
    <rtps>
        <userTransports><transport_id>UDP_transport</transport_id></userTransports>
        <useBuiltinTransports>false</useBuiltinTransports>
    </rtps>
</participant>
<data_writer profile_name="default publisher profile" is_default_profile="true">
    <qos>
        <publishMode><kind>ASYNCHRONOUS</kind></publishMode>
        <data_sharing><kind>AUTOMATIC</kind></data_sharing>
    </qos>
    <historyMemoryPolicy>PREALLOCATED_WITH_REALLOC</historyMemoryPolicy>
</data_writer>
```

For fixed-size types it works well: 147 µs median at 4 MB with loans, and 1.06 ms in copy mode, the best copy number in the table. But data-sharing only covers bounded types. An unbounded message like `sensor_msgs/Image` falls back to the only transport left, UDP, and goes to 12 ms median with a 44 ms p99. If you use a profile like this, keep SHM in `userTransports` next to UDP.

**Data-sharing only showed up with the XML profile.** I listed `/dev/shm` during each 4 MB loan run:

```text
fastdds-default:     fastrtps*, fastrtps_portN*, sem.fastrtps_portN_mutex   (SHM transport only)
fastdds-shm64:       fastrtps*, fastrtps_portN*, sem.fastrtps_portN_mutex   (SHM transport only)
fastdds-datasharing: fast_datasharing_01.0f.…_0.0.14.3, fast_datasharing_…_0.0.14.4
cyclone-iox:         iceoryx_mgmt, root
```

Without the profile and `RMW_FASTRTPS_USE_QOS_FROM_XML=1`, I never saw a `fast_datasharing_*` segment. The publisher still reported it could loan, but the bytes went through the SHM transport. That's still a copy into the segment.

## Small things that cost me time

- **Check the profile variable name.** Fast DDS 2.14 in Jazzy only knows `FASTRTPS_DEFAULT_PROFILES_FILE`. I checked with `strings libfastrtps.so | grep PROFILES_FILE`. Look before you copy a variable name from a newer guide.
- **RouDi needs room.** With my mempool config (512×2 KB, 64×1 MB, 64×4 MB), RouDi reserved 65.7 MB for `iceoryx_mgmt` and 336.7 MB for the data segment. Docker's default `/dev/shm` is 64 MB, so I ran with `--shm-size=2g`. Across containers you'd use `--ipc=host` instead, so they share one `/dev/shm`.
- **RouDi pools must fit your biggest message**, including the chunk header. I sized the pools at a bit over 1 MB and 4 MB.
- **The Cyclone config** that worked with 0.10.5:

```xml
<CycloneDDS xmlns="https://cdds.io/config">
    <Domain id="any">
        <SharedMemory>
            <Enable>true</Enable>
            <LogLevel>warn</LogLevel>
        </SharedMemory>
    </Domain>
</CycloneDDS>
```

```bash
iox-roudi -c roudi.toml &
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export CYCLONEDDS_URI=file://$PWD/config/cyclonedds_shm.xml
export ROS_DISABLE_LOANED_MESSAGES=0
```

## What I'd do now

For big fixed-size messages on one host: Cyclone DDS + iceoryx, loaned publish, `const&` callbacks, and `ROS_DISABLE_LOANED_MESSAGES=0`. That was the only setup where 4 MB cost the same as 1 KB.

If you're staying on Fast DDS, raise the SHM `segment_size` first. That one change fixed the tails. Then add data-sharing for the bounded types, without dropping the SHM transport.

For unbounded types like images and point clouds, no setup here gets you zero-copy. The best I measured was `fastdds-shm64` at 1.4 ms median for 4 MB.

## Caveats

- One machine, one run per case, 500 samples, 100 Hz. Your scheduler and core count will move these numbers. The 10 ms steps and the loan-vs-copy gaps were large enough that I don't expect them to flip.
- In loan mode the publisher doesn't fill the payload.
- Both processes ran in the same container. That's same-host IPC, not intra-process.

## Reproduce

{{< details summary="bench.cpp (one binary, pub or sub role)" >}}

```cpp
#include <algorithm>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <memory>
#include <string>
#include <thread>
#include <vector>

#include <rclcpp/rclcpp.hpp>
#include <shm_bench/msg/dyn.hpp>
#include <shm_bench/msg/fixed1_k.hpp>
#include <shm_bench/msg/fixed1_m.hpp>
#include <shm_bench/msg/fixed4_m.hpp>

using namespace std::chrono_literals;

std::uint64_t now_ns()
{
  return std::chrono::duration_cast<std::chrono::nanoseconds>(
           std::chrono::steady_clock::now().time_since_epoch()).count();
}

rclcpp::QoS bench_qos()
{
  const char * be = std::getenv("BENCH_BEST_EFFORT");
  auto q = rclcpp::QoS(rclcpp::KeepLast(16));
  return (be && *be == '1') ? q.best_effort() : q.reliable();
}

template<typename Msg>
void prepare(Msg & msg, std::size_t dyn_size)
{
  if constexpr (requires { msg.data.resize(0); }) {
    msg.data.assign(dyn_size, 0xAB);
  } else {
    std::fill(msg.data.begin(), msg.data.end(), 0xAB);
  }
}

template<typename Msg>
int run_pub(std::size_t dyn_size, bool loan, int count)
{
  auto node = std::make_shared<rclcpp::Node>("bench_pub");
  auto pub = node->create_publisher<Msg>("bench", bench_qos());
  while (rclcpp::ok() && pub->get_subscription_count() == 0) {
    std::this_thread::sleep_for(50ms);
  }
  std::this_thread::sleep_for(1s);
  std::printf("pub can_loan_messages=%d\n", pub->can_loan_messages() ? 1 : 0);
  auto msg = std::make_unique<Msg>();
  prepare(*msg, dyn_size);
  const char * pe = std::getenv("BENCH_PERIOD_MS");
  const auto period = std::chrono::milliseconds(pe ? std::atoi(pe) : 10);
  constexpr int warmup = 50;
  auto next = std::chrono::steady_clock::now();
  for (int i = 0; i < warmup + count && rclcpp::ok(); ++i) {
    next += period;
    std::this_thread::sleep_until(next);
    if constexpr (requires { msg->data.resize(0); }) {
      msg->stamp_ns = now_ns();
      pub->publish(*msg);
    } else {
      if (loan) {
        auto loaned = pub->borrow_loaned_message();
        loaned.get().stamp_ns = now_ns();
        pub->publish(std::move(loaned));
      } else {
        msg->stamp_ns = now_ns();
        pub->publish(*msg);
      }
    }
  }
  std::this_thread::sleep_for(2s);
  return 0;
}

template<typename Msg>
int run_sub(int count)
{
  auto node = std::make_shared<rclcpp::Node>("bench_sub");
  std::vector<double> lat_us;
  lat_us.reserve(count + 100);
  int seen = 0;
  constexpr int warmup = 50;
  auto sub = node->create_subscription<Msg>(
    "bench", bench_qos(), [&](const Msg & m) {
      auto t = now_ns();
      if (++seen > warmup) {
        lat_us.push_back((t - m.stamp_ns) / 1000.0);
      }
    });
  std::printf("sub can_loan_messages=%d\n", sub->can_loan_messages() ? 1 : 0);
  std::fflush(stdout);
  rclcpp::executors::SingleThreadedExecutor exec;
  exec.add_node(node);
  auto deadline = std::chrono::steady_clock::now() + 60s;
  while (rclcpp::ok() && static_cast<int>(lat_us.size()) < count &&
    std::chrono::steady_clock::now() < deadline)
  {
    exec.spin_some(100ms);
  }
  std::sort(lat_us.begin(), lat_us.end());
  if (lat_us.empty()) {
    std::printf("RESULT n=0\n");
    return 1;
  }
  auto pct = [&](double p) { return lat_us[static_cast<std::size_t>(p * (lat_us.size() - 1))]; };
  std::printf("RESULT n=%zu min=%.1f p50=%.1f p99=%.1f max=%.1f\n",
    lat_us.size(), lat_us.front(), pct(0.5), pct(0.99), lat_us.back());
  return 0;
}

template<typename Msg>
int dispatch(const std::string & role, std::size_t dyn, bool loan, int count)
{
  return role == "pub" ? run_pub<Msg>(dyn, loan, count) : run_sub<Msg>(count);
}

int main(int argc, char ** argv)
{
  rclcpp::init(argc, argv);
  std::vector<std::string> a = rclcpp::remove_ros_arguments(argc, argv);
  if (a.size() < 6) {
    std::fprintf(stderr, "usage: bench pub|sub 1k|1m|4m|dyn <dyn-bytes> copy|loan <count>\n");
    return 2;
  }
  const std::string role = a[1], type = a[2];
  const std::size_t dyn = std::stoul(a[3]);
  const bool loan = a[4] == "loan";
  const int count = std::stoi(a[5]);
  int rc = 2;
  if (type == "1k") {rc = dispatch<shm_bench::msg::Fixed1K>(role, dyn, loan, count);}
  if (type == "1m") {rc = dispatch<shm_bench::msg::Fixed1M>(role, dyn, loan, count);}
  if (type == "4m") {rc = dispatch<shm_bench::msg::Fixed4M>(role, dyn, loan, count);}
  if (type == "dyn") {rc = dispatch<shm_bench::msg::Dyn>(role, dyn, loan, count);}
  rclcpp::shutdown();
  return rc;
}
```

{{< /details >}}

The package is a plain `ament_cmake` package with `rosidl_generate_interfaces` for the four `.msg` files. One gotcha: `project(shm_bench C CXX)`. The generated C typesupport needs the C language enabled, or CMake fails with "Cannot determine link language".

```dockerfile
FROM ros:jazzy-ros-base
RUN apt-get update && apt-get install -y --no-install-recommends ros-jazzy-rmw-cyclonedds-cpp \
    && rm -rf /var/lib/apt/lists/*
COPY ws /ws
RUN . /opt/ros/jazzy/setup.sh && cd /ws && colcon build --cmake-args -DCMAKE_BUILD_TYPE=Release
```

One case looks like this. Start the subscriber, then the publisher:

```bash
docker run --rm --shm-size=2g -v $PWD/config:/cfg:ro shm-bench:jazzy bash -c '
  . /ws/install/setup.bash
  export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp CYCLONEDDS_URI=file:///cfg/cyclonedds_shm.xml
  export ROS_DISABLE_LOANED_MESSAGES=0
  iox-roudi -c /cfg/roudi.toml & sleep 2
  B=/ws/install/shm_bench/lib/shm_bench/bench
  $B sub 4m 0 loan 500 & S=$!; sleep 1
  $B pub 4m 0 loan 500; wait $S'
```

The RouDi mempool config I used:

```toml
[general]
version = 1

[[segment]]

[[segment.mempool]]
size = 2048
count = 512

[[segment.mempool]]
size = 1049600
count = 64

[[segment.mempool]]
size = 4195328
count = 64
```
