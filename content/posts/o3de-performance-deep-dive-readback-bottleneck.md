---
title: 'Chasing 18 Milliseconds: A Performance Deep Dive into O3DE''s Render Readback
  Pipeline'
date: 2026-04-17
draft: false
tags:
- O3DE
- Vulkan
- GStreamer
- C++
- GPU
- performance
- benchmarking
- rendering
- Docker
- headless
- NVENC
keywords:
- O3DE AttachmentReadback performance
- Vulkan readback overhead
- O3DE multi-camera rendering
- frame graph scope cost
- GPU readback optimization
cover:
  image: /images/posts/o3de-migration-exploration.png
  alt: O3DE multi-camera rendering performance analysis
categories:
- deep-dive
summary: 'We spent a full session systematically profiling O3DE''s multi-camera streaming
  pipeline, testing eight different optimization approaches, and pinpointed the exact
  bottleneck: 18 ms of fixed overhead in the AttachmentReadback scope system. Here''s
  what we tried, what we measured, and what it means for the engine.'
ShowToc: true
audio:
  pronunciation:
    O3DE: O three D E
    Atom: atom
    AttachmentReadback: attachment readback
    RenderToTexture: render to texture
    RenderToTexturePass: render to texture pass
    FrameScheduler: frame scheduler
    FrameGraphCompiler: frame graph compiler
    CompileProducers: compile producers
    CompileResources: compile resources
    ImportScopeProducer: import scope producer
    ScopeProducerFunctionNoData: scope producer function no data
    OnReadbackComplete: on readback complete
    OnTick: on tick
    ShaderResourceGroups: shader resource groups
    EndFrame: end frame
    vkCmdCopyImageToBuffer: V K C M D copy image to buffer
    vkQueueSubmit: V K queue submit
    CommandQueue::ProcessQueue: command queue process queue
    GStreamerStreamComponent: G streamer stream component
    GStreamer: G streamer
    appsrc: app source
    nvh264enc: N V H two six four enc
    rtph264pay: R T P H two six four pay
    udpsink: U D P sink
    AZStd::thread: A Z S T D thread
    AZ::JobCompletion: A Z job completion
    RHI::HardwareQueueClass::Copy: R H I hardware queue class copy
    AttachmentLifetimeType::Imported: attachment lifetime type imported
    AttachmentImage: attachment image
    BatchedReadback: batched readback
    FrameCaptureRequestBus: frame capture request bus
    CapturePassAttachmentWithCallback: capture pass attachment with callback
    RTX 3060: R T X thirty sixty
    libAtom_RPI.Private.so: lib atom R P I private dot S O
---

> This is a follow-up to [From Unity to O3DE: Multi-Camera Streaming at 1080p](/posts/o3de-migration-exploration-multi-camera-streaming/). That post covered the initial migration; this one covers what happened when we tried to make it fast.

We had three cameras rendering at 1920x1080 via O3DE's `RenderToTexture` pipeline, each streaming H.264 over UDP through GStreamer. It worked. The problem: **20 FPS**. The GPU was 85% idle. Something was burning 50 ms per frame, and it wasn't rendering.

This post documents the systematic hunt for those milliseconds.

## The setup

Three `RenderToTexture` pipelines in O3DE's Atom renderer, each with its own `View`, rendering to separate output images. A `GStreamerStreamComponent` reads back each camera's output via `AttachmentReadback` and pushes frames through `appsrc -> nvh264enc -> rtph264pay -> udpsink`. Everything runs in a headless Docker container on an RTX 3060 Laptop.

## The baseline

First, establish what costs what:

| Configuration | Frame time | FPS |
|---|---|---|
| Engine + SwapChain only (no RTT) | 31 ms | 32 |
| 3 RTT pipelines, **no readback** | 32 ms | 31 |
| 3 RTT pipelines + readback | **50 ms** | **20** |

The rendering itself is essentially free: three extra full `MainPipeline` render graphs add only 1 ms. The entire 18 ms overhead comes from the readback path.

## Attempt 1: Producer-consumer encode

