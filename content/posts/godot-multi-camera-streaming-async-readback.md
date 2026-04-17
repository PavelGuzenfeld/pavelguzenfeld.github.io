---
title: "From Unity to Godot: Multi-Camera Streaming at 50 FPS with Async GPU Readback"
date: 2026-04-17
draft: false
tags: ["Godot", "GDExtension", "Vulkan", "GStreamer", "Docker", "simulation", "C++", "GPU", "NVENC", "rendering", "performance", "headless", "RTSP", "benchmarking", "drones", "TCP", "X11", "optimization"]
keywords: ["Godot multi-camera streaming", "Godot RenderingDevice texture_get_data_async", "Godot GDExtension GStreamer", "Godot headless Vulkan Docker", "Godot Xvfb present cost"]
cover:
  image: /images/posts/o3de-migration-exploration.png
  alt: "Three live Godot camera streams over RTP/UDP rendered by GStreamer clients"
categories: ["deep-dive"]
summary: "After O3DE's 18 ms frame-graph readback made 30 FPS streaming impossible, we tried Godot. It got us there — eventually. This is the full path from 105 FPS on nothing to 50 FPS per camera with three live RTP streams, including every wrong turn and every underdocumented Godot behavior we hit on the way."
ShowToc: true
---

> Third post in the simulation series. The first two covered the [Unity to O3DE migration](/posts/o3de-migration-exploration-multi-camera-streaming/) and the [O3DE readback deep dive](/posts/o3de-performance-deep-dive-readback-bottleneck/). This one covers what happened when we dropped O3DE and tried Godot.

O3DE gave us 20 FPS with three cameras. The [previous post](/posts/o3de-performance-deep-dive-readback-bottleneck/) showed why: `AttachmentReadback` adds 18 ms of frame-graph overhead per camera no matter what you do. We ran eight optimization attempts against that and every single one bottomed out at the same number.

So we asked a different question: **what if the engine just didn't have that architecture?** Godot's `SubViewport` doesn't use a frame graph. `get_image()` returns bytes. No scope system, no pass compilation. Potentially no 18 ms wall.

This post is the full record of porting the simulation streaming layer onto Godot 4.4.1, including every dead end.

## TL;DR — the numbers

| stage | engine fps | per-cam fps | aggregate | what's actually happening |
|---|---|---|---|---|
| bare Godot + Vulkan + Xvfb (1920×1080 window) | 33 | — | 0 | just the `Xvfb` present cost |
| shrink main window to 16×16 | **105** | 35 (virtual) | 0 | the "present floor" wasn't a floor |
| + round-robin TCP + `x264enc` | 51 | 16 | 51 | first real encoded video |
| all-cams + per-camera producer-consumer | 23 | 23 | 69 | encode off the render thread |
| in-process GStreamer (GDExtension) + live RTP | 23 | 22–25 | 69 | no subprocess, no TCP |
| + `RenderingDevice.texture_get_data_async` | **100** | **50** | **150** | readback off main thread |

End state: **three cameras at 1920×1080, ~50 FPS each, producing `.mp4` files and live RTP/H.264 on UDP ports 5000–5002, all from one headless Docker container.**

---

## Setup

Same host as the O3DE work: RTX 3060 Laptop, Ubuntu, nvidia-container-toolkit. The whole engine runs inside one Docker image so nothing needs to be installed on the host. Godot 4.4.1 with the Vulkan Forward+ renderer, a real `Xvfb` virtual display, and GStreamer 1.24 via `gstreamer1.0-plugins-{base,good,bad,ugly}` plus `gstreamer1.0-x` (for `pango`-based `textoverlay`).

The scene is intentionally minimal: a ground plane, a procedural sky, a directional light, and a rotating orange cube for obvious motion. Three `SubViewport`s each 1920×1080, each with its own `Camera3D` at a different position and FOV.

