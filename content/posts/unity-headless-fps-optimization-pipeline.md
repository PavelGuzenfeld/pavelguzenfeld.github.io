---
title: 'From 21 to 25 FPS: Profiling and Optimizing a Headless Unity Simulation Pipeline'
date: 2026-04-04
draft: false
tags:
- Unity
- Docker
- performance
- profiling
- NVENC
- GPU
- rendering
- optimization
- headless
- RTSP
- FFmpeg
keywords:
- Unity headless FPS optimization
- Unity camera render performance
- NVENC vs libx264 Unity
- GPU instancing Unity headless
- Unity batch camera rendering
cover:
  image: /images/posts/unity-fps-optimization.png
  alt: FPS optimization pipeline for headless Unity simulation
categories:
- deep-dive
summary: A detailed technical walkthrough of profiling and optimizing a headless Unity
  simulation from 21 to 25 FPS — covering NVENC GPU encoding, batch camera rendering,
  GPU instancing, static batching, and the failed URP migration. Every measurement,
  every dead end, every lesson.
ShowToc: true
audio:
  pronunciation:
    Unity: Unity
    Vulkan: vulkan
    URP: U R P
    HDRP: H D R P
    Built-in RP: built in R P
    SRP Batcher: S R P batcher
    RenderGraph: render graph
    Xvfb: X V F B
    EGL: E G L
    FFmpeg: F F mpeg
    NVENC: N V enc
    h264_nvenc: H two six four N V enc
    libx264: lib X two six four
    RTSP: R T S P
    RTX 3060: R T X thirty sixty
    AsyncGPUReadback: async G P U readback
    PCIe: P C I E
    VRAM: V RAM
    camera.Render: camera dot render
    LateUpdate: late update
    WaitForEndOfFrame: wait for end of frame
    SimpleCameraCapture: simple camera capture
    MainCamera: main camera
    FindObjectsByType: find objects by type
    FindObjectsSortMode.None: find objects sort mode none
    Renderer: renderer
    StaticBatchingUtility.Combine: static batching utility combine
    enableInstancing: enable instancing
    isStatic: is static
    targetTexture: target texture
    ApplicationSetting.yaml: application setting dot yaml
    UseInstalledFFmpeg: use installed F F mpeg
    defaultGPU.json: default G P U dot J S O N
    Coroutine: co routine
    EndOfFrameLoop: end of frame loop
    renderGraphSettings.enableRenderCompatibilityMode: render graph settings dot enable
      render compatibility mode
    Unity 6000.0.71f1: Unity six thousand dot zero dot seventy one F one
    FFmpeg pipe write: F F mpeg pipe write
    FPS: F P S
---

## Starting Point

Three RTSP camera streams at 1920x1080 @ 30fps target, running in a Docker container with GPU-accelerated Vulkan rendering. The simulation renders a terrain with satellite imagery, buildings, and a procedural skybox.

Starting metrics:

| Metric | Value |
|--------|-------|
| Render FPS | 21 fps |
| CPU (container) | 323% (3.2 cores) |
| GPU compute | 19% |
| GPU encoder | 0% (CPU encoding) |
| VRAM | 1.5 GB / 6.1 GB |
| Container RAM | 1.6 GB |

The GPU was 81% idle while the CPU was maxed out. Something was very wrong with how the pipeline used resources.

## Step 1: Identify the Bottleneck

### Measuring Actual Render FPS

Unity's target frame rate and actual render rate are different things. The FFmpeg config declared 30fps, but that's just what FFmpeg *expects* — not what Unity delivers.

To measure actual render FPS, I counted bytes flowing through the FFmpeg pipe:

```bash
FRAME_SIZE=$((1920 * 1080 * 4))  # RGBA per frame = 8,294,400 bytes
PID=$(ps aux | grep ffmpeg | head -1 | awk '{print $2}')
BEFORE=$(cat /proc/$PID/io | grep rchar | awk '{print $2}')
sleep 3
AFTER=$(cat /proc/$PID/io | grep rchar | awk '{print $2}')
FPS=$(( (AFTER - BEFORE) / FRAME_SIZE / 3 ))
echo "Actual render FPS: $FPS"
```

Result: **21 fps** per camera — 30% below the 30fps target.

### Where Time Was Spent

```
Unity Main Thread (47ms per frame at 21fps):
├── camera.Render() × 3     ~48ms total  ← BOTTLENECK
│   ├── HeadCamera           ~16ms
│   ├── ChaseCamera          ~16ms
│   └── BodyCamera           ~16ms
├── AsyncGPUReadback × 3     <1ms
├── FFmpeg pipe write × 3    ~2ms
└── Other (physics, REST)    ~1ms
```

Three sequential `camera.Render()` calls consumed the entire frame budget. Each one blocked for ~16ms while the CPU waited for the GPU to finish.

### Resource Utilization Map

