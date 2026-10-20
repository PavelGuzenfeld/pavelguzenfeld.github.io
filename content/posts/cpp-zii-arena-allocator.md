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
  Godbolt session. Plus a struct-of-arrays layout, a Cortex-A78AE run, and the
  Jetson Orin GPU, then one CPU+GPU frame that uses all of it: 3.3x faster per frame.'
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
    '0xCD': hex C D
    cudaMallocAsync: CUDA malloc async
    cudaFreeAsync: CUDA free async
    cudaMemsetAsync: CUDA memset async
    cudaStreamSynchronize: CUDA stream synchronize
    cudaMalloc: CUDA malloc
    cudaFree: CUDA free
    atomicAdd: atomic add
    sm_87: S M 87
    nvcc: N V C C
    µs/frame: microseconds per frame
    µs: microseconds
    'nvcc -O2 -std=c++17 -arch=sm_87 -I. gpu_bench.cu': N V C C at O2, C plus plus 17, for S M 87
    null_memory_resource(): null memory resource
    get_default_resource(): get default resource
    monotonic_buffer_resource::do_allocate: the monotonic buffer resource allocate function
    do_allocate: do allocate
    std::align: S T D align
    glibc.malloc.tcache_max: the glibc tcache max setting
    '[[noinline]]': marked no inline
    __restrict: restrict
    -fopt-info-vec-all: the vectorizer report flag
    '::operator new / ::operator delete': operator new and operator delete
    '::operator new': operator new
    class_id: class I D
    bad_alloc: bad alloc
    new_op.cc: new op dot C C
    cudaMallocHost: CUDA malloc host
    cudaFreeHost: CUDA free host
    cudaStreamDestroy: CUDA stream destroy
    cudaMemcpy: CUDA memcpy
    compute-sanitizer --tool memcheck: compute sanitizer memcheck
    select_hits: select hits
    device_frame: device frame
    pinned_frame: pinned frame
    DeviceArena: device arena
    DeviceBytes: device bytes
    PinnedBytes: pinned bytes
    'nvcc -O2 -std=c++17 -arch=sm_87 -I. gpu_together.cu': N V C C at O2, C plus plus 17, for S M 87
    -static-libstdc++: static lib S T D C plus plus
    malloc(0): M alloc of zero
    nanobench.h: the nanobench header
    libstdc++: lib S T D C plus plus
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

```
+--------------------------------------------------------------+
| RAII boundary: constructors acquire, destructors release     |
|                                                              |
|   GpuContext   Pipeline   File / Socket   Arena (owns block) |
|                                             |                |
|  +------------------------------------------v-------------+  |
|  | ZII inside: zeroed PODs, no destructors                |  |
|  |                                                        |  |
|  |   Track tracks[MAX_TRACKS] = {};   persistent arena    |  |
|  |   detections, gating, temps        scratch arena,      |  |
|  |                                    reset every frame   |  |
|  +--------------------------------------------------------+  |
+--------------------------------------------------------------+
```

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

```
base                                    used                    capacity
 |                                        |                          |
 v                                        v                          v
 +--------+--+-----------+--------+-------+--------------------------+
 | Track  |pd| Detection | float[]| ...   |        free space        |
 +--------+--+-----------+--------+-------+--------------------------+
            ^
            alignment padding

 arena_push(size):  start = align_up(used); used = start + size
 arena_reset():     used = 0     (every allocation is "freed" at once)
```

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

```
 tick n                      tick n+1                    tick n+2
 |<------- 20 ms ------->|   |<------- 20 ms ------->|   |
 push push push ... reset    push push push ... reset    push ...
 scratch.used: 0 -> peak -> 0   0 -> peak -> 0             0 -> ...
```

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

### Why `new` is slower than `malloc`

`new / delete` came out about 2 ns per object slower than `malloc / free`. My first guess was the zeroing from `new Detection{}`. It isn't. Same frame, split up, median of three runs:

| variant | x86 ns/frame | Cortex-A78AE ns/frame |
|---|---:|---:|
| `malloc / free` | 7,792 | 34,318 |
| raw `::operator new / ::operator delete` | 9,529 | 37,416 |
| `new Detection / delete` | 9,564 | 37,487 |
| `new Detection{} / delete` | 9,653 | 38,027 |
| `calloc / free` | 8,736 | 37,475 |