**Hypothesis**: The readback callback runs `memcpy` (8 MB per frame) and `gst_app_src_push_buffer` on the main thread. Moving that off should help.

**Implementation**: `OnReadbackComplete` enqueues a `shared_ptr` to the pixel data into a lock-free queue. A dedicated `AZStd::thread` pops items and does the memcpy + GStreamer push.

**Result**: Main thread CPU dropped from **70% to 21%**. But frame time unchanged at 50 ms. The Vulkan Graphics Queue thread became the new bottleneck at 70% CPU.

**Lesson**: The encode was never on the critical path. We moved work off the main thread, but the frame time is set by the slowest stage in the pipeline. With the encode off the main thread, the graphics queue submission became the limiter.

## Attempt 2: Parallel CompileProducers

**Hypothesis**: `FrameScheduler::CompileProducers` iterates all 160 scope producers (40 passes x 4 pipelines) sequentially. Parallelizing them should help.

**Implementation**: Patched `CompileProducers()` to dispatch each scope's `CompileResources()` to `AZ::JobCompletion` workers.

**Result**: No effect. Worker threads showed <1% CPU. Each scope's `CompileResources` completes in microseconds -- the per-job overhead exceeds the work itself.

**Lesson**: The bottleneck isn't in `CompileResources`. The scope compile is cheap per scope.

## Attempt 3: Round-robin readback

**Hypothesis**: 3 readback scopes per frame cost 3x. Only reading back 1 camera per frame (cycling) should cut the overhead to 1/3.

**Implementation**: `(m_tickCount % m_cameras.size()) == i` guard on `RequestReadback`.

**Result**: No effect. Same 50 ms.

**Lesson**: The overhead isn't proportional to the number of readbacks per frame. It's a fixed cost of having readback objects registered in the frame graph.

## Attempt 4: Ephemeral readback

**Hypothesis**: Persistent `AttachmentReadback` objects keep their scopes registered in the frame graph across frames, adding overhead even when idle. Creating and destroying them per frame should help.

**Implementation**: Create a fresh `AttachmentReadback` in each `OnTick`, capture the `shared_ptr` in the callback lambda so it lives until the callback fires, then gets destroyed.

**Result**: No effect. 50 ms.

**Lesson**: The scope gets added to the frame graph the moment `ReadbackOutput` is called and costs its full overhead within that same frame. Object lifetime doesn't matter.

## Attempt 5: Copy queue

**Hypothesis**: The readback scope runs on the Graphics queue. Moving it to the dedicated Transfer queue (NVIDIA RTX 3060 has a separate transfer queue family) should overlap with graphics work.

**Implementation**: Patched `AttachmentReadback`'s `ScopeProducerFunctionNoData` constructor to pass `RHI::HardwareQueueClass::Copy` instead of `Graphics`. Verified the Vulkan backend already supports it.

**Result**: No effect. 50 ms. Confirmed with recompile of `libAtom_RPI.Private.so`.

**Lesson**: The scope is still in the same frame graph regardless of which queue it targets. The frame graph compiler processes all scopes -- it doesn't know or care about the hardware queue class when resolving dependencies and allocating resources.

## Attempt 6: Persistent RTT output

**Hypothesis**: The RTT output is a transient image that gets allocated/deallocated each frame. Making it persistent (Imported lifetime with `AttachmentImage`) might reduce the readback scope's allocation overhead.

**Implementation**: Patched `RenderToTexturePass::BuildInternal` to create the output as `AttachmentLifetimeType::Imported` with a persistent `AttachmentImage` from the system attachment pool.

**Result**: Partial improvement for 1 camera (50 ms -> 40.7 ms, -18.6%). But with 3 cameras, back to 50 ms.

**Lesson**: The persistent image helps per-scope (eliminates transient allocation), but the total overhead scales with the number of scopes. 3 cameras x 6 ms per scope compile = 18 ms, back to the same cost.

## Attempt 7: Batched readback scope

**Hypothesis**: 3 separate readback scopes = 3x compile overhead. One shared scope that round-robins across cameras should cost 1/3.

**Implementation**: `BatchedReadback` class with a single `AttachmentReadback` instance shared across all cameras. Only one scope registered in the frame graph. Round-robin which camera gets read back each frame.

