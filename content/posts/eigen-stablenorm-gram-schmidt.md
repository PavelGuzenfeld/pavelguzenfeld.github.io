---
title: "Why You Should Use stableNorm() Instead of norm(): A Lesson from Eigen Code Review"
date: 2026-03-27
draft: false
tags: ["C++", "Eigen", "linear-algebra", "numerical-stability", "open-source"]
categories: ["deep-dive"]
summary: "A one-word review comment on my Eigen MR revealed that hand-rolling normalization with .norm() silently breaks on extreme inputs. Eigen already had the fix — I just wasn't using it."
ShowToc: true
---

## The Review Comment

I was iterating on [MR !2337](https://gitlab.com/libeigen/eigen/-/merge_requests/2337) — a Modified Gram-Schmidt QR decomposition for Eigen — when a reviewer left a one-word comment on line 137 of my implementation:

> `stableNorm`?

That's it. One word. Pointing at this line:

```cpp
RealScalar norm = work.col(i).norm();
```

My first reaction was: what's wrong with `.norm()`? It computes the Euclidean norm. That's exactly what I need. The code works, the tests pass, the benchmarks are clean.

But the reviewer was right, and the fix exposed a broader lesson about reaching for library primitives instead of hand-rolling computations.

## What .norm() Actually Does

Eigen's `.norm()` computes `sqrt(v.squaredNorm())`, which is `sqrt(sum of x_i^2)`. For a vector with entries of moderate magnitude, this is fine. But consider what happens at the extremes.

**Overflow:** If any entry is larger than ~1.3×10^154 (for `double`), squaring it produces `inf`. The sum is `inf`. The sqrt is `inf`. Your norm is gone, and everything downstream — the normalized column, the R factor, the reconstruction — is poisoned.

**Underflow:** If all entries are smaller than ~1.5×10^-162, squaring them produces `0.0`. The sum is `0.0`. The sqrt is `0.0`. Your algorithm thinks the column is zero and discards it.

Neither case produces an error or a warning. The computation completes, the result is wrong, and if you're not checking for `nan`/`inf` in your output, you'll never notice.

## What .stableNorm() Does Differently

Eigen's `stableNorm()` uses a scaled summation algorithm (based on Blue's norm). Instead of computing `sqrt(sum(x_i^2))` directly, it tracks a scale factor and accumulates `(x_i / scale)^2`, adjusting the scale as needed to keep intermediate values in a safe range. The final result is `scale * sqrt(sum)`.

This prevents both overflow and underflow at the cost of a few extra comparisons per element. For normal-magnitude inputs, it produces the same result as `.norm()` to within a ULP or two.

## The Evidence

I wrote a comparison test that runs both `.norm()` and `.stableNorm()` through the MGS algorithm on a range of inputs. For each test, I measured reconstruction error (‖A − QR‖/‖A‖) and orthogonality (‖Q^TQ − I‖).

### Normal Inputs: Identical Results

| Matrix | `.norm()` recon | `.stableNorm()` recon | `.norm()` orth | `.stableNorm()` orth |
|--------|-----------------|----------------------|----------------|---------------------|
| Random 8×8 | 1.1e-16 | 1.1e-16 | 1.1e-15 | 1.5e-15 |
| Tall 12×4 | 5.8e-17 | 5.1e-17 | 1.1e-15 | 1.7e-15 |
| Well-conditioned 6×6 | 1.8e-17 | 9.8e-18 | 5.3e-16 | 5.8e-16 |
| Float large (~1e18) | 4.3e-08 | 4.9e-08 | 5.6e-07 | 7.7e-07 |
| Float tiny (~1e-18) | 4.8e-08 | 4.7e-08 | 6.7e-07 | 6.7e-07 |

All within noise of each other. Switching to `stableNorm()` changes nothing for well-behaved inputs.

### The Breaking Case: One Extreme Column

