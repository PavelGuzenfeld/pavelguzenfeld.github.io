---
title: "C++ Low-Latency, Enforced: __builtin_*, Compiler Flags, and clang-tidy, Benchmarked"
date: 2026-04-24
draft: false
tags: ["C++", "optimization", "performance", "benchmarking", "profiling", "compilers", "GCC"]
keywords: ["__builtin_popcount benchmark", "likely unlikely C++20", "__builtin_unreachable switch", "__builtin_bswap64", "march native benchmark", "ffast-math danger", "clang-tidy performance checks", "performance-for-range-copy", "clang-tidy CMake integration"]
cover:
  image: /images/posts/cpp-builtins-clang-tidy.png
  alt: "C++ tools that enforce low-latency patterns — builtins, compiler flags, clang-tidy checks"
categories: ["deep-dive"]
summary: "Follow-up to the 15-pattern HFT post. The first post asked 'which patterns work?' This post answers 'how do you force your team to keep using them?' Seven new nanobench programs, each with a working Godbolt link, covering __builtin_popcountll (24x faster than a bit-count loop), __builtin_unreachable in switch defaults (1.55x), __builtin_bswap64 (same speed as the portable idiom — GCC already folds it), [[likely]] and [[unlikely]] (no measurable effect on tight loops — an honest null result), and a flags matrix showing -ffast-math + -march=x86-64-v3 giving 6.9x over -O2. Then a .clang-tidy config that fails CI on every common perf regression, with the performance-for-range-copy warning demonstrated at 41x real runtime cost."
ShowToc: true
---

The [last post](/posts/hft-cpp-performance-patterns-benchmarked/) was about which C++ low-latency patterns actually reproduce on a modern CPU. Fifteen techniques from Bilokon & Gunduz's HFT paper, Jonathan Müller's Cache-Friendly C++ deck, and Okade & Baker's C++ Performance Tips deck, all run through [nanobench](https://github.com/martinus/nanobench) and published as working Godbolt links with measured ns/op numbers. Three of them didn't reproduce. Twelve did.

This post is the sequel. The first post asked **which patterns work**. This post asks **how do you make them mandatory** — how do you pick them up automatically, reject their violations at review time, and catch the regressions in CI?

The answer sits in three concentric rings:

1. **`__builtin_*` intrinsics.** Code-level opt-ins. One programmer writes `__builtin_popcountll(x)` and the compiler emits a single CPU instruction. Same for `__builtin_bswap64`, `__builtin_unreachable`, `__builtin_prefetch`, the `[[likely]]` / `[[unlikely]]` attributes. They are the vocabulary the compiler expects when you want specific codegen.
2. **Compiler flags.** Project-level. `-march=x86-64-v3` gives the whole binary AVX2; `-ffast-math` lets the compiler associate floating-point reductions; `-Wpessimizing-move` turns one class of perf bug into a build failure.
3. **clang-tidy checks.** Team-level guardrail. `performance-for-range-copy`, `performance-unnecessary-value-param`, `modernize-use-emplace` — the checks that catch the patterns from post 1 the moment someone violates them in a PR.

Seven new nanobench files, one .clang-tidy config, one CMake stanza. Numbers from the same GCC 14 `-O2 -std=c++23` on the same desktop. Same Docker harness, same `make_godbolt_nb.sh` shortener pipeline. Two of the new benchmarks produced honest null results. One exposed a codegen regression at `-march=x86-64-v3` that `-O3` fixed. The rest are clean wins.

![C++ builtins, compiler flags, and clang-tidy — cover](/images/posts/cpp-builtins-clang-tidy.png)

## Part 1: `__builtin_*` — the low-level toolkit

Every GCC/Clang `__builtin_*` is a hand-shake with the compiler: *I know the CPU has a one-instruction way to do this, please emit it.* Some map to a single instruction (`popcount`, `bswap`, `clz`); some change codegen downstream by removing a branch (`unreachable`, `expect`); some are purely compile-time (`constant_p`, `types_compatible_p`). The four benchmarks below cover the four most useful categories.

---

