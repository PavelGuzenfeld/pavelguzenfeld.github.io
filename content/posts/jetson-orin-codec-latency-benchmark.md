---
title: 'H.264, H.265, and AV1 on Jetson Orin: A Real Hardware Latency Benchmark'
date: 2026-05-12
draft: false
tags:
- GStreamer
- NVIDIA
- Jetson
- NVMM
- benchmarking
- performance
- video-processing
- networking
- TCP
- Python
- Docker
- embedded
keywords:
- Jetson Orin codec latency benchmark
- nvv4l2 H.264 H.265 AV1 latency
- GStreamer NVMM encode decode latency
- Jetson AV1 hardware encoder
- nvv4l2decoder DPB buffer delay
- GStreamer tcpserversink wire latency
- h264parse h265parse lookahead latency
- chrony clock synchronization GStreamer
- JetPack 6 codec comparison
- nvv4l2h264enc nvv4l2h265enc nvv4l2av1enc
cover:
  image: /images/posts/jetson-codec-latency-benchmark.png
  alt: H.264 vs H.265 vs AV1 end-to-end latency on Jetson Orin — grouped bar chart
categories:
- deep-dive
summary: >
  A rigorous per-stage latency benchmark across H.264, H.265, and AV1 hardware codecs
  on NVIDIA Jetson Orin (JetPack 6), measuring encode, wire, and decode separately at
  FHD and HD resolutions. AV1 wins end-to-end at 104 ms FHD / 86 ms HD. H.264 is the
  worst choice despite being the oldest: its nvv4l2decoder holds ~4 frames in an internal
  DPB buffer, adding 130–170 ms of hidden latency. Wire latency is governed by
  parse-element lookahead, not byte volume. Clock sync achieves ±234 µs via chrony.
  Full pipeline source, CSVs, and reproduction steps included.
ShowToc: true
audio:
  pronunciation:
    nvv4l2h264enc: N V V for L 2 H 264 enc
    nvv4l2h265enc: N V V for L 2 H 265 enc
    nvv4l2av1enc: N V V for L 2 A V 1 enc
    nvv4l2decoder: N V V for L 2 decoder
    nvvidconv: N V vid conv
    tcpserversink: T C P server sink
    tcpclientsrc: T C P client source
    h264parse: H 264 parse
    h265parse: H 265 parse
    av1parse: A V 1 parse
    GStreamer: G streamer
    NVMM: N V M M
    JetPack: Jet Pack
    chrony: kron ee
    DPB: D P B
    iframeinterval: I frame interval
    insert-sps-pps: insert S P S P P S
    insert-seq-hdr: insert seq header
    num-B-Frames: num B frames
    VVenC: V V enc
    VVdeC: V V dec
---

The question "which codec should I use for a latency-sensitive Jetson pipeline?" does not have a single obvious answer on paper. H.264 is the oldest standard with the longest hardware support history. H.265 offers better compression. AV1 is the newest and is a JetPack 6 addition. Published latency comparisons for Jetson's NVMM (`nvv4l2`) codec stack are sparse, and the ones that exist rarely separate encode, wire, and decode into distinct measured stages.

This post is the benchmark I wanted to find but couldn't.

The setup: two Jetson Orin boards on a GbE LAN. `videotestsrc` → hardware encoder → TCP → hardware decoder. GStreamer pad probes record wall-clock timestamps at four points in the pipeline. Chrony synchronizes the two Jetson clocks to within ±234 µs. 900 frames per combination, 30-frame warmup discarded. Six combinations total: `[H.264, H.265, AV1] × [FHD 1920×1080, HD 1280×720]`.

The punchline: **AV1 wins end-to-end at every resolution**. H.264 is not second — it is last by a large margin, because the `nvv4l2decoder` holds ~4 frames in an internal decoded picture buffer before releasing output, adding 130–170 ms of hidden latency that does not appear in any encoder specification.

---

## Hardware and test conditions

