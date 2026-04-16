---
title: "From Unity to O3DE: Multi-Camera Streaming at 1080p in a Headless Docker Container"
date: 2026-04-16
draft: false
tags: ["O3DE", "Vulkan", "GStreamer", "Docker", "simulation", "C++", "GPU", "NVENC", "rendering", "performance", "headless", "RTSP", "benchmarking", "drones"]
keywords: ["O3DE Unity migration", "O3DE headless Docker rendering", "GStreamer NVENC O3DE", "multi-camera simulation streaming", "RenderToTexture O3DE"]
cover:
  image: /images/posts/o3de-migration-exploration.png
  alt: "O3DE rendering a ground plane from a camera spawned programmatically inside a headless Docker container"
categories: ["deep-dive"]
summary: "Exploring whether O3DE can replace Unity as the render engine for a drone simulation that streams multiple 1080p camera feeds via GStreamer. From first scaffold to three live RenderToTexture pipelines in a single session."
ShowToc: true
---

Our Unity-based drone simulation runs at 11-16 FPS. The cameras stream via RTSP, PX4 SITL controls the airframe, and the whole thing lives in Docker. That frame rate isn't acceptable for the scenarios we need to run, so I set out to answer one question: **can O3DE do better?**

This post covers the exploration from empty scaffold to three independent 1080p camera streams running in a headless container. No Editor, no GUI, no pre-authored levels -- everything spawned programmatically from a YAML config.

## The starting point

The existing Unity Sandbox renders a 6 km terrain (SRTM DTM, Negev desert), ~500 OSM buildings, roads, trees, and a PX4-controlled tailsitter drone. It streams three camera feeds over RTSP using FFmpegOut. The bottleneck is the Unity render loop: 11-16 FPS on an RTX 3060 Laptop.

