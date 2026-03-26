---
title: "behavior-tree-lite -- C++23 Header-Only Behavior Tree Library"
summary: "Header-only C++23 behavior tree with compile-time DSL, zero heap allocations, and sub-nanosecond node dispatch. 10x smaller binary than BehaviorTree.CPP."
tags: ["C++", "C++23", "behavior-tree", "robotics", "game-ai", "header-only"]
---

## What It Is

A lightweight, header-only behavior tree library for C++23. Tree structure is resolved at compile time, execution is flattened, and node dispatch runs in sub-nanosecond time.

```cpp
auto tree = (CheckBattery{} && Attack{}) || RunAway{};
tree.process(Tick{}, ctx);  // ~0.9 ns for full tree evaluation
```

## Why It Exists

Existing behavior tree libraries (like [BehaviorTree.CPP](https://github.com/BehaviorTree/BehaviorTree.CPP)) use runtime polymorphism, heap allocation, and XML configuration. That's fine for many use cases, but not when you're running on constrained hardware with strict latency budgets.

## How It Compares

| | behavior-tree-lite | BehaviorTree.CPP |
|---|---|---|
| **Dispatch** | Compile-time (~0.1 ns) | Runtime polymorphism (~15-30 ns) |
| **Tree definition** | C++ operators: `&&` `\|\|` `!` | XML or runtime builder |
| **Dependencies** | None (STL only) | Boost, tinyxml2, cppzmq |
| **Allocations** | Zero (stack-only) | Heap (shared_ptr, strings) |
| **Header-only** | Yes | No (shared library) |
| **Binary size** | Minimal | ~500 KB shared lib |

## Features

- **Compile-time composition** -- tree structure flattened at compile time
- **Expressive DSL** -- `&&`, `||`, `!` to compose trees naturally
- **Stack-based events** -- `std::variant`, no virtual dispatch
- **Built-in tree visualizer** for debugging
- **ROS 2 ready** -- includes `package.xml` and `ament_cmake` integration

## Installation

```bash
# CMake FetchContent
include(FetchContent)
FetchContent_Declare(behavior-tree-lite
    GIT_REPOSITORY https://github.com/PavelGuzenfeld/behavior-tree-lite.git
    GIT_TAG main)
FetchContent_MakeAvailable(behavior-tree-lite)
target_link_libraries(your_target PRIVATE behavior_tree_lite)
```

[View on GitHub](https://github.com/PavelGuzenfeld/behavior-tree-lite)