| Item | Detail |
|------|--------|
| Hardware | NVIDIA Jetson Orin (both sender and receiver) |
| OS | JetPack 6 / L4T R36.4.x |
| Network | GbE LAN, TCP (`tcpserversink` / `tcpclientsrc`) |
| Bitrate | 1500 kbps (fixed, same for both resolutions) |
| Frame rate | 30 fps |
| Source | `videotestsrc pattern=ball is-live=true` |
| Measurement frames | 900 per combination (30-frame warmup discarded) |
| Resolutions | FHD 1920×1080, HD 1280×720 |
| Codecs | H.264 (`nvv4l2h264enc`), H.265 (`nvv4l2h265enc`), AV1 (`nvv4l2av1enc`) |
| Sender IP | `192.168.1.10` (example) |
| Receiver IP | `192.168.1.20` (example) |

All codecs are hardware-accelerated via NVIDIA's V4L2 (`nvv4l2`) interface. There is no software fallback anywhere in these pipelines. Both systems run inside the same Docker image built from `ubuntu:22.04` with GStreamer 1.22 installed.

---

## Pipeline architecture

### Sender (H.264 example)

```
videotestsrc pattern=ball num-buffers=930 is-live=true
  ! video/x-raw,format=I420,width=1920,height=1080,framerate=30/1
  ! nvvidconv
  ! video/x-raw(memory:NVMM),format=NV12
  ! nvv4l2h264enc name=encoder bitrate=1500000
      insert-sps-pps=true iframeinterval=30 num-B-Frames=0
  ! h264parse
  ! identity name=tx_probe sync=false
  ! tcpserversink name=sink host=0.0.0.0 port=5100 sync=false
      recover-policy=none buffers-soft-max=300
```

The encode path:
1. `videotestsrc` produces raw I420 frames at exactly 30 fps (`is-live=true` is mandatory — without it the encoder runs at unbounded speed, fills the TCP sink buffer in ~1.5 seconds, and the receiver gets a mid-stream join without parameter sets).
2. `nvvidconv` converts to NVMM-backed NV12 so the encoder can do a DMA transfer directly from GPU memory.
3. `nvv4l2h264enc` does hardware encoding. `insert-sps-pps=true iframeinterval=30` embeds parameter sets at every IDR frame so the receiver can sync even on a mid-stream join. `num-B-Frames=0` disables B-frame reordering — a necessary condition for meaningful latency measurement, since B-frames introduce intentional encoder delay.
4. `h264parse` re-frames the bytestream into Access Units.
5. The `tx_probe` identity element is where the sender timestamps the buffer just before it enters the TCP sink.

### Receiver (H.264 example)

```
tcpclientsrc name=src host=192.168.1.10 port=5100
  ! h264parse
  ! identity name=dec_in_probe sync=false
  ! nvv4l2decoder name=decoder
  ! nvvidconv
  ! video/x-raw,format=I420
  ! identity name=dec_out_probe sync=false
  ! fakesink sync=false
```

The decode path:
1. `tcpclientsrc` receives the TCP bytestream.
2. `h264parse` re-frames it into Access Units and passes them to the decoder. Notably, there is **no** `caps` property on `tcpclientsrc` — trying to set caps directly on it produces a `gst_parse_error`. The parse element after the source handles format negotiation.
3. `dec_in_probe` timestamps the buffer entering the decoder.
4. `nvv4l2decoder` does hardware decoding.
5. `dec_out_probe` timestamps the buffer exiting the decoder.
6. `fakesink` discards frames (we are measuring latency, not displaying).

### AV1 differences

AV1 uses `nvv4l2av1enc` with `iframeinterval=30 insert-seq-hdr=true`. The `insert-seq-hdr=true` flag is the AV1 equivalent of `insert-sps-pps=true`: it embeds the Sequence Header OBU at every IDR frame. Without it, `av1parse` on the receiver outputs zero frames after a mid-stream join because it cannot determine video dimensions from inter frames alone.

The receiver uses a bare `av1parse` with no explicit capsfilter — the Sequence Header OBU carries enough information for the parser to negotiate dimensions automatically.

### Sender synchronization: PAUSED + client-added

