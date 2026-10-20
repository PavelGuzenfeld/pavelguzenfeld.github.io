---
title: 'ZII and Arena Allocators in C++: Zero Is Initialization, Benchmarked'
date: 2026-10-20
draft: false
cover:
  image: /images/posts/cpp-zii-arena-allocator.png
  alt: 'A bump arena allocates a frame of 1000 objects about 10x faster than malloc and free'
tags:
- C++
- memory
- performance
- benchmarking
- real-time
keywords:
- zero is initialization
- ZII vs RAII
- arena allocator C++
- bump allocator
- linear allocator
- region allocator
- per-frame scratch arena
- std::pmr::monotonic_buffer_resource
- monotonic_buffer_resource benchmark
- malloc vs arena benchmark
- nanobench
categories:
- deep-dive
summary: 'ZII designs every type so all-zero bytes is a valid default, and pairs it with
  arenas that free a whole group at once. RAII ties cleanup to each object. Here is how
  the two differ, where ZII falls short, a 20-line arena, and a nanobench run of
  1000 allocations per frame: arena, std::pmr, malloc, calloc and new, with a live
  Godbolt session. Plus the same frame as a struct of arrays.'
ShowToc: true
audio:
  pronunciation:
    ZII: Z I I
    RAII: R A I I
    std::pmr::monotonic_buffer_resource: S T D P M R monotonic buffer resource
    monotonic_buffer_resource: monotonic buffer resource
    std::pmr::vector: S T D P M R vector
    memory_resource: memory resource
    pmr: P M R
    arena_push: arena push
    arena_reset: arena reset
    push_zeroed: push zeroed
    memset: mem set
    memcpy: mem copy
    calloc: C alloc
    malloc: M alloc
    alignof: align of
    unique_ptr: unique pointer
    lock_guard: lock guard
    nullptr: null pointer
    nanobench: nano bench
    Godbolt: god bolt
    POD: P O D
    DeepStream: Deep Stream
    0xCD: hex C D
---

**ZII ("Zero Is Initialization")** is a design convention, popularized by Casey Muratori and the Handmade community, where you design every type so that **all-bytes-zero is a valid, meaningful default state**. **RAII** is C++'s convention of tying resource lifetime to object lifetime through constructors and destructors. They answer different questions. RAII is about *who cleans up and when*. ZII is about *what a freshly obtained object means before anyone touches it*.

## RAII in one paragraph

Each object owns its resources. The constructor acquires them and establishes invariants, and the destructor releases them. Lifetimes are granular, one object at a time, and the compiler guarantees cleanup on every exit path, including early returns and exceptions. Ownership is encoded in types (`unique_ptr`, `lock_guard`, a `File` class).

## What ZII looks like

```cpp
struct Track {
    uint32_t id;          // 0 = "no track"
    float    pos[3];      // origin is a fine default
    float    cov[9];      // zero cov is flagged by valid==false anyway
    uint8_t  valid;       // 0 = inactive slot
    uint32_t miss_count;
};

Track tracks[MAX_TRACKS] = {};   // the whole table is ready to use
```

There is no constructor, no `init()`, and no "half-constructed" state. `memset(&x, 0, sizeof x)`, `= {}`, `calloc`, and fresh OS pages are all correct initialization. The type stays trivially copyable and POD.

ZII usually comes with a few companion ideas:

- **Arenas instead of per-object ownership.** You allocate many things from one arena and free them all at once (per frame, per request, per level). Lifetime is managed for *groups*, not individuals, so most objects need no destructor at all.
- **Nil/stub objects instead of null.** A failed lookup returns a pointer to a shared zeroed object rather than `nullptr`. Callers can read from it harmlessly ("empty track, valid=0") without checking at every step.
- **Handles/indices instead of owning pointers.** Index 0 is reserved as "none."

## The core disagreement

The RAII view says: *make invalid states unrepresentable, and let the compiler enforce cleanup per object.*

The ZII view says: *most objects don't own anything individually. Per-object acquire/release creates thousands of tiny failure points and scattered allocations. Group lifetimes, make the default state useful, and the problem largely disappears.*

| | RAII | ZII |
|---|---|---|
| Default state | Whatever the constructor establishes | All zeros, by design |
| Lifetime granularity | Per object | Per group (arena, frame, pool) |
| Cleanup | Destructor, automatic | Bulk reset, or nothing |
| Failure handling | Throw or error at acquisition | Return zeroed/nil object, keep going |
| Invariants | Enforced by constructor | By convention, since zero must mean something sane |
| Bulk ops | Must run ctors/dtors | `memset`/`memcpy` are valid |

## Where ZII falls short