| Resource | Usage | Capacity | Bottleneck? |
|----------|-------|----------|-------------|
| CPU (Unity main thread) | 163% | ~200% | **Yes** |
| CPU (3× FFmpeg libx264) | 147% | - | Contributing |
| GPU compute | 19% | 100% | No (81% idle) |
| GPU encoder (NVENC) | 0% | 100% | Not used |
| PCIe readback | 498 MB/s | ~12 GB/s | No |
| RAM | 1.6 GB | 62 GB | No |

## Step 2: NVENC GPU Encoding

### The Problem

Each FFmpeg process used ~49% CPU for H.264 encoding with `libx264`:

```
/opt/build/ffmpeg ... -c:v libx264 -preset veryfast -tune zerolatency ...
```

Three streams = 147% CPU just for encoding, competing with Unity's render thread.

### The Fix

The bundled FFmpeg binary didn't have NVENC support. But the system FFmpeg (from `apt`) did:

```bash
# Bundled FFmpeg
$ /opt/build/ffmpeg -encoders | grep nvenc
# (nothing)

# System FFmpeg
$ ffmpeg -encoders | grep nvenc
V..... h264_nvenc   NVIDIA NVENC H.264 encoder
```

Two config changes:

```yaml
# ApplicationSetting.yaml
UseInstalledFFmpeg: true  # use system ffmpeg
```

```json
// defaultGPU.json
{
  "PresetSettings": "-pix_fmt yuv420p -c:v h264_nvenc -preset llhp -b:v 3M -fflags nobuffer"
}
```

### Results

| Metric | libx264 | h264_nvenc | Change |
|--------|---------|------------|--------|
| FFmpeg CPU (3 streams) | 147% | 46% | **-69%** |
| Total CPU | 323% | 201% | **-38%** |
| GPU encoder | 0% | 21% | Encoding moved to dedicated NVENC chip |
| Render FPS | 21 → 23 | 19 | Slight drop (GPU now shared) |

The CPU savings were significant — 1.2 fewer cores consumed. The render FPS dropped slightly because the GPU now handles both rendering and encoding.

### Gotcha: NVENC Preset Compatibility

The first attempt with `-preset p1 -tune ll` crashed silently — the NVENC version in the container didn't support newer presets. Falling back to `-preset llhp` (low-latency high-performance) worked reliably.

## Step 3: Batch Camera Rendering

### The Problem

Each `SimpleCameraCapture` had its own `LateUpdate()` that called `camera.Render()` independently:

```csharp
// Three of these run sequentially on the same frame:
void LateUpdate()
{
    camera.Render();  // blocks ~16ms
    _session.PushFrame(_rt);  // async, fast
}
```

Unity's `camera.Render()` is synchronous — it submits GPU commands AND waits for completion before returning. Three sequential calls = 48ms of blocking.

### Approach 1: Batch Submit (Failed)

I tried submitting all three renders back-to-back before any readback:

```csharp
// Phase 1: Submit all renders
foreach (var job in _cameras)
    job.camera.Render();  // still blocks per camera

// Phase 2: Push frames
foreach (var job in _cameras)
    job.capture.PostRender();
```

**Result: No improvement.** `camera.Render()` is fundamentally synchronous in Built-in RP — it doesn't return until the GPU finishes, regardless of ordering.

### Approach 2: Stagger Rendering (Wrong Tradeoff)

Rendered one camera per frame in round-robin:

```csharp
int idx = _frameIndex % _cameras.Count;
_cameras[idx].camera.Render();  // only 1 render per frame
```

**Result: 60fps simulation loop, but each camera dropped to 10fps.** The streams looked choppy — wrong tradeoff for a streaming application.

### Approach 3: Auto-Render Pipeline (Success)

Let Unity's internal rendering pipeline handle camera scheduling instead of manual `Render()` calls:

```csharp
// Start(): enable camera for automatic rendering
_camera.enabled = true;
_camera.targetTexture = _rt;
// DON'T call camera.Render() manually

// EndOfFrame coroutine: push frames after Unity rendered all cameras
IEnumerator EndOfFrameLoop()
{
    while (true)
    {
        yield return new WaitForEndOfFrame();
        foreach (var entry in _cameras)
            entry.capture.PostRender();
    }
}
```

**Result: 21 → 25 fps.** Unity's internal renderer pipelines the GPU work better than manual `Render()` calls. The key insight: Unity batches GPU command submission internally when cameras are enabled, avoiding the per-camera CPU sync that `camera.Render()` forces.

### Why It Works

When cameras are enabled with `targetTexture` assigned:

1. Unity queues all camera renders in its internal render loop
2. GPU command buffers are submitted together
3. The CPU doesn't wait between cameras — it prepares the next while the GPU processes the previous
4. `WaitForEndOfFrame` fires after ALL cameras have rendered

With manual `camera.Render()`:

1. CPU submits camera 1 → waits for GPU → 16ms
2. CPU submits camera 2 → waits for GPU → 16ms
3. CPU submits camera 3 → waits for GPU → 16ms
4. Total: 48ms of blocking

## Step 4: Disable Unused Camera

The scene had a `MainCamera` that rendered every frame but nobody watched its output — it wasn't connected to any stream. In headless mode, it was pure waste:

```csharp
void DisableMainCamera()
{
    foreach (var cam in FindObjectsByType<Camera>(FindObjectsSortMode.None))
    {
        if (cam.gameObject.name == "MainCamera")
        {
            cam.enabled = false;
            break;
        }
    }
}
```

**Result:** CPU 160% → 156%, GPU 25% → 16%. FPS unchanged but freed significant GPU headroom.

## Step 5: GPU Instancing + Static Batching

### GPU Instancing

The scene had ~6800 materials, many shared across identical building meshes. Enabling instancing:

```csharp
foreach (var renderer in FindObjectsByType<Renderer>(FindObjectsSortMode.None))
    foreach (var mat in renderer.materials)
        mat.enableInstancing = true;
```

**6,820 materials instanced.** Instead of 200 separate draw calls for identical buildings, the GPU renders them in a handful of instanced calls.

### Static Batching

Non-moving objects (buildings, terrain) were marked static and combined at runtime:

```csharp
foreach (var go in staticObjects)
    go.isStatic = true;

StaticBatchingUtility.Combine(root);
```

**5,341 objects statically batched.**

### Results

GPU dropped from 24% to 16% — fewer draw calls, less GPU overhead. But FPS didn't increase because the bottleneck was CPU-side draw call *submission*, not GPU-side draw call *execution*.

## Step 6: URP Migration (Failed)

### The Theory

URP's SRP Batcher reduces CPU draw call overhead by 2-4x compared to Built-in RP. It groups draw calls by shader variant instead of per-material, keeping GPU state persistent across draws.

### What Happened

1. **Editor Setup**: Created URP pipeline asset, renderer, assigned to Graphics + Quality settings
2. **Build**: Succeeded — URP shaders compiled correctly
3. **Runtime**: Unity hung during scene load. `RenderGraph is now enabled` was the last log before silence

The scene never loaded. The RenderGraph (Unity 6's URP default) doesn't work with Xvfb virtual display in headless mode. The GPU tries to initialize display-dependent render passes that fail silently.

### Lesson

URP on headless Linux/Vulkan/Xvfb is not production-ready as of Unity 6000.0.71f1. The RenderGraph assumes a real display context. This would need either:

- A Unity bug report for headless RenderGraph support
- Disabling RenderGraph (`renderGraphSettings.enableRenderCompatibilityMode = true`)
- Using a different virtual display (e.g., EGL offscreen instead of Xvfb)

## Final Results

| Step | FPS | CPU | GPU | Key Change |
|------|-----|-----|-----|------------|
| Baseline | 21 | 323% | 19% | 3× manual camera.Render() + libx264 |
| + NVENC | 19 | 201% | 40% | GPU encoding, freed 1.2 CPU cores |
| + Auto-render | 25 | 166% | 25% | Unity internal camera pipeline |
| + Disable MainCamera | 25 | 160% | 16% | Removed wasted render |
| + Instancing + batching | 25 | 158% | 16% | 6820 materials instanced |
| **Total improvement** | **+19%** | **-51%** | **-16%** | |

## What Actually Matters

### Things That Worked

1. **NVENC**: Moving encoding off CPU to dedicated GPU hardware. Massive CPU savings with no quality loss.
2. **Auto-render pipeline**: Letting Unity schedule camera renders internally instead of manual `Render()` calls. The framework knows more about GPU command batching than we do.
3. **Disabling unused cameras**: Pure waste elimination.

### Things That Didn't Help FPS

1. **GPU instancing**: Reduced GPU load but CPU was the bottleneck, not GPU.
2. **Static batching**: Same — GPU optimization when CPU is the limit.
3. **Batch submit ordering**: `camera.Render()` is synchronous regardless of call order.
4. **URP migration**: Would have been the biggest win but doesn't work headless.

### The Fundamental Limit

At 25fps with 3 cameras at 1080p on Built-in RP, the bottleneck is **CPU-side draw call submission**. Each camera requires the CPU to iterate through thousands of renderers and issue draw commands to the GPU. The GPU finishes quickly (16% utilized) but the CPU can't feed it fast enough.

The only path past this limit is URP's SRP Batcher, which batches draw calls by shader variant instead of individually. But that requires solving the headless RenderGraph issue first.

### Per-Frame Cost Breakdown (Final)

```
Frame budget: 40ms (25fps)

CPU work:
├── Unity render loop (3 cameras)  ~35ms
│   ├── Culling                     ~3ms
│   ├── Draw call submission        ~25ms  ← THE WALL
│   └── GPU command buffer build    ~7ms
├── HUD overlay                     ~1ms
├── FFmpeg pipe write × 3           ~2ms
├── Physics + REST + movement       ~2ms
└── Total                          ~40ms

GPU work:
├── Render 3 cameras               ~6ms (parallel with CPU)
├── NVENC encode × 3               ~3ms
└── Total                          ~9ms (GPU mostly idle)
```

25fps at full quality with 3 HD cameras in a Docker container is a solid result for Built-in RP. The next step is URP — when Unity fixes headless RenderGraph support.
