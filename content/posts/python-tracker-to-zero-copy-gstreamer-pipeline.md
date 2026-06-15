---
title: "From a PyTorch Tracker to a Zero-Copy GStreamer Pipeline: Rebuilding SAM2.1/SAMURAI on Jetson, Step by Step"
date: 2026-06-16
draft: true
tags:
- GStreamer
- Jetson
- NVMM
- zero-copy
- C++
- Python
- GPU
- video-processing
- optimization
- testing
- benchmarking
keywords:
- SAM2 TensorRT Jetson
- zero-copy GStreamer CUDA pipeline
- PyTorch model to TensorRT engines
- SAMURAI visual tracker C++
- ONNX export parity validation
cover:
  image: ""
  alt: "Zero-copy GStreamer tracking pipeline on Jetson"
categories:
- deep-dive
summary: A long, hands-on account of turning a research-grade PyTorch visual tracker (SAM2.1 / SAMURAI) into a real-time, zero-copy GStreamer + CUDA + TensorRT pipeline on a Jetson Orin NX — decomposing the model into engines, exporting and parity-validating each one, porting the per-frame math to CUDA, packaging it as a GStreamer element, and squeezing 8 fps into 24 with queues and frame-skipping. Every stage is validated against a golden reference.
ShowToc: true
---

## Why bother

Single-object visual trackers built on segmentation backbones — Meta's **SAM 2.1** and the motion-aware [**SAMURAI**](https://yangchris11.github.io/samurai/) variant on top of it — are wonderful to demo and painful to deploy. You seed them with one box, and they follow that object through occlusion, scale change, and clutter, frame after frame. The catch: the reference implementation is PyTorch, and on an embedded GPU it runs at roughly **8 frames per second**, encoder-bound, with the video bouncing between CPU and GPU memory the whole way.

I wanted the same tracker running in real time, in a production video pipeline, on a **Jetson Orin NX** — ingesting H.264, never copying a frame back to the CPU, and emitting an annotated RTP stream. This post is the full path from the one to the other: not a tidy "here's the final architecture" writeup, but the actual sequence of decompose → export → validate → port → optimize → package, with the dead-ends that taught me something.

The example throughout is deliberately generic: **track a single object — say a person or a vehicle — in a 1080p clip.** The techniques don't care what the object is.