- **Zero isn't always meaningful.** An ID of 0, a divisor, a quaternion (zero isn't the identity rotation), or a covariance matrix (zero means "infinitely certain," which is dangerous in a filter) all need care. You end up adding `valid` flags or storing values offset from zero.
- **Silent failures.** Nil objects mean a bug can read plausible-looking zeros instead of crashing. That keeps the program running in production but makes it harder to debug.
- **Non-memory resources still need real release.** File descriptors, sockets, mutexes, CUDA streams, and DeepStream/GStreamer elements have to be closed explicitly. Arenas don't help with those.
- **Weaker type guarantees.** Nothing stops someone from reading a field that should have been set.

## They combine well

In practice the strongest C++ designs often use both: **RAII at the boundary, ZII inside.** The arena itself, the GPU context, and the file handle are RAII objects. The data structures allocated inside the arena are zero-initializable PODs with no destructors.

This mix fits a hard-real-time loop like a 50 Hz tracker especially well. You can use a per-cycle scratch arena that resets every 20 ms, keep fixed-size zero-initialized state tables, and do no heap allocation on the hot path. The setup and teardown of Jetson/DeepStream resources stay RAII, while the per-frame track and measurement data are pure ZII.

## What an arena is

An **arena** (also called a region, bump allocator, or linear allocator) is a large block of memory you allocate once, then hand out pieces of by just moving a pointer forward. You never free individual objects. You free **everything at once**, by resetting the pointer back to the start.

### The whole idea in ~20 lines

```cpp
struct Arena {
    uint8_t* base;
    size_t   capacity;
    size_t   used;
};

void* arena_push(Arena* a, size_t size, size_t align = alignof(std::max_align_t)) {
    size_t start = (a->used + (align - 1)) & ~(align - 1);   // round up to alignment
    if (start + size > a->capacity) return nullptr;           // or assert / fallback
    a->used = start + size;
    return a->base + start;
}

void arena_reset(Arena* a) { a->used = 0; }   // "free" everything, O(1)

template <typename T>
T* push_zeroed(Arena* a, size_t count = 1) {
    void* p = arena_push(a, sizeof(T) * count, alignof(T));
    if (p) std::memset(p, 0, sizeof(T) * count);              // ZII: zero is valid
    return static_cast<T*>(p);
}
```

That's the entire allocator. Allocation is a few instructions: align, add, and compare. Freeing is one store.

### Why it works

Most allocations in a program aren't independent. They share a lifetime with a whole group of other allocations: everything for this frame, this request, this parse, or this level. A general-purpose `malloc`/`new` pays to track each object individually (headers, free lists, fragmentation handling, thread locking) and then makes you release each one. An arena accepts that the group lives and dies together, so it tracks nothing per object.

### What you get

- **Speed.** Allocation is a pointer bump, and reset is O(1) regardless of how many objects you made.
- **Determinism.** There are no syscalls, locks, or free-list walks on the hot path, so timing is predictable, which matters a lot under a hard deadline.
- **No leaks or double-frees within the group.** There's nothing to forget to free.
- **Locality.** Objects allocated together sit next to each other in memory, which is cache-friendly.
- **Simpler code.** Functions can allocate freely without ownership plumbing, because the caller decides the lifetime by choosing which arena to pass in.

### The common lifetime patterns

**Scratch / per-frame arena.** You reset it at the end of every cycle. In a 50 Hz loop, all per-frame temporaries (detections, gating candidates, association matrices, intermediate buffers) come from it, and `arena_reset` runs once at the end of the 20 ms tick. The steady state is zero heap traffic.

**Persistent arena.** This one holds things that live for the whole run, such as configuration, lookup tables, and the track table. You allocate them at startup and never reset it.

**Temporary scope within an arena.** You save `used`, do some work, then restore it. This acts as a stack-like nested lifetime:

```cpp
size_t mark = scratch.used;
auto* tmp = push_zeroed<float>(&scratch, n * n);
// ... use tmp ...
scratch.used = mark;   // pop just this chunk
```

### Limitations

- **No individual free.** If objects have truly independent, unpredictable lifetimes, an arena is the wrong tool. Use a pool (fixed-size slots with a free list) or the general heap.
- **Capacity must be planned.** You either size for the worst case or support chaining new blocks when one fills. In real-time code, the usual choice is a fixed worst-case size plus an assert or high-water-mark logging, so you learn about overflow during testing instead of in production.
- **Destructors don't run.** Anything placed in an arena should be trivially destructible (which is why it pairs with ZII and POD types). An object that owns a file, a mutex, or a `std::vector` with its own heap buffer will leak that resource on reset.
- **Dangling pointers after reset.** A pointer into last frame's scratch arena is invalid after the reset, and nothing will warn you. A common debug aid is filling the arena with a poison pattern like `0xCD` on reset, so stale reads show up immediately.

