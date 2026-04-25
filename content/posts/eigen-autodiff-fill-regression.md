---
title: How GCC's std::fill_n Silently Regressed Eigen's AutoDiffScalar Performance
date: 2026-03-20
draft: false
tags:
- C++
- Eigen
- GCC
- performance
- open-source
keywords:
- Eigen AutoDiffScalar performance
- Eigen fill regression GCC
- trivially copyable scalar Eigen
cover:
  image: /images/posts/eigen-autodiff.png
  alt: How GCC's fill_n Regressed Eigen's AutoDiffScalar
categories:
- deep-dive
summary: A performance optimization in Eigen's fill path assumed all scalar types
  are equal. GCC's libstdc++ disagreed — and AutoDiffScalar paid the price.
ShowToc: true
audio:
  pronunciation:
    Eigen: Eye gen
    AutoDiffScalar: auto diff scalar
    DerType: der type
    VectorXd: vector X D
    Vector12d: vector twelve D
    eigen_fill_helper: Eigen fill helper
    eigen_memset_helper: Eigen memset helper
    std::fill_n: S T D fill N
    std::is_trivially_copyable: S T D is trivially copyable
    std::true_type: S T D true type
    std::false_type: S T D false type
    std::bool_constant: S T D bool constant
    std::integral_constant: S T D integral constant
    memset: mem set
    setZero: set zero
    setConstant: set constant
    RequireInitialization: require initialization
    GitLab: git lab
    libstdc++: lib S T D C plus plus
---

## The Setup

Eigen's commit [c01ff453](https://gitlab.com/libeigen/eigen/-/commit/c01ff453) (Dec 2024) introduced a `std::fill_n` optimization for filling dense matrices and arrays with a constant value. Instead of Eigen's own coefficient-wise assignment loop, the new code delegated to `std::fill_n` — which, for trivial types like `double` or `int`, compiles down to an optimized `memset`-like loop.

The optimization was gated behind an `eigen_fill_helper` trait that checked whether the expression type *structurally* supported contiguous filling (Matrix, Array, contiguous Block, stride-compatible Map). What it did **not** check was whether the **scalar type** was suitable for `std::fill_n`.

```cpp
// Before: unconditionally enabled for Matrix/Array
template <typename Scalar, int Rows, int Cols, int Options, int MaxRows, int MaxCols>
struct eigen_fill_helper<Matrix<Scalar, Rows, Cols, Options, MaxRows, MaxCols>>
    : std::true_type {};
```

For `Matrix<double, 3, 3>`, this is great. For `Matrix<AutoDiffScalar<Vector12d>, 12, 12>`, it's a regression.

## Why AutoDiffScalar Is Different

`AutoDiffScalar<DerType>` stores a scalar value and a derivatives vector:

```cpp
// unsupported/Eigen/src/AutoDiff/AutoDiffScalar.h
protected:
  Scalar m_value;
  DerType m_derivatives;  // e.g., VectorXd — dynamic allocation
```

Because `DerType` can be a dynamically-allocated Eigen vector, `AutoDiffScalar` requires non-trivial copy/move operations. It is **not trivially copyable** — and `std::is_trivially_copyable<AutoDiffScalar<...>>::value` is `false`.

This matters because GCC's libstdc++ `std::fill_n` has a subtle performance characteristic: for non-trivially-copyable types, it does **not** hoist the fill value out of the loop. Each iteration performs an extra move of the source value. For a type like `AutoDiffScalar<Vector12d>`, that means copying 12 doubles of derivative data on every single iteration — even though the value is the same each time.

Eigen's own `call_dense_assignment_loop` doesn't have this problem. It evaluates the source expression once per coefficient, with no redundant copies.

## The Regression