Raw `::operator new`, which zeroes nothing, already has the whole gap. Zeroing adds about 0.1 ns per object on x86. The rest is the wrapper. This is libstdc++ 14 on x86-64:

```
operator new(size_t)              _Znwm
    test %rdi,%rdi; cmovne        new(0) must return a unique pointer, so 0 becomes 1
    call malloc@plt
    test %rax,%rax; je ...        on null: get_new_handler(), call it, retry or throw
    ret

operator delete(void*, size_t)    _ZdlPvm
    jmp operator delete(void*)@plt
operator delete(void*)            _ZdlPv
    jmp free@plt
```

The allocator underneath is the same glibc `malloc`. `new` adds a call, a trip through the PLT, a size check and a null check on the way in. Sized `delete` adds two PLT jumps on the way out. That comes to about 1.7 ns per object on x86, 22% of `malloc / free`, and about 3.1 ns on the Orin, 9%.

The wrapper is there because the standard asks `operator new` for things `malloc` doesn't promise. Each extra instruction pays for one:

- **Size 0 becomes 1.** `new` of zero bytes must return a unique non-null pointer. `malloc(0)` may return null.
- **The null check and the handler loop.** On failure `new` must call the installed new-handler, which may free memory, and retry. With no handler it throws `std::bad_alloc`. `malloc` just returns null.
- **The call into `libstdc++.so`.** The global `operator new` and `operator delete` are replaceable. Any program can define its own and it has to win at link time, so the compiler can't fold the call into `malloc`.
- **Sized `delete` forwarding.** Since C++14, `delete` passes the object size so an allocator can skip looking it up. glibc's `free` doesn't take it, so libstdc++ drops the size and forwards: two jumps for nothing on this stack. jemalloc, tcmalloc and mimalloc do use it.

The trade-off: you get an exception instead of a null you might forget to check, an out-of-memory policy hook, and a global allocator you can swap without touching call sites. You pay a couple of nanoseconds per pair, and that only matters on a path that allocates thousands of tiny objects per frame. That is the path where an arena removes both `malloc` and the wrapper. If you need the wrapper itself cheaper, you can define `operator new` and `operator delete` in your own binary, link with `-static-libstdc++`, or use an allocator that takes the size from sized `delete`. I didn't measure any of these. I didn't disassemble the aarch64 libstdc++.

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