### Relation to standard C++

C++17 has this built in as `std::pmr::monotonic_buffer_resource`. You can back it with a fixed buffer and use `std::pmr::vector` and similar containers on top, which gives you arena allocation while keeping standard containers. Calling `release()` frees everything at once. It's heavier than a hand-rolled bump allocator, since every allocation goes through the virtual `memory_resource::allocate` interface, but it's a reasonable middle ground when you want STL containers without per-element heap allocation in the loop. How much heavier is measured below.

## Benchmark: one frame of 1000 allocations

The workload is one frame of a scratch arena. Allocate 1000 32-byte `Detection` structs, write two fields into each, then free all of them. The heap variants keep the pointers and free them at the end of the frame, so they do the same group-lifetime work the arena does.

- `new / delete`: `new Detection{}` per object, then `delete` each.
- `malloc / free` and `calloc / free`: the same with the C allocator.
- `arena_push / arena_reset`: the arena above, no zeroing.
- `push_zeroed / arena_reset`: the arena with ZII zeroing.
- `pmr::monotonic_buffer_resource / release`: the standard resource over a fixed 64 KiB buffer, with `null_memory_resource()` upstream. If `release()` ever failed to reuse the buffer, the next frame would throw instead of quietly measuring the heap. The resource pointer comes from `get_default_resource()`, so the loop only has a `memory_resource*`, the same as a `pmr` container.

GCC 14.4, `-O2 -std=c++23`, an i7-12700H pinned to one core, nanobench. Median of three runs:

| variant | ns/frame | ns per allocation | vs malloc |
|---|---:|---:|---:|
| `new / delete` | 9,774 | 9.8 | 0.78x |
| `malloc / free` | 7,650 | 7.7 | 1.0x |
| `calloc / free` | 9,187 | 9.2 | 0.83x |
| `arena_push / arena_reset` | 797 | 0.8 | 9.6x |
| `push_zeroed / arena_reset` | 928 | 0.9 | 8.2x |
| `pmr::monotonic_buffer_resource / release` | 2,003 | 2.0 | 3.8x |

The arena is about 10x faster than `malloc` and `free`. Zeroing every object costs about 0.13 ns per allocation on top of the bump, so ZII is close to free here. `calloc` costs about 1.5 ns more than `malloc` per object for the same zeroing.

`monotonic_buffer_resource` takes 2.5x the time of the hand-rolled arena. That's more than "slightly heavier", but it is still almost 4x faster than the heap. In the disassembly GCC doesn't actually make an indirect call. It devirtualizes speculatively: each allocation loads the vtable slot, compares it with `monotonic_buffer_resource::do_allocate`, and on a match runs an inlined copy built on `std::align`. I didn't break down where the rest of the 1.2 ns goes.

This is the best case for `malloc`: one thread, one size class, and freed blocks go straight back into glibc's per-thread cache. I didn't measure mixed sizes, several threads or a fragmented heap. None of them help `malloc`, and the arena numbers don't depend on any of them.

The same program on Compiler Explorer:

{{< godbolt id="3MKc8zKvh" height="640" >}}

Godbolt runs on shared machines, so its numbers are slower and noisier than the table. On one run there, the arena was about 4x faster than `malloc` and `pmr` about 2.5x. The ordering is the same.

## Struct of arrays instead of array of structs

One allocation per object is the worst case for the heap. If the frame keeps its detections as a struct of arrays, one column per field, it needs 8 allocations instead of 1000:

```cpp
struct Detections {
    float*    box_x0;
    float*    box_y0;
    float*    box_x1;
    float*    box_y1;
    float*    score;
    uint32_t* class_id;
    uint32_t* track_id;
    uint32_t* flags;
};
```

Each variant allocates the 8 columns of 1000 elements, writes `score` and `class_id`, then frees them. Same machine, median of three runs:

| layout and allocator | allocations per frame | ns/frame |
|---|---:|---:|
| AoS, `malloc` per object | 1000 | 7,787 |
| AoS, one `malloc` per frame | 1 | 344 |
| SoA, `malloc` per column | 8 | 621 |
| SoA, `arena_push` per column | 8 | 443 |
| SoA, `push_zeroed` per column | 8 | 613 |
| SoA, pmr per column | 8 | 462 |

Cutting the number of allocations matters more than the allocator. With 8 calls, `malloc` and `free` add about 180 ns per frame over the arena, and the arena's lead drops from about 10x to about 1.4x. Each call does cost more: a 4000-byte `malloc`/`free` pair comes to about 22 ns, against about 8 ns at 32 bytes. I didn't find out why. Raising `glibc.malloc.tcache_max` to 4096 changed nothing.

