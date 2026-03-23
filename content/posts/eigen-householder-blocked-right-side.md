---
title: "Upgrading Eigen's Householder Right-Side Application from BLAS-2 to BLAS-3"
date: 2026-03-23
draft: false
tags: ["C++", "Eigen", "linear-algebra", "performance", "open-source"]
categories: ["deep-dive"]
summary: "Eigen's blocked Householder path only existed for left-side application. I added the right-side equivalent, upgrading M*Q from O(n) rank-1 updates to cache-friendly blocked matrix multiplies."
ShowToc: true
---

## The Asymmetry

While working on Eigen's Householder module, I noticed something odd. The `HouseholderSequence` class has two paths for applying a sequence of reflectors to a matrix:

```cpp
// Left: H * M  — has a blocked (BLAS-3) path
void applyThisOnTheLeft(Dest& dst, Workspace& workspace) const {
    if (m_length >= BlockSize && dst.cols() > 1) {
        // blocked path using compact WY representation
        ...
    } else {
        // scalar fallback: apply reflectors one at a time
    }
}

// Right: M * H  — scalar only
void applyThisOnTheRight(Dest& dst, Workspace& workspace) const {
    for (Index k = 0; k < m_length; ++k) {
        dst.rightCols(...)
            .applyHouseholderOnTheRight(...);  // one reflector at a time
    }
}
```

The left-side path groups reflectors into panels of 48 and applies them as BLAS-3 matrix-matrix multiplies. The right-side path applies each reflector individually — a rank-1 update, which is a BLAS-2 operation.

This matters because `M * Q` (right-side application) shows up in eigensolvers, Schur decompositions, and any code that needs to apply Q to a matrix from the right.

## The Math

A Householder reflector is `H_k = I - tau_k * v_k * v_k^*`. A sequence of `n` reflectors can be represented in compact WY form as:

```
P = I - V * T * V^*
```

where `V` is unit-lower-triangular (columns are the Householder vectors) and `T` is upper-triangular (built from the `tau` coefficients).

**Left application** is straightforward:

```
P * A = A - V * T * (V^* * A)
```

Eigen already implements this as three matrix-matrix operations: `tmp = V^* * A`, then `tmp = T * tmp`, then `A -= V * tmp`.

**Right application** follows the same pattern:

```
A * P = A - (A * V) * T * V^*
```

Three matrix-matrix operations again: `tmp = A * V`, then `tmp = tmp * T`, then `A -= tmp * V^*`.

The key insight: both directions have the same computational structure and the same BLAS-3 character. There's no mathematical reason the right side should be slower.

## The Implementation

The core function is `apply_block_householder_on_the_right`:

```cpp
template <typename MatrixType, typename VectorsType, typename CoeffsType>
void apply_block_householder_on_the_right(
    MatrixType& mat, const VectorsType& vectors,
    const CoeffsType& hCoeffs, bool forward)
{
    Index nbVecs = vectors.cols();
    Matrix<Scalar, TFactorSize, TFactorSize, RowMajor> T(nbVecs, nbVecs);

    if (forward)
        make_block_householder_triangular_factor(T, vectors, hCoeffs);
    else
        make_block_householder_triangular_factor(T, vectors, hCoeffs.conjugate());

    const TriangularView<const VectorsType, UnitLower> V(vectors);

    // A -= A * V * T * V^*
    auto tmp = mat * V;
    if (forward)
        tmp = (tmp * T.triangularView<Upper>()).eval();
    else
        tmp = (tmp * T.triangularView<Upper>().adjoint()).eval();
    mat.noalias() -= tmp * V.adjoint();
}
```

Then `applyThisOnTheRight` uses it the same way the left side does — iterating over blocks of reflectors:

```cpp
if (m_length >= BlockSize && dst.rows() > 1) {
    Index blockSize = ...;
    for (Index i = 0; i < m_length; i += blockSize) {
        // extract sub-vectors and sub-destination for this block
        auto sub_dst = dst.rightCols(dstCols);
        apply_block_householder_on_the_right(
            sub_dst, sub_vecs, m_coeffs.segment(k, bs), !m_reverse);
    }
}
```

## The Subtle Bug

Getting this right required understanding a non-obvious detail about the blocking direction.

The left-side blocked path iterates blocks in **reverse** order (last block first, working backward). This is because left-multiplication by `H_0 * H_1 * ... * H_{n-1}` applies `H_{n-1}` first to the matrix, then `H_{n-2}`, etc. The blocked version groups these and processes from right to left.

For right-multiplication, `M * H_0 * H_1 * ... * H_{n-1}`, the first reflector applied to `M` is `H_0`, then `H_1`, etc. So the blocks must iterate **forward** — the opposite direction from the left side.

I initially copied the left-side iteration order and spent a while debugging why matrices of size > 48 (the `BlockSize` threshold) produced garbage while smaller ones were fine. The fix was flipping the loop direction:

```cpp
// Left-side loop (backward):
Index end = m_reverse ? min(m_length, i + blockSize) : m_length - i;
Index k = m_reverse ? i : max(0, end - blockSize);

// Right-side loop (forward):
Index end = m_reverse ? m_length - i : min(m_length, i + blockSize);
Index k = m_reverse ? max(0, end - blockSize) : i;
```

## Bonus: Resolving Two FIXMEs

While in `BlockHouseholder.h`, I also resolved two long-standing FIXMEs. The original code had scalar loops working around Eigen's triangular product not supporting in-place operation:

```cpp
// FIXME: use .noalias() once triangular product supports in-place operation.
for (Index j = nbVecs - 1; j > i; --j) {
    typename TriangularFactorType::Scalar z = triFactor(i, j);
    triFactor(i, j) = z * triFactor(j, j);
    if (nbVecs - j - 1 > 0)
        triFactor.row(i).tail(nbVecs-j-1) += z * triFactor.row(j).tail(nbVecs-j-1);
}
```

The workaround is simpler than the FIXME suggests — just call `.eval()` to force evaluation into a temporary before assignment:

```cpp
triFactor.row(i).tail(rt) =
    (triFactor.row(i).tail(rt) *
     triFactor.bottomRightCorner(rt, rt).triangularView<Upper>()).eval();
```

Same fix for the second FIXME in `apply_block_householder_on_the_left`.

## Testing

All 62 tests across the Householder/QR/Schur/Eigensolver test suites pass, including the existing right-side application tests that verify `M * hseq == M * hseq_mat` for random matrices up to 320x320.

The MR is [!2341](https://gitlab.com/libeigen/eigen/-/merge_requests/2341), closing [issue #3057](https://gitlab.com/libeigen/eigen/-/issues/3057).