| Metric | `.norm()` | `.stableNorm()` |
|--------|-----------|-----------------|
| Reconstruction error | **`nan`** | 4.1e-17 |
| Orthogonality | **1.0** (completely broken) | 1.7e-15 (machine precision) |

A single column scaled to 1e300 in a 6×6 matrix. `.norm()` overflows on that column, producing `inf` for R(i,i), which propagates `nan` through the normalized Q column. Every subsequent column's orthogonalization against that poisoned column produces garbage. The entire decomposition is silently destroyed.

`.stableNorm()` handles it correctly. The Q factor is orthogonal to machine precision, the reconstruction is exact, and the R factor has the right diagonal entries.

## The Fix

Two lines:

```diff
-      RealScalar norm = work.col(i).norm();
+      RealScalar norm = work.col(i).stableNorm();
```

```diff
-        RealScalar norm = qcol.norm();
+        RealScalar norm = qcol.stableNorm();
```

The first is in the main MGS loop where each column is normalized. The second is in the Q-completion loop where additional basis vectors are orthogonalized for tall matrices.

## The Broader Lesson

This is a specific instance of a general pattern: **the library you're contributing to has already solved your sub-problems — use those solutions instead of reimplementing them**.

I wrote `work.col(i).norm()` because it's the obvious, textbook-correct computation. The MGS algorithm says "compute the norm," so I computed the norm. But Eigen's developers have spent years building numerically robust primitives for exactly this kind of operation. `stableNorm()` exists because someone hit the overflow/underflow problem before and solved it properly.

This applies beyond norms:

- **Don't write `a/b` when you need a safe division.** Check for zero, or use the library's solver that handles rank deficiency.
- **Don't write `sqrt(x*x + y*y)` when you need a hypotenuse.** Use `std::hypot(x, y)` — it handles overflow the same way `stableNorm` does.
- **Don't write `log(1 + x)` for small x.** Use `std::log1p(x)` — it avoids catastrophic cancellation.
- **Don't write manual loops over matrix elements** when Eigen has a vectorized expression that does the same thing with SIMD and aliasing guarantees.

The pattern is always the same: the naive implementation is correct for 99% of inputs, and the library primitive handles the remaining 1% that will bite you in production with no warning.

## Why It's Easy to Miss

I had comprehensive tests — random matrices, tall matrices, wide matrices, ill-conditioned matrices, float and double. Everything passed. The problem only appears with entries near the overflow/underflow boundary of the floating-point format, which random matrices with entries in [-1, 1] will never hit.

This is the insidious part: the bug is invisible to standard testing. You have to specifically construct adversarial inputs, or know from experience (or from a reviewer's one-word comment) that the naive computation is fragile at extremes.

Code review caught what tests didn't. That single `stableNorm?` comment saved a future user from a silent numerical failure that no test in the suite would have flagged.

## Takeaways

1. **Use the library's robust primitives.** If the library provides `stableNorm()`, `hypot()`, `log1p()`, or any "safe" variant of a standard computation, prefer it. The performance cost is negligible; the correctness gain is not.

2. **Adversarial inputs reveal what random tests miss.** Standard test matrices have entries of order 1. Real-world data can have entries of order 10^300 (accumulated products, poorly scaled physical units, recursive computations). Test the extremes explicitly.

3. **One-word review comments can be the most valuable.** The reviewer didn't explain the problem — they just named the solution. That brevity reflects deep familiarity with the failure mode. When an experienced contributor drops a single-word hint, investigate it thoroughly.

4. **"It works" is not the same as "it's correct."** My implementation produced correct results for every test I wrote. It was still wrong, because correctness means handling the full domain of inputs, not just the ones you thought to test.

---

**Related:**
- [Modified Gram-Schmidt vs Householder QR: A Performance Showdown in Eigen](/posts/gram-schmidt-vs-householder-qr-benchmark/)
- [Upgrading Eigen's Householder Right-Side Application from BLAS-2 to BLAS-3](/posts/eigen-householder-blocked-right-side/)
