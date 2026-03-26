---
title: "l2-hybrid-protocol -- Low-Latency Layer 2 Protocol for Drone Telemetry"
summary: "High-performance Layer 2 raw socket networking library for Linux. Bypasses the kernel transport and network layers for deterministic latency in real-time UAV telemetry."
tags: ["C++", "C++23", "networking", "low-latency", "telemetry", "drones"]
---

## What It Is

A Linux networking library that bypasses the kernel's transport and network layers (UDP/TCP/IP), communicating directly via Ethernet frames through `AF_PACKET` raw sockets. Deterministic latency, reduced packet overhead, and high throughput for real-time drone telemetry.

## Why It Exists

UDP is fast, but it still goes through the kernel's IP stack. For real-time drone telemetry where microseconds matter, cutting out that overhead makes a measurable difference. This library provides a hybrid architecture: TCP for the control plane, raw Layer 2 for the data plane.

## Key Features

- **Raw L2 sockets** -- direct Ethernet frame transmission/reception via `AF_PACKET`
- **802.1Q VLAN support** -- priority tagging (PCP) and VLAN segmentation
- **Zero-copy frame building** -- builder pattern with `build_into()` for pre-allocated buffers
- **Hybrid protocol** -- TCP control plane + raw L2 data plane
- **Remote benchmarking** -- SSH-based deployment and cross-network testing
- **Static builds** -- portable binaries via musl/Alpine or static glibc

## Design Principles

- No exceptions -- all error handling via `std::expected<T, error_code>`
- RAII everywhere -- sockets, SSH sessions, channels automatically cleaned up
- Compile-time safety -- `constexpr`/`consteval` validation, `static_assert` on struct layout
- Sanitizer-clean -- all tests pass under ASan + UBSan

## Requirements

- Linux kernel 4.x+, C++23 (GCC 13+ or Clang 16+), CMake 3.21+
- Root privileges for raw socket operations

## Quick Start

```bash
cmake --preset debug
cmake --build --preset debug

# Unit tests
./build/debug/bin/l2net_unit_tests

# Integration tests (requires --privileged for raw sockets)
docker run --rm --privileged l2net-dev ./build/debug/bin/l2net_integration_tests
```

[View on GitHub](https://github.com/PavelGuzenfeld/l2-hybrid-protocol)
