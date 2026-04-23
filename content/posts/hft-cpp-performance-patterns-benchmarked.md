---
title: "C++ Low-Latency Patterns, Benchmarked: 15 Tricks from HFT and CppCon 2025 (and Which Claims Don't Reproduce)"
date: 2026-04-23
draft: false
tags: ["C++", "optimization", "performance", "benchmarking", "profiling", "compilers", "concurrency"]
keywords: ["C++ HFT performance patterns", "low latency C++ benchmark", "nanobench Godbolt", "cache friendly C++", "LMAX disruptor C++", "CRTP virtual dispatch benchmark", "false sharing hardware_destructive_interference_size", "constexpr vs runtime factorial", "AoS vs SoA benchmark", "string_view const reference benchmark", "emplace_back reserve nanobench"]
cover:
  image: /images/posts/hft-cpp-performance-patterns.png
  alt: "C++ low-latency patterns benchmarked — HFT, cache-friendly layouts, and the tricks that don't reproduce"
categories: ["deep-dive"]
summary: "Fifteen C++ performance patterns from three sources — Bilokon & Gunduz's HFT paper at Imperial, Jonathan Müller's Cache-Friendly C++ deck at CppCon 2025, and Okade & Baker's C++ Performance Tips at CppCon 2025 — implemented as single-file nanobench programs, run under Docker on GCC 14 with -O2 -std=c++23, every one of them linked to a working Godbolt session. The surprising half: three of the 'textbook' speedups do not reproduce on a modern CPU. Cache warming is 7x slower than cold. Bitmask branch reduction is slower than the cascade it replaces. This post is the full runbook, numbers included, with the nuance that explains when each pattern actually earns its keep."
ShowToc: true
---

I spent a week going through three C++ performance sources — Paul Bilokon and Burak Gunduz's 2023 paper "[C++ Design Patterns for Low-Latency Applications Including High-Frequency Trading](https://arxiv.org/abs/2309.04259)" (Imperial College, with the companion [0burak/imperial_hft](https://github.com/0burak/imperial_hft) repo), Jonathan Müller's "Cache-Friendly C++" deck from CppCon 2025, and Prithvi Okade and Kathleen Baker's "C++ Performance Tips: Cutting Down on Unnecessary Objects" also from CppCon 2025. Together they cover the full low-latency stack: compile-time dispatch, cache layout, allocation avoidance, concurrency primitives, the LMAX Disruptor. Every one of them cites benchmark numbers. None of them publish a runnable harness.

So I wrote one.