```gdscript
var cam_configs := [
    {"name": "cam0", "pos": Vector3(0, 10, 15),   "rot": Vector3(-30, 0, 0),   "fov": 60.0},
    {"name": "cam1", "pos": Vector3(20, 8, -10),  "rot": Vector3(-20, 120, 0), "fov": 90.0},
    {"name": "cam2", "pos": Vector3(-15, 12, -20),"rot": Vector3(-25, 200, 0), "fov": 45.0},
]
```

---

## Stage 1 — the "Xvfb present floor" that wasn't

First measurement: bare Godot with a 1920×1080 window and nothing else rendering, under `Xvfb`. We got **33 FPS** — suspiciously identical to O3DE's baseline. It looked like a hard floor.

It wasn't. After poking at it we realised the cost wasn't presentation in the Vulkan-swapchain sense; it was the software framebuffer copy Xvfb does when you present a 1920×1080 image to its virtual surface. Nothing in the simulation actually *reads* the main window — the SubViewports are independent render targets — so the cost is pure waste.

Fix, in one line of `override.cfg`:

```ini
[display]
window/vsync/vsync_mode=0
window/size/viewport_width=16
window/size/viewport_height=16
```

A 16×16 main window has negligible blit cost. The 3 × 1080p SubViewports keep rendering normally. Engine tick went from **33 FPS to 105 FPS**.

**Lesson**: when a headless engine under Xvfb measures a hard floor, check if any of that cost comes from the *main* window that you don't care about.

## Stage 2 — actually encoding the frames

105 FPS with no output isn't shipping. We wired the first real pipeline: per-camera round-robin readback on the main thread, one gst-launch subprocess per camera encoding over a loopback TCP socket.

```
SubViewport.get_texture().get_image()
    → raw RGBA bytes
    → StreamPeerTCP.put_data()
    → gst-launch tcpclientsrc ! rawvideoparse ! videoconvert
                  ! x264enc ! mp4mux ! filesink
```

Engine dropped from 105 to 51 FPS. The 16 ms drop wasn't the TCP hop (loopback is ~1 ms for 8 MB) — it was `x264enc` back-pressuring the TCP buffer when it couldn't keep up. Per-camera rate was **16 FPS** (round-robin ÷ 3).

### Gotcha: `OS.execute_with_pipe` only hooks stdin on the first child

Initial plan was to feed the three gst-launch subprocesses via `OS.execute_with_pipe` and write raw bytes to each one's stdin. `cam0.mp4` grew as expected; `cam1.mp4` and `cam2.mp4` stayed at 0 bytes forever. The gst stderr logs showed both subprocesses stuck in `PREROLLING` — they never received a single stdin byte.

I never confirmed whether this is a bug or a documented limitation; the workaround is to use `OS.create_process` plus loopback TCP sockets per camera, which has no such issue. That's what ended up in the final version.

## Stage 3 — producer-consumer per camera

Round-robin is wasteful: at 51 FPS × 1 cam/tick, each camera only gets every 3rd tick. Switching to all-cams-per-tick means three readbacks per tick (30 ms floor) — engine drops but each camera captures every frame.

We gave each camera its own worker `Thread` with a `Semaphore`-signalled, latest-wins single-slot queue, so the TCP push runs in parallel and the encoder's back-pressure doesn't stall rendering:

```gdscript
class_name CameraWorker
extends RefCounted

var _thread := Thread.new()
var _frame_ready := Semaphore.new()
var _mutex := Mutex.new()
var _pending: PackedByteArray = PackedByteArray()
var _has_pending := false

func post_frame(raw: PackedByteArray) -> void:
    _mutex.lock()
    if _has_pending:
        frames_dropped += 1
    _pending = raw
    _has_pending = true
    _mutex.unlock()
    _frame_ready.post()

func _run() -> void:
    while not _exit:
        _frame_ready.wait()
        # drain — we only care about the latest frame
        while _frame_ready.try_wait(): pass
        _mutex.lock()
        var raw := _pending
        _pending = PackedByteArray()
        _has_pending = false
        _mutex.unlock()
        peer.put_data(raw)
```