A subtle but important design choice: the sender pipeline starts in `PAUSED` state. `tcpserversink` binds its port in `PAUSED`, so the receiver can connect before encoding begins. When the receiver's `tcpclientsrc` connects, `tcpserversink` fires a `client-added` signal. The sender's Python code responds with `GLib.idle_add(pipeline.set_state, Gst.State.PLAYING)`, which transitions the pipeline and starts encoding with **zero buffer queue depth**.

Without this, the sender would be encoding at 30 fps while the receiver is still starting up. The TCP sink would buffer 8+ seconds of encoded frames, and the receiver would measure wire latency that includes the time those frames spent queued in memory — inflating wire measurements by ~8600 ms (an outlier we observed during early testing without this fix).

---

## Timing methodology

Four timestamps, three latency stages:

```
SENDER (192.168.1.10)                      RECEIVER (192.168.1.20)
──────────────────────────────             ─────────────────────────────────
videotestsrc (is-live=true)
  │
  ▼ enc_in_ns  ← probe on encoder sink
nvv4l2h264enc / nvv4l2h265enc
  / nvv4l2av1enc
  │
  ▼ enc_out_ns ← probe on encoder src
[h264parse / h265parse]          TCP
  │                           ──────►  tcpclientsrc
  ▼ tx_ns      ← probe on                │
    tx_probe identity                    ▼ [h264parse / h265parse / av1parse]
tcpserversink                            │
                                         ▼ dec_in_ns ← probe on dec_in_probe
                                         │
                                         ▼ nvv4l2decoder
                                         │
                                         ▼ dec_out_ns ← probe on dec_out_probe
                                         │
                                         ▼ fakesink
```

| Stage | Formula | Clock scope |
|-------|---------|-------------|
| Encode | `enc_out_ns − enc_in_ns` | Sender only, no clock sync needed |
| Wire | `dec_in_ns − tx_ns` | Cross-host — requires synchronized clocks |
| Decode | `dec_out_ns − dec_in_ns` | Receiver only, no clock sync needed |
| E2E | `Encode + Wire + Decode` | Full pipeline: encoder input → decoder output |

All timestamps are taken with Python's `time.time_ns()` inside GStreamer pad probe callbacks. Because probes fire synchronously on the streaming thread, there is no additional scheduling jitter beyond what the OS introduces.

### Clock synchronization

Wire latency is the only stage that requires clock synchronization between the two machines.

The sender runs as a chrony stratum-1 orphan (no upstream NTP server needed on an air-gapped LAN). The receiver syncs from the sender over NTP. After ~60 seconds of convergence, achieved offset on this run: **+202 µs ± 234 µs**.

At 30 fps, one frame is 33.3 ms. A ±234 µs clock error is 0.7% of a frame period — well within the acceptable range for a benchmark whose wire latency measurements are in the 67–100 ms range.

The setup is scripted in `scripts/setup_timesync.sh`:

```bash
# On sender: become stratum-1 orphan
ssh nvidia@<sender-ip> "bash scripts/setup_timesync.sh sender"
# After 60 s, on receiver: sync from sender
ssh nvidia@<receiver-ip> "bash scripts/setup_timesync.sh receiver <sender-ip>"
# Verify
ssh nvidia@<receiver-ip> "chronyc tracking"
```

---

## Results

All values in **milliseconds**. Format: **mean / p95**.

### Summary — E2E latency

| Codec | FHD E2E mean | HD E2E mean | vs H.264 FHD |
|:------|---:|---:|---:|
| **AV1** | **104.0 ms** | **85.8 ms** | **−122.9 ms** |
| H.265 | 134.3 ms | 117.1 ms | −92.6 ms |
| H.264 | 226.9 ms | 245.8 ms | — |

AV1 beats H.265 by ~30 ms and H.264 by ~120–160 ms at both resolutions.

### Per-stage breakdown — FHD 1920×1080