```
AoS: 1000 allocations, each 32 bytes
 [box box box box score cls trk flg] [box box box box score cls trk flg] ...

SoA: 8 allocations, each 4000 bytes
 box_x0:   [x0 x0 x0 x0 x0 x0 ... 1000]
 box_y0:   [y0 y0 y0 y0 y0 y0 ... 1000]
 ...
 score:    [s  s  s  s  s  s  ... 1000]   <- the loop touches only these two
 class_id: [c  c  c  c  c  c  ... 1000]
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

## On ARM

I ran the same two programs on a Jetson Orin (Cortex-A78AE, aarch64). The compiler and C library are the same `gcc:14` image as the x86 run, so GCC 14.4, glibc 2.41, `-O2 -std=c++23`, pinned to one core. The core ran at its steady 1.5 GHz after a 60-second warmup. Median of three runs:

| variant | ns/frame | vs malloc |
|---|---:|---:|
| `new / delete` | 37,730 | 0.90x |
| `malloc / free` | 33,841 | 1.0x |
| `calloc / free` | 36,875 | 0.92x |
| `arena_push / arena_reset` | 4,846 | 7.0x |
| `push_zeroed / arena_reset` | 6,377 to 7,600 | 4.5x to 5.3x |
| `pmr::monotonic_buffer_resource / release` | 6,577 | 5.1x |

| struct of arrays | ns/frame |
|---|---:|
| AoS, one `malloc` per frame | 1,744 |
| SoA, `malloc` per column | 2,060 |
| SoA, `arena_push` per column | 1,349 |
| SoA, `push_zeroed` per column | 1,757 |
| SoA, pmr per column | 1,382 |

![Speedup over malloc and free on x86-64 and Cortex-A78AE: arena_push 9.6x and 7.0x, push_zeroed 8.2x and 4.5x, pmr 3.8x and 5.1x, calloc 0.8x and 0.9x, new 0.8x and 0.9x](/images/posts/cpp-zii-arena-allocator-speedup.svg)

The ordering holds. The arena is 7x faster than `malloc` here instead of about 10x, and `pmr` is much closer to the hand-rolled arena: 1.36x slower, against 2.5x on x86.

Zeroing is the odd one out. On x86 it cost 0.13 ns per object. On the Orin it costs 1.5 to 2.7 ns, and `push_zeroed` jumps between two values from run to run (6,377 and about 7,600). GCC inlines the zeroing as two `stp xzr, xzr` stores per object, with no `memset` call, so it isn't the call. I didn't find the cause.

## On the Jetson GPU

The same question comes up on the Orin's GPU, in two places. A kernel can allocate per thread with device-side `malloc`, and the host can allocate per-frame buffers with `cudaMalloc`. I measured both with CUDA 12.6, `-O2 -arch=sm_87`, built natively on the Orin. The host thread was pinned to one core, and the GPU stayed at 1.173 GHz under the default governor. Every frame ends with `cudaStreamSynchronize`, so the numbers are what a frame loop waits for. Median of three runs, all within 0.5%.

Inside a kernel, 1000 threads each allocate one 32-byte `Detection`, write two fields, and then everything is freed. The arena is a `DeviceArena` in device memory, and `arena_push` is a single `atomicAdd` on its `used` offset. A one-thread kernel resets it.

| variant | µs/frame |
|---|---:|
| empty kernel + sync (floor) | 14.6 |
| device `malloc` / `free` | 529.6 |
| device `arena_push` / reset | 18.2 |
| device `push_zeroed` / reset | 18.2 |

Device `malloc` costs about half a millisecond for 1000 allocations, 29x the arena. The arena row is two launches and sits about 3.6 µs above the one-launch floor. At a 20 ms frame budget, device `malloc` alone eats 2.6% of the frame before any real work. Zeroing 32 bytes per thread doesn't show up at all.

From the host, each frame allocates the 8 SoA columns of 1000 elements, runs one kernel that fills two of them, and frees them. The arena variants carve the columns out of one `cudaMalloc` buffer made at startup.

| variant | µs/frame |
|---|---:|
| `cudaMalloc` / `cudaFree` per column | 65.4 |
| `cudaMallocAsync` / `cudaFreeAsync` per column | 23.8 |
| host bump over one `cudaMalloc` buffer | 15.1 |
| host bump + `cudaMemsetAsync` of 32 KB (ZII) | 19.1 |

With the fill kernel and sync subtracted, `cudaMalloc` and `cudaFree` cost about 6.3 µs per column. The stream-ordered pool behind `cudaMallocAsync` cuts that to about 1.1 µs. I set its release threshold to keep all memory, so it never hands memory back to the driver. That pool is CUDA's own arena-style allocator, and it is the right default when buffers really change size from frame to frame. A fixed buffer carved by pointer arithmetic is still cheapest, at only 0.5 µs above the floor. Zeroing on the GPU is an extra stream operation, and `cudaMemsetAsync` over 32 KB adds about 4 µs per frame. That is the cost of ZII here, so zero only the columns whose zero means something.

![Jetson Orin GPU microseconds per frame: inside a kernel, device malloc 529.6 against 18.2 for the arena and a 14.6 floor; from the host, cudaMalloc 65.4, cudaMallocAsync 23.8, bump 15.1, bump plus memset 19.1](/images/posts/cpp-zii-arena-allocator-gpu.svg)

```
 device arena, one atomicAdd per thread
 thread 0 --+
 thread 1 --+--> atomicAdd(&arena->used, 32) --> base + old_used
 ...        |
 thread 999-+    one-thread kernel afterwards: arena->used = 0
```

Compiler Explorer can't run CUDA on a GPU, so there's no live session for this one. The full program is at the end.

## Putting it all together: CPU + GPU + arenas + SoA

What does it take to follow all of the advice above at once? Here is one frame of a detection pipeline on the Orin. The CPU produces 1000 detections. The GPU keeps the ones scoring at least 0.5, and the CPU reads the hits back. That is upload, filter, readback, every frame.

The usual first version allocates everything per frame: `malloc` for the host columns, `cudaMalloc` for every device buffer, pageable `cudaMemcpy` calls that each block, then `cudaFree` and `free`. The second version applies every rule in this post:

```
 RAII boundary, made once:   Stream      DeviceBytes block        PinnedBytes block
                                |              |                        |
 arenas inside, per frame:      |   +----------+-----------+   +--------+---------+
                                |   | DeviceArena header   |   | score[] x[] y[]  |  CPU writes SoA
                                |   | hits[] (kernel bump) |   | readback header  |
                                |   | score[] x[] y[]      |   | hits[]           |
                                |   +----------------------+   +------------------+
                                v
 one stream:  H2D x3 -> memset(header.used = 0) -> select_hits -> D2H x2 -> one sync
 end of frame: arena_reset(device_frame), arena_reset(pinned_frame)