The result: any code filling a matrix of `AutoDiffScalar` — including common operations like `setZero()`, `setConstant()`, or construction from a constant — got measurably slower after c01ff453. This was reported as [Eigen issue #2956](https://gitlab.com/libeigen/eigen/-/issues/2956).

## The Fix

The fix is a one-line conceptual change: gate `eigen_fill_helper` on `std::is_trivially_copyable<Scalar>` in addition to the structural checks:

```cpp
// After: only enabled when the scalar type is trivially copyable
template <typename Scalar, int Rows, int Cols, int Options, int MaxRows, int MaxCols>
struct eigen_fill_helper<Matrix<Scalar, Rows, Cols, Options, MaxRows, MaxCols>>
    : std::is_trivially_copyable<Scalar> {};
```

When `Scalar` is trivially copyable, `std::is_trivially_copyable<Scalar>` inherits from `std::true_type` — the optimized `std::fill_n` path is taken. When it's not (AutoDiffScalar, custom types with non-trivial copy), it inherits from `std::false_type` — Eigen falls back to its own coefficient-wise loop.

This mirrors what `eigen_memset_helper` (used for `setZero()`) already does:

```cpp
template <typename Xpr>
struct eigen_memset_helper {
  using Scalar = typename Xpr::Scalar;
  static constexpr bool value = std::is_trivially_copyable<Scalar>::value &&
                                !static_cast<bool>(NumTraits<Scalar>::RequireInitialization) &&
                                eigen_fill_helper<Xpr>::value;
};
```

The `memset` path was already safe because it checked `is_trivially_copyable`. The `fill_n` path just needed the same guard.

## The Review Iteration

Getting to the final one-liner took a few iterations, which are instructive:

**Iteration 1: `std::bool_constant`**
The initial implementation used `std::bool_constant<std::is_trivially_copyable<Scalar>::value>`. Clean, but `std::bool_constant` is a C++17 feature — and Eigen supports C++14.

**Iteration 2: `std::integral_constant`**
Switched to `std::integral_constant<bool, std::is_trivially_copyable<Scalar>::value>` for C++14 compatibility. Functionally correct, but verbose.

**Iteration 3: Direct inheritance** (reviewer suggestion)
Charles Schlosser, the author of the original fill optimization, [pointed out](https://gitlab.com/libeigen/eigen/-/merge_requests/2313#note_3177688767) that `std::is_trivially_copyable<T>` already inherits from `std::integral_constant<bool, ...>`. The wrapper is redundant — just inherit directly:

```cpp
: std::is_trivially_copyable<Scalar> {};
```

This is the kind of simplification that's easy to miss if you're thinking about the *value* rather than the *type hierarchy*. `std::is_trivially_copyable<T>` isn't just a compile-time boolean — it's a type that inherits from `std::true_type` or `std::false_type`, which are themselves `std::integral_constant<bool, true/false>`. Since `eigen_fill_helper` inherits from this trait, it gets `::value`, implicit `bool` conversion, and everything else for free.

## What We Learned

**1. `std::fill_n` is not a universal optimization.**
Library implementations make trade-offs. GCC's libstdc++ optimizes `fill_n` for trivially copyable types (it can use `memset` or SIMD). For non-trivially-copyable types, the generic fallback adds per-iteration overhead that a hand-written loop avoids. The lesson: profile before assuming a standard algorithm is faster than your domain-specific implementation.

**2. Type traits compose through inheritance, not just `::value`.**
When you write `struct Foo : std::true_type {}`, `Foo` doesn't just carry a `value` — it *is* a `std::integral_constant<bool, true>`. You can inherit from type traits directly. This is a common pattern in Eigen's trait system and throughout the STL.

**3. Consistency within a codebase catches bugs.**
The `memset` path already had the `is_trivially_copyable` guard. The `fill_n` path didn't. When two code paths have the same preconditions, they should have the same guards. The fix was essentially "make `fill_n` match `memset`."

**4. `std::bool_constant` vs `std::integral_constant<bool, ...>` is a C++ version boundary.**
If your library supports C++14, you can't use `std::bool_constant` (C++17). But you often don't need either — inheriting from the trait directly is both shorter and version-agnostic.

**5. Code review from the original author is invaluable.**
The person who wrote the optimization knows the type hierarchy intimately. Their one-line suggestion eliminated unnecessary indirection and made the intent clearer.

## The MR

[!2313: Guard eigen_fill_helper on trivially copyable scalars](https://gitlab.com/libeigen/eigen/-/merge_requests/2313) — closes [#2956](https://gitlab.com/libeigen/eigen/-/issues/2956).

---

**Related:**
- [Fixing GCC False-Positive Warnings in Eigen](/posts/fixing-gcc-false-positives-in-eigen/)
- [Fixing an Infinite Loop in Eigen's 128-bit Integer Division](/posts/fixing-eigen-uint128-division-infinite-loop/)