| Stage | H.264 | H.265 | AV1 |
|-------|------:|------:|----:|
| Encode mean | 16.4 ms | 15.5 ms | 17.4 ms |
| Encode p95 | 16.9 ms | 15.8 ms | 17.9 ms |
| Wire mean | 67.3 ms | 100.4 ms | 67.6 ms |
| Wire p95 | 68.1 ms | 101.4 ms | 68.6 ms |
| Decode mean | **143.2 ms** | 18.5 ms | 19.0 ms |
| Decode p95 | **145.1 ms** | 19.0 ms | 19.6 ms |
| **E2E mean** | **226.9 ms** | **134.3 ms** | **104.0 ms** |
| **E2E p95** | **228.7 ms** | **135.2 ms** | **104.9 ms** |

### Per-stage breakdown — HD 1280×720

| Stage | H.264 | H.265 | AV1 |
|-------|------:|------:|----:|
| Encode mean | 8.5 ms | 8.0 ms | 9.4 ms |
| Encode p95 | 8.9 ms | 8.4 ms | 9.8 ms |
| Wire mean | 67.3 ms | 100.4 ms | 67.5 ms |
| Wire p95 | 68.0 ms | 101.3 ms | 68.3 ms |
| Decode mean | **170.0 ms** | 8.6 ms | 8.9 ms |
| Decode p95 | **172.5 ms** | 9.0 ms | 9.3 ms |
| **E2E mean** | **245.8 ms** | **117.1 ms** | **85.8 ms** |
| **E2E p95** | **248.2 ms** | **118.0 ms** | **86.4 ms** |

### Full percentile data — notable outliers

| Codec | Res | Stage | mean | p50 | p95 | p99 | max |
|-------|-----|-------|-----:|----:|----:|----:|----:|
| H.264 | FHD | Decode | 143.2 | 144.0 | 145.1 | 146.2 | 147.1 |
| H.264 | HD | Decode | 170.0 | 171.6 | 172.5 | 173.0 | 173.5 |
| H.265 | FHD | Encode | 15.5 | 15.1 | 15.8 | **23.3 ⚠** | 23.8 |
| H.265 | FHD | Wire | 100.4 | 100.6 | 101.4 | **109.1 ⚠** | 109.6 |
| AV1 | FHD | Wire | 67.6 | 67.6 | 68.6 | 70.2 | **84.1 ⚠** |

The ⚠ values spike significantly above p95. H.265 p99 encode spikes (23 ms vs 15 ms mean) correlate with IDR frame insertion. AV1 wire max outliers are isolated single-frame events, not systematic.

---

## Visual breakdown

![E2E latency stacked breakdown by stage — H.264, H.265, AV1 at FHD and HD](/images/posts/jetson-codec-benchmark-stacked.png)

The stacked chart makes the H.264 decoder anomaly immediately visible: decode (red segment) consumes most of the H.264 bar while being negligible for H.265 and AV1.

![E2E latency FHD vs HD grouped by codec](/images/posts/jetson-codec-benchmark-grouped.png)

The grouped chart shows two unexpected patterns: H.264 E2E is *worse* at HD than FHD (245 ms vs 227 ms), and AV1 achieves the lowest E2E at both resolutions despite being the newest codec on the stack.

![Per-stage latency breakdown horizontal — all combinations](/images/posts/jetson-codec-benchmark-breakdown.png)

---

## Key finding 1: H.264 decode anomaly

The most surprising result: H.264 decode latency is **143 ms at FHD and 170 ms at HD**.

For reference, H.265 and AV1 decode in 8–19 ms at both resolutions. H.264 decode is **7–20× slower**.

The cause is the Decoded Picture Buffer (DPB). The H.264 standard allows decoders to hold a configurable number of reference frames before releasing output. NVIDIA's `nvv4l2decoder` on JetPack 6 holds approximately **4 frames** internally before releasing output — even with `num-B-Frames=0` set on the encoder.

At 30 fps, 4 frames = 133 ms of mandatory decoder delay. The measured decode latency (143 ms at FHD, 170 ms at HD) matches this: frame delivery latency + the 4-frame buffer = the observed numbers.

This is not a bug. It is the decoder's DPB configuration. But it means H.264 has hidden latency that does not appear in encoder specifications and is not visible to anyone reasoning only about encoder settings.

### Why HD is slower than FHD