```

- **RAII at the boundary.** The stream, one device block and one pinned host block are `unique_ptr`s with empty deleters (`cudaStreamDestroy`, `cudaFree`, `cudaFreeHost`), made once in `Pipeline`. Nothing is allocated in the loop.
- **Bump arenas inside them.** `device_frame` hands out the device input columns and `pinned_frame` the host staging and readback buffers. Both reset with one store at the end of the frame.
- **SoA where the loop is per field.** The CPU writes `score`, `x` and `y` as three columns, and the kernel reads `score` alone to decide. The output stays AoS: a `Hit` is consumed whole, so one record per hit is the right shape there.
- **A device arena for variable output.** The kernel doesn't know how many hits there will be. Each passing thread takes its slot with one `atomicAdd` on the output arena's `used`.
- **ZII for the reset.** An arena whose `used` is zero is empty, so resetting the device arena is `cudaMemsetAsync` of 8 bytes on the stream. There's no kernel and no host round trip.
- **Pinned memory, one stream, one sync.** The copies come from page-locked memory, so they are truly async and the CPU waits once per frame.

Same machine and method as before: CUDA 12.6, sm_87, host thread pinned to one core, median of three runs. Both versions return the same 500 hits per frame, and `compute-sanitizer --tool memcheck` reports 0 errors.

| one frame | µs/frame |
|---|---:|
| allocate per frame (`malloc`, `cudaMalloc`, pageable copies) | 126.6 |
| RAII owners + arenas + SoA (pinned, one stream, one sync) | 37.9 |

That is 3.3x for changing how memory is owned, with the kernel left exactly the same. This is every change at once, so the table doesn't say how much each rule contributes. From the host-side table above, `cudaMalloc` and `cudaFree` cost about 6.3 µs per buffer. That puts the five device buffers here at roughly 30 µs of the 89 µs gap. I didn't measure how the rest splits between the pageable copies, the extra syncs and the host `malloc`s.

The full program:

```cpp
#define ANKERL_NANOBENCH_IMPLEMENT
#include <nanobench.h>

#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <memory>
#include <new>

#include <cuda_runtime.h>

static void check(cudaError_t status, const char* what) {
    if (status != cudaSuccess) {
        std::fprintf(stderr, "%s: %s\n", what, cudaGetErrorString(status));
        std::exit(1);
    }
}

struct DeviceFree {
    void operator()(void* p) const noexcept { cudaFree(p); }
};
struct PinnedFree {
    void operator()(void* p) const noexcept { cudaFreeHost(p); }
};
struct StreamDestroy {
    void operator()(cudaStream_t s) const noexcept { cudaStreamDestroy(s); }
};

using DeviceBytes = std::unique_ptr<uint8_t, DeviceFree>;
using PinnedBytes = std::unique_ptr<uint8_t, PinnedFree>;
using Stream = std::unique_ptr<CUstream_st, StreamDestroy>;

DeviceBytes device_bytes(size_t size) {
    void* p = nullptr;
    check(cudaMalloc(&p, size), "cudaMalloc");
    return DeviceBytes{static_cast<uint8_t*>(p)};
}

PinnedBytes pinned_bytes(size_t size) {
    void* p = nullptr;
    check(cudaMallocHost(&p, size), "cudaMallocHost");
    return PinnedBytes{static_cast<uint8_t*>(p)};
}

Stream make_stream() {
    cudaStream_t s = nullptr;
    check(cudaStreamCreate(&s), "cudaStreamCreate");
    return Stream{s};
}

struct Arena {
    uint8_t* base;
    size_t   capacity;
    size_t   used;
};

void* arena_push(Arena* a, size_t size, size_t align) {
    size_t start = (a->used + (align - 1)) & ~(align - 1);
    if (start + size > a->capacity) throw std::bad_alloc{};
    a->used = start + size;
    return a->base + start;
}

template <typename T>
T* push(Arena* a, size_t count) {
    return static_cast<T*>(arena_push(a, sizeof(T) * count, alignof(T)));
}

void arena_reset(Arena* a) { a->used = 0; }