Everything sits on top of [**`gst-nvmm-cpp`**](https://github.com/PavelGuzenfeld/gst-nvmm-cpp), an open-source set of zero-copy, NVMM-native GStreamer elements for Jetson (no DeepStream). The tracker becomes two new elements in that family — `nvmmsamurai` (the tracker) and `nvmmfusekf` (a fusion filter) — plus the tooling to build the engine assets, all documented in the repo's [Building the engines](https://pavelguzenfeld.com/gst-nvmm-cpp/building-engines/) guide.

## The shape of the problem

A SAM2-style tracker is a small graph of sub-models with state threaded between them:

1. an **image encoder** (a Hiera backbone + FPN neck) that turns a cropped frame into multi-scale features;
2. a **prompt encoder** that turns the seed box into sparse/dense embeddings;
3. a **mask decoder** that, given features + prompt + a memory-conditioned embedding, predicts mask candidates and scores;
4. a **memory encoder** that compresses the chosen mask back into a memory token;
5. a **memory attention** block that conditions the current frame on a ring of past-frame memories.

In PyTorch all five live in one `nn.Module` and the per-frame glue (cropping, normalization, bilinear upsampling, mask→box, the memory bank assembly, a Kalman score) is plain Python running on the host. To get this real-time and zero-copy I had to:

- turn each sub-model into a **TensorRT engine**,
- prove each engine matches PyTorch numerically,
- re-implement all the per-frame glue as **CUDA kernels** so the frame never leaves the GPU,
- wrap the orchestration in a **GStreamer element**, and
- find the throughput levers once it was correct.

Let me take those in order.

## Step 0 — A feasibility gate, in pure PyTorch first

Before touching TensorRT I ran the stock PyTorch tracker end-to-end on a representative 1080p clip and measured it. Two reasons. First, to confirm the tracker actually solves the task at all (seed it once, does it hold the object?). Second, to capture a **golden reference**: the exact input/output tensors at every stage, which become the parity oracle for everything downstream.

This gate paid for itself immediately — it told me the tracker held the object at high confidence across the whole clip at ~8 fps, and it gave me a number to beat. If the feasibility run had failed, no amount of TensorRT would have saved it. **Never start optimizing a thing you haven't proven works.**

## Step 1 — Decompose into engines

The five sub-models, with the I/O contract each engine has to honor (batch size is always 1 — single target):

| Engine | Inputs | Outputs |
|---|---|---|
| `image_encoder` | crop `1×3×512×512` | 6 tensors: 3 positional encodings + 3 FPN levels (`128²`, `64²`, `32²`) |
| `prompt_encoder` | box corners `1×Np×2` | `sparse`, `dense` embeddings |
| `mask_decoder` | image embed `1×256×32×32`, image PE, sparse, dense, feat `128²` + `64²` | `masks 1×4×128×128`, `ious 1×4`, `tokens`, `obj_score` |
| `memory_encoder` | feature `1×256×32×32`, mask `1×1×512×512` | `maskmem_feat 1×64×32×32`, `maskmem_pos` |
| `memory_attention` | `curr 1024×1×256`, `curr_pos`, `memory 7232×1×64`, `memory_pos` | `1024×1×256` |

A few decisions baked in here. The encoder runs on a **512×512 crop** around the target, not the model's native 1024 — half the spatial resolution, a big chunk of the latency back, and the tracker only ever looks at a window around the object anyway. And the memory is a **static** `7232×1×64` tensor: 7 mask-memory frames (`7×1024` tokens) plus 16 object-pointer tokens. Fixing the shape lets TensorRT build one optimized engine instead of re-planning per frame; the cold-start case (fewer than 7 real memories) is handled by replicating the seed frame, which keeps the rotary-embedding tiling factor constant.

## Step 2 — Export each sub-model to ONNX (where the bodies are buried)

This is the step that eats your week. A research model is written for training flexibility, not for `torch.onnx.export`, and three patterns in particular fought back.

**Tracing builds host-side indices.** `torch.repeat_interleave` constructs its index tensor on the CPU during trace, which then clashes with CUDA inputs at runtime. With `B=1` the repeat-by-1 is a no-op, so a small shim sidesteps it:

```python
_orig_ri = torch.repeat_interleave

def _safe_ri(x, repeats, dim=None, output_size=None):
    if dim == 0:                      # B=1 export: repeat batch dim by 1 == no-op
        return x
    if isinstance(repeats, int):
        idx = torch.arange(x.shape[dim], device=x.device).repeat_interleave(repeats)
        return x.index_select(dim, idx)
    return _orig_ri(x, repeats, dim=dim, output_size=output_size)

torch.repeat_interleave = _safe_ri
```

**The prompt encoder uses boolean-mask scatter that TensorRT can't parse.** The stock path adds learned label embeddings via boolean indexing. For a fixed box-seed (two corner points plus a padding point), you can express the exact same arithmetic as slice + concat, which exports cleanly:

```python
class PromptEncoderBox(nn.Module):
    """Box-seed only: 2 corner points (labels 2,3) + 1 padding point (label -1),
    rewritten without boolean-mask scatter so TensorRT can parse it."""
    def __init__(self, pe): super().__init__(); self.pe = pe

    def forward(self, coords):                      # coords [1,2,2] box corners
        bs = coords.shape[0]
        pts = torch.cat([coords + 0.5,
                         torch.zeros((bs, 1, 2), device=coords.device)], dim=1)
        emb = self.pe.pe_layer.forward_with_coords(pts, self.pe.input_image_size)
        e0 = emb[:, 0:1, :] + self.pe.point_embeddings[2].weight
        e1 = emb[:, 1:2, :] + self.pe.point_embeddings[3].weight
        e2 = emb[:, 2:3, :] * 0.0 + self.pe.not_a_point_embed.weight   # label -1
        sparse = torch.cat([e0, e1, e2], dim=1)
        dense = self.pe.no_mask_embed.weight.reshape(1, -1, 1, 1).expand(
            bs, -1, *self.pe.image_embedding_size)
        return sparse, dense
```

**The mask decoder's hypernetwork is four parallel MLPs**, and TensorRT 10.3 mis-built the per-token `Slice → Gemm` loop (a correctness bug, precision-independent). Stacking the weights and doing one batched `einsum` is identical math and builds correctly:

```python
class BatchedHyper(nn.Module):
    def __init__(self, mlps):
        super().__init__()
        self.nl = mlps[0].num_layers
        self.W = nn.ParameterList(); self.B = nn.ParameterList()
        for li in range(self.nl):
            self.W.append(nn.Parameter(torch.stack([m.layers[li].weight for m in mlps], 0), requires_grad=False))
            self.B.append(nn.Parameter(torch.stack([m.layers[li].bias   for m in mlps], 0), requires_grad=False))

    def forward(self, mto):
        x = mto
        for li in range(self.nl):
            x = torch.einsum("bni,noi->bno", x, self.W[li]) + self.B[li]
            if li < self.nl - 1:
                x = torch.relu(x)
        return x
```

The decoder is exported **raw** — all four mask candidates, with selection done later in C++ — and with a **dynamic `sparse` axis** so the same engine serves both the box-seed (`Np=3`) and the empty-prompt tracking (`Np=2`) cases.

**Memory attention is the research-grade risk.** Its rotary positional embedding uses `view_as_complex`/`torch.polar`, which simply will not export. The fix is to rewrite the rotation as real-valued arithmetic, baking the `cos`/`sin` tables out of the model's `freqs_cis` buffer as constants:

```python
def rope_real(x, cos, sin):            # x:[B,H,L,D]  cos/sin:[L,D/2]
    xr = x.reshape(*x.shape[:-1], -1, 2)
    x0, x1 = xr[..., 0], xr[..., 1]
    o0 = x0 * cos - x1 * sin
    o1 = x0 * sin + x1 * cos
    return torch.stack([o0, o1], dim=-1).reshape(*x.shape)
```

One more subtlety worth stating: **ONNX export records the graph, not the values.** That means the trace inputs can be *synthetic* tensors of the right shape — you do not need real captured data to export. This matters for keeping the export tooling self-contained and reproducible from public weights; the real captures are only needed later, as the parity oracle.

There's also a fistful of **out-of-engine constants** the runtime needs — the temporal positional encodings, the no-memory / no-object embeddings, the object-pointer projections, the image positional encoding, and the empty-prompt embeddings. Those get gathered from the checkpoint and packed into a small self-describing binary that the C++ loads directly.

## Step 3 — Build the engines and validate every one

ONNX → TensorRT is one `trtexec` invocation per model (fp16), but the engine is **version-locked** to the TensorRT it was built with, so the build has to run in the same container the runtime links against. The dynamic decoder needs its shape profile spelled out:

```bash
trtexec --onnx=mask_decoder.onnx --fp16 \
  --minShapes=sparse:1x2x256 --optShapes=sparse:1x3x256 --maxShapes=sparse:1x3x256 \
  --saveEngine=mask_decoder.engine
```

Then the part that actually matters: **prove each engine matches PyTorch.** For every engine I fed it the captured golden inputs, ran both the engine and the reference module, and compared by cosine similarity, gating at **≥ 0.999**:

| Engine | Cosine vs PyTorch |
|---|---|
| `prompt_encoder` | 1.000000 |
| `memory_encoder` | 1.000000 |
| `mask_decoder` (masks) | 0.999999 |
| `image_encoder` (6 outputs) | ≥ 0.99996 |
| `memory_attention` (fp16, hardest) | 0.99967 |

Two residuals are worth calling out because they look like bugs and aren't:

- The mask decoder's `iou` head shows a uniform **+0.12 sigmoid offset** in fp16. Since the candidate ranking (argmax) and the `>0.5` admit threshold are both preserved, it changes nothing downstream — but you only know that because you *looked*, rather than trusting the cosine number alone.
- The end-to-end encoder output drifts ~1.4% once you feed it a frame that went through the **hardware colorspace conversion** (VIC NV12→RGB) instead of the reference's CPU conversion. The two YUV→RGB conventions differ by a few levels per pixel; the deep encoder amplifies it. It's self-consistent within the pipeline (every stage uses the same hardware path), so it's a documented deviation, not a defect. Knowing *which* stage introduces a discrepancy is the entire point of per-component golden capture.

This is the habit that makes a port like this tractable: **validate inward.** Don't run the whole tracker and eyeball the box. Bind a golden tensor at each stage boundary and assert the stage reproduces it. When something breaks at frame 900, you already know which of five engines to suspect.

## Step 4 — The GStreamer element

With validated engines, the orchestration becomes a `GstBaseTransform` that owns all five engines on a single CUDA stream and attaches a small metadata struct (`GstNvmmTrackMeta`) to each buffer. The element is an **in-place passthrough** on `video/x-raw(memory:NVMM), format=NV12` — it reads pixels, writes metadata, and touches the frame data not at all:

```cpp
static GstFlowReturn
gst_nvmm_samurai_transform_ip(GstBaseTransform *bt, GstBuffer *buf)
{
    auto *self = GST_NVMM_SAMURAI(bt);
    NvBufSurface *surf = /* map the NVMM surface from buf (no copy) */;

    TrackBox box;
    std::string err;
    if (!self->tracker->seeded()) {
        if (!self->tracker->seed(surf, seed_box(self), err))   // first lock
            GST_WARNING_OBJECT(self, "seed failed: %s", err.c_str());
    } else if (!self->tracker->track(surf, box, err)) {        // per-frame
        GST_WARNING_OBJECT(self, "track failed: %s", err.c_str());
    }

    GstNvmmTrackMeta *tm = gst_buffer_add_nvmm_track_meta(buf);
    *tm = self->tracker->current();   // box + object score + valid flag
    return GST_FLOW_OK;
}
```

Inside, the per-frame flow mirrors the PyTorch graph exactly: crop around the predicted box on the VIC → encoder → transpose features → assemble the memory bank → memory attention → mask decoder (empty prompt) → select the best of the candidate masks under a Kalman-aware score → mask→box → push the new memory into the ring. The seed path is a one-off variant (real prompt, single mask token, initialize the Kalman state).

Because the seed comes from outside (a detector, or a forced ROI), the element exposes a fistful of range-checked GObject properties — `engine-dir`, `consts-file`, `max-kf`, `seed-roi`, `target-class`, and so on — and listens for an upstream custom event to re-seed on loss. (That re-seed authority lives in the fusion element; more below.)

## Step 5 — Make it zero-copy: port the per-frame glue to CUDA

A correct port is not a fast port. My first working version still did the per-frame *glue* on the host — transpose the encoder output, add a bias channel, scale-and-sigmoid the memory mask, bilinear-upsample 128→512, reduce a mask to a bounding box. Each of those is a device→host→device round trip, and they add up.

So each became a CUDA kernel. They're not glamorous — that's the point; they're exact, deterministic mirrors of the host math:

```cpp
// align_corners=False bilinear: src = (dst+0.5)*scale - 0.5, edge-clamped.
__global__ void bilinear_k(const float *src, float *dst,
                           int hi, int wi, int ho, int wo)
{
    const int idx = blockIdx.x * blockDim.x + threadIdx.x;
    if (idx >= ho * wo) return;
    const int oy = idx / wo, ox = idx % wo;
    const float sy = (float)hi / ho, sx = (float)wi / wo;
    const float fy = cuda::std::fmaxf((oy + 0.5f) * sy - 0.5f, 0.f);
    const float fx = cuda::std::fmaxf((ox + 0.5f) * sx - 0.5f, 0.f);
    const int y0 = (int)fy, x0 = (int)fx;
    const int y1 = y0 + 1 < hi ? y0 + 1 : hi - 1;
    const int x1 = x0 + 1 < wi ? x0 + 1 : wi - 1;
    const float wy = fy - y0, wx = fx - x0;
    const float a = src[y0*wi+x0], b = src[y0*wi+x1];
    const float c = src[y1*wi+x0], d = src[y1*wi+x1];
    const float top = a + (b-a)*wx, bot = c + (d-c)*wx;
    dst[idx] = top + (bot-top)*wy;
}
```

The bounding-box reduction is an `atomicMin`/`atomicMax` over the thresholded mask; the bias-add indexes a per-channel vector; the memory-mask transform is a fused scale-sigmoid. The trickiest is the **memory-bank assembly**: a single kernel builds the entire `7232×1×64` memory and its positional encoding on-device, computing the per-token sinusoidal position encoding inline and reading a device pointer-array of the seven memory slots. That kills the last big host round-trips (two ~460 KB uploads and a download per frame), and lets the **memory ring itself live on the GPU** — six circular buffers plus a seed buffer, written device-to-device.

The result: the frame is decoded into NVMM by the hardware decoder and *never comes back to the CPU* until the encoder consumes it. The tracker reads GPU memory in place and writes a 40-byte metadata struct.

Crucially, the CUDA path produced a **bit-identical trajectory** to the validated host version. That's not luck — it's because each kernel was parity-checked against its host reference before being wired in.

## Step 6 — Validate each component (again, but for the GPU)

Three layers of test, all runnable in Docker, none requiring the real model assets:

- **Pure-host unit tests** for the dependency-free math — the Kalman filter, the crop geometry, the metadata round-trip — compiled straight into the CI build with a mock surface API, so they run on x86 with no GPU.
- A **CUDA kernel parity probe** that drives every kernel with deterministic synthetic inputs and compares to the host reference (`transpose`/`add`/`threshold`/`mask_bbox` exact; `sigmoid` within `2e-6`; `bilinear` within `2e-7`). This is a real, self-contained correctness test — no engines, no captured data — and it ships as part of the suite.
- **Sanitizers.** `compute-sanitizer --tool memcheck` and `--tool initcheck` over all the kernels: zero out-of-bounds, zero uninitialized device reads. `-fsanitize=address,undefined` over the host math: clean. A GPU port that hasn't been through `compute-sanitizer` is a port you don't actually trust.

```cpp
// One of the host unit tests — the Kalman filter, no CUDA, no GStreamer.
TEST_CASE("kalman_box predicts constant velocity") {
    nvmm::KalmanBox kf;
    kf.initiate(100, 100, 20, 20);
    kf.predict(1.0);
    auto b = kf.box();   // center should hold with zero measured velocity
    CHECK(b.cx == doctest::Approx(100).epsilon(1e-6));
}
```

## Step 7 — Find the throughput

Correct and zero-copy, the pipeline ran at about **11 fps** on the Orin NX at 1080p30. Getting to real time was two levers, and understanding *why* mattered more than the code.

First I profiled the engines (`trtexec`, warm GPU compute time):

| Engine | per-frame GPU time |
|---|---|
| `image_encoder` | **41.8 ms** (the bottleneck, ~54% of a frame) |
| YOLO detector (runs every frame) | 16.6 ms |
| `memory_attention` | 16.3 ms |
| `mask_decoder` | 1.9 ms |
| `memory_encoder` | 1.4 ms |

That table reframed everything. The pipeline is **engine-bound** — five sequential TensorRT engines per frame on a single-stream GPU. The CUDA-kernel work I'd just done saved ~11 ms/frame (real, but small against ~78 ms of engine time). The big levers were elsewhere:

- **Frame-skipping with a motion model (`max-kf`).** Run the full inference, then coast for up to *N* frames on a pure Kalman `predict()` — no engines, the box extrapolated. With `max-kf=2` the per-frame cost drops to roughly `(78 + 2×16.6)/3 ≈ 37 ms`, which is where most of the speedup comes from. This required one real fix: the Kalman filter had to run in **frame coordinates**, not crop-relative ones. Every full frame re-centers the crop, and without camera-motion compensation a crop-relative state blows up across the 2-frame gaps. Every-frame updates had been hiding the bug.
- **Queues for pipeline parallelism.** Dropping a `queue` between each stage —
  `… ! nvmminfer ! queue ! nvmmsamurai ! queue ! nvmmfusekf ! queue ! …` —
  puts each element on its own thread. Order is preserved, so tracking is unaffected, and it bought ~18% on its own.

Stacked up, on the same hardware and resolution:

```
every-frame, host glue   9.6 fps
+ CUDA per-frame kernels 10.7
+ device-side ring       11.0
+ max-kf=2               20.5
+ queues                 23.6
+ device ring            24.1
```

Roughly **2.5×**, from 8-ish to ~24 fps at 1080p30 — real time for a 30 fps source with headroom for the encode tail. The remaining ceiling is the encoder; the ranked backlog for going further is INT8-quantizing it (~2×, with a calibration + parity re-check), offloading it to the Orin's DLA, or overlapping the detector and tracker on separate CUDA streams.

## Step 8 — The other half: the detector path

Everything above is about the *tracker*, but a tracker only ever *follows* — it can't *find* an object, and once it loses one it stays lost. That's the job of a separate **object detector**: a TensorRT YOLO, running as the framework's existing `nvmminfer` element. It sits **upstream of the tracker and runs every frame**, attaching its boxes as `GstNvmmDetMeta`. Three distinct things hang off that detector path:

1. **Seed.** On the first frame, `nvmmsamurai` takes a YOLO detection of the target class — the most confident, or the one nearest frame center — and uses its box as the prompt that initializes the track. (A forced `seed-roi` can bypass YOLO entirely when you want to track something the detector won't fire on.)
2. **Fuse.** Every frame, a second, pure-host element — a **master constant-velocity Kalman filter** (`nvmmfusekf`) — fuses the two estimates: the **tracker is the trusted primary** (it gates internally), and the **best YOLO box is a gated secondary**, folded in only if it lands within a pixel radius of the prediction.
3. **Re-seed.** After a run of frames with no good measurement, `nvmmfusekf` declares the track lost and emits the upstream `nvmm-reseed` event so the tracker re-acquires from a fresh detection.

The filtering sits at two levels. `nvmmsamurai` carries its own `KalmanBox`: it scores the mask-decoder candidates and, on `max-kf` fast frames, extrapolates the box while the engines are skipped — so the tracker emits either a full-inference box or a predicted one. `nvmmfusekf` runs the master filter on top: each frame it predicts, updates from the SAM box as the primary, and updates from the best YOLO box when it falls inside the gate. Both show up in the diagrams below — the master KF in `nvmmfusekf`, the secondary one inside `nvmmsamurai`. Extrapolated and full-inference SAM boxes are fused identically today; down-weighting the extrapolated ones is a natural extension.

The YOLO engine is an [Ultralytics](https://docs.ultralytics.com/) detector exported to ONNX and built with `trtexec`, same as the SAM2 sub-models. Its cost is the wrinkle: it runs on *every* frame — including the `max-kf` fast frames where the tracker's own engines are skipped — so it sets the throughput floor (the 16.6 ms in the table above). Throttling it on fast frames is on the backlog; it trades re-seed responsiveness for speed.

The one non-obvious lesson here: I gated the detector by **Euclidean center distance in pixels**, not the textbook Mahalanobis distance. A Kalman filter's measurement-noise covariance scales with the box size, so for a small object the Mahalanobis gate degenerates into reject-everything or accept-everything. A flat pixel radius is cruder and far more robust. The "correct" statistical tool was the wrong engineering choice.

## Step 9 — A dead-end worth keeping: camera-motion compensation

When the camera itself moves, a seed that was perfect drifts as soon as the view pans. The reference handles this with global motion compensation (GMC). I ported the obvious version first: downscale the frame, take a center patch, normalized cross-correlation against the previous patch, integer shift, apply it to the box and the Kalman state.

It made tracking **worse**. Two reasons, both instructive: a quarter-resolution *integer* shift, scaled back up, amplifies and accumulates small biases; and the moving object sits *inside* the correlation patch, contaminating the very "global" motion estimate you're trying to read. Spatial NCC simply isn't accurate enough.

The right answer — which the reference uses and which I left as a follow-up — is **FFT phase-correlation**: sub-pixel accuracy, spectral whitening for robustness, and a residual-application scheme that moves the box and the view by the estimated camera motion while feeding only the *residual* to the Kalman filter. The framework and the on/off knob are in place; the cuFFT implementation is the next iteration. I'm keeping the failed attempt in the writeup because "I tried the cheap version and measured it getting worse" is the useful part.

## Step 10 — Packaging

The whole thing ships as two elements in the `gst-nvmm-cpp` family, built with **Meson**, alongside the existing inference/tracking/overlay nodes. Once built, they're ordinary GStreamer elements:

```bash
gst-inspect-1.0 nvmmsamurai      # NVMM SAMURAI tracker — Filter/Effect/Video
gst-inspect-1.0 nvmmfusekf       # NVMM master-KF fusion
```

and the end-to-end pipeline is a single `gst-launch` line — hardware decode → detector → tracker → fusion → overlay → hardware encode → RTP/UDP — every boundary `video/x-raw(memory:NVMM)` so the frame stays on the GPU from decode to encode:

```bash
gst-launch-1.0 -e \
  filesrc location=clip.mp4 ! qtdemux ! h264parse ! nvv4l2decoder ! queue ! \
  nvvidconv ! 'video/x-raw(memory:NVMM),format=NV12' ! queue ! \
  nvmminfer engine-file=detector.engine ! queue ! \
  nvmmsamurai engine-dir=trt consts-file=trt/samurai_consts.bin max-kf=2 ! queue ! \
  nvmmfusekf target-class=0 ! queue ! \
  nvmmdrawdet ! nvvidconv ! 'video/x-raw(memory:NVMM),format=NV12' ! \
  nvv4l2h264enc bitrate=8000000 ! h264parse ! \
  rtph264pay config-interval=1 pt=96 ! udpsink host=127.0.0.1 port=5600
```

The engine assets aren't shipped — they're version-locked and weight-derived. Instead the repo carries the **export and build tooling** and a [step-by-step guide](https://pavelguzenfeld.com/gst-nvmm-cpp/building-engines/) to reproduce them from the SAM 2.1 checkpoint and an Ultralytics YOLO detector, entirely in Docker. (The whole chain — public weights → ONNX → engines → loaded in the element — is what I validated end-to-end on the Orin.)

## The end result: architecture and data flow

Here is the whole thing in GStreamer terms. The frame enters NVMM (GPU memory) at the hardware decoder and **never returns to the CPU** until the hardware encoder consumes it; everything in between reads GPU memory in place and communicates by attaching small **metadata** structs to each buffer. `queue` elements put each stage on its own thread.

![End-to-end GStreamer pipeline and data flow: a hardware-decoded frame enters NVMM GPU memory, passes zero-copy through nvvidconv, nvmminfer, nvmmsamurai, nvmmfusekf and nvmmdrawdet with metadata accumulating per buffer, and leaves at the hardware encoder for RTP over UDP.](/images/posts/tracker-pipeline-dataflow.svg)

Two data planes ride the same buffer chain in opposite directions: **pixels flow downstream** as NVMM surfaces (one GPU-side buffer, never copied), while **metadata accumulates** on each buffer — `nvmminfer` attaches detections, `nvmmsamurai` attaches the track, `nvmmfusekf` rewrites the track with the fused estimate, and `nvmmdrawdet` reads it to draw. The one upstream signal is the `nvmm-reseed` event: when the fusion filter declares the track lost, it pushes a custom event *back up* the pads to make the tracker re-acquire from a fresh detection.

And the part that does the heavy lifting, `nvmmsamurai`, is itself a small orchestrator — five TensorRT engines and a handful of CUDA kernels on a single CUDA stream, with the memory ring living on the GPU:

![Inside the nvmmsamurai element: a GstBaseTransform running five TensorRT engines (image encoder, memory attention, mask decoder, memory encoder) and CUDA kernels on one CUDA stream, with an on-GPU memory ring. The box is seeded by a YOLO detection from nvmminfer; a full-inference frame laps through the engines while a max-kf fast frame skips them and the secondary Kalman filter extrapolates, both converging to write GstNvmmTrackMeta.](/images/posts/nvmmsamurai-internals.svg)

`[ ... ]` are the TensorRT engines; everything else is a CUDA kernel or host scalar math. On a full-inference frame the data does one lap through the engines; on a `max-kf` fast frame it skips them entirely and just advances the Kalman filter — which is most of where the 2.5× throughput came from.

## What I'd tell myself at the start

- **Prove it works in the slow language first, and capture a golden reference while you do.** That reference is your debugger for the next three weeks.
- **Validate inward, per component.** Cosine ≥ 0.999 at every stage boundary turns "the tracker drifts at frame 900" into "engine 3 is off by X."
- **A correct port and a fast port are different projects.** Get bit-identical first; profile before you optimize; and when you do, the bottleneck is usually not where your last week of work was.
- **The textbook tool is sometimes the wrong tool.** Mahalanobis gating, spatial NCC — both "correct," both worse than the cruder choice for this regime. Measure, don't assume.
- **`compute-sanitizer` is not optional.** A GPU kernel that's never been memcheck'd is a latent crash.

The code — the two GStreamer elements, the CUDA kernels, the export/build tooling, and the docs — is all in [**`gst-nvmm-cpp`**](https://github.com/PavelGuzenfeld/gst-nvmm-cpp). If you're putting a research model into a real video pipeline on Jetson, I hope the path above saves you a week.
