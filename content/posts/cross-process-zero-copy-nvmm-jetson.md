---
title: "Cross-Process Zero-Copy on Jetson: dma-buf fds, NvBufSurfaceImport, and a Cache-Line-Padded Pool"
date: 2026-04-25
draft: false
tags: ["zero-copy", "concurrency", "NVMM", "NVIDIA", "Jetson", "GPU", "GStreamer", "C++", "Linux", "video-processing", "shared-memory", "performance"]
keywords: ["NvBufSurfaceImport", "dma-buf SCM_RIGHTS Jetson", "NVMM cross-process IPC", "cache line false sharing C++", "futex shared memory cross-process", "GstBufferPool propose_allocation NVMM", "Jetson zero-copy GStreamer", "gst-nvmm-cpp"]
cover:
  image: /images/posts/nvmm-zero-copy-ipc.png
  alt: "Cross-process zero-copy NVMM IPC on Jetson — dma-buf fd passing, NvBufSurfaceImport, lock-free pool"
categories: ["deep-dive"]
summary: "Two processes on a Jetson, one camera frame in NVMM (GPU memory), no copies. The kernel does the heavy lifting via dma-buf fds; SCM_RIGHTS carries the fd across the process boundary; NvBufSurfaceImport reconstructs the surface on the consumer side; a cache-line-padded ring of atomic ref-counts keeps fan-out coherent without locks. With benchmark numbers and a Godbolt-runnable demo of the SCM_RIGHTS pattern."
ShowToc: true
---

## The problem

You have a Jetson. A camera frame lives in NVMM — Tegra-native, physically contiguous GPU-managed memory wrapped in `NvBufSurface`. One process captures it (Argus, nvv4l2decoder, nvvidconv, …). Another process — a separate ROS2 node, a CUDA inference worker, a recording daemon — needs to consume it.

The naive answer is "POSIX shared memory: `shm_open`, `mmap`, and `memcpy` the pixels in." That works, but it's two CPU copies per frame and you lose every benefit of NVMM living on the GPU side. At 1080p60 NV12 that's ~187 MB/s of CPU memcpy round-trip, plus cache pressure, plus you've negated the whole point of having a unified-memory SoC.

The right answer is to share the **kernel handle** to the GPU buffer, not the pixels. Two processes, one DMA-coherent surface. No copies on the data path. Consumer-side reads come straight from GPU memory.