struct DeviceArena {
    uint8_t*           base;
    unsigned long long capacity;
    unsigned long long used;
};

struct Hit {
    float    x;
    float    y;
    float    score;
    uint32_t index;
};

struct Columns {
    float* score;
    float* x;
    float* y;
};

constexpr unsigned detections_per_frame = 1000;
constexpr unsigned threads_per_block = 256;
constexpr unsigned blocks = (detections_per_frame + threads_per_block - 1) / threads_per_block;
constexpr float threshold = 0.5f;
constexpr size_t hit_bytes = sizeof(Hit) * detections_per_frame;
constexpr size_t column_bytes = sizeof(float) * detections_per_frame;

__global__ void select_hits(Columns in, unsigned n, float min_score, DeviceArena* out) {
    unsigned i = blockIdx.x * blockDim.x + threadIdx.x;
    if (i >= n || in.score[i] < min_score) return;
    unsigned long long at = atomicAdd(&out->used, sizeof(Hit));
    if (at + sizeof(Hit) > out->capacity) return;
    *reinterpret_cast<Hit*>(out->base + at) = Hit{in.x[i], in.y[i], in.score[i], i};
}

static void make_detections(Columns host, uint32_t frame) {
    for (unsigned i = 0; i < detections_per_frame; ++i) {
        host.score[i] = static_cast<float>((i * 37 + frame * 11) % 100) / 100.0f;
        host.x[i] = static_cast<float>(i);
        host.y[i] = static_cast<float>(frame);
    }
}

static Columns push_columns(Arena* a) {
    return {push<float>(a, detections_per_frame), push<float>(a, detections_per_frame),
            push<float>(a, detections_per_frame)};
}

static void upload(Columns device, Columns host, cudaStream_t stream) {
    check(cudaMemcpyAsync(device.score, host.score, column_bytes, cudaMemcpyHostToDevice, stream), "h2d");
    check(cudaMemcpyAsync(device.x, host.x, column_bytes, cudaMemcpyHostToDevice, stream), "h2d");
    check(cudaMemcpyAsync(device.y, host.y, column_bytes, cudaMemcpyHostToDevice, stream), "h2d");
}

struct Pipeline {
    Stream      stream = make_stream();
    DeviceBytes device_block = device_bytes(sizeof(DeviceArena) + hit_bytes + 4 * column_bytes);
    PinnedBytes pinned_block = pinned_bytes(sizeof(DeviceArena) + hit_bytes + 4 * column_bytes);
    DeviceArena* hits_header = reinterpret_cast<DeviceArena*>(device_block.get());
    Arena device_frame{device_block.get() + sizeof(DeviceArena) + hit_bytes, 4 * column_bytes, 0};
    Arena pinned_frame{pinned_block.get(), sizeof(DeviceArena) + hit_bytes + 4 * column_bytes, 0};

    Pipeline() {
        DeviceArena header{device_block.get() + sizeof(DeviceArena), hit_bytes, 0};
        check(cudaMemcpy(hits_header, &header, sizeof header, cudaMemcpyHostToDevice), "header");
    }

    unsigned long long run_frame(uint32_t frame) {
        cudaStream_t s = stream.get();
        Columns host = push_columns(&pinned_frame);
        make_detections(host, frame);
        Columns device = push_columns(&device_frame);
        upload(device, host, s);

        check(cudaMemsetAsync(&hits_header->used, 0, sizeof hits_header->used, s), "reset hits");
        select_hits<<<blocks, threads_per_block, 0, s>>>(device, detections_per_frame, threshold, hits_header);

        auto* readback = push<DeviceArena>(&pinned_frame, 1);
        auto* hits = push<Hit>(&pinned_frame, detections_per_frame);
        check(cudaMemcpyAsync(readback, hits_header, sizeof(DeviceArena), cudaMemcpyDeviceToHost, s), "d2h");
        check(cudaMemcpyAsync(hits, hits_header + 1, hit_bytes, cudaMemcpyDeviceToHost, s), "d2h");
        check(cudaStreamSynchronize(s), "sync");

        unsigned long long count = readback->used / sizeof(Hit);
        ankerl::nanobench::doNotOptimizeAway(hits[0]);
        arena_reset(&device_frame);
        arena_reset(&pinned_frame);
        return count;
    }
};