Result: **23 FPS per camera**, drop count zero (consumers keep up). Aggregate throughput: 51 → 69 frames/sec (+35%).

### The wall we couldn't get past in GDScript

`SubViewport.get_texture()` errors out if called from a worker thread:

```
ERROR: This function in this node (/root/FrameLogger/cam1) can only be
accessed from either the main thread or a thread group.
   at: get_texture (scene/main/viewport.cpp:1308)
```

So the readback stays on the main thread no matter what you do in plain GDScript. Three `get_image()` calls × ~10 ms each = 30 ms/tick floor = 33 FPS ceiling. You cannot push past this from GDScript alone.

## Stage 4 — in-process GStreamer via GDExtension

The subprocess + TCP pipeline works but has three costs: OS context switches, an 8 MB/frame TCP copy, and `OS.execute_with_pipe` pitfalls. A GDExtension — Godot's C++ plugin interface — lets us embed GStreamer in the same address space.

The class is a thin wrapper over `gst_parse_launch`:

```cpp
// StreamEncoder::start builds a pipeline per camera:
"appsrc name=src is-live=true do-timestamp=true format=time "
"  caps=\"video/x-raw,format=RGBA,width=%d,height=%d,framerate=%d/1\" "
"! queue max-size-buffers=3 leaky=downstream "
"! videoconvert "
"! textoverlay name=label text=\"%s\" ... "
"! clockoverlay ... "
"! x264enc tune=zerolatency speed-preset=ultrafast bitrate=8000 key-int-max=%d "
"! h264parse config-interval=1 "
"! tee name=t "
"t. ! queue ! mp4mux fragment-duration=100 streamable=true ! filesink location=%s "
"t. ! queue ! rtph264pay pt=96 config-interval=1 "
"   ! udpsink host=%s port=%d sync=false async=false auto-multicast=false"
```

`push_frame(PackedByteArray)` memcpy's the bytes into a `GstBuffer` and calls `gst_app_src_push_buffer`. That call is non-blocking — the encoder's internal thread drains `appsrc` when it's ready, and the `leaky=downstream` queue drops frames rather than stalling the producer.

End-to-end: GDScript reads the SubViewport, calls `encoder.push_frame(bytes)`, everything after that runs on GStreamer threads. The `tee` splits the H.264 stream to both an `.mp4` file and a live RTP/UDP sink on the camera's port. Multiple consumers can subscribe to any of the three UDP streams simultaneously.

Numbers didn't change much (23 FPS/cam, 2–5 ms total push down from 6–10 ms) — the renderer was already the bottleneck — but we're now a single process with live RTP and no subprocesses. This is the architecture a real deployment would ship.

## Stage 5 — the async readback that broke the 30 ms floor

Godot 4.4 shipped a non-blocking variant of the texture readback:

```
Error RenderingDevice.texture_get_data_async(RID texture, int layer, Callable callback)
```

The call submits a copy to a staging buffer and returns immediately. When the GPU fence signals, the callback fires on the main thread with the bytes. Readbacks for all three cameras overlap each other and with rendering.

```gdscript
var rd := RenderingServer.get_rendering_device()

func _process(_delta):
    for i in viewports.size():
        if in_flight_count[i] >= 1: continue
        var rd_rid := RenderingServer.texture_get_rd_texture(
            viewports[i].get_texture().get_rid())
        in_flight_count[i] += 1
        rd.texture_get_data_async(rd_rid, 0, _callbacks[i])

func _on_readback_cam0(data: PackedByteArray): _encoders[0].push_frame(data); in_flight_count[0] -= 1
```

Result: **engine 23 → 100 FPS (+335%), per-camera 23 → 50 FPS (+117%)**. Aggregate 69 → 150 frames/sec across the three streams.

### Gotcha: `Callable.bind()` silently fails here