H.264 HD decode (170 ms) is counterintuitively **slower** than FHD (143 ms). This is reproducible across multiple runs and is believed to be a driver-level quirk in the `nvv4l2` H.264 decoder path at this JetPack version. One possible explanation: the driver's DPB management path may have a different code path for small-resolution buffers (potentially holding more frames in the buffer when frame sizes are small, since memory pressure is lower). This is consistent with a "hold more when you can afford to" heuristic in the driver. Regardless of cause, the effect is confirmed and reproducible.

**Practical implication:** If you are using H.264 on Jetson for a latency-sensitive application and observing ~200–250 ms end-to-end latency, the H.264 decoder is likely responsible for roughly 60–70% of that latency. Switching to H.265 or AV1 will drop E2E latency by 90–120 ms without any other changes.

---

## Key finding 2: Wire latency is governed by parse-element lookahead

The wire latency results are counterintuitive at first glance:

| Codec | FHD wire | HD wire | Difference |
|-------|--------:|--------:|----------:|
| H.264 | 67.3 ms | 67.3 ms | 0.0 ms |
| H.265 | 100.4 ms | 100.4 ms | 0.0 ms |
| AV1 | 67.6 ms | 67.5 ms | 0.1 ms |

Wire latency is **identical for FHD and HD** within the same codec. If wire latency were governed by byte volume on the wire, HD (smaller frames) would be faster than FHD. It is not.

The explanation: wire latency is dominated by the **parse element frame lookahead**, not by byte volume.

At 1500 kbps and 30 fps, both FHD and HD encode to the same number of bytes per frame (bitrate is fixed). The parse element (`h264parse`, `h265parse`, `av1parse`) reads ahead a fixed number of frames to detect Access Unit boundaries:

- `h264parse` and `av1parse` use a ~2-frame lookahead: `2 / 30 fps = 66.7 ms ≈ 67 ms`
- `h265parse` uses a ~3-frame lookahead: `3 / 30 fps = 100 ms ≈ 100 ms`

This is why H.265 has 33 ms more wire latency than H.264 and AV1 — not because H.265 frames are larger (they are actually smaller at the same bitrate), but because the H.265 parse element holds one extra frame for AU boundary detection.

Network propagation on the LAN is less than 0.5 ms and is buried entirely inside these parse-element delays.

**Practical implication:** If you want to reduce wire latency on GStreamer TCP pipelines, look at the parse element configuration, not just the network. Replacing `h265parse` with a lower-lookahead alternative (or removing it if your decoder does not require AU-framing) can save 33 ms of wire latency.

---

## Key finding 3: AV1 wins end-to-end

AV1's victory deserves explanation because it is not obvious from encoder cost alone. AV1 encode costs 1.5–2 ms more per frame than H.265 at both resolutions. However:

- AV1 wire latency (~67 ms) matches H.264, not H.265 — saving 33 ms vs H.265 on wire.
- AV1 decode latency (~9–19 ms) is comparable to H.265 decode (8–18 ms).
- AV1 has no DPB buffering anomaly.

The net result:

| | Encode | Wire | Decode | E2E |
|---|---:|---:|---:|---:|
| AV1 vs H.265 (FHD) | +1.9 ms | −32.8 ms | +0.5 ms | **−30.3 ms** |
| AV1 vs H.264 (FHD) | +1.0 ms | +0.3 ms | −124.2 ms | **−122.9 ms** |

AV1 beats H.265 by ~30 ms entirely due to the shorter parse-element lookahead. It beats H.264 by ~123 ms entirely due to H.264's DPB buffering.

---

## Encode latency scales with pixel count

Encode latency roughly halves from FHD to HD, as expected for constant-bitrate hardware encoders:

| Codec | FHD encode | HD encode | Ratio |
|-------|----------:|--------:|------:|
| H.264 | 16.4 ms | 8.5 ms | 1.93× |
| H.265 | 15.5 ms | 8.0 ms | 1.94× |
| AV1 | 17.4 ms | 9.4 ms | 1.85× |

H.265 is consistently the fastest encoder (~0.9 ms less than H.264, ~1.9 ms less than AV1 at FHD). AV1 has the highest encode cost, but the margin is small: 1 ms over H.264 and 2 ms over H.265 at FHD. For a latency budget measured in hundreds of milliseconds, encoder cost differences between codecs are negligible.