static unsigned long long run_frame_allocating(uint32_t frame) {
    Columns host{static_cast<float*>(std::malloc(column_bytes)), static_cast<float*>(std::malloc(column_bytes)),
                 static_cast<float*>(std::malloc(column_bytes))};
    make_detections(host, frame);

    Columns device{};
    check(cudaMalloc(&device.score, column_bytes), "cudaMalloc");
    check(cudaMalloc(&device.x, column_bytes), "cudaMalloc");
    check(cudaMalloc(&device.y, column_bytes), "cudaMalloc");
    uint8_t* hit_storage = nullptr;
    DeviceArena* header = nullptr;
    check(cudaMalloc(&hit_storage, hit_bytes), "cudaMalloc");
    check(cudaMalloc(&header, sizeof(DeviceArena)), "cudaMalloc");

    check(cudaMemcpy(device.score, host.score, column_bytes, cudaMemcpyHostToDevice), "h2d");
    check(cudaMemcpy(device.x, host.x, column_bytes, cudaMemcpyHostToDevice), "h2d");
    check(cudaMemcpy(device.y, host.y, column_bytes, cudaMemcpyHostToDevice), "h2d");
    DeviceArena fresh{hit_storage, hit_bytes, 0};
    check(cudaMemcpy(header, &fresh, sizeof fresh, cudaMemcpyHostToDevice), "header");

    select_hits<<<blocks, threads_per_block>>>(device, detections_per_frame, threshold, header);

    DeviceArena readback{};
    auto* hits = static_cast<Hit*>(std::malloc(hit_bytes));
    check(cudaMemcpy(&readback, header, sizeof readback, cudaMemcpyDeviceToHost), "d2h");
    check(cudaMemcpy(hits, hit_storage, hit_bytes, cudaMemcpyDeviceToHost), "d2h");
    ankerl::nanobench::doNotOptimizeAway(hits[0]);

    std::free(hits);
    check(cudaFree(header), "cudaFree");
    check(cudaFree(hit_storage), "cudaFree");
    check(cudaFree(device.y), "cudaFree");
    check(cudaFree(device.x), "cudaFree");
    check(cudaFree(device.score), "cudaFree");
    std::free(host.y);
    std::free(host.x);
    std::free(host.score);
    return readback.used / sizeof(Hit);
}

int main() {
    Pipeline pipeline;

    for (uint32_t frame = 0; frame < 3; ++frame)
        std::printf("frame %u: %llu hits (allocating), %llu hits (arenas)\n", frame, run_frame_allocating(frame),
                    pipeline.run_frame(frame));

    ankerl::nanobench::Bench bench;
    bench.title("one CPU+GPU frame: 1000 detections, threshold, readback")
        .unit("frame")
        .relative(true)
        .minEpochIterations(300)
        .warmup(50);

    uint32_t frame = 0;
    bench.run("allocate per frame (malloc, cudaMalloc, pageable copies)", [&] {
        ankerl::nanobench::doNotOptimizeAway(run_frame_allocating(frame++));
    });
    bench.run("RAII owners + arenas (pinned, one stream, one sync)", [&] {
        ankerl::nanobench::doNotOptimizeAway(pipeline.run_frame(frame++));
    });
}
```

Built with `nvcc -O2 -std=c++17 -arch=sm_87 -I. gpu_together.cu`, with `nanobench.h` next to it. Compiler Explorer cannot run it on a GPU.

## References

- [Systems Languages Should Support Zero Is Initialization](https://blog.xoria.org/zii/): the case for ZII, and why fresh OS pages come zeroed for free.
- [Untangling Lifetimes: The Arena Allocator](https://www.dgtlgrove.com/p/untangling-lifetimes-the-arena-allocator), Ryan Fleury: the long-form argument for grouping lifetimes into arenas.
- [Handmade Hero](https://handmadehero.org/): the series and community behind much of this style.
- [CppCon 2014: Data-Oriented Design and C++](https://isocpp.org/blog/2015/01/cppcon-2014-data-oriented-design-and-c-mike-acton), Mike Acton: the data-first view behind the struct-of-arrays section.
- [RAII on cppreference](https://en.cppreference.com/w/cpp/language/raii).
- [`std::pmr::monotonic_buffer_resource` on cppreference](https://en.cppreference.com/w/cpp/memory/monotonic_buffer_resource): `release()` and the initial-buffer rules.
- [glibc MallocInternals](https://sourceware.org/glibc/wiki/MallocInternals): chunks, bins and the per-thread cache that `malloc` uses here.
- [glibc memory allocation tunables](https://sourceware.org/glibc/manual/latest/html_node/Memory-Allocation-Tunables.html): `glibc.malloc.tcache_max`.
- [libstdc++ `new_op.cc`](https://github.com/gcc-mirror/gcc/blob/master/libstdc%2B%2B-v3/libsupc%2B%2B/new_op.cc): the source of `operator new` disassembled above.
- [GCC optimize options](https://gcc.gnu.org/onlinedocs/gcc/Optimize-Options.html): `-fdevirtualize-speculatively`, which produced the guarded inline `do_allocate`.
- [CUDA 12.6 programming guide: dynamic global memory allocation](https://docs.nvidia.com/cuda/archive/12.6.0/cuda-c-programming-guide/index.html#dynamic-global-memory-allocation-and-operations): device-side `malloc` and `free`.
- [CUDA programming guide: stream-ordered memory allocation](https://docs.nvidia.com/cuda/cuda-programming-guide/04-special-topics/stream-ordered-memory-allocation.html) and [Using the NVIDIA CUDA Stream-Ordered Memory Allocator](https://developer.nvidia.com/blog/using-cuda-stream-ordered-memory-allocator-part-1/): `cudaMallocAsync` and pool release thresholds.
- [nanobench](https://github.com/martinus/nanobench), the benchmark harness, and [Compiler Explorer](https://godbolt.org/) for the live sessions.

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

## The GPU program

Built with `nvcc -O2 -std=c++17 -arch=sm_87 -I. gpu_bench.cu`, with `nanobench.h` next to it.

```cpp
#define ANKERL_NANOBENCH_IMPLEMENT
#include <nanobench.h>

