---
title: "Fixing GCC False-Positive Warnings in Eigen: A Deep Dive into -Warray-bounds at -O3"
date: 2026-03-18
draft: false
tags: ["C++", "Eigen", "GCC", "compilers", "open-source"]
keywords: ["GCC Warray-bounds false positive", "Eigen GCC 13 warning", "suppress compiler warning Eigen"]
cover:
  image: /images/posts/gcc-eigen.png
  alt: "Fixing GCC False-Positive Warnings in Eigen"
categories: ["deep-dive"]
summary: "How a GCC 13 false-positive -Warray-bounds warning in Eigen's TensorContraction led to a lesson about if constexpr, C++14 portability, and the right way to suppress compiler warnings in a large codebase."
ShowToc: true
---

## The Warning

While building a project that depends on [Eigen](https://gitlab.com/libeigen/eigen) with GCC 13 at `-O3 -Warray-bounds -Werror`, the build failed with:

```
error: array subscript 1 is outside array bounds of
  'Eigen::DSizes<long, 1>' [-Werror=array-bounds]
```

The warning pointed to `TensorContraction.h`, deep in Eigen's tensor module. The code looked like this:

```cpp
if (nocontract_idx + 1 < internal::array_size<left_nocontract_t>::value) {
    m_i_strides[nocontract_idx + 1] = m_i_strides[nocontract_idx] * eval_left_dims[i];
} else {
    m_i_size = m_i_strides[nocontract_idx] * eval_left_dims[i];
}
```

When `left_nocontract_t` is `DSizes<long, 1>` (a fixed-size array of length 1), GCC's value range analysis at `-O3` determines that `nocontract_idx + 1` could be `1` — which is out of bounds for a size-1 array. The runtime condition `nocontract_idx + 1 < 1` is always false, so the branch is dead code. But GCC still warns about the *potential* access.

This pattern appeared three times in the same function, for `m_i_strides`, `m_j_strides`, and `m_k_strides`.

## First Attempt: `if constexpr`

The initial fix wrapped each block with `EIGEN_IF_CONSTEXPR`:

```cpp
EIGEN_IF_CONSTEXPR(internal::array_size<left_nocontract_t>::value > 1) {
    if (nocontract_idx + 1 < internal::array_size<left_nocontract_t>::value) {
        m_i_strides[nocontract_idx + 1] = ...;
    } else {
        m_i_size = ...;
    }
} else {
    m_i_size = ...;
}
```

The idea: when the array size is 1, `if constexpr` discards the inner branch entirely at compile time, so GCC never sees the `[nocontract_idx + 1]` access. The outer `else` handles the size-1 case.

This worked in C++17. The MR passed CI.

## The Review Comment That Changed Everything

Rasmus Munk Larsen, an Eigen maintainer, [pointed out](https://gitlab.com/libeigen/eigen/-/merge_requests/2311#note_3171885117):

> As is, this only fixes the warning for c++17 or newer, but not for c++14, since `EIGEN_IF_CONSTEXPR` evaluates to regular `if` in c++14.

He was right. Here's how `EIGEN_IF_CONSTEXPR` is defined in Eigen:

```cpp
// C++17+
#define EIGEN_IF_CONSTEXPR(X) if constexpr (X)

// C++14
#define EIGEN_IF_CONSTEXPR(X) if (X)
```

In C++14, `if constexpr` doesn't exist. The macro falls back to a regular `if`. Both branches are compiled. GCC still sees the array access in the dead branch and still warns.

## Why This Matters

Eigen supports C++14 through C++23. Many embedded and robotics toolchains still target C++14. A fix that only works in C++17+ leaves a significant portion of users with a broken `-Werror` build.

This is a broader pattern worth understanding: **`if constexpr` is not just syntactic sugar for `if` with a constant condition.** They have fundamentally different semantics:

| | `if (constant)` | `if constexpr (constant)` |
|---|---|---|
| Dead branch compiled? | Yes | No |
| Dead branch type-checked? | Yes | No |
| Template instantiation in dead branch? | Yes | No |
| Compiler warnings from dead branch? | Yes | No |

GCC's `-Warray-bounds` at `-O3` is particularly aggressive because it uses interprocedural value range propagation. It can determine that a loop variable will reach a specific value, then warns about array accesses with that value — even inside branches guarded by runtime checks that prevent the access.

## The Fix: Diagnostic Pragmas

Eigen already has portable diagnostic macros:

```cpp
// GCC/Clang
#define EIGEN_DIAGNOSTICS(tokens)     _Pragma(#tokens)
#define EIGEN_DIAGNOSTICS_OFF(msc, gcc) EIGEN_DIAGNOSTICS(gcc)

// MSVC
#define EIGEN_DIAGNOSTICS(tokens)     __pragma(tokens)
#define EIGEN_DIAGNOSTICS_OFF(msc, gcc) EIGEN_DIAGNOSTICS(msc)
```

The fix became:

```cpp
EIGEN_DIAGNOSTICS(push)
EIGEN_DIAGNOSTICS_OFF(disable : 4789, ignored "-Warray-bounds")
if (nocontract_idx + 1 < internal::array_size<left_nocontract_t>::value) {
    m_i_strides[nocontract_idx + 1] = m_i_strides[nocontract_idx] * eval_left_dims[i];
} else {
    m_i_size = m_i_strides[nocontract_idx] * eval_left_dims[i];
}
EIGEN_DIAGNOSTICS(pop)
```

Combined with value-initialization of the stride arrays (`m_i_strides{}` instead of `m_i_strides`), this provides defense in depth:
- **Value-initialization** ensures the array contains zeros even if the dead branch were somehow reached — no uninitialized memory reads
- **Diagnostic pragmas** suppress the false-positive warning precisely where it occurs
- **Works in C++14, C++17, and C++23** — no dependency on language-version-specific features

## Verifying the Fix

Tested in a Docker container with GCC 13 under both C++ standards:

```bash
# C++17 (default)
cmake -DCMAKE_CXX_FLAGS="-O3 -Warray-bounds -Werror" ..
ninja cxx11_tensor_contraction  # 16/16 compiled, 0 warnings
ctest -R cxx11_tensor_contraction  # 8/8 passed

# C++14 (the case the reviewer flagged)
cmake -DCMAKE_CXX_STANDARD=14 -DCMAKE_CXX_FLAGS="-O3 -Warray-bounds -Werror" ..
ninja cxx11_tensor_contraction  # 16/16 compiled, 0 warnings
ctest -R cxx11_tensor_contraction  # 8/8 passed
```

## Takeaways

1. **`if constexpr` is not a drop-in replacement for `if` when you need to hide code from the compiler.** If your project supports C++14, `if constexpr` wrapped in a compatibility macro gives you zero benefit for warning suppression.

2. **Diagnostic pragmas are the right tool for false-positive warnings.** They're explicit ("we know this is a false positive"), scoped (push/pop), and standard-agnostic. Prefer them over restructuring code to work around compiler analysis limitations.

3. **GCC's `-Warray-bounds` at `-O3` is aggressive by design.** The interprocedural value range propagation that makes `-O3` fast also makes it see "possible" array accesses that runtime checks prevent. This is a known category of false positives — [GCC bug 56456](https://gcc.gnu.org/bugzilla/show_bug.cgi?id=56456) has tracked this since 2013.

4. **Value-initialization (`{}`) is cheap defense in depth.** Zero-initializing a few `Index` values costs nothing at runtime but prevents uninitialized reads if assumptions ever break.

5. **Review comments from maintainers are gold.** The initial fix looked correct, passed CI, and solved the immediate problem. The reviewer's one-line comment about C++14 led to a fundamentally better solution.

---

**Related:**
- [How GCC's std::fill_n Silently Regressed Eigen's AutoDiffScalar Performance](/posts/eigen-autodiff-fill-regression/)
- [Fixing an Infinite Loop in Eigen's 128-bit Integer Division](/posts/fixing-eigen-uint128-division-infinite-loop/)