---

## H.266 / VVC — tested and dropped

H.266 (VVC) was in the original benchmark plan. The `gst-bench` Docker image includes VVenC (encoder) and VVdeC (decoder) compiled from source. It was removed from the measurement matrix for three reasons.

**No hardware support on Jetson Orin.** There is no NVMM (hardware-accelerated) VVC encoder or decoder in NVIDIA JetPack as of L4T R36.4.x. Both encode and decode run entirely in software on the ARM Cortex-A78AE CPU cores.

**Impractically slow for a 30 fps benchmark.** VVenC at `--preset fast` on ARM64 achieves approximately 0.3–1 fps for FHD and 1–3 fps for HD. Encoding 930 frames (30 s measurement + 30 warmup) takes 10–30 minutes per combination. Two combinations add up to an hour of wall time.

**Synthetic per-frame timing.** VVenC is a batch encoder — a single process call for the entire sequence. Per-frame `enc_in_ns` / `enc_out_ns` timestamps are synthetic: total encode time divided evenly across all frames. This gives a valid mean but no frame-level variance, jitter, or decode-pipeline timing.

The `Dockerfile`, `sender.py`, and `receiver.py` retain the H.266 code paths for future use when NVIDIA adds VVC hardware support to JetPack.

---

## Notable design decisions in the measurement harness

**`is-live=true` on `videotestsrc`.** Without it, the encoder runs at uncapped speed (~200 fps), fills the `tcpserversink` internal buffer in ~1.5 seconds, and the receiver gets a mid-stream join without parameter sets or an accurate wire latency baseline.

**`recover-policy=none buffers-soft-max=300` on `tcpserversink`.** Buffers up to 300 frames while the receiver is connecting. With PAUSED+`client-added` synchronization, the buffer is always empty when encoding starts, so this is a safety net only.

**`insert-sps-pps=true iframeinterval=30` on H.264/H.265 encoders.** Embeds parameter sets at every IDR frame. This is also what allows the receiver to re-sync cleanly in the event of a mid-stream TCP reconnect.

**Sequential frame counters on the receiver.** After a parse element, each buffer is exactly one frame. Sequential counters (`_dec_in_count`, `_dec_out_count`) are safe because parse → decoder is a 1:1 FIFO with no B-frames and TCP is lossless. PTS is not preserved across the TCP connection, so PTS-based matching would require sending explicit frame indices out-of-band.

**Cross-host wire latency from `time.time_ns()`.** Python's `time.time_ns()` reads the system CLOCK_REALTIME, which chrony keeps synchronized. On a well-synchronized chrony pair, this is accurate to the clock offset — ±234 µs in this run. GStreamer's own `GST_CLOCK_TIME_NONE`-based system clocks are pipeline-local and cannot be compared across hosts; using `time.time_ns()` in the probe callback is the correct approach.

---

## Reproduction steps

### Prerequisites

- Two NVIDIA Jetson Orin devices on JetPack 6 (L4T R36.4.x), GbE LAN
- SSH key auth (passwordless) from dev machine to both Jetsons
- Docker installed on both Jetsons with NVIDIA container runtime enabled

Sender and receiver addresses depend on your LAN — substitute your own IPs throughout.

### Step 1 — Deploy to both Jetsons

```bash
cd ~/benchmark
bash scripts/deploy.sh
```

This rsync's the benchmark directory to both Jetsons and builds the `gst-bench` Docker image on each (ARM64, ~10–15 min on first run due to VVenC/VVdeC compilation).

> **Always build with `--network=host`** — Docker bridge networking is broken on these Jetsons due to an iptables raw table issue.

### Step 2 — Synchronize clocks

```bash
# Sender first
ssh nvidia@<sender-ip> "bash ~/benchmark/scripts/setup_timesync.sh sender"
# Wait 60 s, then receiver
ssh nvidia@<receiver-ip> "bash ~/benchmark/scripts/setup_timesync.sh receiver <sender-ip>"
# Verify — target offset < 1 ms
ssh nvidia@<receiver-ip> "chronyc tracking"
```

