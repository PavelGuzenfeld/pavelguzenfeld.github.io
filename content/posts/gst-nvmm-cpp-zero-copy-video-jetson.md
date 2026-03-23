---
title: "Zero-Copy Video on Jetson: Building gst-nvmm-cpp and Contributing to GStreamer"
date: 2026-03-23
draft: false
tags: ["GStreamer", "NVIDIA", "Jetson", "NVMM", "C++", "video-processing", "zero-copy", "open-source", "contributing"]
categories: ["deep-dive"]
summary: "How we built a GStreamer plugin suite for zero-copy NVMM video on NVIDIA Jetson, the bugs we hit along the way, and what it takes to contribute to the GStreamer project — from filing issues to getting an MR merged."
ShowToc: true
---

## The Problem Nobody Talks About

Every robotics and edge AI team running NVIDIA Jetson eventually hits the same wall: GStreamer doesn't understand Jetson's native video memory.

On a Jetson Xavier NX or Orin, video data lives in **NVMM** (NvBufSurface) — physically contiguous, DMA-coherent memory managed by the Tegra VIC hardware engine. This is the format that `nvv4l2decoder` outputs, that `nvvidconv` consumes, and that every NVIDIA hardware accelerator expects. It's fast, it's zero-copy, and it's completely invisible to upstream GStreamer.

The standard GStreamer `nvcodec` plugin targets desktop NVIDIA GPUs via CUDA. It has no concept of NvBufSurface, no allocator for NVMM memory, and no element that can call NvBufSurfTransform. If you want to crop, scale, flip, or convert video on Jetson without touching the CPU, you have three options — all bad:

1. **Pin to L4T's ancient GStreamer fork** (1.16.x on JetPack 5). You get NVIDIA's proprietary `nvvidconv` but you're stuck on a 7-year-old GStreamer.
2. **Use NVIDIA's source-drop plugins** patched per JetPack version. Untested with newer GStreamer, undocumented, and you're on your own.
3. **Write it yourself.** Every team reinvents the same NvBufSurface-to-GstMemory mapping code. Every team gets the plane offsets wrong. Every team discovers that `NvBufSurfaceSyncForDevice` with plane=-1 doesn't work on their L4T version.