Zeroing costs more here: `push_zeroed` clears all 32 KB of columns, about 170 ns, even though the loop writes only two of them. With SoA you can zero only the columns whose zero means something.

One caveat about the fill loop. It is `[[gnu::noinline]]` in this benchmark so every variant runs the same code. When I let it inline, GCC vectorized the copy in the `malloc` variant and not the copies in the arena and pmr variants (`-fopt-info-vec-all` says so). SoA with `malloc` then came out at about 300 ns, ahead of the arena. I didn't find the reason, and `__restrict` locals and a 32-bit loop counter didn't change it. SoA is supposed to pay off through vectorization, so check the vectorizer report instead of assuming you got it.

{{< godbolt id="7daeoeq5h" height="640" >}}

## The full program

```cpp
#define ANKERL_NANOBENCH_IMPLEMENT
#include <nanobench.h>

#include <array>
#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <memory_resource>

struct Detection {
    float    box[4];
    float    score;
    uint32_t class_id;
    uint32_t track_id;
    uint32_t flags;
};

struct Arena {
    uint8_t* base;
    size_t   capacity;
    size_t   used;
};

void* arena_push(Arena* a, size_t size, size_t align = alignof(std::max_align_t)) {
    size_t start = (a->used + (align - 1)) & ~(align - 1);
    if (start + size > a->capacity) return nullptr;
    a->used = start + size;
    return a->base + start;
}

void arena_reset(Arena* a) { a->used = 0; }

template <typename T>
T* push_zeroed(Arena* a, size_t count = 1) {
    void* p = arena_push(a, sizeof(T) * count, alignof(T));
    if (p) std::memset(p, 0, sizeof(T) * count);
    return static_cast<T*>(p);
}

constexpr size_t detections_per_frame = 1000;
constexpr size_t arena_bytes = 64 * 1024;

alignas(std::max_align_t) static uint8_t arena_storage[arena_bytes];
alignas(std::max_align_t) static uint8_t pmr_storage[arena_bytes];
static std::array<Detection*, detections_per_frame> frame;

static void touch(Detection* d, size_t i) {
    d->score = static_cast<float>(i);
    d->class_id = static_cast<uint32_t>(i);
    ankerl::nanobench::doNotOptimizeAway(d);
}

int main() {
    ankerl::nanobench::Bench bench;
    bench.title("1000 x 32-byte allocations per frame, then free all")
        .unit("frame")
        .relative(true)
        .minEpochIterations(2000)
        .warmup(100);

    bench.run("new / delete", [] {
        for (size_t i = 0; i < detections_per_frame; ++i) {
            frame[i] = new Detection{};
            touch(frame[i], i);
        }
        for (Detection* d : frame) delete d;
    });

    bench.run("malloc / free", [] {
        for (size_t i = 0; i < detections_per_frame; ++i) {
            frame[i] = static_cast<Detection*>(std::malloc(sizeof(Detection)));
            touch(frame[i], i);
        }
        for (Detection* d : frame) std::free(d);
    });

    bench.run("calloc / free", [] {
        for (size_t i = 0; i < detections_per_frame; ++i) {
            frame[i] = static_cast<Detection*>(std::calloc(1, sizeof(Detection)));
            touch(frame[i], i);
        }
        for (Detection* d : frame) std::free(d);
    });

    Arena arena{arena_storage, arena_bytes, 0};

    bench.run("arena_push / arena_reset", [&] {
        for (size_t i = 0; i < detections_per_frame; ++i) {
            frame[i] = static_cast<Detection*>(arena_push(&arena, sizeof(Detection), alignof(Detection)));
            touch(frame[i], i);
        }
        arena_reset(&arena);
    });

    bench.run("push_zeroed / arena_reset", [&] {
        for (size_t i = 0; i < detections_per_frame; ++i) {
            frame[i] = push_zeroed<Detection>(&arena);
            touch(frame[i], i);
        }
        arena_reset(&arena);
    });

    std::pmr::monotonic_buffer_resource pmr{pmr_storage, arena_bytes, std::pmr::null_memory_resource()};
    std::pmr::set_default_resource(&pmr);
    std::pmr::memory_resource* resource = std::pmr::get_default_resource();

    bench.run("pmr::monotonic_buffer_resource / release", [&] {
        for (size_t i = 0; i < detections_per_frame; ++i) {
            frame[i] = static_cast<Detection*>(resource->allocate(sizeof(Detection), alignof(Detection)));
            touch(frame[i], i);
        }
        pmr.release();
    });
}
```