### Step 3 — Run the full matrix

```bash
cd ~/benchmark
bash scripts/run_matrix.sh
```

Six combinations run sequentially. Each takes ~36–40 seconds. Total: ~4 minutes.

The script:
1. Starts the sender container in `PAUSED` (port bound, encoding not started)
2. Polls sender Docker logs until `READY port=N` appears
3. Starts the receiver container
4. Receiver connects → sender detects `client-added` → transitions to `PLAYING`
5. Encoding starts with receiver already consuming frames
6. Both containers exit; CSVs are `scp`'d to `./results/`

### Step 4 — Analyze

```bash
python3 scripts/analyze.py --results-dir ./results
```

Outputs a Markdown table and writes `results/summary.json` with full percentile data.

### Running a single combination manually

```bash
# Sender — waits in PAUSED until receiver connects
ssh nvidia@<sender-ip> "
  docker run --rm --runtime nvidia --network host \
    --name bench_sender \
    -e NVIDIA_VISIBLE_DEVICES=all -e NVIDIA_DRIVER_CAPABILITIES=all \
    -v /tmp/bench_results:/results \
    gst-bench \
    python3 /app/scripts/sender.py \
      --codec h265 --resolution fhd \
      --bitrate 1500000 --port 5200 \
      --duration 30 --warmup 30
"
# Watch for READY port=5200, then start receiver
ssh nvidia@<receiver-ip> "
  docker run --rm --runtime nvidia --network host \
    --name bench_receiver \
    -e NVIDIA_VISIBLE_DEVICES=all -e NVIDIA_DRIVER_CAPABILITIES=all \
    -v /tmp/bench_results:/results \
    gst-bench \
    python3 /app/scripts/receiver.py \
      --codec h265 --resolution fhd \
      --sender-ip <sender-ip> --port 5200 \
      --warmup 30
"
```

---

## Troubleshooting reference

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| H.265 receiver: 0 frames parsed | Receiver connected after sender buffered frames without SPS/PPS | Ensure `is-live=true` on `videotestsrc`; use PAUSED+`client-added` sync |
| AV1 receiver: "No valid frames" | Missed Sequence Header OBU | Ensure `insert-seq-hdr=true iframeinterval=30` on `nvv4l2av1enc` |
| Wire latency ~8600 ms | Receiver connected 8+ s after sender started encoding | PAUSED+`client-added` sync (already in current `sender.py`) |
| Docker build fails: "parent snapshot does not exist" | Corrupted build cache on Jetson | `docker builder prune -f && docker build --no-cache --network=host -t gst-bench .` |
| `gst_parse_error: no property "caps" in element "src"` | `tcpclientsrc` has no `caps` property | Use parse element after `tcpclientsrc` instead |
| Docker networking fails | iptables raw table broken on Jetson | Always `--network=host` |

---

## Conclusions

On JetPack 6 hardware with `nvv4l2` codecs at 30 fps / 1500 kbps / GbE TCP:

**Use AV1 for latency-sensitive pipelines.** 104 ms FHD, 86 ms HD. The encode cost (+1–2 ms vs H.265) is outweighed by saving 33 ms of wire latency (shorter `av1parse` lookahead vs `h265parse`) and avoiding H.264's DPB issue.

**Avoid H.264.** The `nvv4l2decoder` holds ~4 frames before releasing output, adding 130–170 ms of hidden latency. H.264 delivers the worst E2E numbers despite being the oldest and most-supported codec. The anomaly is driver-level and does not respond to `num-B-Frames=0`.

**Wire latency is a parse-element problem, not a network problem.** On a GbE LAN, network propagation is <0.5 ms. Wire latency is 67–100 ms because parse elements perform lookahead. Choosing AV1 over H.265 saves 33 ms of wire latency purely through this effect.

**Encode latency is a secondary concern.** Differences between codecs at the encoder stage are 1–2 ms. For pipelines targeting sub-200 ms E2E, encoder selection is not the lever to pull — decoder behavior and parse-element lookahead are.

The full per-frame CSV data and `Dockerfile` are available in the benchmark repository.
