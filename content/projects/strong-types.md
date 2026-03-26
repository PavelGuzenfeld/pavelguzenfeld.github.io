---
title: "strong-types -- Compile-Time Type Safety for C++ Primitives"
summary: "Zero-dependency C++23 strong type library with SI units, dimensional analysis, quantity points, and safe integer math. Prevents unit and coordinate mix-ups at compile time."
tags: ["C++", "C++23", "type-safety", "units", "header-only"]
---

## What It Is

A zero-dependency C++23 library that wraps primitives in named types so the compiler catches unit and coordinate mix-ups before your code ever runs.

```cpp
auto altitude = 500.0_m;
auto speed = 120.0_kmh;
// altitude + speed;  // compile error -- incompatible dimensions
```

## Why It Exists

Because `meters` and `feet` should never silently convert. In drone avionics, mixing up coordinate frames or physical units isn't a bug report -- it's a crash. This library makes those mistakes impossible at the type level.

## Key Features

- **constexpr everything** -- compile-time math where supported
- **SI units** with trait-based dimensional analysis (length, mass, time, speed, force, energy, etc.)
- **Scaled units** -- `Kilometers`, `Milliseconds`, `KilometersPerHour` with compile-time ratio conversions
- **User-defined literals** -- `5.0_m`, `9.81_mps2`, `100.0_km`, `36.0_kmh`
- **Quantity points** (affine types) -- type-safe absolute positions (MSL altitude, GPS coordinates)
- **Safe integer math** -- `std::expected`-based overflow/underflow/division-by-zero detection
- **Non-arithmetic T** -- `Strong<Vec2, PositionTag>` works with vectors, quaternions, custom types
- **~1,500 LOC** -- minimal compile-time overhead

## How It Compares

| Feature | strong-types | mp-units | Au | nholthaus/units |
|---|---|---|---|---|
| C++ standard | **C++23** | C++20 | C++14 | C++14 |
| Header-only | yes | no | yes | yes |
| Dependencies | **zero** | gsl-lite | none | none |
| LOC | **~1,500** | ~30,000 | ~15,000 | ~12,000 |
| Custom non-arithmetic T | **yes** | no | no | no |
| Integer overflow safety | **yes** | partial | best-in-class | no |

## Installation

```cmake
include(FetchContent)
FetchContent_Declare(strong-types
    GIT_REPOSITORY https://github.com/PavelGuzenfeld/strong-types.git
    GIT_TAG v0.2.10)
FetchContent_MakeAvailable(strong-types)
target_link_libraries(your_target PRIVATE strong-types)
```

[View on GitHub](https://github.com/PavelGuzenfeld/strong-types)