The question isn't whether O3DE is a better engine -- it's whether Atom (O3DE's renderer) can push frames fast enough through a GStreamer encode pipeline to beat Unity's current throughput.

## What we built

Everything lives under `o3de/` in the repo, on the `experiment/o3de-replacement` branch.

### Project structure

```
o3de/
  config/sandbox.yaml          # All parameters -- zero magic numbers in C++
  project/Sandbox/             # Buildable O3DE project
    Gem/Code/Source/
      SandboxConfig.h/cpp      # YAML config loader
      FrameLoggerSystemComponent    # Per-frame dt_us to stdout
      GStreamerStreamComponent      # RTT readback -> appsrc -> nvh264enc -> UDP
      SceneBootstrapComponent       # Spawns camera/ground/light/sky from config
  docker/
    Dockerfile                 # Inherits fiber-nav-o3de:phase1 + GStreamer
    build_sandbox.sh           # CMake + Ninja inside container
  bench/
    run_phase0.sh              # Automated bench harness
    capture_video.sh           # H264 stream capture
    PHASE0_RESULT.md           # Measurement results
  docs/
    GEM_AUDIT.md               # Dead-weight gem analysis
```

### The config

Every numeric constant lives in `sandbox.yaml`:

```yaml
cameras:
  - name: cam0
    width: 1920
    height: 1080
    fps: 30
    fov_degrees: 60.0
    position: [0.0, -15.0, 10.0]
    rotation_degrees: [-30.0, 0.0, 0.0]
    udp_port: 5000
  - name: cam1
    ...
```

Camera positions, FOVs, encoder settings, warmup timings, scene parameters -- all tunable without recompilation.

## Phase 0: can the engine tick fast enough?

### Measurement approach

`FrameLoggerSystemComponent` hooks into `AZ::TickBus::Handler` at `TICK_LAST` and prints:

```
[FrameLogger] frame=42 dt_us=28934
```

The bench script (`run_phase0.sh`) collects these over 60 seconds, computes p50/p95, and checks against the gate.

### What we found

The first measurement with 31 gems loaded showed p50 = 43.2 ms (~23 FPS). The engine was CPU-bound at 24% GPU utilization -- the Atom RPI pass graph was the bottleneck, not the GPU.

| Step | p50 | FPS | What changed |
|---|---|---|---|
| Baseline (31 gems, SwapChain) | 43.2 ms | 23 | Everything loaded |
| Trimmed gems (20 modules) | 40.9 ms | 24 | Dropped PhysX, ScriptCanvas, Audio |
| **AttachmentReadback path** | **29.0 ms** | **34.5** | Bypassed Xvfb present stall |
| Release build | 29.7 ms | 33.6 | No improvement |

The decisive optimization was switching from SwapChain readback (which goes through Xvfb's present path) to `AttachmentReadback` reading directly from the render target. That eliminated a 14 ms stall caused by the virtual framebuffer's swap synchronization.

### Dead-weight audit

We audited all 31 loaded modules. 23 were pure overhead for an empty scene -- PhysX running its solver at 200 Hz with no colliders, EMotionFX scheduling skeleton updates with no meshes, ScriptCanvas evaluating zero graphs. Trimming them saved 2.3 ms. The real cost was the Atom pass graph itself: ~40 render passes scheduled every frame regardless of content.

## GStreamer integration

### The readback pipeline

`GStreamerStreamComponent` reads back the rendered frame using O3DE's `AttachmentReadback` API:

```
O3DE Atom renderer
  -> RenderToTexture pass (per camera)
  -> AttachmentReadback (async GPU->CPU)
  -> appsrc (RGBA 1920x1080)
  -> videoconvert (I420)
  -> nvh264enc (NVENC hardware encoder)
  -> rtph264pay
  -> udpsink (per-camera UDP port)
```

Each camera gets its own `RenderToTexture` pipeline, its own `AttachmentReadback`, and its own GStreamer encoder pipeline. The encoder runs at ~500 fps throughput on the RTX 3060 -- encoding is never the bottleneck.

### Format detection

O3DE's RTT path outputs `R8G8B8A8_UNORM_SRGB` (format 19), while the SwapChain outputs `B8G8R8A8_UNORM`. The component detects the format at runtime and sets the correct GStreamer caps:

```cpp
const char* gstFormat = "BGRA";
if (desc.m_format == AZ::RHI::Format::R8G8B8A8_UNORM ||
    desc.m_format == AZ::RHI::Format::R8G8B8A8_UNORM_SRGB)
{
    gstFormat = "RGBA";
}
```

## The RenderToTexture journey

Getting per-camera offscreen rendering working was the hardest part.

### Attempt 1: SwapChain readback (works, one camera)

Reading the SwapChain gives you whatever the active viewport camera sees. This works for a single camera but all cameras read the same image -- no multi-view.

### Attempt 2: Manual RenderPipeline creation (crashes)

Creating a `RenderPipeline` with the `MainPipelineRenderToTexture` template and calling `Scene::AddRenderPipeline` crashed immediately with `VK_ERROR_DEVICE_LOST` or `SIGABRT` in `SetPersistentView`.

Two bugs found via GDB:

1. **`SetDefaultView` called before `AddRenderPipeline`** -- the pipeline's internal pointer was corrupted because the scene hadn't taken ownership yet.

2. **MSAA mismatch** -- the RTT pipeline was created with `samples=1` but the MainPipeline's shaders expect `samples=2`. Fix: read `GetApplicationMultisampleState()` from the engine at runtime.

### Working solution

```cpp
// Match engine MSAA
desc.m_renderSettings.m_multisampleState.m_samples =
    AZ::RPI::RPISystemInterface::Get()->GetApplicationMultisampleState().m_samples;

// Add to scene FIRST, then set view
scene->AddRenderPipeline(cam.renderPipeline);
cam.renderPipeline->SetDefaultView(view);
```

### Entity creation matters

Entities created with `aznew AZ::Entity()` are standalone -- they have no scene context, so `MeshFeatureProcessor`, `DirectionalLightFeatureProcessor`, and `CameraComponent` can't find their feature processors. The fix: use `GameEntityContextRequestBus::CreateGameEntity()` which registers the entity with the scene.

## Results

### Three cameras streaming

Three independent 1920x1080 camera views, each rendered by its own `RenderToTexture` pipeline, each encoding to H.264 via NVENC, each streaming to a separate UDP port:

- **cam0**: position (0,-15,10), FOV 60, port 5000
- **cam1**: position (20,-10,8), FOV 90, port 5001
- **cam2**: position (-15,-20,12), FOV 45, port 5002

View them with:

```bash
gst-launch-1.0 udpsrc port=5000 \
  caps='application/x-rtp,media=video,encoding-name=H264,payload=96' \
  ! rtph264depay ! h264parse ! avdec_h264 ! videoconvert \
  ! autovideosink sync=false
```

### Performance

| Config | p50 | FPS |
|---|---|---|
| 1 camera (SwapChain, no content) | 29 ms | 34.5 |
| 1 camera (RTT + scene content) | 31 ms | 32 |
| 3 cameras (3 RTT pipelines) | 48 ms | 21 |

Each `MainPipelineRenderToTexture` instance costs ~15 ms CPU (40 render passes). Three cameras = three full pipeline instances. The GPU stays at 8-24% -- the bottleneck is CPU-side pass scheduling, not rendering.

### Where this stands vs Unity

These numbers are **not a fair comparison**. Unity renders a full scene (6 km terrain, 500 buildings, roads, trees, a drone entity, PX4 integration). O3DE is rendering a flat ground plane and a sky. The GPU headroom (8-24% vs Unity's ~90%) only tells us that the GPU isn't the bottleneck *yet* -- it says nothing about what happens when real content loads.

| | Unity (full scene) | O3DE (empty scene) |
|---|---|---|
| Content | Terrain + 500 buildings + drone + PX4 | Ground plane + sky |
| 1 camera | 11-16 FPS | 34.5 FPS |
| 3 cameras | ~8 FPS | 21 FPS |
| GPU utilization | ~90% | ~20% |

The only honest conclusion: O3DE's engine overhead on an empty scene leaves room for content. Whether that room is enough for the full Sandbox scene is an open question that Phase 2-4 will answer.

## What we didn't solve

- **Custom render pipeline**: the full MainPipeline (40 passes including SSAO, bloom, DoF, TAA) runs for each camera. A stripped 5-pass pipeline could cut per-camera cost from 15 ms to ~5 ms, enabling 3x1080p at 30+ FPS.
- **MSAA override**: the project-scope `MainRenderPipeline.azasset` override didn't take effect (engine loads from gem path, not project assets). MSAA 2x is always on.
- **Level authoring**: without the Editor, all content is spawned programmatically. A proper `.spawnable` level would improve load times and asset management.

## What's next

- **Phase 2**: port the SRTM terrain heightmap and satellite imagery
- **Phase 3**: port the OSM buildings, roads, and trees
- **Phase 4**: connect PX4 SITL and fly the tailsitter
- **Phase 5**: port all art assets (drone, vehicles, characters)

The engine boots, renders, and streams. The plumbing works. But the real question -- whether O3DE can handle the full Sandbox scene (terrain, 500 buildings, drone, PX4) at a higher frame rate than Unity -- is still unanswered. That's Phase 2-4.