### 1.1 `__builtin_popcountll` — 24× over a naive bit count

Counting the set bits in a 64-bit integer. The naive version is a loop over 64 bit positions; the classic "Kernighan's trick" is `while (x) { x &= x - 1; ++c; }` which only iterates once per set bit. The intrinsic, on any POPCNT-capable CPU (every x86-64 in the last decade), lowers to one `popcntq` instruction.

```cpp
static int popcount_naive(std::uint64_t x) {
  int c = 0;
  for (int i = 0; i < 64; ++i) c += (x >> i) & 1;
  return c;
}
static int popcount_kernighan(std::uint64_t x) {
  int c = 0;
  while (x) { x &= x - 1; ++c; }
  return c;
}
// __builtin_popcountll(x) — one instruction
```

Run over 64K random `uint64_t`s:

**Godbolt:** [godbolt.org/z/rxfG5TjjG](https://godbolt.org/z/rxfG5TjjG)

```
naive 64-bit loop                           1,698,193 ns/op
Kernighan's trick (x &= x - 1)                918,384 ns/op   1.85×
__builtin_popcountll (one CPU instruction)     71,416 ns/op   23.8×
```

**23.8× over the naive loop, 12.8× over Kernighan.** `__builtin_popcountll` is the single biggest bang-for-buck intrinsic on x86-64, and yet I still see custom bit-count loops in production code because people forget it exists.

Its siblings deserve a line: `__builtin_clzll(x)` counts leading zeros (= `63 - log2(x)` for non-zero x), `__builtin_ctzll(x)` counts trailing zeros, `__builtin_ffsll(x)` finds the lowest-set bit (1-indexed). All three lower to one instruction on modern x86 (`lzcnt`, `tzcnt`, `bsf`). The C++20 `<bit>` header wraps them as `std::popcount`, `std::countl_zero`, `std::countr_zero`, `std::bit_floor` — the standard-library names if you want them.

**When to use:** hash computation, population-count-based similarity, bitmap iteration, log2/align-up math. **When not to:** if your bitset is larger than 64 bits, use `std::bitset::count()` — libstdc++ routes through `__builtin_popcountll` in a loop, and the abstraction is free.

---

### 1.2 `[[likely]]` / `[[unlikely]]` — an honest null result

The C++20 attributes were supposed to finally standardise the `__builtin_expect` hint. On an error-check branch where the error fires 1% of the time, `[[unlikely]]` on the error path should move the cold block off the hot i-cache line and speed up the loop.

```cpp
__attribute__((noinline)) static int process_none(int x) {
  if (x < 0) return -x;
  return x * 3;
}
__attribute__((noinline)) static int process_likely(int x) {
  if (x < 0) [[unlikely]] return -x;      // truth: only 1% are negative
  return x * 3;
}
__attribute__((noinline)) static int process_wrong(int x) {
  if (x < 0) [[likely]] return -x;        // lies to GCC — most x are >= 0
  return x * 3;
}
```

**Godbolt:** [godbolt.org/z/W9bjaE6rP](https://godbolt.org/z/W9bjaE6rP)

```
no hint                                         532,965 ns/op
[[unlikely]] on the rare branch (correct)       545,022 ns/op    0.98×
[[likely]] on the rare branch (wrong hint)      522,675 ns/op    1.02×
```

**All three are within 2% of each other — noise.** Including the *deliberately wrong* hint. The branch predictor learns the pattern after the first handful of iterations and dispatches correctly regardless of what the attribute says. The hint does move the cold block in the emitted code, but the function body is so small that it fits entirely in L1i no matter the layout, so the move is a no-op.

**When `[[likely]]` / `[[unlikely]]` actually pays:**

- The cold branch contains a lot of code (logging, error formatting, metric emission) that would otherwise inflate the hot loop's i-cache footprint.
- The hot function is large enough that i-cache pressure matters in aggregate, even if any one call site doesn't spill.
- Profile-guided optimisation (PGO) isn't available — with `-fprofile-use`, the compiler has real branch frequencies and the attributes become redundant.

**Rule I apply:** reach for `[[unlikely]]` only on error-handling / logging paths with non-trivial body size, or on paths the predictor *can't* learn because the input distribution is adversarial. On a two-instruction branch, the attribute is documentation at best.

---

### 1.3 `__builtin_unreachable()` in a switch default — 1.55×

The counter-case to the honest null above. When you genuinely know a point in control flow is unreachable — for instance, a `switch` on an enum whose input is validated upstream — telling the compiler lets it drop bounds checks and emit a denser dispatch table.

```cpp
enum class Op : int { Add = 0, Sub = 1, Mul = 2, Xor = 3 };

static int apply_safe(Op op, int a, int b) {
  switch (op) {
    case Op::Add: return a + b;
    case Op::Sub: return a - b;
    case Op::Mul: return a * b;
    case Op::Xor: return a ^ b;
  }
  std::abort();   // defensive default — keeps a branch live
}

static int apply_unreachable(Op op, int a, int b) {
  switch (op) {
    case Op::Add: return a + b;
    case Op::Sub: return a - b;
    case Op::Mul: return a * b;
    case Op::Xor: return a ^ b;
  }
  __builtin_unreachable();   // compiler assumes this point is never reached
}
```

Input: 1 M random `Op` values drawn uniformly from `{0, 1, 2, 3}`.

**Godbolt:** [godbolt.org/z/srsGxEEhv](https://godbolt.org/z/srsGxEEhv)

```
switch with std::abort() default              6,347,288 ns/op
switch with __builtin_unreachable() default   4,102,408 ns/op    1.55×
```

**1.55× speedup.** The `std::abort` version forces the compiler to keep a bounds check and an out-of-band call site live; the unreachable version drops both, and GCC collapses the `switch` into a four-entry jump table with no range check.

The C++23 replacement is `std::unreachable()` — same semantics, standard name. Use it over the builtin when you can.

**Footgun warning:** `__builtin_unreachable` is undefined behaviour if the compiler can actually reach it. If your enum has a fifth value silently added later and you don't update the switch, you get silent UB — a wrong result, a memory-corruption crash, or a trap, depending on the compiler's mood. Pair it with an assertion in debug builds: `#ifdef NDEBUG __builtin_unreachable(); #else std::abort(); #endif` or, better, a `-Wswitch` / `-Wswitch-enum` that fails the build if a case is missing.

---

### 1.4 `__builtin_bswap64` — the idiom GCC already recognises

Flipping the endianness of a 64-bit integer is a one-instruction job on x86 (`bswap`). The portable idiom is eight shift-and-or operations:

```cpp
static std::uint64_t bswap_portable(std::uint64_t x) {
  return ((x & 0x00000000000000ffull) << 56)
       | ((x & 0x000000000000ff00ull) << 40)
       | ((x & 0x0000000000ff0000ull) << 24)
       | ((x & 0x00000000ff000000ull) <<  8)
       | ((x & 0x000000ff00000000ull) >>  8)
       | ((x & 0x0000ff0000000000ull) >> 24)
       | ((x & 0x00ff000000000000ull) >> 40)
       | ((x & 0xff00000000000000ull) >> 56);
}
```

vs `__builtin_bswap64(x)`. Iteration over 64K random `uint64_t`s:

**Godbolt:** [godbolt.org/z/Pfbja61Eb](https://godbolt.org/z/Pfbja61Eb)

```
portable shift-and-OR expression     28,623 ns/op
__builtin_bswap64 (one instruction)  28,801 ns/op    0.99×
```

**Identical.** GCC has recognised the shift-and-or bswap idiom since version 4.8 (2013) and folds it to the same `bswap` instruction. So the intrinsic is — for this exact idiom on modern GCC — a wash.

It still matters in three ways:

- **Clarity.** `__builtin_bswap64(x)` says *byte-swap a 64-bit integer*. The 8-line portable version says *please audit me for off-by-one shift errors*.
- **Portability across compilers.** MSVC has `_byteswap_uint64`; Clang has `__builtin_bswap64`; GCC has it too. C++23 finally added `std::byteswap`. Before that, the platform define-dance is unavoidable.
- **Version-of-compiler robustness.** The idiom recognition is a pattern match; it breaks if you write the expression slightly differently. The intrinsic is guaranteed.

Same story for `__builtin_bswap16` (→ `xchg` or `rol 8`) and `__builtin_bswap32`. C++23: use `std::byteswap` and let the standard library worry about which builtin to call.

---

### 1.5 Three more builtins that don't need a benchmark

Runtime speed isn't the only thing builtins unlock. Three worth knowing, none with a measurable runtime delta in my harness but all with a clear codegen or correctness payoff:

**`__builtin_assume_aligned(p, 64)`** tells the compiler the pointer is aligned to a 64-byte boundary, which lets the auto-vectoriser emit aligned loads/stores instead of unaligned ones. On recent Intel, aligned and unaligned loads have the same throughput when the address is actually aligned, so the runtime effect is zero — but on strict-alignment ARM targets, and on older x86, it is the difference between a single load and a split pair of loads. Use it on SIMD-sized inputs you control the allocation of.

**`__builtin_prefetch(addr, rw, locality)`** — covered in [post 1's §7](/posts/hft-cpp-performance-patterns-benchmarked/#7-software-prefetching-on-pointer-chases). TL;DR: 20% win on a 1M-node pointer chase; marginal or negative on anything the hardware prefetcher can predict.

**`__builtin_constant_p(x)`** returns true inside the compiler when `x` is a compile-time constant, false otherwise. Used to pick between a cheap compile-time specialisation and a generic runtime path inside a macro. You won't see it in modern C++ much — `if constexpr` and concepts do the job better — but glibc's `strcpy` / `memcpy` / `strlen` still branch on it to emit a `rep movs` for small literal sizes vs a generic loop for variable ones. Handy if you're writing header-only libraries that want to specialise on literal arguments.

Other builtins you'll see in real codebases: `__builtin_trap()` (unconditional fault — smaller code than `abort()`), `__builtin_assume(cond)` (Clang-only; a `__builtin_unreachable` gated by `cond`), `__builtin_FILE()` / `__builtin_LINE()` / `__builtin_FUNCTION()` (pre-C++20 `std::source_location`), `__builtin_types_compatible_p(T1, T2)` (legacy type equality, obsoleted by `std::is_same_v`).

---

## Part 2: Compiler flags that change everything

The intrinsic is a sentence; the flag is a paragraph. Flags are the project-level knobs that shift what the optimiser is willing to do across the whole binary. The two that move the most wall time on a compute loop are `-march` and `-ffast-math`. The ones that catch the most bugs at compile time are the `-W` family.

### 2.1 Optimisation levels — the ladder

Quick reminder on what each `-O` level unlocks:

| Flag | Purpose | What turns on | When to use |
|------|---------|---------------|-------------|
| `-O0` | Debug / no opt | Nothing. Every variable lives on the stack. | Debugging with a sane `gdb`. |
| `-Og` | Debug + easy opts | Basic cleanup that doesn't hinder the debugger. | The default for dev builds. |
| `-O1` | Light opt | Simple passes, no aggressive inlining. | Rare — usually skip to O2. |
| `-O2` | Production default | Inlining, vectorisation, constant folding, dead-code elimination. | Everything that ships. |
| `-O3` | + aggressive inlining, + auto-vectorisation | Larger inlining budget, more loop vectorisation, loop unrolling. | Hot paths; measure first. |
| `-Os` | Smallest code | Like -O2 but avoids optimisations that grow text size. | Embedded, i-cache-constrained. |
| `-Ofast` | `-O3 -ffast-math -fno-signed-zeros -ffinite-math-only ...` | Breaks IEEE-754 for speed. | Compute kernels you control. |

`-O2` is the right default for 95% of code. `-O3` is not always faster — it increases inlining and unrolling, which can overflow the i-cache on larger binaries. Profile before committing.

### 2.2 `-march` and the x86-64 microarchitecture levels

By default, GCC targets the lowest-common-denominator `x86-64` ISA — SSE2, no AVX, no BMI. On any desktop or server CPU made since 2013, you are leaving a lot of silicon idle.

The four `x86-64-v*` levels (introduced in GCC 11) give a portable way to dial in a feature set without pinning to a specific CPU:

| Level | Roughly | Features added |
|-------|---------|----------------|
| `x86-64` | 2003 | SSE2 |
| `x86-64-v2` | Nehalem, 2008 | SSE3, SSSE3, SSE4.1, SSE4.2 |
| `x86-64-v3` | Haswell, 2013 | AVX, AVX2, BMI1, BMI2, FMA |
| `x86-64-v4` | Skylake-X, 2017 | AVX-512 (various) |

Benchmark: auto-vectorisable 5-term polynomial eval over a 4 KiB (L1-resident) float array. Same source, three builds:

```cpp
float s = 0.f;
for (int i = 0; i < N; ++i) {
  float x = a[i], y = b[i];
  float p = ((((x * 0.1f + y) * 0.2f + x) * 0.3f + y) * 0.4f + x) * 0.5f + y;
  s += p;
}
```

| Flags | ns/op | Ratio | Godbolt |
|-------|-------|-------|---------|
| `-O2` | 2,013 | 1.00× (baseline) | [godbolt.org/z/W43EWq6zK](https://godbolt.org/z/W43EWq6zK) |
| `-O3 -march=x86-64-v3` | 3,596 | **0.56× (slower!)** | [godbolt.org/z/bTso64Kv3](https://godbolt.org/z/bTso64Kv3) |
| `-O3 -ffast-math -march=x86-64-v3` | 292 | **6.9×** | [godbolt.org/z/515PdjMMh](https://godbolt.org/z/515PdjMMh) |

Two surprises:

1. `-O3 -march=x86-64-v3` *without* `-ffast-math` is **slower than -O2 baseline**. Without `-ffast-math`, the compiler cannot associate the `s += p` reduction, so the whole loop stays sequential. AVX2 doesn't help a sequential reduction; it does help emit FMA instructions for the polynomial, which GCC schedules onto execution ports in a way that turns out to be worse than the scalar sequence on my Intel. This is a real codegen regression on GCC 14 for this kernel. `-O3 -march=native` produced unstable timings too (41% error bar). **`-march=native` is not a free speedup.**
2. Add `-ffast-math` and AVX2 unlocks: now the reduction vectorises (sum 8 floats per cycle), and you get a clean **6.9× over -O2**. That is the real floating-point-SIMD payoff.

**The rule that survives this:** enable `-march=x86-64-v3` or `-march=x86-64-v4` when your deployment targets are modern (most servers and workstations since 2014), but always pair it with `-O3` *and* measure. The default `x86-64` target gives you SSE2; leaving that on a server benchmark is the biggest single-flag leak I see.

### 2.3 `-ffast-math` — why the 2× ships with a warning

From the benchmark above, one-dimensional view: `-O3` vs `-O3 -ffast-math` on a sum of 1 M doubles.

**Godbolt:** [godbolt.org/z/osMTbGsWv](https://godbolt.org/z/osMTbGsWv) (no ffast) vs [godbolt.org/z/ocb9fEq5r](https://godbolt.org/z/ocb9fEq5r) (ffast)

```
-O3                 454,328 ns/op
-O3 -ffast-math     229,697 ns/op    1.98×
```

**2× speedup** from a single flag. Why it isn't on by default: `-ffast-math` turns on six sub-flags, the most dangerous being `-fassociative-math` (sums can reorder), `-ffinite-math-only` (assume no NaN/Inf), and `-fno-signed-zeros` (treat -0 == 0). In a trading system where `nan` is a legitimate "no quote" value, or where a price-change log sums to a running total and must match to the cent across two replicas, these assumptions are catastrophic.

**Use `-ffast-math` on compute kernels where:**

- Inputs are bounded and free of NaN/Inf by construction.
- Associativity of floating-point sums is safe (you accept per-run rounding noise).
- The kernel is isolated — you can flag-switch it without flooding the rest of the binary with the new assumptions.

GCC 13+ offers `-fassociative-math` and the other sub-flags individually, so you can take the specific reordering permission without the full bundle.

### 2.4 `-fno-exceptions` / `-fno-rtti` — the Chromium defaults

Two flags that sound scary and aren't: `-fno-exceptions` drops the exception-handling tables and `throw` support; `-fno-rtti` drops `typeid` and `dynamic_cast`. Chromium and LLVM both ship with both disabled by default. The runtime speed gain on well-inlined code is small (a few % in my measurements); the **binary size** gain is 10–25%, and the **i-cache pressure** reduction that implies can dominate the speed story on larger binaries.

The catch: `std::vector<T>` will still call `__throw_bad_alloc` on OOM, which becomes `std::terminate` under `-fno-exceptions`. If your code relies on exceptions for anything other than allocation failure, audit before switching. And a library compiled with exceptions enabled can't reliably be linked against code compiled with them disabled — the ABI for stack unwinding differs.

### 2.5 Warnings that catch perf bugs

From Okade & Baker's deck (covered in post 1), the warning flags that specifically catch the patterns that post measured:

| Flag | Catches |
|------|---------|
| `-Wpessimizing-move` | `return std::move(local);` (defeats NRVO) |
| `-Wrange-loop-construct` | `for (const auto x : vec)` when `x` is copied silently |
| `-Wexit-time-destructors` | Global objects with non-trivial destructors that run at program exit |
| `-Wglobal-constructors` | Global objects with non-trivial constructors that run at program start |
| `-Wmove` | Various moves-into-const or moves-of-trivially-copyable |
| `-Wswitch-enum` | Missing case in a `switch` over an enum (pairs with `__builtin_unreachable`) |
| `-Wnrvo` (GCC 13+) | Explicit spot where NRVO *would* have fired but got prevented |

Add them all to your `-Wall -Wextra -Werror` stack. They catch at compile time exactly the patterns that post 1's benchmarks measured at run time. Every warning is a PR that doesn't land with the bug.

---

## Part 3: clang-tidy — enforce the patterns in CI

The warning flags above are gcc/clang's built-in diagnostics. **clang-tidy** is a separate static analyzer that ships with LLVM, runs over your whole codebase, and has ~400 named checks. For post 1's patterns, the relevant checks fall into three families.

### 3.1 The performance-* checks you actually need

From the CppCon 2025 deck — the minimum set that catches the common perf regressions:

| Check | Catches | Post-1 section |
|-------|---------|---------------|
| `performance-unnecessary-value-param` | Non-trivial type passed by value but only used as const ref | §12 `string_view` |
| `performance-unnecessary-copy-initialization` | `const auto x = obj.ref_returning_member();` making a copy | §9 AoS/SoA discipline |
| `performance-for-range-copy` | `for (auto x : ...)` over a non-trivially-copyable container | — (see §3.2 below) |
| `performance-inefficient-vector-operation` | `emplace_back` in a loop with no prior `reserve()` | §11 reserve+emplace |
| `performance-noexcept-move-constructor` | Move constructor without `noexcept` — vector falls back to copy on reallocation | §11 emplace |
| `performance-move-const-arg` | `std::move` on a const — no-op, silently copies | — |
| `performance-implicit-conversion-in-loop` | `for (auto x : map)` when the real type is `std::pair<const K, V>` vs the bound `std::pair<K, V>` (silent copy) | — |
| `modernize-use-emplace` | `push_back(T{args...})` instead of `emplace_back(args...)` | §11 |
| `modernize-pass-by-value` | Constructor taking `const T&` when `T` could be moved-in | §12 string_view sink notes |
| `bugprone-implicit-widening-of-multiplication-result` | `size_t bytes = int(n) * sizeof(T)` — overflow before widening | — |

### 3.2 `performance-for-range-copy` — the 41× benchmark

The clearest of the bunch. A range-based `for` over `std::vector<std::string>` that binds each element by value instead of `const auto&`.

```cpp
static const auto names = make_names();  // 10,000 strings, each > SSO

// Silent copy per iteration — each std::string allocates on the heap
std::size_t total = 0;
for (auto x : names) total += x.size();

// No copy — just a reference
std::size_t total = 0;
for (const auto& x : names) total += x.size();
```

**Godbolt:** [godbolt.org/z/rox1xc76T](https://godbolt.org/z/rox1xc76T)

```
for (auto x : names)  — copies each string         88,654 ns/op
for (const auto& x : names)  — no copy              2,169 ns/op    40.9×
```

**40.9× real runtime cost.** That is 10,000 heap allocations per iteration × millions of iterations in aggregate. The mistake shows up in every junior-to-mid-level C++ codebase I have reviewed. `clang-tidy --checks=performance-for-range-copy` flags it with:

```
warning: loop variable is copied but only used as const reference;
consider making it a const reference [performance-for-range-copy]
    for (auto x : names) total += x.size();
         ^
         const &
```

Turn that into `-warnings-as-errors=*` and the PR doesn't merge.

### 3.3 A `.clang-tidy` you can drop in

Place at the root of your repo. Runs automatically when the editor or CI invokes clang-tidy.

```yaml
---
Checks: >
  -*,
  bugprone-*,
  -bugprone-easily-swappable-parameters,
  -bugprone-exception-escape,
  cppcoreguidelines-pro-type-cstyle-cast,
  cppcoreguidelines-pro-type-member-init,
  cppcoreguidelines-slicing,
  misc-const-correctness,
  misc-definitions-in-headers,
  misc-unused-parameters,
  misc-use-anonymous-namespace,
  modernize-*,
  -modernize-use-trailing-return-type,
  -modernize-avoid-c-arrays,
  performance-*,
  readability-identifier-naming,
  readability-redundant-*

WarningsAsErrors: 'performance-*,bugprone-*,modernize-use-emplace,modernize-pass-by-value'

HeaderFilterRegex: '.*'

CheckOptions:
  - key: modernize-use-nullptr.NullMacros
    value: 'NULL'
  - key: readability-identifier-naming.ClassCase
    value: CamelCase
  - key: readability-identifier-naming.FunctionCase
    value: lower_case
  - key: readability-identifier-naming.VariableCase
    value: lower_case
```

Three notes:

- **Starting with `-*`** and enabling specific families is easier to maintain than "everything except some exclusions." clang-tidy ships hundreds of checks; whitelisting is saner.
- **`WarningsAsErrors` is the enforcement mechanism.** Without it, clang-tidy prints warnings that everybody ignores. With it, the performance and bugprone checks are a CI gate.
- **`-modernize-use-trailing-return-type`** and **`-modernize-avoid-c-arrays`** are the two checks I always turn off — they're style preferences that don't reflect real-world C++ idioms.

### 3.4 Wiring clang-tidy into CMake

Two lines in your top-level `CMakeLists.txt`:

```cmake
find_program(CLANG_TIDY_EXE clang-tidy REQUIRED)
set(CMAKE_CXX_CLANG_TIDY
    ${CLANG_TIDY_EXE}
    -warnings-as-errors=*
    --extra-arg=-std=c++23)
```

CMake then invokes clang-tidy as part of every `add_library` / `add_executable` target's compile step. No `.tidy` targets to add; no custom commands. The `--extra-arg=-std=c++23` line is important — clang-tidy parses your sources with its own Clang frontend and needs to be told the language mode.

To opt specific targets *out* (e.g., third-party dependencies pulled in as source), clear the variable per-target:

```cmake
add_library(third_party_thing STATIC vendor/foo.cpp)
set_target_properties(third_party_thing PROPERTIES CXX_CLANG_TIDY "")
```

### 3.5 The GitHub Actions job

A minimal workflow that runs the whole lint in parallel with the build:

```yaml
name: clang-tidy
on: [pull_request]

jobs:
  lint:
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/checkout@v4
      - name: Install clang-tidy
        run: sudo apt-get update && sudo apt-get install -y clang-tidy-19
      - name: Configure
        run: cmake -B build -DCMAKE_EXPORT_COMPILE_COMMANDS=ON
      - name: Run clang-tidy
        run: |
          git diff --name-only --diff-filter=AM origin/main...HEAD \
            | grep -E '\.(cpp|h|hpp)$' \
            | xargs -r clang-tidy-19 -p build --warnings-as-errors=*
```

The `git diff --name-only` trick runs clang-tidy *only on files changed in the PR*, not the whole tree — which keeps the lint step under a minute on even large codebases. For a full-tree check, run clang-tidy nightly on `main` instead.

---

## Takeaways

Fifteen patterns were in post 1. Seven tools enforce them here:

| Tool | What it does | Runtime win | Where it lives |
|------|--------------|-------------|----------------|
| `__builtin_popcountll` | One-instruction bit count | 24× over naive | code |
| `__builtin_unreachable` | Drops bounds check in switch default | 1.55× | code |
| `__builtin_bswap64` | Idiom recognised anyway on GCC | 1.0× (clarity) | code |
| `[[likely]]` / `[[unlikely]]` | Block reorder hint | ~1.0× (noise on small loops) | code |
| `-march=x86-64-v3 -O3 -ffast-math` | Unlocks AVX2 reduction vectorisation | 6.9× (compute-bound) | flag |
| `-ffast-math` (alone) | Associates FP reductions | 2.0× | flag |
| `-W` family | Catches pessimising-move, range-copy, etc. | builds fail | flag |
| `performance-for-range-copy` | Catches `for (auto x : vec)` copy | 41× | clang-tidy |
| `performance-inefficient-vector-operation` | Catches emplace-without-reserve | 2× (post 1 §11) | clang-tidy |
| `performance-unnecessary-value-param` | Catches non-trivial-by-value | 1.25× (post 1 §12) | clang-tidy |

The stack is not one big decision. It's a series of layered defaults:

- **At the source-code level**: use intrinsics when you need specific codegen; use `[[likely]]`/`[[unlikely]]` only on cold paths with non-trivial bodies.
- **At the build level**: `-O2 -march=x86-64-v3 -Wall -Wextra -Werror -Wpessimizing-move -Wrange-loop-construct` for every production build; `-ffast-math` only on isolated compute kernels where you own the inputs.
- **At the CI level**: `.clang-tidy` with `performance-*` and `modernize-*` as errors; a `clang-tidy` workflow that blocks PRs.

None of the three rings alone catches everything. The builtins need humans to type them. The flags affect the whole binary, for better or worse. The clang-tidy checks have false positives that need disabling. Layered, they give you a codebase that tends toward the fast path without every author needing to remember every rule.

## References

- [Post 1: C++ Low-Latency Patterns, Benchmarked](/posts/hft-cpp-performance-patterns-benchmarked/) — the 15 patterns these tools enforce.
- [GCC: Other Built-in Functions Provided by GCC](https://gcc.gnu.org/onlinedocs/gcc/Other-Builtins.html) — the canonical builtin reference.
- [LLVM clang-tidy Checks](https://clang.llvm.org/extra/clang-tidy/checks/list.html) — every check, every option.
- [x86-64 microarchitecture levels (Wikipedia)](https://en.wikipedia.org/wiki/X86-64#Microarchitecture_levels) — the v2/v3/v4 feature matrix.
- Okade, P., and Baker, K. (2025). *C++ Performance Tips: Cutting Down on Unnecessary Objects*. CppCon 2025 — the source of the warning-flag list in §2.5.
- Lakos, J. *Large-Scale C++ Software Design* — the long-form case for `-fno-exceptions`, `-fno-rtti`, and the rest of the no-cost-abstractions discipline.

The full source for all seven benchmarks (plus the Dockerfile and the `make_godbolt_nb.sh` + `make_godbolt_nb_flags.sh` scripts) lives in the same `hft-perf-benchmarks/` directory as post 1. Build the image once, `docker run -v $(pwd):/work hft-nb bash -c "for f in 16_*.cpp 17_*.cpp 18_*.cpp 19_*.cpp 22_*.cpp; do g++ -O2 -std=c++23 \$f -pthread -o \${f%.cpp}.out && ./\${f%.cpp}.out; done"`, and you will get a per-tool scoreboard for your CPU.