#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstdlib>

#include <cuda_runtime.h>

static void check(cudaError_t status, const char* what) {
    if (status != cudaSuccess) {
        std::fprintf(stderr, "%s: %s\n", what, cudaGetErrorString(status));
        std::exit(1);
    }
}

struct Detection {
    float    box[4];
    float    score;
    uint32_t class_id;
    uint32_t track_id;
    uint32_t flags;
};

struct DeviceArena {
    uint8_t*           base;
    unsigned long long capacity;
    unsigned long long used;
};

constexpr unsigned detections_per_frame = 1000;
constexpr unsigned threads_per_block = 256;
constexpr unsigned blocks = (detections_per_frame + threads_per_block - 1) / threads_per_block;
constexpr size_t arena_bytes = 64 * 1024;
constexpr int columns = 8;
constexpr size_t column_bytes = sizeof(float) * detections_per_frame;

__device__ void touch(Detection* d, unsigned i) {
    d->score = static_cast<float>(i);
    d->class_id = i;
}

__global__ void empty_kernel() {}

__global__ void device_malloc_kernel(Detection** frame) {
    unsigned i = blockIdx.x * blockDim.x + threadIdx.x;
    if (i >= detections_per_frame) return;
    auto* d = static_cast<Detection*>(malloc(sizeof(Detection)));
    if (d) touch(d, i);
    frame[i] = d;
}

__global__ void device_free_kernel(Detection** frame) {
    unsigned i = blockIdx.x * blockDim.x + threadIdx.x;
    if (i >= detections_per_frame) return;
    free(frame[i]);
}

__device__ void* arena_push(DeviceArena* a, unsigned long long size) {
    unsigned long long start = atomicAdd(&a->used, size);
    if (start + size > a->capacity) return nullptr;
    return a->base + start;
}

template <bool Zeroed>
__global__ void device_arena_kernel(DeviceArena* arena, Detection** frame) {
    unsigned i = blockIdx.x * blockDim.x + threadIdx.x;
    if (i >= detections_per_frame) return;
    auto* d = static_cast<Detection*>(arena_push(arena, sizeof(Detection)));
    if (d) {
        if constexpr (Zeroed) *d = Detection{};
        touch(d, i);
    }
    frame[i] = d;
}

__global__ void arena_reset_kernel(DeviceArena* arena) { arena->used = 0; }

__global__ void fill_columns_kernel(float* score, uint32_t* class_id) {
    unsigned i = blockIdx.x * blockDim.x + threadIdx.x;
    if (i >= detections_per_frame) return;
    score[i] = static_cast<float>(i);
    class_id[i] = i;
}

static void fill_columns(void** cols, cudaStream_t stream) {
    fill_columns_kernel<<<blocks, threads_per_block, 0, stream>>>(static_cast<float*>(cols[4]),
                                                                  static_cast<uint32_t*>(cols[5]));
}

