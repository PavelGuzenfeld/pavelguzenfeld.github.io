---
title: "Fixing O(N²) Entity Addition in ROS 2's CallbackGroup"
date: 2026-03-23
draft: false
tags: ["ROS2", "C++", "performance", "open-source", "rclcpp"]
keywords: ["rclcpp CallbackGroup performance", "ROS 2 O(N²) bug", "rclcpp entity registration slow"]
cover:
  image: /images/posts/rclcpp-callbackgroup.png
  alt: "Fixing O(N²) Entity Addition in ROS 2's CallbackGroup"
categories: ["deep-dive"]
summary: "How a simple erase-remove in every add_timer() call turned entity registration into a quadratic bottleneck — and the 71x speedup from moving cleanup to the right place."
ShowToc: true
---

## The Bug

ROS 2 issue [#2942](https://github.com/ros2/rclcpp/issues/2942) reported a surprising result: creating 10,000 timers took **429 milliseconds**. That's 23,310 timers per second — not a number that screams "bottleneck" until you realize the work per timer should be constant. Adding N timers shouldn't take O(N²) time. But it did.

The reproducer was simple:

```cpp
auto node = std::make_shared<rclcpp::Node>("test");
auto cbg = node->create_callback_group(rclcpp::CallbackGroupType::MutuallyExclusive);
for (int i = 0; i < 10000; ++i) {
  node->create_wall_timer(1h, []() {}, cbg);
}
```

Profiling showed that **96% of wall time** was spent inside `CallbackGroup::add_timer()`.

---

## The Root Cause

Here's what `add_timer()` looked like before the fix (and every other `add_*` method had the same pattern):

```cpp
void CallbackGroup::add_timer(const rclcpp::TimerBase::SharedPtr & timer_ptr)
{
  std::lock_guard<std::mutex> lock(mutex_);
  timer_ptrs_.push_back(timer_ptr);
  timer_ptrs_.erase(
    std::remove_if(
      timer_ptrs_.begin(),
      timer_ptrs_.end(),
      [](const rclcpp::TimerBase::WeakPtr & x) { return x.expired(); }),
    timer_ptrs_.end());
}
```

The `push_back` is O(1). But immediately after, the code runs a **full linear scan** of the entire vector to remove expired `weak_ptr`s. On the first call, that scans 1 element. On the second, 2. On the N-th, N. Total: 1 + 2 + ... + N = **N(N+1)/2** — classic quadratic.

The irony: during bulk addition of timers, none of them are expired. The cleanup pass does nothing useful. It's just burning cycles scanning a growing vector.

All five `add_*` methods (`add_timer`, `add_subscription`, `add_service`, `add_client`, `add_waitable`) had the same pattern.

---

## The Fix

The insight is that `collect_all_ptrs()` — called by the executor on every spin iteration — already iterates all entities. It already skips expired entries. It's the natural place to also *remove* them.

**Step 1: Make `add_*` methods O(1)**

Strip out the cleanup. Just push:

```cpp
void CallbackGroup::add_timer(const rclcpp::TimerBase::SharedPtr & timer_ptr)
{
  std::lock_guard<std::mutex> lock(mutex_);
  timer_ptrs_.push_back(timer_ptr);
}
```

**Step 2: Clean up expired entries in `collect_all_ptrs`**

After iterating each vector and calling the user-provided function for live entries, remove the dead ones with `remove_if`:

```cpp
void CallbackGroup::collect_all_ptrs(/* ... */)
{
  std::lock_guard<std::mutex> lock(mutex_);

  for (const auto & weak_ptr : timer_ptrs_) {
    auto ref_ptr = weak_ptr.lock();
    if (ref_ptr) {
      timer_func(ref_ptr);
    }
  }
  timer_ptrs_.erase(
    std::remove_if(
      timer_ptrs_.begin(), timer_ptrs_.end(),
      [](const auto & w) { return w.expired(); }),
    timer_ptrs_.end());

  // Same pattern for subscriptions, services, clients, waitables...
}
```

This is safe because:

- `collect_all_ptrs` already skipped expired entries; now it also removes them
- The executor calls `collect_all_ptrs` on every spin iteration, so expired entries are cleaned up promptly
- All `find_*_ptrs_if` methods already handle expired `weak_ptr`s gracefully (they call `.lock()` and skip nulls)

No public API or ABI change — only the internal cleanup scheduling moved.

---

## The Result

| | Time | Throughput |
|---|---|---|
| **Before** | 429 ms | 23,310 timers/sec |
| **After** | 6 ms | 1,666,667 timers/sec |
| **Speedup** | **71.5x** | |

The fix is trivially correct. The performance gain is massive. The diff is small. That's the best kind of optimization.

---

## The Review

Maintainer [@jmachowinski](https://github.com/jmachowinski) had two clean requests:

**1. Don't use `mutable` on the entity vectors**

My initial version marked the five entity vectors as `mutable` so the `const`-qualified `collect_all_ptrs` could modify them during cleanup. The reviewer correctly pointed out: just make `collect_all_ptrs` non-const instead. All callers lock from `WeakPtr` to get a non-const `SharedPtr`, so this is safe.

**2. Use `remove_if` instead of manual index compaction**

My first implementation used a hand-rolled `collect_and_compact` helper that iterated with read/write indices to compact in a single pass. It was correct and cache-friendly, but unnecessary — the standard `erase(remove_if(...))` idiom does the same thing and is immediately recognizable to any C++ developer.

Both were good calls. The code got simpler and more idiomatic.

---

## Testing

The PR includes integration tests that verify:

- **Expired entries are compacted** — Add 100 timers, destroy 50, trigger `collect_all_ptrs`, assert `size() == 50`
- **Only live entities are yielded** — Interleave live and expired entries, confirm collection count matches live count
- **No quadratic regression** — Add 5,000 timers, assert total time < 5 seconds (generous threshold for CI)
- **Mixed entity types** — Timers + subscriptions cleaned independently
- **Interleaved add/remove cycles** — Multiple rounds of add and destroy produce correct counts

All tests pass under AddressSanitizer and UndefinedBehaviorSanitizer.

---

## Takeaways

**1. Cleanup doesn't have to happen at insertion time.** The original code cleaned up expired entries on every `add_*` call because it seemed like the right place — "clean up as you go." But when insertion is frequent and expiration is rare, this creates unnecessary work. Moving cleanup to a point where iteration already happens (the executor spin) makes it free.

**2. O(N) per call doesn't mean O(N) total.** Each individual `add_*` call was O(N) — linear in the current size. That sounds fine until you realize N grows with each call. N calls of O(N) each = O(N²). Always think about the total cost across a sequence of operations, not just one.

**3. Profile before guessing.** The reproducer made this obvious — 96% of time in `add_timer()`. Without measurement, you might waste time optimizing the timer callback dispatch or the executor loop.

---

The PR is [ros2/rclcpp#3109](https://github.com/ros2/rclcpp/pull/3109). The fix targets the `rolling` branch.

---

**Related:**
- [Contributing to ROS 2 — A Practical Guide from Four Accepted PRs](/posts/contributing-to-ros2-a-practical-guide/)
- [PX4 Autopilot: A Practitioner's Guide to Troubleshooting, Debugging, Building, and Testing](/posts/px4-autopilot-troubleshooting-debugging-testing-guide/)