First implementation passed a single callback with the camera index bound:

```gdscript
rd.texture_get_data_async(rd_rid, 0, _on_readback.bind(i))
```

The async call returned `OK`. The callback never fired. Over 900 engine ticks the counter stayed at 0 sent, 900 skipped. No error, no stderr output, nothing.

Replacing the bound callable with three distinct named methods made it work immediately:

```gdscript
func _on_readback_cam0(data: PackedByteArray): _on_readback(0, data)
func _on_readback_cam1(data: PackedByteArray): _on_readback(1, data)
func _on_readback_cam2(data: PackedByteArray): _on_readback(2, data)
```

My guess is that the bound `Callable` doesn't survive the render-thread `call_deferred` round-trip the async API uses. I haven't filed it upstream yet but the workaround is trivial.

### Gotcha: double-buffering made things worse

Obvious next move: allow two async readbacks in flight per camera, since the staging round-trip takes ~2 engine ticks so with only 1 in flight each camera completes every other tick. Changed `MAX_IN_FLIGHT` from 1 to 2.

Engine tick dropped from 100 → 40 FPS. Per-camera from 50 → 40. Throughput regression.

Measured: each `rd.texture_get_data_async` call costs ~4 ms on the main thread. Doubling the in-flight count doubles that overhead. At 3 cams × 2 slots × 4 ms = 24 ms just to *fire* readbacks per tick. The async call is not free.

Single-slot is the sweet spot. Leaving it at 1.

## Stage 6 — the bugs that ate an hour of debugging

Two surprises showed up only once I tried to actually *watch* the output.

### `udpsink auto-multicast=true` hijacks the destination port

The sim's `udpsink host=127.0.0.1 port=5000` also binds a *receive* socket on port 5000 for IGMP multicast management. Even with unicast traffic, that bind makes any external `udpsrc port=5000` compete for packets — and, because the sim isn't reading its own receive socket, every packet ends up in the kernel drop queue.

Fix:

```
! udpsink host=127.0.0.1 port=5000 sync=false async=false auto-multicast=false
```

Live consumers could actually receive after that. I must have spent 45 minutes staring at zero `chain:` events before figuring this out.

### `docker run -d` leaks containers when the parent script gets killed

During iteration I was starting background containers from within bash tasks:

```bash
docker run -d --rm --network host ... --name throwaway gst-launch ... &
```

When the parent task got interrupted, the `docker run` process died but the detached container kept running. By the time I noticed, **thirteen** zombie containers were holding UDP ports 5000–5002. Any new receiver would bind the same port (gst uses `SO_REUSEADDR`) and the kernel would round-robin packets across all the binds, so no single consumer saw a complete H.264 stream.

Fix was to `docker kill $(docker ps -q)` everything and always tear down by name afterwards:

```bash
docker ps -q --filter name=godot_view_ | xargs -r docker kill
```

Lesson: if `docker run -d` is ever going to be in a script that gets killed, name it and clean it up explicitly.

### `videoflip` was needed with `get_image()` and wrong with `texture_get_data_async`

Original pipeline had `videoflip method=vertical-flip` because `Image.get_data()` returns bottom-up bytes (Godot/OpenGL convention). After switching to `texture_get_data_async`, bytes come back in native Vulkan top-down order — and the flip makes them upside down again. Removed the element; orientation correct.

---

## How to reproduce

Everything is on the `experiment/godot-replacement` branch. The whole build and run happen inside Docker.

### Build

```bash
cd godot/docker
docker build -f Dockerfile -t sandbox-godot:latest .
```

The multi-stage build compiles `godot-cpp`, then the `sandbox_stream` GDExtension (links `gstreamer-1.0`, `gstreamer-app-1.0`), then assembles the runtime image with `Xvfb`, `libvulkan1`, `mesa-vulkan-drivers`, and the full GStreamer plugin set.

### Run the sim