We wrote [gst-nvmm-cpp](https://github.com/PavelGuzenfeld/gst-nvmm-cpp) to fix this permanently, and [contributed it upstream](https://gitlab.freedesktop.org/gstreamer/gstreamer/-/merge_requests/11101) to GStreamer.

## What gst-nvmm-cpp Does

The plugin suite provides three components that fill the NVMM gap:

### Architecture

```
+----------------------------------------------------------+
|                     GStreamer Pipeline                     |
|                                                           |
|  +----------+   +--------------+   +------------------+  |
|  | decoder  |-->| nvmmconvert  |-->|    nvmmsink      |  |
|  |(nvv4l2)  |   |  (VIC h/w)   |   |  (POSIX shm)    |  |
|  +----------+   +------+-------+   +--------+---------+  |
|                        |                     |            |
|                        v                     v            |
|  +----------------------------------------------------+  |
|  |              GstNvmmAllocator                       |  |
|  |                                                     |  |
|  |  alloc --> NvBufSurfaceCreate                       |  |
|  |  free  --> NvBufSurfaceDestroy                      |  |
|  |  map   --> NvBufSurface* (NVIDIA convention)        |  |
|  |  fd    --> bufferDesc (DMA-buf)                     |  |
|  |                                                     |  |
|  |         GstNvmmBufferPool                           |  |
|  |  acquire --> recycled NVMM surface                  |  |
|  |  release --> return to pool (no GPU alloc)          |  |
|  +----------------------------------------------------+  |
|                        |                                  |
|                        v                                  |
|  +----------------------------------------------------+  |
|  |  NvBufSurface API    (libnvbufsurface.so)           |  |
|  |  NvBufSurfTransform  (libnvbufsurftransform.so)     |  |
|  |  Tegra VIC Engine    (zero-copy hardware)           |  |
|  +----------------------------------------------------+  |
+----------------------------------------------------------+

         +------------+
  SHM -->| nvmmappsrc |--> downstream (ROS2, inference, etc.)
         +------------+
```

### Component 1: GstNvmmAllocator

The allocator wraps `NvBufSurfaceCreate` / `NvBufSurfaceDestroy` behind GStreamer's `GstAllocator` interface. Following the upstream pattern used by `GstGLMemory` and `GstVulkanImageMemory`, it does **not** override `GstAllocator::alloc(size)` — video allocators need explicit format, width, and height, not just a byte count. Instead, allocation goes through a custom function:

```cpp
GstMemory *mem = gst_nvmm_allocator_alloc_video (alloc,
    GST_VIDEO_FORMAT_NV12, 1920, 1080);
```

The critical design decision: **what does `gst_memory_map()` return?**

On desktop CUDA, mapping gives you a CPU-accessible pointer to pixel data. On Jetson NVMM, the planes aren't contiguous in virtual memory — plane 0 (Y) and plane 1 (UV) can be at completely different addresses. Returning a flat pointer that pretends all planes are contiguous would crash when downstream writes past plane 0's boundary.

We follow NVIDIA's convention: `gst_memory_map()` returns the `NvBufSurface*` pointer itself. NVIDIA's elements (`nvvidconv`, `nvv4l2decoder`) expect this — they cast the mapped data back to `NvBufSurface*` and access the hardware buffer directly. For actual CPU pixel access, we provide `gst_nvmm_memory_map_plane()` which maps one plane at a time with proper `NvBufSurfaceSyncForCpu` cache coherency.

```cpp
// NVIDIA convention: mapped data = NvBufSurface pointer
static gpointer
gst_nvmm_allocator_mem_map (GstMemory *memory, gsize maxsize,
                             GstMapFlags flags)
{
    auto *mem = reinterpret_cast<GstNvmmMemory *>(memory);
    if (!mem->surface) return nullptr;
    return mem->surface;  // NvBufSurface*, not pixels
}

// For actual CPU access: per-plane map
gboolean
gst_nvmm_memory_map_plane (GstMemory *mem, guint plane,
                            GstMapFlags flags,
                            guint8 **data, gsize *size)
{
    NvBufSurfaceMap (surface, 0, plane, flags);
    NvBufSurfaceSyncForCpu (surface, 0, plane);
    *data = surface->surfaceList[0].mappedAddr.addr[plane];
    *size = surface->surfaceList[0].planeParams.psize[plane];
    return TRUE;
}
```

### Component 2: GstNvmmBufferPool

Without a buffer pool, every frame triggers `NvBufSurfaceCreate` + `NvBufSurfaceDestroy` — a 600-microsecond round trip on Xavier NX. At 30fps, that's 18ms per second burned on allocation alone.

`GstNvmmBufferPool` pre-allocates a set of NVMM surfaces and recycles them. When the transform element finishes with a buffer, it goes back to the pool instead of being destroyed. The next frame grabs an already-allocated surface.

The key implementation detail: the pool reads **actual hardware strides** from the allocated NvBufSurface, not from GStreamer's `GstVideoInfo` calculation. NVMM surfaces on Jetson have alignment padding that differs from what GStreamer computes. Without correct strides in `GstVideoMeta`, downstream elements would garble the output.

```cpp
// Read actual NVMM strides, not GstVideoInfo defaults
void *surface = gst_nvmm_memory_get_surface (mem);
auto *nvsurf = static_cast<NvBufSurface *>(surface);
auto &pp = nvsurf->surfaceList[0].planeParams;
for (guint i = 0; i < n_planes; i++) {
    offsets[i] = pp.offset[i];    // hardware offset
    strides[i] = pp.pitch[i];     // hardware pitch
}
gst_buffer_add_video_meta_full (buffer, flags, fmt, w, h,
    n_planes, offsets, strides);
```

### Component 3: nvmmconvert

This is the user-facing element — a `GstBaseTransform` that wraps `NvBufSurfTransform`, the Tegra VIC (Video Image Compositor) hardware engine.

The VIC is a dedicated hardware block on every Jetson SoC. It can crop, scale, flip/rotate, and convert color formats — all without touching the CPU or GPU. A 1080p-to-480p scale takes ~2ms on Xavier NX and ~35 microseconds on Orin NX.

**Caps negotiation** was the hardest part to get right. GStreamer's `GstBaseTransform` needs several virtual methods to negotiate what the element can accept and produce:

- `transform_caps`: given input caps, what output caps are possible? We remove format fields (can convert NV12<->RGBA) and rangify dimensions (can scale to any size).
- `fixate_caps`: when multiple output options exist, which one do we prefer? We prefer the crop dimensions if set, otherwise the input dimensions.
- `get_unit_size`: how many bytes is one frame? We parse caps and return `GST_VIDEO_INFO_SIZE`.
- `prepare_output_buffer`: where does the output go? We acquire a buffer from the NVMM pool.
- `propose_allocation` / `decide_allocation`: the standard GStreamer allocation query dance. We offer an NVMM pool upstream and create one for our output.

The transform itself is straightforward:

```cpp
static GstFlowReturn
gst_nvmm_convert_transform (GstBaseTransform *trans,
                             GstBuffer *inbuf, GstBuffer *outbuf)
{
    NvBufSurface *src = get_nvbuf_surface (inbuf);
    NvBufSurface *dst = get_nvbuf_surface (outbuf);

    NvBufSurfTransformParams xform = {};
    xform.transform_flip = to_nv_flip (flip);

    if (crop_w > 0 && crop_h > 0) {
        NvBufSurfTransformRect rect = {crop_y, crop_x, crop_w, crop_h};
        xform.src_rect = &rect;
        xform.transform_flag |= NVBUFSURF_TRANSFORM_CROP_SRC;
    }

    NvBufSurfTransform (src, dst, &xform);  // VIC hardware, zero CPU
    return GST_FLOW_OK;
}
```

All four operations (crop, scale, flip, format convert) happen in a **single VIC hardware call**. No intermediate buffers, no CPU involvement, no round-trips through system memory.

### Data Flow

Here's what happens when a frame flows through a typical pipeline:

```
videotestsrc       nvvidconv          nvmmconvert         nvvidconv        sink
    |                  |                   |                  |              |
    | video/x-raw      |                   |                  |              |
    | (CPU pixels)     |                   |                  |              |
    |----------------->|                   |                  |              |
    |                  | NvBufSurfCreate   |                  |              |
    |                  | CPU -> NVMM copy  |                  |              |
    |                  |                   |                  |              |
    |                  | video/x-raw(NVMM) |                  |              |
    |                  |------------------>|                  |              |
    |                  |                   | pool.acquire()   |              |
    |                  |                   | NvBufSurfTransf  |              |
    |                  |                   | (VIC hardware)   |              |
    |                  |                   |                  |              |
    |                  |                   | video/x-raw(NVMM)|              |
    |                  |                   |----------------->|              |
    |                  |                   |                  | NVMM -> CPU  |
    |                  |                   |                  | video/x-raw  |
    |                  |                   |                  |------------->|
```

The zero-copy path is between nvvidconv and nvmmconvert: the NVMM buffer passes through without any CPU-side data movement. The VIC reads from one NVMM surface and writes to another, entirely in hardware.

## Bugs We Hit (So You Don't Have To)

### The numFilled Bug

`NvBufSurfaceCreate` initializes `numFilled` to 0. Every subsequent API call checks `index < numFilled`. So if you create a surface and immediately try to map it, the API returns "wrong buffer index" because 0 < 0 is false.

Fix: set `surface->numFilled = surface->batchSize` after creation.

### The Plane Sync Bug

`NvBufSurfaceSyncForDevice(surface, 0, -1)` should sync all planes. On some L4T versions, it returns error 4 (`NvMapMemCacheMaint Bad parameter`). The fix: track which plane you actually mapped and sync only that one.

```cpp
// Wrong: sync all planes when only one was mapped
for (uint32_t p = 0; p < num_planes; p++)
    NvBufSurfaceSyncForDevice (surface, 0, p);  // error on unmapped planes!

// Right: sync only the mapped plane
NvBufSurfaceSyncForDevice (surface, 0, mapped_plane_);
```

### The Allocator Design Bug

Our initial allocator overrode `GstAllocator::alloc(size)` and tried to reverse-engineer width/height from the byte count. This is fundamentally wrong — a GStreamer maintainer pointed us to `GstGLMemory` and `GstVulkanImageMemory` which use a custom alloc function with explicit video parameters and don't touch the `alloc(size)` path at all.

The heuristic also produced off-by-one dimensions (640x481 instead of 640x480) due to integer rounding, which crashed on Orin.

Fix: dropped `GstAllocator::alloc(size)` entirely. All allocation goes through `gst_nvmm_allocator_alloc_video(format, width, height)` — the correct upstream pattern for video allocators.

### The Double-Free Bug

`NvmmBuffer` is an RAII wrapper that calls `NvBufSurfaceDestroy` in its destructor. In `nvmmconvert::transform`, we wrapped borrowed `NvBufSurface*` pointers (owned by the pipeline allocator) in `NvmmBuffer` objects. When they went out of scope, the destructor destroyed surfaces that weren't ours.

Fix: `NvmmBuffer::release()` that detaches ownership without destroying.

## Performance

Benchmarks on Jetson Xavier NX (JetPack 5.1) and Orin NX (JetPack 6), 1000 iterations:

```
                            Xavier NX        Orin NX        Speedup
                            ---------        -------        -------
NV12 1080p alloc/free       591 us           117 us         5x
NV12 1080p map/unmap        231 us           298 us         —
VIC 1080p->480p             1947 us          35 us          56x
VIC 4K->1080p               4002 us          285 us         14x
VIC 4K->480p                3548 us          31 us          114x
```

The Orin's VIC is dramatically faster across the board. 4K-to-480p in 31 microseconds — that's ~32,000 frames per second of hardware transform throughput.

## How to Use It

### Basic pipeline: decode, scale, and save

```bash
gst-launch-1.0 \
  filesrc location=video.mp4 ! qtdemux ! h264parse ! nvv4l2decoder \
  ! 'video/x-raw(memory:NVMM)' \
  ! nvmmconvert crop-x=100 crop-y=50 crop-w=800 crop-h=600 \
  ! 'video/x-raw(memory:NVMM),width=640,height=480' \
  ! nvvidconv ! 'video/x-raw,format=I420' \
  ! jpegenc ! filesink location=output.jpg
```

### Flip and scale in one pass

```bash
gst-launch-1.0 \
  ... ! nvmmconvert flip-method=rotate-180 ! \
  'video/x-raw(memory:NVMM),width=1280,height=720' ! ...
```

The `flip-method` property uses GEnum values: `none`, `rotate-90`, `rotate-180`, `rotate-270`, `horizontal-flip`, `vertical-flip`, `upper-right-diagonal`, `upper-left-diagonal`.

### Fan-out with tee

```bash
gst-launch-1.0 \
  ... ! tee name=t \
  t. ! queue ! nvmmconvert flip-method=rotate-180 ! ... \
  t. ! queue ! nvmmconvert ! 'video/x-raw(memory:NVMM),width=320,height=240' ! ...
```

Each branch gets its own nvmmconvert with independent crop/scale/flip settings. The tee handles buffer refcounting correctly — no copies at the fan-out point.

### Inter-process video sharing

Producer (writes frames to shared memory):
```bash
gst-launch-1.0 \
  ... ! nvmmsink shm-name=/camera_feed export-dmabuf=true
```

Consumer (reads from shared memory):
```bash
gst-launch-1.0 \
  nvmmappsrc shm-name=/camera_feed ! videoconvert ! autovideosink
```

The shared memory protocol uses a `NvmmShmHeader` with magic bytes, resolution, format, frame number, timestamp, and an atomic ready flag for lock-free reads.

### Docker on Jetson

```bash
# Build
docker build --network host -f docker/Dockerfile.jetson \
  -t gst-nvmm-cpp:jetson .

# Run with NVIDIA runtime and host libraries mounted
docker run --runtime nvidia --rm --network host --privileged \
  -v /usr/lib/aarch64-linux-gnu/tegra:/usr/lib/aarch64-linux-gnu/tegra:ro \
  -v /usr/lib/aarch64-linux-gnu/tegra-egl:/usr/lib/aarch64-linux-gnu/tegra-egl:ro \
  -v /usr/lib/aarch64-linux-gnu/gstreamer-1.0:/usr/lib/aarch64-linux-gnu/gstreamer-1.0:ro \
  -v /usr/src/jetson_multimedia_api:/usr/src/jetson_multimedia_api:ro \
  -v /usr/share/glvnd:/usr/share/glvnd:ro \
  -v /etc/alternatives:/etc/alternatives:ro \
  -v /etc/ld.so.conf.d:/etc/ld.so.conf.d:ro \
  gst-nvmm-cpp:jetson
```

The EGL and tegra-egl mounts are essential — `NvBufSurfTransform` needs EGL initialization even when using the VIC (not GPU) compute path.

## Contributing to GStreamer: What We Learned

### The Process

GStreamer is hosted on freedesktop.org's GitLab instance. The contribution process:

1. **File issues first.** Before writing code, describe the gap you want to fill. This starts a conversation with maintainers about whether and how the feature should be implemented. We filed three issues ([#4979](https://gitlab.freedesktop.org/gstreamer/gstreamer/-/issues/4979), [#4980](https://gitlab.freedesktop.org/gstreamer/gstreamer/-/issues/4980), [#4981](https://gitlab.freedesktop.org/gstreamer/gstreamer/-/issues/4981)) for the allocator, buffer pool, and transform element.

2. **Wait for feedback.** Sebastian Droge (`@slomo`), a core maintainer, responded within days. He had specific preferences: single MR combining all three, C++14 to match the existing nvcodec plugin, location in `sys/nvcodec/`.

3. **Request account verification.** New freedesktop.org GitLab accounts can't create forks. You need to file a [user verification issue](https://gitlab.freedesktop.org/freedesktop/freedesktop/issues/new?issuable_template=User%20verification) — tick two checkboxes agreeing to the code of conduct. A bot processes it within minutes.

4. **Fork, branch, push, MR.** Standard GitLab flow. Fork `gstreamer/gstreamer`, create a branch from `main`, push your changes, open MR against upstream `main`.

5. **CI runs.** GStreamer has extensive CI that builds on Linux, Windows, macOS, cross-compiles for various architectures. Your MR needs to pass CI. For Jetson-specific code behind `#ifdef HAVE_CUDA_NVMM`, CI won't test the actual hardware path — but it verifies compilation doesn't break anything.

### What Maintainers Expect

GStreamer maintainers are experienced and busy. They care about:

**Code quality over features.** A smaller, correct MR is better than a large feature-complete one with rough edges. The allocator, buffer pool, and transform element are the minimum viable contribution. The shared memory sink/source elements are useful but separate — they can come in a follow-up MR.

**GStreamer conventions.** Every element should have:
- `GST_DEBUG_CATEGORY` for per-element log filtering
- `GEnum` for properties with named values (not raw integers)
- `GstVideoMeta` attached to buffers with correct strides
- Proper `propose_allocation` / `decide_allocation` for pool negotiation
- `passthrough_on_same_caps` when caps match and no transform is needed

**Clean separation.** The NVMM code is guarded by `#ifdef HAVE_CUDA_NVMM` and only compiles on systems where `nvbufsurface.h` is detected. It adds zero overhead to non-Jetson builds.

**C over C++.** GStreamer prefers C for elements unless the wrapped API is C++. The NvBufSurface API is C, so a pure-C implementation would be preferred. We used C++14 because the existing `nvcodec` plugin is already C++ (`cpp_std=c++14` in meson.build). The C++ is minimal — `std::atomic` for thread-safe properties, RAII in internal helpers.

**Be honest about limitations.** Our reference implementation has a mock API for host-side testing that matches the real NVIDIA struct layouts. Tests pass on x86_64 with the mock, on Xavier NX and Orin NX with real hardware. We documented what's tested and what's not.

### Things That Surprised Us

**Caps negotiation is the hardest part.** Writing the actual transform (call `NvBufSurfTransform`, done) took an hour. Getting caps negotiation right — `transform_caps`, `fixate_caps`, `get_unit_size`, handling passthrough, allocation queries — took days. The GStreamer design manual explains the theory; reading existing elements' source code teaches the practice.

**Pipeline tests catch what unit tests miss.** Our unit tests all passed, but real `gst-launch-1.0` pipelines failed because the allocator's byte-size heuristic produced 640x481 instead of 640x480. One pixel off. This only manifested when downstream `nvvidconv` (on Orin specifically) rejected the surface dimensions.

**Docker on Jetson needs specific mounts.** The NVIDIA runtime (`--runtime nvidia`) isn't enough for GStreamer pipelines. You also need to mount the host's GStreamer plugins directory (`/usr/lib/aarch64-linux-gnu/gstreamer-1.0/`), the EGL libraries (`tegra-egl/`), and the GLVND alternatives. Without EGL, `NvBufSurfTransform` silently fails even though it uses VIC (not GPU) compute.

**Sanitizers work on the mock path.** We ran AddressSanitizer and ThreadSanitizer on the mock-API builds. Since the mock matches the real API's struct layout exactly, bugs caught by sanitizers on x86_64 apply to Jetson too. Both came back clean: no memory errors, no data races.

## Links

- **Reference implementation:** [github.com/PavelGuzenfeld/gst-nvmm-cpp](https://github.com/PavelGuzenfeld/gst-nvmm-cpp)
- **Upstream MR:** [!11101](https://gitlab.freedesktop.org/gstreamer/gstreamer/-/merge_requests/11101)
- **Issues:** [#4979](https://gitlab.freedesktop.org/gstreamer/gstreamer/-/issues/4979), [#4980](https://gitlab.freedesktop.org/gstreamer/gstreamer/-/issues/4980), [#4981](https://gitlab.freedesktop.org/gstreamer/gstreamer/-/issues/4981)
- **GStreamer contribution guide:** [gstreamer.freedesktop.org/documentation/contribute](https://gstreamer.freedesktop.org/documentation/contribute/index.html)