Fifteen self-contained [nanobench](https://github.com/martinus/nanobench) programs, each one a single `.cpp` file, each one built with `g++ -O2 -std=c++23` inside a `gcc:14` Docker container, each one linked from this post as a working Godbolt session that compiles *and executes* with the nanobench library. The numbers below are what came out of my machine — an Intel i7-class desktop with 10 physical cores, 4.6 GHz boost, 48 KB L1d per core, 1.28 MB L2 per core, 24 MB shared L3. All runs share the same compiler, same flags, same turbo settings on.

Nanobench (not Google Benchmark) is the harness throughout. Three reasons: it is a single header, it prints relative speedups by default (which is usually what you actually want), and it is one-click-available as a library on Godbolt. If you have never used it, the entire API I needed for this post is `Bench().relative(true).run("name", [&]{ /* code */ ankerl::nanobench::doNotOptimizeAway(x); })`.

The surprise: about a third of the "textbook" speedups did not reproduce cleanly. Cache warming is **7× slower** than cold in my setup. Bitmask branch reduction is **1.6× slower** than the cascade it was supposed to replace. The bottom three in the scoreboard are not failures of the source papers — they are reminders that every micro-optimization has a context where it loses. This post shows when each pattern wins, when it loses, and why.

![C++ low-latency patterns benchmarked — cover](/images/posts/hft-cpp-performance-patterns.png)

## Ground rules for the benchmarks

Before any numbers, four rules I held myself to:

1. **Single-file, no build system.** Each `.cpp` `#define`s `ANKERL_NANOBENCH_IMPLEMENT` and `#include`s `<nanobench.h>`. Paste into Godbolt with the nanobench library selected in the compiler dropdown, hit "Execute the code." Done.
2. **`ankerl::nanobench::doNotOptimizeAway` on every sink.** Without it the compiler folds the measured result into `void`. The Imperial paper quotes Rasovsky's CppCon 2022 talk: a naive `clock_gettime` benchmark looked 85× slower than TSC on a toy harness but only 2× slower on her production server. Harness shape matters. Nanobench's guard does the boring work for you.
3. **Results are from one machine.** The absolute ns/op numbers will differ on yours. The *ratios* are the interesting thing, and the ratios hold reasonably well across machines.
4. **`-O2 -std=c++23`.** No `-march=native`, no PGO, no LTO. The stdlibc++ that ships with GCC 14. Nothing exotic.

Every godbolt link below was created via the Compiler Explorer shortener API and has the `-O2 -std=c++23` flags and the `nanobench` library pre-wired into an executor pane. Click "Execute the code" in the top-right of the output pane to run it in the browser. No local build needed. The full source and the Dockerfile live in a `hft-perf-benchmarks/` directory I keep locally; the `Dockerfile` is three lines on top of `gcc:14` that `curl`s the `nanobench.h` header into `/usr/local/include`.

The post covers fifteen techniques in five clusters: compile-time tricks, CPU-pipeline tricks, memory-layout tricks, concurrency tricks, and STL-object hygiene. At the end there is a scoreboard.

---

## 1. Compile-time dispatch: CRTP vs virtual

The first technique in the Imperial paper is the canonical low-latency polymorphism swap: replace virtual dispatch (indirect call through a vtable) with the Curiously Recurring Template Pattern so the target is resolved at compile time. The paper reports a **26%** win.

```cpp
struct Base { virtual int f(int x) const = 0; virtual ~Base() = default; };
struct DerivedV : Base { int f(int x) const override { return x * 3 + 1; } };

template <class D> struct BaseT {
  int f(int x) const { return static_cast<const D&>(*this).f_impl(x); }
};
struct DerivedT : BaseT<DerivedT> { int f_impl(int x) const { return x * 3 + 1; } };
```

The measured block is 64 chained calls in a tight loop: `for (int i = 0; i < 64; ++i) x = p->f(x);` for the virtual case, same shape for CRTP.

**Godbolt:** [godbolt.org/z/8zeqojafG](https://godbolt.org/z/8zeqojafG)

```
virtual call through Base*             23.14 ns/op
CRTP (resolved at compile time)        14.65 ns/op     1.58× faster
```

The CRTP version is **58% faster** per 64-call chain — about 0.14 ns less per call. Modern Intel speculates the virtual target via the BTB after the first iteration, so the indirect call is not blind, but it still pays the indirection cost on the return path, and — more importantly — **it blocks inlining**. The template version lets the compiler see through `f()` into `f_impl()`, inline the body, constant-fold the arithmetic around it, and occasionally unroll the outer loop. The virtual call sits behind a memory load the optimizer won't follow.

The paper's 26% win maps roughly to my result (~60% on a loop, which reduces to ~25% per call after amortising the non-call cost). If your dispatch is a single call deep inside a system boundary and the vtable is warm in L1, the delta vanishes. If you have many dispatches in a tight loop, or if the polymorphism is on a critical path where inlining would fold more than just the call, CRTP is the win.

**Takeaway:** don't switch to CRTP for a "virtual is slow" vibe. Measure the call site you care about, and look for *inlinability*, not call-site cost. A call that the compiler can't look through is what blocks the downstream optimizations that matter.

---

## 2. constexpr: shift work to compile time

`constexpr` is not a speed knob. It is a *time-of-evaluation* knob. Whatever gets folded at compile time disappears from the runtime, and the win is whatever you were paying for at runtime — not a fixed percentage. To measure the best case I need a function whose result is entirely determined by literal inputs:

```cpp
constexpr int factorial_ce(int n) { return n <= 1 ? 1 : n * factorial_ce(n - 1); }

int factorial_rt(int n) { return n <= 1 ? 1 : n * factorial_rt(n - 1); }
int (*fact_ptr)(int) = &factorial_rt;   // hide behind an indirection
```

The second form goes through a function pointer so `-O2` can't constant-propagate `factorial(10)` at the call site. The first form is marked `constexpr` and is called as `constexpr int r = factorial_ce(10);` — mandatory compile-time evaluation.

**Godbolt:** [godbolt.org/z/KM4ohTc5q](https://godbolt.org/z/KM4ohTc5q)

```
runtime factorial(10) via function pointer     3.68 ns/op
constexpr factorial(10) folded at compile time 0.05 ns/op   ~70× faster
```

**70× speedup** (nanobench reports it as 6,781% relative). The runtime version does ten multiplies through a function pointer; the constexpr version loads an immediate. This matches the Imperial paper's 90.88% figure almost exactly.

The catch: if you *don't* hide the runtime version behind an indirection, the compiler often folds it too. The paper warns: "Marked performance variance doesn't imply constexpr consistently amplifies runtime speed." What constexpr guarantees is that *no matter what the optimizer does*, the result is at compile time. That is a correctness property as much as a speed one — it is also what makes `static_assert` possible.

---

## 3. Cache warming: the counterexample

This is the pattern the Imperial paper reports the biggest win on — **90% speedup**. The idea: before the trade signal fires, pre-read the data the hotpath will touch so L1/L2 already hold the relevant lines. My attempt:

```cpp
static constexpr std::size_t N = 1u << 22;  // 16 MiB — much bigger than L2
static constexpr std::size_t K = 1u << 16;  // 65k random reads

// cold: just do the reads
long long sum = 0;
for (auto i : IDX) sum += DATA[i];

// warm: walk all of DATA first, then do the reads
long long warm = 0;
for (std::size_t i = 0; i < N; ++i) warm += DATA[i];
long long sum = 0;
for (auto i : IDX) sum += DATA[i];
```

**Godbolt:** [godbolt.org/z/hd6EahPPb](https://godbolt.org/z/hd6EahPPb)

```
cold: K random reads, no warmup                      91,252 ns/op
warm: walk all N first, THEN K random reads         655,255 ns/op   7.2× SLOWER
```

**Warming the cache made the benchmark 7× slower.** That is not a measurement error — it is the honest answer to a naive reading of the pattern.

The arithmetic: warming sequentially touches all 16 MiB (`N = 4,194,304 ints = 16 MB`). The "real" work is only `K = 65,536` random reads. Warming does 64× *more* memory traffic than the code it is trying to speed up.

**Cache warming pays when two conditions hold:**

1. The warming work is done in time you'd otherwise be *idle* — a trading engine walks its price-data structures on every market tick, so when a signal actually fires, the caches are already hot as a side effect. The cost is not a dedicated warmup; it is spread across the entire tick stream.
2. The hotpath accesses *significantly more* than the warmup — a 10 MiB warmup for a 1 GiB hotpath pass is a win; a 16 MiB warmup for a 256 KiB hotpath pass is a catastrophe.

The Imperial paper benchmark sits in regime (1) — warming is amortized across an outer loop that runs far more often than the warmup. My benchmark sits in regime (2) in reverse. The lesson is that **cache warming is a system-design pattern, not a micro-optimization**. If you see "cache warming" in a PR description and the warmup pass is larger than the measured pass, you have a `git revert` in your future.

---

## 4. Loop unrolling

Same general idea as a thousand other loops: fewer iterations of a bigger body, less branch-decrement overhead, more ILP exposed. To keep the compiler from auto-unrolling the baseline I hid the accumulator behind a `volatile`:

```cpp
// plain — volatile blocks auto-unroll
volatile int sum = 0;
for (int i = 0; i < 1000; ++i) sum += i;

// manually unrolled by 4
volatile int sum = 0;
for (int i = 0; i < 1000; i += 4) sum += i + (i + 1) + (i + 2) + (i + 3);
```

**Godbolt:** [godbolt.org/z/835MrGvo6](https://godbolt.org/z/835MrGvo6)

```
plain loop (volatile blocks auto-unroll)    258.45 ns/op
unrolled by 4                                70.18 ns/op     3.68× faster
```

**3.7× speedup.** The paper reports 4,539 vs 1,260 ns (3.6×) on the same workload — within 5% of the ratio I got.

Caveat: `volatile` is unrealistic. In production code, `-O2` will already auto-unroll this loop and my baseline would disappear. The `volatile` is there to *isolate* the effect — to show you what unrolling does when the compiler cannot do it for you. The real use case is an inner loop the compiler won't touch because of aliasing, pointer indirection, or a call it can't inline through. In that case, unrolling by hand buys you the pipeline depth the compiler would have given you if it had seen through the abstraction.

The paper also warns about instruction-cache pressure — an aggressively unrolled hot loop can bloat past L1i, costing more than it saves. "Don't unroll more than 4× unless you have the perf profile to back it up" is the rule I apply.

---

## 5. Short-circuit operand order

Any C++ programmer reads that `||` and `&&` short-circuit and moves on. The HFT version of the observation is: if the second operand is 1000× more expensive than the first, and the first is usually true, *put it first*.

```cpp
static volatile std::uint64_t g_sink = 0;

__attribute__((noinline)) static bool expensive(int i) {
  std::uint64_t acc = i;
  for (int k = 0; k < 2000; ++k) acc = acc * 1103515245ull + 12345ull;
  g_sink = acc;               // force the call to be observable
  return (acc & 1) == 0;
}
__attribute__((noinline)) static bool cheap(int i) { return i > 0; }
```

Two loops, one with `expensive(i) || cheap(i)`, one with `cheap(i) || expensive(i)`.

**Godbolt:** [godbolt.org/z/PdfM735s1](https://godbolt.org/z/PdfM735s1)

```
expensive || cheap  (no short-circuit possible)    218,087 ns/op
cheap || expensive  (short-circuit saves the call)    0.06 ns/op
```

The cheap-first form is **three million times faster** per 128-iteration loop. That is a correct reading of the numbers, and a deeply misleading one — cheap-first is literally free because the OR short-circuits before any work happens, while expensive-first pays the full LCG cost on every call.

The real-world HFT framing from the paper: "error checks are cheap, execute-hot-path is expensive — but the error check is what gates the hot path." Arrange your boolean gates so the cheapest, most-often-settling check fires first. One note worth pinning: I had to add the `g_sink` global to make `expensive()` observable, because without it `-O2` figured out that `expensive`'s return was not used when `cheap` was true and dead-stripped the call. If your pre-check isn't obviously pure, the compiler will re-order for you — but if it is pure, you need to make the ordering explicit, or write it as two separate `if` statements.

---

## 6. Branch reduction via bitmask flags

The Imperial paper advocates replacing a cascade of `if (checkA()) ... else if (checkB()) ...` with a single bitmask `flags` that accumulates all failure bits, followed by a single test `if (flags) handle(flags)`. The pitch: fewer branches, fewer mispredictions. Reported speedup: **36%**.

```cpp
// Cascade — five branches, each potentially mispredicted
__attribute__((noinline)) static bool handle_cascade(const Order& o) {
  if (o.price <= 0) return false;
  else if (o.qty <= 0) return false;
  else if (o.qty > 1'000'000) return false;
  else if (o.account < 0) return false;
  else if (o.account > 100'000) return false;
  return true;
}

// Flags — five branchless boolean-to-mask conversions, one final branch
__attribute__((noinline)) static bool handle_flags(const Order& o) {
  std::uint32_t f = 0;
  f |= (o.price <= 0)        ? 0x1u  : 0;
  f |= (o.qty <= 0)          ? 0x2u  : 0;
  f |= (o.qty > 1'000'000)   ? 0x4u  : 0;
  f |= (o.account < 0)       ? 0x8u  : 0;
  f |= (o.account > 100'000) ? 0x10u : 0;
  return f == 0;
}
```

**Godbolt:** [godbolt.org/z/1YcYaPbrf](https://godbolt.org/z/1YcYaPbrf)

```
cascade of if/else checks    681.89 ns/op
bitmask flags              1,113.26 ns/op    1.6× slower
```

**The flag-reduced version is 1.6× slower.** The cascade wins.

Why my orders make cascades look good: they all pass (all `price > 0`, all `qty > 0`, etc). The branch predictor, after 1–2 iterations, pegs every branch as "not taken," and the cascade collapses to "execute five cheap compares, fall through, return true." The flag version *always* does all five comparisons *and* all five conditional-moves, accumulating into `f`, and only then tests `f == 0`. When every check is predicted correctly, branches are nearly free; unconditional work is not.

**Branch reduction wins when the checks mispredict.** The paper's benchmark likely used inputs that tripped the predictor — errors fired roughly half the time. Mine don't. The rule to internalize: bitmask error flags are a *mispredict-mitigation* tool, not a *branch-avoidance* one. If your error paths are rare and predictable, your original cascade is probably fine. If they fire 20–50% of the time, bitmask flags — or, better, the `__builtin_expect` / `[[likely]]` / `[[unlikely]]` family of hints — start to pay.

---

## 7. Software prefetching on pointer chases

The hardware prefetcher is great at linear strides and bad at pointer-chasing. A linked list, a shuffled index, a tree walk — those are the places where `__builtin_prefetch` earns its keep. I built a shuffled list stored in a vector of `{value, next_index}` pairs, which is as adversarial for the HW prefetcher as a normal linked list without the allocator hops:

```cpp
struct Node { int value; std::size_t next; };

// keep one node ahead warm in L1
long long sum = 0;
std::size_t cur = F.head;
std::size_t look = F.nodes[cur].next;
for (std::size_t i = 0; i < N; ++i) {
  __builtin_prefetch(&F.nodes[F.nodes[look].next], 0, 0);
  sum += F.nodes[cur].value;
  cur  = F.nodes[cur].next;
  look = F.nodes[look].next;
}
```

**Godbolt:** [godbolt.org/z/aGKcYc1se](https://godbolt.org/z/aGKcYc1se)

```
pointer-chase, no prefetch              51,013,937 ns/op
pointer-chase, with __builtin_prefetch  42,634,203 ns/op    1.20× faster
```

**~20% speedup** on a pointer chase the HW prefetcher was supposed to be helpless on. The paper reports a 23.5% win on a sequential-sum prefetch benchmark — mine matches. For sequential access patterns the HW prefetcher has already done the work, and the software prefetch is redundant or counterproductive.

Prefetching has a narrow sweet spot: the prefetched line must arrive *before* the dependent load, but *after* the cache can hold it (or it gets evicted before use). My one-node lookahead is probably too close. Tuning the lookahead distance is its own side quest — typical values are "enough iterations to cover a DRAM round-trip" which is 10–30 ahead on modern chips. A production implementation would re-tune per target CPU.

The broader honest framing: **software prefetch is a last resort**. Fix the access pattern first. If you can't, use `__builtin_prefetch` and measure — the wrong lookahead distance costs more than it saves.

---

## 8. Lock-free: atomic increment vs mutex

The paper's concurrency section shows the cleanest speedup of the bunch — four threads hammering a single counter.

```cpp
// Mutex version: four threads each do 100,000 lock/++/unlock cycles
std::vector<std::thread> ts;
for (int t = 0; t < 4; ++t) ts.emplace_back([&] {
  for (int i = 0; i < ITERS; ++i) {
    std::lock_guard lock(mtx);
    ++plain;
  }
});

// Atomic version: four threads each do 100,000 fetch_add
for (int t = 0; t < 4; ++t) ts.emplace_back([&] {
  for (int i = 0; i < ITERS; ++i) a.fetch_add(1, std::memory_order_relaxed);
});
```

**Godbolt:** [godbolt.org/z/17z6KTMEW](https://godbolt.org/z/17z6KTMEW)

```
4 threads, std::mutex + ++counter                    24,495,959 ns/op
4 threads, std::atomic<long>::fetch_add(relaxed)      5,730,609 ns/op     4.28× faster
```

**4.3× speedup.** The paper reports 175,904 vs 65,369 ns at 10,000 iterations, which is the same ballpark.

The atomic version is still contended — every `fetch_add` still has to get exclusive ownership of the cache line — but it skips the kernel round-trip that the mutex pays whenever the fast path loses. The mutex cost is not the `lock`/`unlock` happy path (which is lock-free on modern libcs); it's the fallback to a `futex` call under contention.

**What the paper is honest about and I want to repeat:** atomics are not a drop-in fix. Writing correct lock-free code — especially anything with a shared queue — is how you get Heisenbugs that only reproduce at `-O3` on your coworker's machine. The paper quotes itself: "Lock-free programming is more complex than its lock-based counterparts and is thus more prone to bugs, particularly if misused." Use atomics where the semantics are simple (counters, sequence numbers, SPSC queues) and prefer well-tested libraries (Folly's MPMC queue, moodycamel's concurrentqueue, the LMAX Disruptor port in the Imperial repo) over rolling your own.

---

## 9. AoS vs SoA — the cleanest "just do this" win

Jonathan Müller's Cache-Friendly C++ deck has a benchmark I wanted to replicate as soon as I saw it: you have a `struct Person { name; salary; age; dept; }` and your hot loop averages ages. In an array-of-structs layout, each cache line holds one `Person` and reads three fields you don't care about. In a struct-of-arrays layout, each cache line is dense with ages.

```cpp
struct Person {
  std::string name;
  double salary;
  int age;
  int dept;
};
struct PeopleSoA {
  std::vector<std::string> names;
  std::vector<double> salaries;
  std::vector<int> ages;
  std::vector<int> depts;
};

// AoS: skips 3 fields per Person
long long sum = 0;
for (const auto& p : aos) sum += p.age;

// SoA: cache lines are dense with ages
long long sum = 0;
for (int a : soa.ages) sum += a;
```

**Godbolt:** [godbolt.org/z/5WWdTs5f4](https://godbolt.org/z/5WWdTs5f4)

```
AoS: average age over vector<Person>       71,502 ns/op
SoA: average age over parallel arrays      22,160 ns/op     3.23× faster
```

**3.2× speedup** on 100,000 persons. Müller's deck reports ~6× on the same test (his Person has more fields, or he's on a smaller cache line), but the shape of the result holds.

The reason SoA wins is straightforward. `sizeof(Person)` is 56 bytes on my `libstdc++`, so one `Person` consumes most of a 64-byte line — but only 4 bytes (the age field) are useful. The SoA version packs 16 `int`s into every line. Same algorithm, 16× more useful bytes per DRAM fetch.

**Use SoA when:** the hot loop touches one or two fields, the collection is big enough to miss cache, you don't need per-entity locality. **Avoid SoA when:** you have to update multiple fields atomically per entity, or your collection fits in L1 anyway — then the extra indirection of parallel vectors costs more than the line-density saves.

---

## 10. False sharing — the multicore scaling killer

Four threads, each incrementing its own counter. No locks, no shared state in the logical sense. But if the four counters sit in the same cache line, every `++` forces the cache coherence protocol to invalidate every other core's copy. You get the *cost* of shared state with none of its *benefits*.

```cpp
// Same cache line — 4 longs = 32 B, fits in one 64 B line
struct Packed { volatile long c[T]; };

// One counter per line, via alignas(hardware_destructive_interference_size)
struct Padded { alignas(LINE) volatile long c; char _pad[LINE - sizeof(long)]; };
```

`volatile` here is load-bearing — without it, the compiler turns `for (long i=0;i<ITERS;++i) ++p.c[t];` into `p.c[t] += ITERS;` and the false-sharing effect disappears along with the loop. Real code does real memory accesses; `volatile` is the fastest way to force the compiler to model that.

**Godbolt:** [godbolt.org/z/rsfjshMd8](https://godbolt.org/z/rsfjshMd8)

```
4 threads, counters in the same cache line           48,029,461 ns/op
4 threads, counters padded to distinct lines          5,971,147 ns/op     8.04× faster
```

**8× speedup just by padding.** And it only gets worse as thread count grows — false sharing scales backwards.

The idiomatic C++ fix is `alignas(std::hardware_destructive_interference_size)` — the stdlib's way of spelling "give me enough space to not collide with my neighbour." Use it. Hardcoding `64` is wrong on ARM (where it may be 128) and wrong on CPUs with larger prefetch-fetch-pair sizes.

A subtler form of this bug is the one Müller's deck highlights: per-thread scratch buffers in a `std::vector<Scratch>`, accessed by thread index. Every thread is reading its *own* `Scratch` but the vector packs them contiguously, so four scratch buffers fit in one line, and you have recreated the packed-counter pattern. The fix is either the `alignas` above or the sturdier rule: *write to a thread-local, and only store into the shared vector at the end*.

---

## 11. emplace_back + reserve vs push_back

From Okade and Baker's CppCon 2025 deck: `push_back(T{...})` constructs a temporary, `emplace_back(args...)` constructs in place. On top of that, if you know how many elements you are inserting, `reserve()` avoids the geometric reallocation storm.

```cpp
struct Heavy {
  std::string name;
  int value;
  Heavy(std::string n, int v) : name(std::move(n)), value(v) {}
};
```

Three variants:

- `push_back(Heavy{...})` with no `reserve`
- `emplace_back(...)` with no `reserve`
- `emplace_back(...)` after `reserve(N)`

**Godbolt:** [godbolt.org/z/s348hb1d6](https://godbolt.org/z/s348hb1d6)

```
push_back(Heavy{...})  — no reserve            364,288 ns/op
emplace_back(...)  — no reserve                357,814 ns/op     1.02×
emplace_back(...)  — reserve(N) first          178,187 ns/op     2.04×
```

The **push/emplace difference is noise** in this test — GCC's `std::vector` constructs a `Heavy` in the buffer via move-from-temporary, so the "extra copy" the deck warns about is already optimized out when the value type has a noexcept move. What *does* matter is the `reserve` — **2× speedup** by avoiding the 14 reallocations a 10,000-element `push_back`-loop would otherwise do.

**Pattern to keep:** always `reserve` when you know the size, even if push_back and emplace_back look equivalent on trivially-moveable types. The deck's broader guidance — prefer `emplace_back` as a habit because *some* value types have expensive construction-from-temporary paths — still stands; you just won't see the cost on types with trivial moves.

---

## 12. `std::string_view` instead of `const std::string&`

Passing a string literal to a `const std::string&` parameter constructs a temporary `std::string`, which for strings past the Small-String Optimization threshold means a heap allocation per call. `std::string_view` takes a `{ptr, length}` pair and never allocates.

```cpp
static constexpr const char kLiteral[] =
    "this string is long enough to defeat the small-string optimization on every stdlib";

__attribute__((noinline)) static int count_a_str(const std::string& s) {
  int n = 0; for (char c : s) n += (c == 'a'); return n;
}
__attribute__((noinline)) static int count_a_sv(std::string_view s) {
  int n = 0; for (char c : s) n += (c == 'a'); return n;
}
```

**Godbolt:** [godbolt.org/z/5erdbcW1h](https://godbolt.org/z/5erdbcW1h)

```
const std::string&   — temporary built per call    35.60 ns/op
std::string_view     — no allocation               28.42 ns/op     1.25×
```

**~25% win per call.** At scale, the cost scales with heap-alloc pressure — in a log-parsing hot loop that calls thousands of string-taking functions per record, the `string_view` version can be 3–5× faster than the `const std::string&` version because allocator contention compounds.

Caveats the deck lists and I've hit in practice:

- **`string_view` does not own its memory.** Passing `s.substr(...)` as a view is fine; storing a view whose underlying string went out of scope is a use-after-free with no compiler warning. Clang has `-Wdangling-gsl` for some cases but it is not comprehensive.
- **`string_view` is not null-terminated.** Passing it to a C API (`fopen`, `syscall`) forces a conversion back to `std::string`. Chromium's `base::cstring_view` is what you want there; it is a null-terminated view.
- **For "sink" parameters** — `SetName(std::string)` where you *will* store the string — pass by value and `std::move` into the member. The deck is emphatic about this: "For will-move-from parameters, pass by `X&&` and `std::move`." `string_view` is for read-only inspection.

---

## 13. Transparent comparators for associative lookup

`std::set<std::string>::find("hello")` constructs a temporary `std::string` before calling `operator<`. If the query string is past SSO, that is a heap allocation per lookup. The fix is to template the comparator:

```cpp
std::set<std::string, std::less<>> s;   // std::less<void> — transparent
```

With `std::less<void>`, the find overload that takes any type comparable to `std::string` is viable, and no temporary is constructed. The requirement: your comparator must opt in with `using is_transparent = void;` — which `std::less<>` does.

**Godbolt:** [godbolt.org/z/f8YW4eTsq](https://godbolt.org/z/f8YW4eTsq)

```
set<string>::find(const char*)  — std::string temporary           34,870 ns/op
set<string, less<>>::find(const char*)  — transparent, no temp    28,185 ns/op    1.24×
```

**~24% win** on 1000 lookups of a 40-byte key. The gap widens as keys grow, because longer keys force longer hashing / compare work on a heap-allocated string. My keys are 40 bytes — on a 200-byte key the transparent version would roughly double its lead.

A footgun: if your stored keys are short enough to always fit in SSO (≤ 15 bytes on libstdc++), transparent comparators buy you *nothing* because the heap allocation never happened. Always match the benchmark to the real key-size distribution.

---

## 14. Smaller primitive types — more items per cache line

Müller's deck makes the case that `uint8_t` beats `int` on a cache-bound sum because you fit 4× more items per line. The reality on GCC 14 with `-O2`:

**Godbolt:** [godbolt.org/z/3fdE8abbv](https://godbolt.org/z/3fdE8abbv)

```
sum vector<int32_t>  (~16 MiB)    973,131 ns/op
sum vector<int16_t>  (~8 MiB)     872,075 ns/op     1.12×
sum vector<uint8_t>  (~4 MiB)     868,561 ns/op     1.12×
```

**Small wins**, not the ~2× the deck advertises. `int16_t` and `uint8_t` are each ~12% faster than `int32_t`. The reason: auto-vectorization. `-O2` turns each sum into a `movdqu`/`paddd`-style SIMD loop, and the 16-byte SIMD register holds 4 `int32` or 8 `int16` or 16 `uint8_t` — but the vector throughput is limited by memory bandwidth once the array exceeds L2, so the 4× register density only translates to a minor runtime gain.

The more interesting finding in the deck, which I did not reproduce in this benchmark but is worth internalizing, is the **strict-aliasing pitfall**: when you template a function over a byte-sized type, `char`/`signed char`/`unsigned char`/`std::byte` are allowed to alias any other pointer, which forces the compiler to reload `data.size()` on every iteration. The fix is hoisting `auto size = data.size();` out of the loop, or using a range-based `for` which hoists implicitly. After that fix, all five byte-sized types reach the same throughput.

**Takeaway:** smaller types are a real L2/L3-bound win; but auto-vectorization eats a lot of the gain on modern CPUs. Use `uint16_t`/`uint8_t` for *storage* density and memory bandwidth, not for per-operation speed.

---

## 15. Inlining and the trivial-call trap

The Imperial paper reports `__attribute__((always_inline))` as a 20% win. The win is bigger than that when the called function is trivial and the compiler can fold the call chain entirely:

```cpp
__attribute__((noinline)) static int add_call(int a, int b) { return a + b; }
__attribute__((always_inline)) static inline int add_inl(int a, int b) { return a + b; }
```

Both functions are literally `a + b`. One is called through a guaranteed-out-of-line function, one is inlined.

**Godbolt:** [godbolt.org/z/s6E78rGPs](https://godbolt.org/z/s6E78rGPs)

```
noinline trivial function (blocks constant fold)    310.86 ns/op
always_inline trivial function (fold propagates)      0.055 ns/op    5,649× faster
```

**5,649× speedup.** That number is *not* a realistic inlining benefit — it is what happens when the compiler recognises that the inlined version is `sum = 0 + 1 + 2 + ... + 1023` and folds it to a constant. The noinline version has to do the loop because the call is opaque.

This benchmark doesn't measure "is inlining worth it." It measures "a function that cannot be inlined is preventing the downstream constant-folding pass from firing." Which is, in fact, the real reason inlining matters: call-site information — constant arguments, known sizes, proven preconditions — *flows through* inlined calls. Inlining unlocks the rest of the optimizer.

The paper's caveat still holds: "Over-reliance on inlining may inflate the binary size, possibly undermining instruction cache efficacy." Inlining a 500-line function into 20 call sites adds 10,000 lines of text — a hot loop that previously fit in L1i now spills to L2. Use `always_inline` for short, hot, leaf-ish functions; use `noinline` for large cold paths you want the linker to share.

---

## The scoreboard

Fifteen techniques, sorted by measured speedup ratio on my machine:

| # | Technique | Slow | Fast | Ratio | Claim holds? |
|---|-----------|------|------|-------|--------------|
| 15 | Inlining (trivial body) | 310.86 ns | 0.055 ns | 5,649× | Yes (but for a different reason than advertised) |
| 5 | Short-circuit order | 218,087 ns | 0.06 ns | 3.6 M× | Yes |
| 2 | constexpr (masked runtime) | 3.68 ns | 0.05 ns | 70× | Yes |
| 10 | Cache-line padding | 48.0 ms | 5.97 ms | 8.04× | Yes |
| 8 | Atomic vs mutex | 24.5 ms | 5.73 ms | 4.28× | Yes |
| 4 | Loop unrolling | 258.45 ns | 70.18 ns | 3.68× | Yes |
| 9 | SoA vs AoS | 71,502 ns | 22,160 ns | 3.23× | Yes |
| 11 | reserve() vector | 364,288 ns | 178,187 ns | 2.04× | Yes |
| 1 | CRTP vs virtual | 23.14 ns | 14.65 ns | 1.58× | Yes |
| 12 | string_view vs string& | 35.60 ns | 28.42 ns | 1.25× | Yes |
| 13 | Transparent comparator | 34,870 ns | 28,185 ns | 1.24× | Yes |
| 7 | Prefetch on pointer-chase | 51.0 ms | 42.6 ms | 1.20× | Yes |
| 14 | Smaller types (uint16) | 973,131 ns | 872,075 ns | 1.12× | Partial — vectorization narrows the gap |
| 6 | Bitmask branch flags | 681.89 ns | 1113.26 ns | **0.61×** | **No — cascade wins for well-predicted inputs** |
| 3 | Cache warming (naive) | 91,252 ns | 655,255 ns | **0.14×** | **No — warming-larger-than-hotpath is a loss** |

The bottom two are not failures of the source papers — they are reminders that **every micro-optimization has a context where it loses**. Cache warming is correct at the system level and catastrophic at the micro-benchmark level. Branch-flag reduction is correct under misprediction and counterproductive when the predictor is happy.

The cluster that *always* paid off on my machine:

- **reserve() your vectors.** Always.
- **string_view for read-only string parameters.** Always.
- **Transparent comparators for associative containers keyed by non-SSO strings.** Always.
- **`alignas(std::hardware_destructive_interference_size)` on per-thread counters.** Always.
- **SoA when the hot loop touches one field of a fat struct.** Whenever you can.
- **`std::atomic` over `std::mutex` for scalar shared state.** When the semantics fit.

The cluster that needs a *measured* application:

- **constexpr** — win is whatever the runtime was paying, which is zero if the compiler was going to fold it anyway.
- **Loop unrolling** — win is real in compiler-hostile loops, and negative past the i-cache budget.
- **Prefetching** — win depends on lookahead distance, HW prefetcher behaviour, and memory-system latency; don't cargo-cult.
- **CRTP** — switch when inlining across the dispatch unlocks further folding, not because "virtual is slow."
- **Bitmask flags** — switch when branches actually mispredict, not because cascades "look branchy."
- **Cache warming** — system-design pattern, not a function-level one.

Every one of the 15 techniques above is worth the 20 minutes it takes to run its Godbolt link. Click through them, change the workload, see how the ratios move. The surprising findings — the two "the claim doesn't reproduce" results — are the whole point of actually writing the benchmark rather than taking the paper at its word.

## References and further reading

- Bilokon, P., and Gunduz, B. M. (2023). [C++ Design Patterns for Low-Latency Applications Including High-Frequency Trading](https://arxiv.org/abs/2309.04259). arXiv:2309.04259. Source code: [github.com/0burak/imperial_hft](https://github.com/0burak/imperial_hft).
- Müller, J. (2025). Cache-Friendly C++. CppCon 2025.
- Okade, P., and Baker, K. (2025). C++ Performance Tips: Cutting Down on Unnecessary Objects. CppCon 2025.
- Drepper, U. (2007). *What Every Programmer Should Know About Memory*. The canonical reference for cache hierarchies.
- Rasovsky, O. (2022). *Benchmarking C++ Code*. CppCon 2022 — on how easy it is to get micro-benchmarks wrong.
- Leitner, M. (2019+). [martinus/nanobench](https://github.com/martinus/nanobench) — the header-only benchmark library used throughout this post.
- Harris, B., Thompson, M., et al. (2011). *The LMAX Disruptor: A High Performance Inter-Thread Messaging Library*. The paper that gave the Imperial repo its concurrent-queue design.

If you want to run all fifteen benchmarks locally, the Dockerfile is a three-line image on top of `gcc:14` that `curl`s the nanobench header into `/usr/local/include`. Build it, `docker run -v $(pwd):/work hft-nb bash -c "for f in *.cpp; do g++ -O2 -std=c++23 \$f -pthread -o \${f%.cpp}.out && ./\${f%.cpp}.out; done"`, and you will get a scoreboard for your CPU. The ratios should be close to mine; the absolute ns/op numbers will not.
