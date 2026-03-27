---
title: "Modified Gram-Schmidt vs Householder QR: A Performance Showdown in Eigen"
date: 2026-03-21
draft: false
tags: ["C++", "Eigen", "linear-algebra", "benchmarking", "open-source"]
keywords: ["Gram Schmidt vs Householder benchmark", "Modified Gram Schmidt QR", "Eigen QR decomposition comparison"]
cover:
  image: /images/posts/gram-schmidt-qr.png
  alt: "Modified Gram-Schmidt vs Householder QR"
categories: ["deep-dive"]
summary: "I submitted a Modified Gram-Schmidt QR decomposition to Eigen and a maintainer asked: why? Here's the benchmark data that answered the question."
ShowToc: true
---

## The Question

I submitted [MR !2337](https://gitlab.com/libeigen/eigen/-/merge_requests/2337) to [Eigen](https://gitlab.com/libeigen/eigen), adding a `GramSchmidtQR` class that implements Modified Gram-Schmidt (MGS) QR decomposition. The implementation stores Q and R as explicit dense matrices, unlike Eigen's `HouseholderQR` which stores Q as a compact sequence of Householder reflectors.

Within minutes, [Rasmus Munk Larsen](https://gitlab.com/rmlarsen1) — an Eigen maintainer — asked:

> What is the motivation for adding this? MGS QR is generally slower and no more accurate than blocked Householder QR.

Fair question. Instead of arguing from theory, I wrote a benchmark.

## The Algorithms

**Householder QR** works by applying a sequence of orthogonal reflections (Householder transformations) to zero out sub-diagonal entries column by column. Eigen's implementation uses *blocked* Householder reflectors — it groups reflectors into panels and applies them as BLAS-3 (matrix-matrix) operations. Q is stored implicitly as a product of reflectors.

**Modified Gram-Schmidt (MGS)** orthogonalizes columns one at a time: for each column, project out components along all previously computed orthonormal vectors, then normalize. Q and R are stored as explicit dense matrices. This is inherently a BLAS-2 (matrix-vector) algorithm — each column requires dot products and axpy operations against all previous columns.

The key difference: **blocked Householder exploits cache-friendly BLAS-3 operations** that modern CPUs execute extremely efficiently. MGS is limited to BLAS-2 operations that have lower arithmetic intensity.

## The Implementation

The `GramSchmidtQR` class I submitted:

```cpp
template <typename InputType>
GramSchmidtQR& compute(const EigenBase<InputType>& matrix) {
    const Index rows = matrix.rows();
    const Index cols = matrix.cols();
    const Index size = (std::min)(rows, cols);

    m_q.resize(rows, rows);
    m_r.resize(rows, cols);
    m_r.setZero();

    MatrixType work = matrix.derived();

    for (Index i = 0; i < size; ++i) {
        // Orthogonalize column i against all previous columns
        for (Index j = 0; j < i; ++j) {
            Scalar rji = m_q.col(j).dot(work.col(i));
            m_r(j, i) = rji;
            work.col(i) -= rji * m_q.col(j);
        }
        // Normalize
        RealScalar norm = work.col(i).norm();
        m_r(i, i) = norm;
        if (norm > RealScalar(0))
            m_q.col(i) = work.col(i) / norm;
        else
            m_q.col(i).setZero();
    }

    // Complete Q to full orthonormal basis for tall matrices...
    // (omitted for brevity)
}
```

Simple, readable, correct. But fast?

## The Benchmark

I compared MGS against `HouseholderQR` across:
- **Square matrices:** 4×4 to 1024×1024
- **Tall matrices:** 100×10 to 1000×100 (overdetermined systems)
- **Wide matrices:** 10×100 to 50×500 (underdetermined)
- **Ill-conditioned matrices:** condition numbers from 10⁴ to 10¹²
- **Both double and float precision**

Compiled with `g++ -O3 -march=native -DNDEBUG`.

Try it yourself on Compiler Explorer — click the play button to run:

<iframe width="100%" height="800px" src="https://godbolt.org/z/YE537ec18" frameborder="0" allowfullscreen></iframe>

Or open it directly: [godbolt.org/z/YE537ec18](https://godbolt.org/z/YE537ec18)

## Results

All results below are from a dedicated machine (`g++ -O3 -march=native -DNDEBUG`, double precision). The Godbolt link above reproduces the same ratios on shared infrastructure.

### Performance: Speed

| Size | MGS (μs) | HH (μs) | Ratio | Winner |
|------|----------|---------|-------|--------|
| 4×4 | 0.2 | 0.5 | **2.9x** | MGS |
| 8×8 | 0.2 | 1.2 | **5.6x** | MGS |
| 16×16 | 1.1 | 3.1 | **3.0x** | MGS |
| 32×32 | 5.3 | 8.4 | **1.6x** | MGS |
| 64×64 | 27.6 | 41.0 | **1.5x** | MGS |
| 128×128 | 217 | 152 | 0.70x | HH |
| 256×256 | 1621 | 857 | 0.53x | HH |
| 512×512 | 13678 | 5500 | 0.40x | HH |
| 1024×1024 | 113725 | 34911 | 0.31x | HH |

**Ratio** = HH_time / MGS_time. Values > 1 mean MGS is faster.

At **n = 128** Householder takes the lead and never looks back. By 1024×1024, it's **3.3x faster**. The solve benchmark shows the same crossover — MGS is 4.3x faster at 8×8 but 2.7x slower at 512×512.

### Performance: Tall Matrices

This is where MGS falls apart:

| Size | MGS (μs) | HH (μs) | Ratio |
|------|----------|---------|-------|
| 100×10 | 93.8 | 2.5 | 0.03x |
| 500×50 | 10487 | 178 | 0.02x |
| 1000×10 | 93924 | 16.4 | **0.0002x** |
| 1000×100 | 90504 | 854 | 0.009x |

For a 1000×10 matrix, Householder is **5700x faster**. This isn't a typo.

The problem: my MGS implementation builds a full m×m Q matrix (1000×1000) and completes the remaining 990 columns by orthogonalizing standard basis vectors. Householder stores Q as 10 compact reflectors and never materializes the full matrix. Even with a thin-Q optimization, the core BLAS-2 vs BLAS-3 gap would remain.

### Accuracy: Orthogonality Under Ill-Conditioning

Both algorithms reconstruct A = QR to machine precision (~10⁻¹⁶). The real difference is **orthogonality of Q** — how close Q^T Q is to the identity:

| Condition (κ) | MGS ‖Q^TQ − I‖ | HH ‖Q^TQ − I‖ | MGS degradation |
|---------------|-----------------|----------------|-----------------|
| Well-conditioned | 2.6e-14 | 5.8e-15 | ~5x worse |
| 10⁴ | 5.9e-13 | 5.8e-15 | 100x worse |
| 10⁸ | 3.7e-09 | 6.1e-15 | 600,000x worse |
| 10¹² | **3.2e-05** | 6.2e-15 | 5 billion x worse |

This is the killer. Householder's orthogonality stays at **~10⁻¹⁵** regardless of condition number. MGS degrades as O(κ · ε) — a well-known theoretical result the data confirms precisely. If you need Q to actually be orthogonal — for projections, basis computations, or numerical stability downstream — MGS becomes unreliable as κ grows. The same pattern holds for single-precision float, with an even earlier onset of degradation.

## Why MGS Loses

Three fundamental factors:

**1. BLAS-2 vs BLAS-3.** MGS processes one column at a time with dot products and rank-1 updates (BLAS-2). Blocked Householder groups reflectors into panels and applies them with matrix-matrix multiplications (BLAS-3). On modern CPUs with deep cache hierarchies, BLAS-3 achieves much higher throughput because it reuses data in cache. The gap grows with matrix size — exactly what we see.

**2. Full Q materialization.** My implementation stores Q as a dense m×m matrix. For tall matrices, this means computing and storing columns that may never be needed. Householder stores Q as min(m,n) compact reflectors and only materializes columns on demand.

**3. Orthogonality loss.** MGS's orthogonality error grows as O(κ · ε), where κ is the condition number and ε is machine precision. Householder achieves O(ε) regardless of κ. This is a fundamental algorithmic property, not an implementation deficiency.

## Where MGS Wins

For completeness, there *is* a niche:

- **Small matrices (n ≤ 64):** 1.5–5.6x faster due to lower overhead. No reflector storage machinery, no blocked panel application — just straightforward dot products and column updates.
- **Explicit Q/R output:** `matrixQ()` returns a plain `MatrixXd`, not a `HouseholderSequence`. If you need Q as an actual matrix for subsequent `Q * B` or `Q.transpose() * C` operations, MGS gives you that directly. With Householder, you'd evaluate the implicit Q into a dense matrix anyway — adding a separate step.
- **Small system solves:** 1.6–4.3x faster for n ≤ 64 when you need both decomposition and solve.

But this niche is narrow. Most real-world QR use cases involve matrices larger than 64×64, or ill-conditioned systems, or tall overdetermined systems — all cases where Householder is strictly superior.

## The Decision

I initially closed the MR, reasoning that the maintenance burden wasn't justified for a method that only wins on small matrices. But then Rasmus Munk Larsen — the Eigen maintainer who originally challenged the MR — reviewed the benchmark data and commented:

> Thanks for the careful investigation.

And:

> I don't think supporting both APIs is a problem. MGS does have its uses as you point out.

He then **reopened the MR** for further review. The benchmark data made the case: MGS has a legitimate niche for small matrices and explicit Q access. The original [feature request (issue #2495)](https://gitlab.com/libeigen/eigen/-/issues/2495) made compelling arguments about API ergonomics, and the data showed the tradeoffs clearly enough for the maintainer to reconsider.

## Takeaways

1. **Benchmark before you argue.** The theoretical O(2mn²) flop count is the same for both algorithms. The difference is entirely in constants — cache behavior, BLAS level, and implementation overhead. Theory said "comparable"; data said "not even close at scale."

2. **BLAS-3 blocking is not optional at scale.** Any algorithm that processes one column at a time (BLAS-2) will lose to one that processes panels of columns together (BLAS-3) once matrices exceed cache size. This applies far beyond QR — it's why blocked LU, blocked Cholesky, and tiled algorithms dominate modern numerical linear algebra.

3. **Orthogonality matters more than reconstruction error.** Both algorithms reconstruct A = QR to machine precision. But MGS's Q drifts from orthogonal as condition number grows. If you're using Q for anything beyond reconstructing A — projections, basis extraction, iterative refinement — that drift compounds.

4. **Let the data speak.** When a maintainer challenges your approach, respond with benchmarks, not arguments. The data confirmed MGS is slower at scale — but also showed where it wins. That honest assessment is what ultimately got the MR reopened.

5. **Know your niche.** Small-matrix MGS QR is legitimately faster. If I were building a robotics system that decomposes hundreds of thousands of 6×6 matrices per second, MGS would be the right choice. But that's not what Eigen's `QR` module is for — it serves the general case, and the general case is Householder.

---

**Related:**
- [Upgrading Eigen's Householder Right-Side Application from BLAS-2 to BLAS-3](/posts/eigen-householder-blocked-right-side/)
- [Why You Should Use stableNorm() Instead of norm()](/posts/eigen-stablenorm-gram-schmidt/)
