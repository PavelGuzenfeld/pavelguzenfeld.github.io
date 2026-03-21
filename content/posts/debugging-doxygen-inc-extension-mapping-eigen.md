---
title: "Debugging Doxygen: How .inc Files Silently Break C++ Documentation"
date: 2026-03-21
draft: false
tags: ["C++", "Eigen", "Doxygen", "debugging", "documentation", "open-source", "Docker"]
categories: ["deep-dive"]
summary: "Eigen's .inc plugin headers were read by Doxygen but never preprocessed as C++ — meaning macros like EIGEN_PARSED_BY_DOXYGEN were silently ignored. Here's how I verified it in Docker and what the one-line fix looks like."
ShowToc: true
---

## The Symptom

Eigen's official documentation has blind spots. Methods like `middleCols`, `topRightCorner`, `unaryExpr`, and `binaryExpr` are defined in `.inc` plugin headers — files that get `#include`d into `DenseBase.h`, `MatrixBase.h`, and `ArrayBase.h`. Searching for them on [eigen.tuxfamily.org](https://eigen.tuxfamily.org/dox/) works, but the source file references point to `.inc` files that Doxygen doesn't fully understand.

Two long-standing issues tracked this:
- [Issue #1978](https://gitlab.com/libeigen/eigen/-/issues/1978): Official documentation missing `*naryExpr` documentation
- [Issue #2024](https://gitlab.com/libeigen/eigen/-/issues/2024): Block operations not documented on the website

The question was: **why?** The `.inc` files exist in the source tree. Doxygen's `FILE_PATTERNS = *` picks up everything. The methods show up in DenseBase's member list. What's actually broken?

## The Architecture: How .inc Plugin Files Work

Eigen uses a plugin pattern for injecting methods into base classes. Rather than putting hundreds of methods directly in `DenseBase.h`, they're split into purpose-specific `.inc` files:

```
Eigen/src/plugins/
├── BlockMethods.inc          # middleCols, topRows, bottomLeftCorner, ...
├── CommonCwiseUnaryOps.inc   # unaryExpr, unaryViewExpr, cast, ...
├── CommonCwiseBinaryOps.inc  # binaryExpr, cwiseProduct, ...
├── ArrayCwiseBinaryOps.inc   # operator*, operator/, min, max, ...
├── ArrayCwiseUnaryOps.inc    # abs, sqrt, exp, log, ...
├── MatrixCwiseBinaryOps.inc  # cwiseProduct (matrix-specific), ...
├── MatrixCwiseUnaryOps.inc   # cwiseAbs, cwiseInverse, ...
├── IndexedViewMethods.inc    # operator(), indexed views
├── ReshapedMethods.inc       # reshaped views
└── InternalHeaderCheck.inc   # include guard validation
```

These are included via the C preprocessor inside class bodies:

```cpp
// In DenseBase.h
template<typename Derived>
class DenseBase : public EigenBase<Derived> {
    // ...
    #include "../plugins/CommonCwiseUnaryOps.inc"
    #include "../plugins/CommonCwiseBinaryOps.inc"
    #include "../plugins/BlockMethods.inc"
    // ...
};
```

This is a common C++ pattern — the `.inc` extension signals "this file is meant to be included, not compiled standalone." But it creates an interesting problem for Doxygen.

## The Doxyfile Configuration

Here's what Eigen's `Doxyfile.in` looked like before the fix:

```
EXTENSION_MAPPING      = .h=C++ \
                         no_extension=C++
FILE_PATTERNS          = *
MACRO_EXPANSION        = YES
EXPAND_ONLY_PREDEF     = YES
PREDEFINED             = EIGEN_PARSED_BY_DOXYGEN \
                         EIGEN_DEVICE_FUNC= \
                         ...
```

Notice what's missing: there's no `.inc=C++` in `EXTENSION_MAPPING`.

Doxygen picks up `.inc` files because `FILE_PATTERNS = *` matches everything. But without a mapping, Doxygen doesn't know these are C++ files. This is where things get subtle.

## What Doxygen Actually Does Without the Mapping

I needed to understand the difference empirically. Doxygen's processing pipeline has three distinct phases for each file:

1. **Reading** — loading the file into memory
2. **Preprocessing** — expanding macros, evaluating `#ifdef` blocks (only for files recognized as C/C++)
3. **Parsing** — extracting documentation structure (classes, functions, comments)

Without `.inc=C++`, Doxygen **reads** and **parses** the `.inc` files, but **skips preprocessing**. This means:

- `EIGEN_PARSED_BY_DOXYGEN` is never defined when processing `.inc` files standalone
- `EIGEN_DEVICE_FUNC=` never expands to empty
- `EIGEN_STRONG_INLINE=inline` never applies
- Any `#ifdef EIGEN_PARSED_BY_DOXYGEN` blocks in `.inc` files are silently skipped

The methods still appear in the documentation because DenseBase.h `#include`s the `.inc` files, and DenseBase.h *is* recognized as C++. But when Doxygen encounters the `.inc` files as standalone entries in the file list, it treats them as plain text.

## Verifying in Docker

Speculation isn't proof. I built a Docker container to run Doxygen twice — once without the mapping (master behavior) and once with `.inc=C++` — then compared the outputs.

### The Setup

```dockerfile
FROM ubuntu:24.04
RUN apt-get update && apt-get install -y --no-install-recommends doxygen
WORKDIR /eigen
COPY . /eigen/
```

The verification script creates a standalone Doxyfile from Eigen's template (substituting CMake variables), runs Doxygen in both modes, and diffs the results.

### The Smoking Gun: Processing Logs

This is where the difference became undeniable.

**Without `.inc=C++`** — Doxygen reads the files but does not preprocess them:

```
Reading /eigen/Eigen/src/plugins/BlockMethods.inc...
Reading /eigen/Eigen/src/plugins/CommonCwiseUnaryOps.inc...
Reading /eigen/Eigen/src/plugins/CommonCwiseBinaryOps.inc...
Parsing file /eigen/Eigen/src/plugins/CommonCwiseBinaryOps.inc...
```

**With `.inc=C++`** — Doxygen preprocesses the files as C++ before parsing:

```
Preprocessing /eigen/Eigen/src/plugins/BlockMethods.inc...
Preprocessing /eigen/Eigen/src/plugins/CommonCwiseUnaryOps.inc...
Preprocessing /eigen/Eigen/src/plugins/CommonCwiseBinaryOps.inc...
Parsing file /eigen/Eigen/src/plugins/CommonCwiseBinaryOps.inc...
```

The word **"Preprocessing"** vs **"Reading"** is the entire story. Without the mapping, Doxygen's C preprocessor never runs on these files. Macros defined in `PREDEFINED` — the ones that control what Doxygen sees — are simply never applied.

### Quantitative Comparison

| Metric | Without `.inc=C++` | With `.inc=C++` | Delta |
|--------|-------------------|-----------------|-------|
| Total HTML pages | 1,034 | 1,041 | +7 |
| Search index entries | 2,296 | 2,325 | +29 |
| DenseBase member links | 479 | 479 | 0 |
| DenseBase.html diff lines | — | — | 132 (hash changes only) |
| MatrixBase.html diff lines | — | — | 66 (hash changes only) |
| ArrayBase.html diff lines | — | — | 54 (hash changes only) |

The member counts in DenseBase/MatrixBase/ArrayBase are unchanged — because those methods were already pulled in via `#include`. The 132-line diff in DenseBase.html is entirely Doxygen-generated anchor hash changes, not content changes.

The 7 new HTML pages come from `TrsmUnrolls.inc` (an AVX512 internal file):

```
unrolls::gemm       — AVX512 GEMM kernel template
unrolls::transB     — Matrix transpose helper
unrolls::trsm       — Triangular solve kernel
```

These are standalone .inc files (not included via `#include` into any header) that contain real C++ classes. Without the mapping, Doxygen couldn't parse them as C++ at all.

The 29 new search index entries correspond to members of these newly-documented classes — methods like `aux_loadB`, `aux_microKernel`, `aux_storeC`, `aux_triSolveMicroKernel`.

### What About the Plugin Methods?

The plugin .inc files (`BlockMethods.inc`, `CommonCwiseUnaryOps.inc`, etc.) show identical documentation with and without the mapping. This is expected — their content enters Doxygen's parser through the `#include` directive in the `.h` files, where preprocessing does occur.

The mapping ensures they're *also* properly preprocessed when Doxygen encounters them as standalone files. This matters for:

1. **Source file pages** — the `BlockMethods_8inc_source.html` pages. With the mapping, Doxygen can properly syntax-highlight and cross-reference these pages with macro expansion applied.

2. **Future changes** — if any `.inc` file starts using `#ifdef EIGEN_PARSED_BY_DOXYGEN` to expose Doxygen-only documentation (a common Eigen pattern), those blocks would be silently ignored without the mapping.

3. **Consistency** — a `.h` file and a `.inc` file in the same directory should receive the same Doxygen treatment.

## The Fix

One line in `Doxyfile.in`:

```diff
 EXTENSION_MAPPING      = .h=C++ \
+                         .inc=C++ \
                          no_extension=C++
```

That's it. The [merge request](https://gitlab.com/libeigen/eigen/-/merge_requests/2338) is a single-line change with zero impact on compilation, zero impact on existing documentation content for the plugin methods, and correct new documentation for standalone `.inc` files.

## How to Debug Doxygen Yourself

If you suspect Doxygen is mishandling files in your project, here's the approach that worked:

### 1. Run Doxygen with verbose output

```bash
doxygen Doxyfile 2>&1 | grep -E "(Reading|Preprocessing|Parsing).*yourfile"
```

If you see `Reading` but no `Preprocessing`, your file isn't being treated as a recognized language. Doxygen's macro expansion, `#ifdef` evaluation, and other C/C++ preprocessing features are silently skipped.

### 2. Compare with and without your change

Run Doxygen twice — once with master config, once with your fix — and diff the output directories:

```bash
# Count pages
find build-a/html -name "*.html" | wc -l
find build-b/html -name "*.html" | wc -l

# Find new pages
diff <(cd build-a/html && find . -name "*.html" | sort) \
     <(cd build-b/html && find . -name "*.html" | sort)

# Check specific class pages
diff build-a/html/classYourClass.html build-b/html/classYourClass.html | wc -l
```

### 3. Check the search index

Doxygen generates JavaScript search index files in `html/search/`. These are a quick way to see if new members became discoverable:

```bash
diff <(cat build-a/html/search/all_*.js | sort) \
     <(cat build-b/html/search/all_*.js | sort) | grep "^>"
```

### 4. Use Docker for reproducibility

Doxygen versions behave differently. Pin the version in a Dockerfile so your verification is reproducible:

```dockerfile
FROM ubuntu:24.04
RUN apt-get update && apt-get install -y --no-install-recommends doxygen
```

This gives you Doxygen 1.12.0 on Ubuntu 24.04. Different versions may produce different results — especially for edge cases like extension mapping.

### 5. Check EXTENSION_MAPPING vs FILE_PATTERNS

These are independent settings that interact in non-obvious ways:

- `FILE_PATTERNS = *` tells Doxygen which files to pick up from `INPUT` directories
- `EXTENSION_MAPPING` tells Doxygen how to treat files it has already picked up

A file can match `FILE_PATTERNS` but have no extension mapping. Doxygen will still read and parse it, but it won't preprocess it as C/C++. This is the trap that Eigen fell into.

## Relationship to !2330

A reviewer on the MR asked whether this change was redundant with [!2330](https://gitlab.com/libeigen/eigen/-/merge_requests/2330), which inlines `IndexedViewMethods.inc` directly into `DenseBase.h` (eliminating it from the source tree).

These are complementary, not overlapping:

- **!2330** removes one specific `.inc` file (`IndexedViewMethods.inc`) by inlining its contents
- **!2338** ensures all `.inc` files — including `BlockMethods.inc`, `CommonCwiseUnaryOps.inc`, `CommonCwiseBinaryOps.inc`, `ArrayCwiseBinaryOps.inc`, `ReshapedMethods.inc`, and others — are properly preprocessed as C++

If !2330 merges first, `IndexedViewMethods.inc` goes away. But the other 9+ plugin `.inc` files remain, plus the architecture-specific ones (`TrsmUnrolls.inc`, `MatrixVectorProduct.inc`, `GpuHipCudaDefines.inc`). They all benefit from this mapping.

## Takeaways

1. **Doxygen's `EXTENSION_MAPPING` controls preprocessing, not just parsing.** Without it, files with unrecognized extensions are read and parsed but never preprocessed. This means `PREDEFINED` macros, `#ifdef` evaluation, and macro expansion are silently skipped. The documentation may *look* fine because the content enters through `#include`, but the standalone file pages miss critical processing.

2. **`FILE_PATTERNS = *` is necessary but not sufficient.** It gets files into Doxygen's input set. But if those files don't have recognized extensions (or explicit mappings), they get second-class treatment. This is documented in the [Doxygen manual](https://www.doxygen.nl/manual/config.html#cfg_extension_mapping) but easy to miss.

3. **Docker-based A/B testing is the fastest way to debug Doxygen.** Running two Doxygen passes and diffing HTML output takes minutes. Reading Doxygen source code to understand its file-type detection heuristics takes hours. Empirical beats theoretical for configuration debugging.

4. **Check the processing logs, not just the output.** The `Reading` vs `Preprocessing` distinction in Doxygen's stderr output is invisible in the generated HTML for files that are `#include`d elsewhere. The logs are the only way to confirm the processing pipeline is correct.

5. **One-line configuration fixes deserve the same verification rigor as code changes.** This was a one-line diff to `Doxyfile.in`. The Docker verification that proved it works took 30 lines of shell. The ratio is worth it — configuration bugs are notoriously hard to debug because their symptoms are silent omissions, not errors.