**Result**: No effect. 50 ms with a single scope.

**Lesson**: The 18 ms is the fixed cost of having **any** `AttachmentReadback` scope in the frame graph, regardless of count. One scope costs the same as three.

## Attempt 8: FrameCaptureRequestBus

**Hypothesis**: Maybe the public `FrameCaptureRequestBus::CapturePassAttachmentWithCallback` API has a more efficient internal path.

**Result**: Same 50 ms. It uses `AttachmentReadback` internally.

## What we actually measured

The GPU fence wait between frames: **4-6 microseconds**. The frames-in-flight system (3-frame ring buffer) is already working. GPU is never blocking the CPU.

Per-thread CPU usage with producer-consumer:
```
Main thread:       21% (was 70% before producer-consumer)
Graphics Queue:    70% (Vulkan command submission)
Encode thread:      5% (our consumer -- memcpy + GStreamer)
GStreamer encoders:  7% each (NVENC hardware encoding)
```

The main thread is free. The GPU is free. The encode is free. The bottleneck is the `CommandQueue::ProcessQueue` thread doing `vkQueueSubmit` for all the scopes including the readback scope.

## The root cause

`AttachmentReadback` adds a scope to O3DE's frame graph via `ImportScopeProducer`. Every frame, the `FrameGraphCompiler` processes this scope:

1. Resolves its attachment dependencies against all other scopes
2. Allocates transient resources (staging buffer)  
3. Builds the execution schedule
4. Compiles its `ShaderResourceGroups`
5. Records its command buffer
6. Submits via the graphics queue

Steps 1-4 happen on the main thread during `FrameScheduler::Compile`. Steps 5-6 happen during `FrameScheduler::Execute`. The total: 18 ms of fixed overhead, regardless of how many images are copied or which queue is used.

This is fundamental to O3DE's architecture. The frame graph compiler doesn't distinguish between a readback scope and a render scope -- both get the full compile treatment.

## The fix that would work

The copy needs to happen **outside the frame graph**, after `FrameScheduler::EndFrame()`. This requires:

1. Making the RTT output image persistent (we proved this works -- rendering is unaffected)
2. After `EndFrame()`, recording `vkCmdCopyImageToBuffer` into a command buffer on the dedicated transfer queue
3. Using a semaphore to synchronize: graphics queue signals when rendering is done, transfer queue waits before copying
4. Mapping the staging buffer on the CPU and pushing pixels to GStreamer

This bypasses the scope system entirely. The estimated cost: DMA copy time (~1 ms for 8 MB at PCIe bandwidth) instead of 18 ms of frame graph compilation.

This is an engine-level change -- not something achievable from gem/plugin code. The right path is a contribution to O3DE: adding a `DirectReadback` mode to `RenderToTexturePass` that copies the output to a persistent staging buffer within the existing render scope's command list.

## What we shipped anyway

Despite not beating the 18 ms wall:

- **3-camera RTT streaming works end-to-end** at 20-22 FPS via GStreamer
- **Producer-consumer architecture** decouples encode from the main thread
- **Config-driven** -- all camera positions, FOVs, ports, encoder settings from YAML
- **6 engine patches documented** with measurements for each
- **The exact bottleneck identified** with profiling data at every level

The profiling methodology -- fence timing, per-thread CPU measurement, elimination testing (with/without readback), engine instrumentation -- is reusable for any O3DE performance investigation.

## Numbers

| Configuration | Frame time | FPS | GPU |
|---|---|---|---|
| Baseline (SwapChain only) | 31 ms | 32 | 24% |
| 3 RTT, no readback | 32 ms | 31 | 15% |
| 3 RTT + readback (before) | 50 ms | 20 | 15% |
| 3 RTT + readback (after all opts) | 45-50 ms | 20-22 | 16% |
| Theoretical (bypass scope system) | ~33 ms | ~30 | ~20% |

The gap between 32 ms (no readback) and 50 ms (with readback) is the engineering opportunity. 18 ms of scope compilation overhead, recoverable with a targeted engine change that doesn't touch the rendering path at all.
