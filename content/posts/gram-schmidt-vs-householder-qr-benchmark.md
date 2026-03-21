---
title: "Modified Gram-Schmidt vs Householder QR: A Performance Showdown in Eigen"
date: 2026-03-21
draft: false
tags: ["C++", "Eigen", "linear-algebra", "benchmarking", "open-source"]
categories: ["deep-dive"]
summary: "I submitted a Modified Gram-Schmidt QR decomposition to Eigen and an maintainer asked: why? Here's the benchmark data that answered the question — and ultimately led me to close the MR."
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

You can run a version of this benchmark yourself on Compiler Explorer:

<iframe width="100%" height="600px" src="https://godbolt.org/e/z/bc8x91To9" frameborder="0"></iframe>

Or open it directly: [godbolt.org/z/bc8x91To9](https://godbolt.org/z/bc8x91To9)

### Godbolt Results (Reproducible)

Running the benchmark on Compiler Explorer (GCC 14.2, `-O3 -DNDEBUG`, shared infrastructure) produces these results — absolute times are slower than a dedicated machine, but the **ratios and accuracy numbers are consistent**:

| Case | Size | MGS (μs) | HH (μs) | Ratio | MGS orth | HH orth | MGS rec | HH rec |
|------|------|----------|---------|-------|----------|---------|---------|--------|
| Square | 8×8 | 0.7 | 1.7 | **2.43x** | 1.1e-15 | 1.3e-15 | 1.1e-16 | 3.2e-16 |
| Square | 16×16 | 3.6 | 5.0 | **1.40x** | 2.6e-15 | 1.8e-15 | 1.4e-16 | 3.1e-16 |
| Square | 32×32 | 19.4 | 19.6 | **1.01x** | 7.3e-14 | 3.0e-15 | 1.9e-16 | 4.1e-16 |
| Square | 64×64 | 138.5 | 149.8 | **1.08x** | 2.8e-14 | 6.4e-15 | 2.6e-16 | 6.1e-16 |
| Square | 128×128 | 1131.5 | 753.0 | 0.67x | 4.1e-14 | 1.1e-14 | 3.8e-16 | 7.1e-16 |
| Square | 256×256 | 8676.4 | 4731.5 | 0.55x | 3.4e-13 | 1.7e-14 | 5.3e-16 | 8.1e-16 |
| Tall | 100×10 | 1272.0 | 7.1 | 0.01x | 1.2e-15 | 1.4e-15 | 1.1e-16 | 2.7e-16 |
| Tall | 200×20 | 6246.3 | 41.0 | 0.01x | 1.9e-15 | 2.2e-15 | 1.5e-16 | 3.0e-16 |
| Tall | 500×50 | 108128.9 | 419.4 | 0.00x | 4.7e-15 | 4.9e-15 | 2.3e-16 | 3.9e-16 |

**Ill-Conditioned (64×64):**

| Condition (κ) | MGS orth | HH orth |
|---------------|----------|---------|
| 10⁴ | 6.7e-13 | 5.9e-15 |
| 10⁸ | 3.9e-09 | 6.6e-15 |
| 10¹² | 3.1e-05 | 6.2e-15 |

The crossover on Godbolt happens at 32×32 (ratio ~1.0x) compared to ~64×64 on a dedicated machine — likely due to shared-infrastructure cache effects — but the trend is identical.

## Dedicated Machine Results

The following results were collected on a dedicated machine with `g++ -O3 -march=native -DNDEBUG`:

### Decomposition: Performance & Accuracy (double)

| Test Case | Size | MGS (μs) | HH (μs) | Speedup | MGS ortho err | HH ortho err | MGS recon err | HH recon err |
|-----------|------|----------|---------|---------|---------------|--------------|---------------|--------------|
| Small square | 4×4 | 0.2 | 0.5 | **2.9x** | 5.6e-16 | 4.1e-16 | 8.3e-17 | 1.8e-16 |
| Small square | 8×8 | 0.2 | 1.2 | **5.6x** | 2.2e-15 | 8.2e-16 | 9.5e-17 | 2.2e-16 |
| Small square | 16×16 | 1.1 | 3.1 | **3.0x** | 3.1e-15 | 1.6e-15 | 1.3e-16 | 3.2e-16 |
| Small square | 32×32 | 5.3 | 8.4 | **1.6x** | 5.5e-15 | 3.5e-15 | 2.0e-16 | 4.3e-16 |
| Medium square | 64×64 | 27.6 | 41.0 | **1.5x** | 2.6e-14 | 5.8e-15 | 2.7e-16 | 5.3e-16 |
| Medium square | 128×128 | 217 | 152 | 0.70x | 2.6e-14 | 1.0e-14 | 3.6e-16 | 6.7e-16 |
| Medium square | 256×256 | 1621 | 857 | 0.53x | 2.5e-13 | 1.6e-14 | 5.2e-16 | 7.5e-16 |
| Large square | 512×512 | 13678 | 5500 | 0.40x | 5.5e-13 | 2.3e-14 | 6.9e-16 | 7.8e-16 |
| Large square | 1024×1024 | 113725 | 34911 | 0.31x | 6.7e-11 | 3.6e-14 | 9.4e-16 | 8.6e-16 |

At **n = 128** Householder takes the lead and never looks back. By 1024×1024, it's **3.3x faster**.

### Tall Matrices: Where MGS Falls Apart

| Test Case | Size | MGS (μs) | HH (μs) | Speedup | MGS ortho err | HH ortho err |
|-----------|------|----------|---------|---------|---------------|--------------|
| Tall | 100×10 | 93.8 | 2.5 | 0.03x | 1.2e-15 | 8.1e-16 |
| Tall | 1000×10 | 93924 | 16.4 | 0.0002x | 1.1e-15 | 1.0e-15 |
| Tall | 1000×100 | 90504 | 854 | 0.009x | 4.1e-15 | 4.4e-15 |
| Tall | 500×50 | 10487 | 178 | 0.02x | 2.6e-15 | 3.1e-15 |

For a 1000×10 matrix, Householder is **5700x faster**. This isn't a typo.

The problem: my MGS implementation builds a full m×m Q matrix (1000×1000) and completes the remaining 990 columns by orthogonalizing standard basis vectors. Householder stores Q as 10 compact reflectors and never materializes the full matrix.

Even with a thin-Q optimization, the core BLAS-2 vs BLAS-3 gap would remain for the orthogonalization itself.

### Solve Performance (Ax = b, double)

| Size | MGS (μs) | HH (μs) | Speedup | MGS err | HH err |
|------|----------|---------|---------|---------|--------|
| 8×8 | 0.3 | 1.3 | **4.3x** | 1.3e-15 | 8.6e-16 |
| 16×16 | 1.1 | 3.2 | **2.9x** | 1.0e-15 | 2.2e-15 |
| 64×64 | 26.1 | 42.3 | **1.6x** | 7.2e-15 | 2.4e-15 |
| 128×128 | 166 | 147 | 0.89x | 3.5e-15 | 3.0e-15 |
| 256×256 | 1285 | 739 | 0.57x | 1.3e-14 | 1.4e-14 |
| 512×512 | 11708 | 4363 | 0.37x | 1.3e-14 | 1.1e-14 |

Same crossover at ~128. For small systems, MGS's lower overhead wins. For anything practical at scale, Householder dominates.

### Ill-Conditioned Matrices: The Accuracy Gap

| Condition (κ) | MGS ortho err | HH ortho err | Ratio |
|---------------|---------------|--------------|-------|
| 10⁴ | 5.9e-13 | 5.8e-15 | 100x worse |
| 10⁸ | 3.7e-09 | 6.1e-15 | 600000x worse |
| 10¹² | 3.2e-05 | 6.2e-15 | 5 billion x worse |

This is the killer. Householder's orthogonality error stays at **~10⁻¹⁵** regardless of condition number. MGS degrades proportionally to κ — a well-known theoretical result that the data confirms precisely.

For reconstruction error (‖A − QR‖/‖A‖), both methods are comparable at ~10⁻¹⁶. The factorization is correct in both cases. But if you need Q to actually be orthogonal — for projections, basis computations, or numerical stability in downstream operations — MGS's Q becomes unreliable as condition number grows.

### Single Precision (float)

| Size | MGS (μs) | HH (μs) | Speedup | MGS ortho err | HH ortho err |
|------|----------|---------|---------|---------------|--------------|
| 16×16 | 0.8 | 2.6 | **3.4x** | 6.6e-06 | 7.0e-07 |
| 64×64 | 20.2 | 37.3 | **1.9x** | 2.3e-05 | 3.3e-06 |
| 256×256 | 578 | 429 | 0.74x | 9.9e-05 | 8.8e-06 |
| 512×512 | 5023 | 2295 | 0.46x | 4.3e-04 | 1.3e-05 |

Same pattern. The crossover moves slightly because float has lower arithmetic intensity per element, but BLAS-3 blocking still wins at scale.

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

I closed the MR. The maintenance burden of adding a new QR decomposition to Eigen — documentation, tests, API surface, compatibility across compilers and platforms — isn't justified for a method that only wins on matrices small enough that QR decomposition isn't your bottleneck anyway.

The original [feature request (issue #2495)](https://gitlab.com/libeigen/eigen/-/issues/2495) made compelling arguments about API ergonomics and explicit Q access. Those are real pain points. But the right solution is probably improving the ergonomics of `HouseholderQR` — making Q easier to extract as a dense matrix — rather than adding an algorithmically inferior decomposition.

## Takeaways

1. **Benchmark before you argue.** The theoretical O(2mn²) flop count is the same for both algorithms. The difference is entirely in constants — cache behavior, BLAS level, and implementation overhead. Theory said "comparable"; data said "not even close at scale."

2. **BLAS-3 blocking is not optional at scale.** Any algorithm that processes one column at a time (BLAS-2) will lose to one that processes panels of columns together (BLAS-3) once matrices exceed cache size. This applies far beyond QR — it's why blocked LU, blocked Cholesky, and tiled algorithms dominate modern numerical linear algebra.

3. **Orthogonality matters more than reconstruction error.** Both algorithms reconstruct A = QR to machine precision. But MGS's Q drifts from orthogonal as condition number grows. If you're using Q for anything beyond reconstructing A — projections, basis extraction, iterative refinement — that drift compounds.

4. **Don't fight the maintainer.** When someone who's spent years optimizing a numerical library tells you your algorithm is slower, they're probably right. The benchmark confirmed it, and the conversation was better for having data behind it.

5. **Know your niche.** Small-matrix MGS QR is legitimately faster. If I were building a robotics system that decomposes hundreds of thousands of 6×6 matrices per second, MGS would be the right choice. But that's not what Eigen's `QR` module is for — it serves the general case, and the general case is Householder.