int main() {
    cudaStream_t stream;
    check(cudaStreamCreate(&stream), "cudaStreamCreate");

    Detection** frame;
    check(cudaMalloc(&frame, sizeof(Detection*) * detections_per_frame), "cudaMalloc frame");

    uint8_t* arena_storage;
    check(cudaMalloc(&arena_storage, arena_bytes), "cudaMalloc arena");
    DeviceArena host_arena{arena_storage, arena_bytes, 0};
    DeviceArena* arena;
    check(cudaMalloc(&arena, sizeof(DeviceArena)), "cudaMalloc arena header");
    check(cudaMemcpy(arena, &host_arena, sizeof(DeviceArena), cudaMemcpyHostToDevice), "cudaMemcpy arena");

    cudaMemPool_t pool;
    check(cudaDeviceGetDefaultMemPool(&pool, 0), "cudaDeviceGetDefaultMemPool");
    unsigned long long keep_all = ~0ull;
    check(cudaMemPoolSetAttribute(pool, cudaMemPoolAttrReleaseThreshold, &keep_all), "cudaMemPoolSetAttribute");

    ankerl::nanobench::Bench bench;
    bench.unit("frame").relative(true).minEpochIterations(500).warmup(50);

    bench.title("1000 x 32-byte allocations inside a kernel, then free all");

    bench.run("empty kernel + sync (floor)", [&] {
        empty_kernel<<<blocks, threads_per_block, 0, stream>>>();
        check(cudaStreamSynchronize(stream), "sync");
    });

    bench.run("device malloc / free", [&] {
        device_malloc_kernel<<<blocks, threads_per_block, 0, stream>>>(frame);
        device_free_kernel<<<blocks, threads_per_block, 0, stream>>>(frame);
        check(cudaStreamSynchronize(stream), "sync");
    });

    bench.run("device arena_push / reset", [&] {
        device_arena_kernel<false><<<blocks, threads_per_block, 0, stream>>>(arena, frame);
        arena_reset_kernel<<<1, 1, 0, stream>>>(arena);
        check(cudaStreamSynchronize(stream), "sync");
    });

    bench.run("device push_zeroed / reset", [&] {
        device_arena_kernel<true><<<blocks, threads_per_block, 0, stream>>>(arena, frame);
        arena_reset_kernel<<<1, 1, 0, stream>>>(arena);
        check(cudaStreamSynchronize(stream), "sync");
    });

    bench.title("8 SoA columns of 1000 per frame, allocated from the host");

    bench.run("cudaMalloc / cudaFree per column", [&] {
        void* cols[columns];
        for (auto& c : cols) check(cudaMalloc(&c, column_bytes), "cudaMalloc");
        fill_columns(cols, stream);
        check(cudaStreamSynchronize(stream), "sync");
        for (auto* c : cols) check(cudaFree(c), "cudaFree");
    });

    bench.run("cudaMallocAsync / cudaFreeAsync per column", [&] {
        void* cols[columns];
        for (auto& c : cols) check(cudaMallocAsync(&c, column_bytes, stream), "cudaMallocAsync");
        fill_columns(cols, stream);
        for (auto* c : cols) check(cudaFreeAsync(c, stream), "cudaFreeAsync");
        check(cudaStreamSynchronize(stream), "sync");
    });

    bench.run("host bump over one cudaMalloc buffer", [&] {
        void* cols[columns];
        for (int c = 0; c < columns; ++c) cols[c] = arena_storage + c * column_bytes;
        fill_columns(cols, stream);
        check(cudaStreamSynchronize(stream), "sync");
    });

    bench.run("host bump + cudaMemsetAsync (ZII)", [&] {
        void* cols[columns];
        for (int c = 0; c < columns; ++c) cols[c] = arena_storage + c * column_bytes;
        check(cudaMemsetAsync(arena_storage, 0, columns * column_bytes, stream), "cudaMemsetAsync");
        fill_columns(cols, stream);
        check(cudaStreamSynchronize(stream), "sync");
    });

    check(cudaMemcpy(&host_arena, arena, sizeof(DeviceArena), cudaMemcpyDeviceToHost), "cudaMemcpy back");
    std::printf("device arena used after last reset: %llu\n", host_arena.used);
    check(cudaGetLastError(), "kernel launch");
}
```
