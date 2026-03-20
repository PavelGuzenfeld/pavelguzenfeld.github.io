---
title: "Fixing an Infinite Loop in Eigen's 128-bit Integer Division"
date: 2026-03-20
draft: false
tags: ["C++", "Eigen", "debugging", "open-source", "integer-arithmetic"]
categories: ["deep-dive"]
summary: "How a missing overflow check in Eigen's TensorUInt128 division operator caused an infinite loop for any dividend above 2^127 — and the one-line fix that stopped it."
ShowToc: true
---

## The Problem

While working with Eigen's tensor module, I hit a hang. A division operation on a `TensorUInt128` value never returned. No crash, no error — just a thread burning 100% CPU forever.

The reproducer was simple:

```cpp
TensorUInt128<uint64_t, uint64_t> a(1ULL << 63, 1);  // a value > 2^127
TensorUInt128<uint64_t, uint64_t> b(2);
auto result = a / b;  // hangs forever
```

Any dividend with bit 127 set would trigger it. That includes `UINT128_MAX / 1`, `UINT128_MAX / 3`, and any large tensor index computation that happened to cross the 2^127 boundary.

## Tracing the Bug

Eigen implements `TensorUInt128` as a pair of `uint64_t` values (`high` and `low`) for platforms that lack native 128-bit integer support. The division operator uses binary long division — repeatedly doubling the divisor to find the largest power-of-2 multiple that fits within the dividend, then subtracting downward.

Here's the buggy code:

```cpp
// calculate the biggest power of 2 times rhs that's less than or equal to lhs
TensorUInt128<uint64_t, uint64_t> power2(1);
TensorUInt128<uint64_t, uint64_t> d(rhs);
TensorUInt128<uint64_t, uint64_t> tmp(lhs - d);
while (lhs >= d) {
    tmp = tmp - d;
    d = d + d;
    power2 = power2 + power2;
}
```

The loop doubles `d` each iteration, searching for the point where `d` exceeds `lhs`. The problem: **what happens when `d` is already using the high bit?**

Say `d.high` is `0x8000000000000000` (bit 63 set, meaning the full 128-bit value has bit 127 set). The next `d = d + d` overflows the 128-bit representation. The result wraps around to a small value. Now `lhs >= d` is true again. And again. And again. Forever.

There's no overflow detection. The unsigned addition just wraps, and the loop condition never becomes false.

The `tmp` variable made this harder to spot during code review — it participates in subtractions inside the loop but serves no purpose in the first phase of the algorithm. It's dead computation that obscures the real logic.

## The Fix

One line of overflow detection before the doubling:

```cpp
TensorUInt128<uint64_t, uint64_t> power2(1);
TensorUInt128<uint64_t, uint64_t> d(rhs);
while (lhs >= d) {
    if (d.high >> 63) break;  // next doubling would overflow 128 bits
    d = d + d;
    power2 = power2 + power2;
}
```

If the high bit of `d.high` is already set, the next doubling would overflow. We break out of the loop instead. The second phase of the algorithm — the subtraction loop that walks `power2` and `d` back down via right-shifts — handles this case correctly without any changes.

The dead `tmp` computation in the first loop was also removed. It was computing `lhs - d - d - d - ...` but the result was immediately overwritten after the loop with `tmp = TensorUInt128<uint64_t, uint64_t>(lhs.high, lhs.low)`. Pure waste.

The full diff is minimal:

```diff
     TensorUInt128<uint64_t, uint64_t> power2(1);
     TensorUInt128<uint64_t, uint64_t> d(rhs);
-    TensorUInt128<uint64_t, uint64_t> tmp(lhs - d);
     while (lhs >= d) {
-      tmp = tmp - d;
+      if (d.high >> 63) break;  // next doubling would overflow 128 bits
       d = d + d;
       power2 = power2 + power2;
     }

-    tmp = TensorUInt128<uint64_t, uint64_t>(lhs.high, lhs.low);
+    TensorUInt128<uint64_t, uint64_t> tmp(lhs.high, lhs.low);
```

## Regression Tests

Three cases that cover the boundary:

```cpp
void test_div_overflow() {
  // Regression test for infinite loop when lhs > 2^127 (issue #3012).
  TensorUInt128<uint64_t, uint64_t> a(1ULL << 63, 1);
  TensorUInt128<uint64_t, uint64_t> b(2);
  uint128_t expected = ((static_cast<uint128_t>(1ULL << 63) << 64) + 1) / 2;
  VERIFY_EQUAL(a / b, expected);

  // UINT128_MAX / 1
  TensorUInt128<uint64_t, uint64_t> c(UINT64_MAX, UINT64_MAX);
  TensorUInt128<uint64_t, uint64_t> d(1);
  uint128_t c128 = (static_cast<uint128_t>(UINT64_MAX) << 64) | UINT64_MAX;
  VERIFY_EQUAL(c / d, c128);

  // UINT128_MAX / 3
  TensorUInt128<uint64_t, uint64_t> e(UINT64_MAX, UINT64_MAX);
  TensorUInt128<uint64_t, uint64_t> f(0, 3);
  uint128_t e128 = (static_cast<uint128_t>(UINT64_MAX) << 64) | UINT64_MAX;
  VERIFY_EQUAL(e / f, e128 / 3);
}
```

All seven subtests pass with GCC 15.2.0 under C++20.

## Why This Went Unnoticed

`TensorUInt128` exists as a fallback for platforms without `__int128`. Most x86-64 toolchains provide native 128-bit integers, so this code path is rarely exercised. On platforms that do use it (some embedded targets, MSVC, older compilers), workloads may not have produced dividends above 2^127.

The bug has been present since the division operator was written. It's the kind of defect that lurks for years until someone's tensor dimensions or index computations happen to produce a large enough value.

## Takeaways

1. **Unsigned integer overflow is silent.** There's no trap, no exception, no undefined behavior — the value just wraps. In a loop that doubles a value, this turns a terminating algorithm into an infinite one.

2. **Check overflow *before* it happens, not after.** Testing `d.high >> 63` before `d = d + d` is the only reliable way. After the addition, the evidence of overflow is gone.

3. **Dead code in algorithms obscures bugs.** The unused `tmp` computation in the first loop added visual noise that made the missing overflow check harder to spot during review.

4. **Fallback code paths need the same test coverage as primary ones.** If your codebase has a software implementation behind a hardware-accelerated fast path, the slow path needs its own edge-case tests — especially at numeric boundaries.