```bash
docker run -d --rm --gpus all --network host \
    -v /tmp/godot_out:/output \
    -e DISPLAY_MODE=xvfb \
    --name godot_live \
    sandbox-godot:latest
```

The entrypoint (`entrypoint.sh`) starts Xvfb on `:99`, then launches Godot with `--rendering-driver vulkan` pointing at the project. The runtime image exposes UDP 5000–5002 for RTP and writes three `.mp4` files to `/output`.

### Watch the three cameras live

The repo ships three throwaway-container viewers that forward the host's `$DISPLAY` into a `gst-launch` client:

```bash
godot/tools/view_cam.sh 5000    # cam0
godot/tools/view_cam.sh 5001    # cam1
godot/tools/view_cam.sh 5002    # cam2
# or all three at once:
godot/tools/view_all_cams.sh
```

Each script runs `udpsrc → rtpjitterbuffer → rtph264depay → avdec_h264 → autovideosink`, so you get a real X11 window per camera without installing GStreamer on the host.

If you want to consume the streams from another machine, set the encoder's `UDP_HOST` to `0.0.0.0` (or the network interface address) and point `udpsrc port=5000` at the sim's IP from anywhere on the network.

### Tear down

```bash
docker kill godot_view_5000 godot_view_5001 godot_view_5002 godot_live
```

---

## What the engine ends up looking like

- **Input**: `config/sandbox.yaml` with cameras, ports, bitrates. No hardcoded constants in the engine code.
- **Renderer**: Godot 4.4.1 + Vulkan Forward+, one `SubViewport` per camera at 1920×1080.
- **Readback**: `RenderingDevice.texture_get_data_async` — non-blocking, one in flight per camera.
- **Encoder**: `sandbox_stream` GDExtension, one `StreamEncoder` instance per camera, each wrapping an in-process GStreamer pipeline.
- **Outputs**: each camera produces both a recorded `.mp4` (via `filesink`) and a live RTP/H.264 stream (via `rtph264pay ! udpsink`) from the same `tee`.
- **Overlay**: a live FPS counter in the top-left and a wall clock in the bottom-right of each stream, updated every 10 engine ticks from GDScript via `encoder.set_label()`.
- **Container**: 5.5 GB total (O3DE's was 17 GB).

With three cameras running concurrently you get ~50 FPS per camera, which clears the 30 FPS streaming target with headroom, and the file recordings plus live UDP consumers work simultaneously off the same encode.

## What's left

- **Go past 50 FPS/camera.** The floor now is the render thread itself — 3 × `texture_get_data_async` firing is ~12 ms/tick on the main thread. A native GPU-direct path using `RenderingServer.texture_get_native_handle()` and Vulkan/CUDA interop into `nvh264enc` would skip the CPU DMA entirely and in principle push past 100 FPS/camera.
- **Port the Unity scene content.** Nothing here touches the actual simulation: no SRTM terrain, no OSM buildings, no drone, no PX4 SITL. The streaming pipeline is done; the world isn't.
- **File the `Callable.bind` bug.** The silent-drop behaviour when the bound Callable crosses the render thread's `call_deferred` boundary deserves an upstream report.

## What changed my mind about engines

O3DE's problem wasn't the engine being slow — it was the *architecture* of the render graph making readback cost a fixed overhead. Godot doesn't have that problem because its `SubViewport` + `RenderingDevice.texture_get_data_async` is simply a lower abstraction: a texture RID and a DMA copy. Every optimization we attempted in O3DE fought the frame graph. In Godot the API composes: async readback, in-process encoder, per-camera pipeline, all of them layered additively, none of them fighting each other.

The total distance from "fresh Godot project" to "three live RTP streams at 50 FPS/cam in Docker" was one afternoon. The wrong turns (stdin inheritance, `Callable.bind`, `auto-multicast`, zombie containers) took about half of that afternoon. None of them are in the documentation anywhere I looked, so hopefully this post saves someone else the same hour.