This post walks through how that actually works — the kernel piece (dma-buf fds + SCM_RIGHTS), the NVIDIA-userspace piece (`NvBufSurfaceImport`), the concurrency piece (a fixed pool of slots with per-slot atomic ref-counts and cache-line padding), and the producer-side piece (a `GstBufferPool` subclass that closes the loop). I built all of this for [`gst-nvmm-cpp`](https://github.com/PavelGuzenfeld/gst-nvmm-cpp) — a GStreamer NVMM IPC plugin pair (`nvmmsink` / `nvmmappsrc`) — and the numbers at the end are from a real Xavier NX.

## What `NvBufSurface` actually is

An `NvBufSurface` is a userspace struct describing a Tegra-managed video buffer. The pointer you hold isn't to the pixel bytes — it's to a metadata struct whose `surfaceList[i].bufferDesc` field is a **DMA-buf file descriptor** owned by the kernel. The pixel data lives wherever the Tegra VIC engine decided to put it (typically `NVBUF_MEM_SURFACE_ARRAY`, a Tegra-specific tiled GPU layout).

`NvBufSurfaceMap` mmap's that fd into your process so the CPU can poke the bytes, but the canonical reference is the fd. That's what makes cross-process sharing tractable: **the fd is the handle.** Pass the fd to another process and that process now has a kernel-validated reference to the same physical pages. The kernel ref-counts the dma-buf object; nothing gets freed until every reference is dropped.

## Step 1: SCM_RIGHTS — getting the fd to the other process

Linux lets you transfer file descriptors over a Unix-domain socket using ancillary data with type `SCM_RIGHTS`. The receiving process doesn't get the literal integer the sender had — it gets a fresh fd in *its own* fd table, pointing at the same kernel object.

This is a 30-line pattern that hasn't changed in 25 years. Here's the core:

```cpp
// Send a batch of fds over a unix socket. C++23: std::span for the
// batch, std::expected for the result so the error path is on the type.
[[nodiscard]] std::expected<void, int>
send_fds(int sock, std::span<const int> fds)
{
    alignas(cmsghdr) std::byte ctrl[CMSG_SPACE(sizeof(int) * 16)]{};
    char     dummy = 'X';
    iovec    iov{ &dummy, 1 };
    msghdr   msg{};
    msg.msg_iov     = &iov;
    msg.msg_iovlen  = 1;
    msg.msg_control = ctrl;
    msg.msg_controllen = CMSG_LEN(sizeof(int) * fds.size());

    auto *c = CMSG_FIRSTHDR(&msg);
    c->cmsg_level = SOL_SOCKET;
    c->cmsg_type  = SCM_RIGHTS;
    c->cmsg_len   = CMSG_LEN(sizeof(int) * fds.size());
    std::memcpy(CMSG_DATA(c), fds.data(), sizeof(int) * fds.size());

    if (sendmsg(sock, &msg, 0) < 0) return std::unexpected(errno);
    return {};
}

// Caller-supplied span; we fill it. Caller closes the fds when done.
[[nodiscard]] std::expected<void, int>
recv_fds(int sock, std::span<int> out)
{
    alignas(cmsghdr) std::byte ctrl[CMSG_SPACE(sizeof(int) * 16)]{};
    char     dummy{};
    iovec    iov{ &dummy, 1 };
    msghdr   msg{};
    msg.msg_iov     = &iov;
    msg.msg_iovlen  = 1;
    msg.msg_control = ctrl;
    msg.msg_controllen = sizeof(ctrl);

    if (recvmsg(sock, &msg, 0) < 0) return std::unexpected(errno);
    auto *c = CMSG_FIRSTHDR(&msg);
    if (!c || c->cmsg_level != SOL_SOCKET || c->cmsg_type != SCM_RIGHTS)
        return std::unexpected(EBADMSG);
    std::memcpy(out.data(), CMSG_DATA(c), sizeof(int) * out.size());
    return {};
}
```

You connect a `socketpair(AF_UNIX, SOCK_STREAM, 0, sv)`, fork, and send fds across. **You can also send fds over a connected `AF_UNIX` socket between unrelated processes** — that's how a long-running camera daemon hands out fds to ROS nodes that come and go.

A standalone runnable demo of the whole producer→consumer fd handshake (no NVIDIA libs, just kernel dma-buf via `memfd_create`, fork, socketpair, write/read through a shared mmap) — runnable on Compiler Explorer:

> **[Run it on Compiler Explorer →](https://godbolt.org/z/4dvx8P6c5)** (gcc 14.2, `-std=c++23 -O2 -pthread`). The child process opens the parent's `memfd` via SCM_RIGHTS, mmaps it, reads the message the parent wrote. Source also reproduced [at the bottom of this post](#full-godbolt-example).

## Step 2: NvBufSurfaceImport — the userspace bridge

Kernel-side, the consumer now has a valid fd. But the rest of the NVIDIA stack works on `NvBufSurface*`, not raw fds. We need to bridge from "I have a dma-buf fd" to "I have an `NvBufSurface*` that nvvidconv / nvv4l2encoder / NvBufSurfaceMap will accept."

This bridge is `NvBufSurfaceImport`. It takes an `NvBufSurfaceMapParams` struct (geometry — width, height, color format, plane pitches/offsets, layout) plus the fd, and reconstructs a per-process `NvBufSurface*` referring to the same physical memory:

```cpp
// On the producer side, populate map_params from your slot surface:
NvBufSurfaceMapParams map_params{};
NvBufSurfaceGetMapParams(slot_surface, /*idx*/0, &map_params);

// Send map_params over the socket (plain bytes), then SCM_RIGHTS-send
// the fd from slot_surface->surfaceList[0].bufferDesc.

// On the consumer side, after recv'ing both:
map_params.fd = recv_fd;          // patch the fd to our fresh one
NvBufSurface *imported = nullptr;
if (NvBufSurfaceImport(&imported, &map_params) != 0) { /* fail */ }
// `imported` is now usable like any locally-created NvBufSurface.
NvBufSurfaceMap(imported, 0, -1, NVBUF_MAP_READ);
NvBufSurfaceSyncForCpu(imported, 0, -1);
const uint8_t *pixels = (const uint8_t *)imported->surfaceList[0].mappedAddr.addr[0];
```

**`NvBufSurfaceImport` shipped in L4T R35.3.1 (JetPack 5.1.1, March 2023).** Earlier L4T 35.x lacks it, and older fd-based functions like `NvBufSurfaceFromFd` consult a process-local userspace map that's only populated by `NvBufSurfaceCreate` in the *same* process — they return -1 for SCM_RIGHTS-passed fds. I confirmed this empirically (fork + SCM_RIGHTS probe on R35.2.1, both `NvBufSurfaceFromFd` and the legacy `NvBufferGetParams` failed) before bumping the floor. Anyone trying this on JP 5.0.x is going to spend an evening confused.

JP6 (L4T R36.x, Orin) has the same API. The wire format and code path are identical.

## Step 3: a fixed pool — bounded memory, predictable latency

A producer that allocates a fresh NVMM surface per frame is going to run out of memory or stall on `NvBufSurfaceCreate`'s ~ms latency. Use a fixed pool: N slots, each pre-allocated at `set_caps` time, fds shipped to consumers once at handshake.

```cpp
struct PoolSlot {
    NvBufSurface          *surface;
    int                    fd;          // = surface->surfaceList[0].bufferDesc
    NvBufSurfaceMapParams  map_params;  // sent to consumers at handshake
};
std::vector<PoolSlot> pool;             // N entries, lifetime = producer's
```

Per frame, the producer:
1. Picks an idle slot (rotation hint + atomic CAS to claim).
2. `NvBufSurfaceCopy` upstream's frame into the slot. (Or skips this entirely — see "producer-side zero-copy" below.)
3. Publishes the slot index in shared memory.

Consumers see the new index, read directly from the slot's surface, drop their reference when done. Producer recycles the slot once everyone's done with it.

The interesting part is the bookkeeping: how do producer and N consumers coordinate "this slot is in use" without taking a global lock per frame?

## Step 4: per-slot atomic ref-counts in shared memory

Each slot gets a 32-bit signed ref-count in the shared header:

```c
typedef struct NvmmPoolSlotState {
    int32_t ref_count;
    char    _pad[NVMM_CACHE_LINE - sizeof(int32_t)];
} __attribute__((aligned(NVMM_CACHE_LINE))) NvmmPoolSlotState;
```

The state machine:

| Value | Meaning |
|-------|---------|
| `0`   | Idle. Producer may CAS-claim via `0 → -1`. |
| `-1`  | Writer-locked. Producer is filling the slot. Consumers skip. |
| `>0`  | N consumers currently reading. Producer waits before reusing. |

The producer's claim:

```cpp
if (__atomic_compare_exchange_n(&header->slots[i].ref_count,
                                &expected /*=0*/, -1, false,
                                __ATOMIC_ACQ_REL, __ATOMIC_ACQUIRE)) {
    // Slot i is ours. Fill it, then store 0 again to release the writer lock.
}
```

The consumer's grab:

```cpp
int32_t cur = __atomic_load_n(&header->slots[i].ref_count, __ATOMIC_ACQUIRE);
while (cur >= 0) {
    if (__atomic_compare_exchange_n(&header->slots[i].ref_count,
                                    &cur, cur + 1, false,
                                    __ATOMIC_ACQ_REL, __ATOMIC_ACQUIRE))
        break;  // grabbed it; cur was the value we incremented
}
```

Plain `int32_t`, accessed via `__atomic_*` builtins with explicit memory order. **Not `volatile`** — `volatile` blocks compiler register caching but provides no atomicity or cross-CPU ordering, and is the wrong tool for IPC sync. **Not `std::atomic<T>`** either: in C++14, reinterpret-casting a shm byte range to `std::atomic<T>*` is UB and ABI-implementation-defined. C++20's `std::atomic_ref<T>` solves this cleanly; until I can bump the language level, `__atomic_*` on plain integers is the documented pattern.

`uint32_t` / `int32_t` / `uint64_t` are lock-free on every Linux target this code supports (aarch64 + x86_64, glibc).

## Step 5: don't put 16 ref-counts on one cache line

This is where almost every "shared ring buffer" in a blog post falls over. The naive layout:

```c
struct PoolHeader {
    uint32_t ready;
    uint32_t write_idx;
    uint64_t frame_number;
    uint64_t timestamp_ns;
    int32_t  ref_counts[16];   // <-- here be dragons
    /* ... */
};
```

`ref_counts[0..15]` all sit on the same 64-byte cache line. Two consumers reading slots 3 and 7, on different cores, ping-pong that line back and forth on every refcount update — false sharing in textbook form. Worse, the hot publish fields (`ready`, `write_idx`, `frame_number`) share that same line, so the producer's RELEASE store on `ready` invalidates every consumer's ref-count load, even consumers reading slots the producer never touched.

The fix is to put each ref-count on its own cache line, and put the hot publish fields on a separate line of their own:

```c
typedef struct __attribute__((aligned(NVMM_CACHE_LINE))) NvmmPoolSlotState {
    int32_t ref_count;
    char _pad[NVMM_CACHE_LINE - sizeof(int32_t)];
} NvmmPoolSlotState;

typedef struct NvmmShmPoolHeader {
    /* setup-time fields, read-mostly */
    uint32_t magic;
    uint32_t version;
    /* ... width, height, format, pitches, offsets, socket_path[108] ... */

    /* hot publish line — its own cache line */
    __attribute__((aligned(NVMM_CACHE_LINE))) uint32_t ready;
    uint32_t write_idx;
    uint64_t frame_number;
    uint64_t timestamp_ns;
    uint32_t wake_counter;
    char _hot_pad[NVMM_CACHE_LINE - sizeof(uint32_t) * 3 - sizeof(uint64_t) * 2];

    /* per-slot ref counts, each on its own cache line */
    NvmmPoolSlotState slots[NVMM_POOL_SIZE_MAX];
} NvmmShmPoolHeader;
```

And — this is the part most people skip — pin the layout at compile time so it can't silently regress:

```cpp
static_assert(sizeof(NvmmPoolSlotState) == NVMM_CACHE_LINE,
              "PoolSlotState must be exactly one cache line");
static_assert(alignof(NvmmPoolSlotState) == NVMM_CACHE_LINE,
              "PoolSlotState must be cache-line aligned");
static_assert(offsetof(NvmmShmPoolHeader, ready) % NVMM_CACHE_LINE == 0,
              "ready must start a fresh cache line");
static_assert(offsetof(NvmmShmPoolHeader, slots) % NVMM_CACHE_LINE == 0,
              "slots[] must start a fresh cache line");
```

Three years from now, when someone reorganizes the struct because "this padding looks wasteful," the build breaks. Good. The padding is the feature.

The throughput payoff is real. With the false-sharing layout, my multi-consumer benchmark on Xavier NX showed throughput collapsing from 1 → 4 consumers. With the padded layout, throughput is essentially flat (and actually trends slightly *positive* — the consumer poll cycles overlap better with the producer when the cache line traffic isn't there).

## Step 6: futex wakeup, not 1 ms polling

A consumer waiting for the next frame loops on `__atomic_load_n(&header->ready, __ATOMIC_ACQUIRE)`. Naively, you sleep `g_usleep(1000)` between checks. That puts a 1 ms floor on end-to-end latency even when the producer published in a microsecond.

Linux `FUTEX_WAIT` / `FUTEX_WAKE` works **across processes** when the futex address is in a shared mmap. (`FUTEX_PRIVATE_FLAG` is the same-process variant; you want the non-private form for IPC.) Add a `wake_counter` to the hot publish line. Producer increments it after publishing and wakes everyone:

```cpp
__atomic_add_fetch(&header->wake_counter, 1, __ATOMIC_RELEASE);
syscall(SYS_futex, &header->wake_counter, FUTEX_WAKE, INT_MAX,
        nullptr, nullptr, 0);
```

Consumer ACQUIRE-loads the counter, futex-waits if unchanged:

```cpp
const uint32_t observed = __atomic_load_n(&header->wake_counter, __ATOMIC_ACQUIRE);
if (observed == self->last_wake) {
    struct timespec to{ 0, 1'000'000 };  // 1 ms upper bound (for flush detection)
    syscall(SYS_futex, &header->wake_counter, FUTEX_WAIT, observed,
            &to, nullptr, 0);
}
self->last_wake = __atomic_load_n(&header->wake_counter, __ATOMIC_ACQUIRE);
```

The wait address is a `uint32_t` — futex is 32-bit by API. The timeout is just an upper bound for periodic flush/EOS checks; the actual wakeup latency is a syscall round-trip (typically <100 µs).

## Step 7: closing the loop — producer-side zero-copy

So far the consumer side is zero-copy (it `NvBufSurfaceImport`s and reads GPU memory directly), but the producer is still doing one `NvBufSurfaceCopy` per frame to copy upstream's surface into a slot the consumers can see. That's GPU-to-GPU and fast (VIC engine) but it's still a copy.

GStreamer has a primitive for this: `propose_allocation`. The sink advertises a `GstBufferPool`; if upstream agrees to allocate from it, every frame upstream renders lands directly into one of the sink's pre-allocated buffers. No copy.

For our case, the pool wraps the IPC slot surfaces themselves. A `GstBufferPool` subclass:

```cpp
struct _GstNvmmIpcUpstreamPool {
    GstBufferPool       parent;
    NvmmIpcProducer    *producer;       // back-ref; not owned
    int                 next_slot_hint;
};

// alloc_buffer: hand out the pre-allocated slot surfaces in round-robin
static GstFlowReturn
nvmm_ipc_upstream_pool_alloc(GstBufferPool *pool, GstBuffer **out,
                              GstBufferPoolAcquireParams *) {
    auto *self = NVMM_IPC_UPSTREAM_POOL(pool);
    int idx = self->next_slot_hint++ % self->producer->pool.size();

    GstBuffer *buf = gst_buffer_new();
    gst_buffer_append_memory(buf, gst_memory_new_wrapped(
        GST_MEMORY_FLAG_NO_SHARE,
        self->producer->pool[idx].surface, sizeof(NvBufSurface),
        0, sizeof(NvBufSurface), nullptr, nullptr));
    // Tag with slot index so render() can find it via qdata.
    gst_mini_object_set_qdata(GST_MINI_OBJECT_CAST(buf),
                              nvmm_pool_slot_quark(),
                              GINT_TO_POINTER(idx + 1), nullptr);
    *out = buf;
    return GST_FLOW_OK;
}

// acquire_buffer: pop from the parent's free queue, then check shm
// ref_count to make sure remote consumers aren't still reading. Try
// the next slot if pinned, give up after 2N tries.
```

The render path reads the qdata tag; if present, it skips `NvBufSurfaceCopy` entirely and just publishes the slot index. The buffer is held through a `pool_release_delay`-deep ring on the producer side too, so the slot doesn't get reissued until both (a) the GstBuffer was unref'd locally and (b) `header->slots[i].ref_count == 0` remotely.

The acceptance criterion is bytes survive the round trip. I added a CRC test that fills frames with a deterministic pattern and verifies on the consumer side — 50/50 frames matched on real Xavier R35.6.4, and the visual roundtrip dump (color gradient + frame-index progress bar) shows pixel-for-pixel identical TX/RX pairs.

## Numbers (real Xavier NX, R35.6.4, 64×64 RGBA, 5000 frames, open-loop)

```
copy       n_cons=1  prod_fps=  2316  cons_frames=5000/5000  p99= 453us
zero-copy  n_cons=1  prod_fps= 93593  cons_frames=4976/5000  p99=  14us
copy       n_cons=4  prod_fps=  2387  cons_frames=4977/5000  p99= 451us
zero-copy  n_cons=4  prod_fps= 86322  cons_frames=4935/5000  p99=  13us
```

~36× the throughput, ~32× lower p99 latency. The copy path was bound on `NvBufSurfaceCopy + alloc`; the zero-copy path is bound on `pool_acquire + atomic publish + futex_wake`. Multi-consumer scaling is essentially flat across both paths — the cache-line-per-slot layout earned its complexity.

Frame loss climbs slightly at high consumer counts on the zero-copy path (~1.3% at 4 consumers) because the producer is now pushing 86k fps and the consumer's release ring saturates before the futex wake loop drains it. Real applications running at 30–240 fps never see this.

For comparison, the previous shm-copy implementation (two CPU memcpys per frame, no fd passing) on the same Xavier was ~1170 fps with p99 ~830 µs. Zero-copy is ~80× the throughput and ~60× lower latency vs that starting point.

## Architecture summary

```
      Process A (producer)                    Process B (consumer)
      ─────────────────────                   ─────────────────────
       upstream                                downstream
          │                                       ▲
          ▼                                       │
   ┌─────────────┐  GstBufferPool          ┌─────────────┐
   │  nvmmsink   │  (slot 3 surface)       │ nvmmappsrc  │
   └──────┬──────┘                         └──────┬──────┘
          │ render(buf with slot=3 qdata)         │ fetch returns GstBuffer
          ▼                                       │ wrapping imported surface
   ┌──────────────────────────────────┐           ▲
   │  ipc_pool.cpp (libnvbufsurface)  │           │
   │  ─ NvBufSurfaceCreate × N        │           │ NvBufSurfaceImport
   │  ─ refc_cas(slot.ref_count)      │           │ (per slot, once at start)
   │  ─ futex_wake(wake_counter)      │           │
   └────────────┬─────────────────────┘           │
                │                                  │
                │ shm header (POSIX)               │ shm header (read-only mmap)
                ▼                                  ▲
        ┌─────────────────────────────────────────────────┐
        │  /dev/shm/nvmm_x  (NvmmShmPoolHeader)           │
        │   • magic, version=4                            │
        │   • caps: width, height, format, pitches        │
        │   • socket_path = "/tmp/nvmm_x.sock"            │
        │   ── HOT publish line (cache-aligned) ──        │
        │   • ready, write_idx, frame_number,             │
        │     timestamp_ns, wake_counter (futex addr)     │
        │   ── per-slot ref_counts (each its own line) ── │
        │   • slots[0..N].ref_count                       │
        └─────────────────────────────────────────────────┘
                ▲                                  ▲
                │                                  │
        ┌───────┴──────────┐                       │
        │ accept_thread    │  unix socket (SCM_RIGHTS handshake, once)
        │ /tmp/nvmm_x.sock ├──────────────────────►│  recv pool_size,
        │                  │   sends N fds +       │  N × NvBufSurfaceMapParams,
        └──────────────────┘   N × MapParams       │  N × dma-buf fds
```

The shm header carries metadata + the futex word + the per-slot ref-counts. The unix socket carries the one-shot fd handshake. Pixel data never touches CPU memory — every frame stays in the GPU-coherent NVMM pool the kernel allocated, and consumers' `NvBufSurfaceMap` is just a CPU-side mmap of that memory if they want to read it.

## NVIDIA library boundaries

- **`libnvbufsurface.so`** (`<nvbufsurface.h>`, `/usr/src/jetson_multimedia_api/include/`): `NvBufSurfaceCreate`, `NvBufSurfaceDestroy`, `NvBufSurfaceMap`, `NvBufSurfaceCopy`, `NvBufSurfaceImport`, `NvBufSurfaceGetMapParams`. The whole IPC backend is built against this single header. **Floor: L4T R35.3.1 (JP 5.1.1).** Earlier L4T 35.x ships the lib but doesn't export the import-related symbols. The build system probes for `NvBufSurfaceImport` at meson configure and a runtime `dlsym` check fires at first `producer_start` — the latter catches the deploy-time mismatch where a binary built against newer headers ends up running on an older host BSP (containers with `--runtime nvidia` mounting host libs are the common cause).

- **`libnvbufsurftransform.so`**: `NvBufSurfTransform` for VIC-side colorspace / scale / detile. Used inside `nvvidconv`, not directly by the IPC backend. *Important caveat:* this one's kernel ABI is **not** stable across L4T 35.x minors. If you mix R35.6 userspace with an R35.2 kernel (e.g., because your carrier board's kernel postinst doesn't run cleanly), `nvvidconv` breaks with `gst_nvvconv_transform: NvBufSurfTransform Failed` even though the simpler `NvBufSurfaceMap` path keeps working. Plan accordingly.

- **`libnvscibuf.so`** (NvSciBuf): NVIDIA's "official" cross-process buffer sharing library, ships on JP5+ but **without public headers** in the standard `nvidia-l4t-nvsci` package. The runtime libs are there because Argus / nvbufsurface use them internally; using NvSciBuf from your own code requires sourcing headers from the L4T BSP source bundle. For a single-host Linux Unix-socket use case, plain SCM_RIGHTS + NvBufSurfaceImport is simpler and more portable.

- **`libgstreamer-1.0.so` / `libgstvideo-1.0.so`**: `GstBufferPool` subclass for the producer-side zero-copy, `GstAllocator` boundary for upstream NVMM frames, `GstQuery` / `propose_allocation` for the pool advertisement. The `nvmmsink` and `nvmmappsrc` element files are thin delegates over a C ABI (`gst/common/ipc_backend.h`) — no `#ifdef` on JetPack version anywhere in the call path.

## What I'd tell my past self before starting

1. **Don't conflate "JetPack version" with "feature gate."** The real gate is "does `libnvbufsurface.so` export `NvBufSurfaceImport`?" That's R35.3.1+ on the JP5 line, R36.0+ on JP6. Treating "JP5" as a single thing — when JP 5.0.x and JP 5.1.x have completely different cross-process IPC surfaces — is what made the original PR have two backends. There's only one backend; the gate is a header symbol probe.

2. **`volatile` is not an atomics replacement.** Anyone touching shm IPC code in 2026 already knows this, but it bears the static_assert treatment too — no field marked `volatile` ever, with a comment explaining the C++14 / `std::atomic_ref` constraint that justifies the `__atomic_*` choice.

3. **Cache-line padding pays for itself in benchmarks, not in code review.** The naive layout *passes all functional tests* — the tests don't measure throughput collapse. The compile-time `static_assert` pins are the only thing that prevents the next refactor from silently regressing perf.

4. **Build-time + runtime guards both earn their place.** Linker errors are opaque ("undefined reference to NvBufSurfaceImport"). A friendly `GST_ERROR_OBJECT` saying "your host BSP is older than R35.3.1, here's how to fix it" turns a 4-hour debugging session into a 30-second one.

5. **`gst_nvvconv_transform: NvBufSurfTransform Failed` is the canary** for kernel/userspace ABI skew. If you've apt-upgraded `nvidia-l4t-jetson-multimedia-api` without flashing a matched kernel, this is the symptom you'll hit. The IPC layer itself doesn't depend on this code path, so the unit tests pass and you can spend hours wondering why `gst-launch ... ! nvvidconv ! pngenc` doesn't work.

The full implementation is at <https://github.com/PavelGuzenfeld/gst-nvmm-cpp> if you want to build on it. PR #2 contains everything described above (build/runtime guards, atomics, padded layout, futex, propose_allocation pool, CRC + visual roundtrip tests, throughput bench).

## Full Godbolt example

Live link: **<https://godbolt.org/z/4dvx8P6c5>** (gcc 14.2, `-std=c++23 -O2 -pthread`).

Standalone demo of the SCM_RIGHTS pattern — no NVIDIA libs, runs anywhere with a Linux kernel. Producer creates a `memfd`, writes a string, sends the fd to a child process via `socketpair`. Child receives, mmaps, prints. The exact same pattern the NVMM backend uses, with NVIDIA's `NvBufSurfaceCreate` standing in for `memfd_create`.

```cpp
// Build: g++ -std=c++23 -O2 -pthread scm_rights_demo.cpp -o demo && ./demo

#include <array>
#include <cerrno>
#include <cstring>
#include <cstdint>
#include <expected>
#include <print>
#include <span>
#include <string_view>

#include <fcntl.h>
#include <linux/memfd.h>
#include <sys/mman.h>
#include <sys/socket.h>
#include <sys/syscall.h>
#include <sys/wait.h>
#include <unistd.h>

// ── Tunables ────────────────────────────────────────────────────────────────

// Compile-time upper bound on how many fds we ever pass in one sendmsg.
// CMSG_SPACE() needs a constant expression to size the ancillary buffer;
// there's no kernel facility for "max ancillary fds per message" beyond
// per-process /proc/sys/net/core/optmem_max divided by sizeof(int), and
// that's runtime / non-constexpr. 16 covers our pool sizes.
inline constexpr std::size_t kMaxFdsPerMsg = 16;

// SCM_RIGHTS messages must carry at least one byte of normal payload —
// the kernel rejects msghdrs whose iovec is empty. Any byte will do; we
// use 'X' so it's identifiable in a packet capture.
inline constexpr char        kIovDummy     = 'X';

// mmap'd region size for the demo. mmap requires the size to be a
// multiple of the runtime page size; sysconf(_SC_PAGESIZE) is the
// POSIX facility for that. Per-arch: 4 KiB on x86_64 + most aarch64,
// 16 KiB on Apple Silicon, 64 KiB on some Power.
[[nodiscard]] static std::size_t demo_page_size() noexcept {
    long ps = sysconf(_SC_PAGESIZE);
    return ps > 0 ? static_cast<std::size_t>(ps) : 4096;
}

// ── SCM_RIGHTS helpers ──────────────────────────────────────────────────────

[[nodiscard]] std::expected<void, int>
send_fds(int sock, std::span<const int> fds)
{
    alignas(cmsghdr) std::byte ctrl[CMSG_SPACE(sizeof(int) * kMaxFdsPerMsg)]{};
    char     dummy = kIovDummy;
    iovec    iov{ &dummy, 1 };
    msghdr   msg{};
    msg.msg_iov     = &iov;
    msg.msg_iovlen  = 1;
    msg.msg_control = ctrl;
    msg.msg_controllen = CMSG_LEN(sizeof(int) * fds.size());

    auto *c = CMSG_FIRSTHDR(&msg);
    c->cmsg_level = SOL_SOCKET;
    c->cmsg_type  = SCM_RIGHTS;
    c->cmsg_len   = CMSG_LEN(sizeof(int) * fds.size());
    std::memcpy(CMSG_DATA(c), fds.data(), sizeof(int) * fds.size());

    if (sendmsg(sock, &msg, 0) < 0) return std::unexpected(errno);
    return {};
}

[[nodiscard]] std::expected<void, int>
recv_fds(int sock, std::span<int> out)
{
    alignas(cmsghdr) std::byte ctrl[CMSG_SPACE(sizeof(int) * kMaxFdsPerMsg)]{};
    char     dummy{};
    iovec    iov{ &dummy, 1 };
    msghdr   msg{};
    msg.msg_iov     = &iov;
    msg.msg_iovlen  = 1;
    msg.msg_control = ctrl;
    msg.msg_controllen = sizeof(ctrl);

    if (recvmsg(sock, &msg, 0) < 0) return std::unexpected(errno);
    auto *c = CMSG_FIRSTHDR(&msg);
    if (!c || c->cmsg_level != SOL_SOCKET || c->cmsg_type != SCM_RIGHTS)
        return std::unexpected(EBADMSG);
    std::memcpy(out.data(), CMSG_DATA(c), sizeof(int) * out.size());
    return {};
}

// ── Demo ────────────────────────────────────────────────────────────────────

int main()
{
    const std::size_t kSize = demo_page_size();   // one page

    std::array<int, 2> sv{};
    if (socketpair(AF_UNIX, SOCK_STREAM, 0, sv.data()) < 0) {
        std::println(stderr, "socketpair: {}", std::strerror(errno));
        return 1;
    }

    if (auto pid = fork(); pid == 0) {
        // ── child = consumer ───────────────────────────────────────────────
        close(sv[0]);
        int fd = -1;
        if (auto r = recv_fds(sv[1], std::span{&fd, 1}); !r) {
            std::println(stderr, "recv_fds: {}", std::strerror(r.error()));
            return 1;
        }
        void *p = mmap(nullptr, kSize, PROT_READ, MAP_SHARED, fd, 0);
        if (p == MAP_FAILED) {
            std::println(stderr, "mmap: {}", std::strerror(errno));
            return 1;
        }
        std::println("[child  pid={}] received fd={}, content=\"{}\"",
                     getpid(), fd, static_cast<const char*>(p));
        munmap(p, kSize);
        close(fd);
        return 0;
    }

    // ── parent = producer ───────────────────────────────────────────────────
    close(sv[1]);
    int fd = static_cast<int>(syscall(SYS_memfd_create, "demo", 0u));
    if (fd < 0 || ftruncate(fd, kSize) < 0) {
        std::println(stderr, "memfd_create/ftruncate: {}", std::strerror(errno));
        return 1;
    }
    void *p = mmap(nullptr, kSize, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
    constexpr std::string_view kMsg = "hello from process A - same physical page";
    std::memcpy(p, kMsg.data(), kMsg.size() + 1);
    munmap(p, kSize);

    std::println("[parent pid={}] sending fd={}", getpid(), fd);
    if (auto r = send_fds(sv[0], std::span{&fd, 1}); !r) {
        std::println(stderr, "send_fds: {}", std::strerror(r.error()));
        return 1;
    }
    int status{};
    wait(&status);
    close(fd);
    return WEXITSTATUS(status);
}
```

Verified output (gcc 14, x86_64 Linux):

```
[child  pid=14] received fd=3, content="hello from process A - same physical page"
[parent pid=13] sending fd=4
```

Note the fd integers differ between the processes (parent's `4`, child's `3`) — they're independent fd-table entries pointing at the same kernel object. That's the kernel's fd-passing semantics, identical for `memfd` (this demo) and dma-buf (the real NVMM case).

Replace `memfd_create` with `NvBufSurfaceCreate(..., NVBUF_MEM_SURFACE_ARRAY, ...)`, send the `bufferDesc` fd plus the geometry struct, and on the child side call `NvBufSurfaceImport` instead of `mmap`. The pattern is otherwise identical.
