---
title: 'GStreamer Latency to a Midpoint, Not Just the Sink'
date: 2026-10-20
draft: true
tags:
- GStreamer
- video-processing
- profiling
- performance
- debugging
- Docker
keywords:
- GStreamer latency tracer
- GST_TRACERS latency flags pipeline element
- measure latency between two GStreamer elements
- GStreamer tee queue latency
- GStreamer tee deadlock sync sink
- decoupled tap GStreamer
- partial pipeline latency
categories:
- how-to
summary: The latency tracer measures source to sink. To measure source to some point in the middle,
  hang a fakesink off a tee. Without queues on both branches the slow branch leaks into your
  number, or hangs the pipeline. Measured on GStreamer 1.24 in Docker.
ShowToc: true
---

The latency tracer only knows source-to-sink. Most of the time I want something else: how long from capture to the point where my tracker gets the frame, ignoring whatever the display branch does after that.

The trick is to put a sink exactly where you want to measure. Hang a `fakesink` off a `tee` at that point and read the tracer's numbers for that sink only. Do it naively and the display branch pollutes the number. Do it really naively and the pipeline hangs.

Everything below ran in an `ubuntu:24.04` container, GStreamer 1.24.2, `videotestsrc` at 30 fps, on an i7-12700H laptop. 300 buffers per run.

## The tracer

```bash
GST_DEBUG="GST_TRACER:7" \
GST_TRACERS="latency(flags=pipeline+element)" \
gst-launch-1.0 ... 2> trace.log
```

The tracer writes to the debug log, so it goes to stderr. `flags=pipeline` gives one `latency` record per buffer per sink. `flags=element` adds an `element-latency` record per element. On 1.24 the lines look like this:

```text
... GST_TRACER :0:: latency, src-element-id=(string)0x..., src-element=(string)src, src=(string)src,
    sink-element-id=(string)0x..., sink-element=(string)final_sink, sink=(string)sink,
    time=(guint64)10099968, ts=(guint64)198245357;
... GST_TRACER :0:: element-latency, element-id=(string)0x..., element=(string)proc, src=(string)src,
    time=(guint64)10099968, ts=(guint64)198245357;
```

`time` is in nanoseconds. Name every element, or you get `fakesink0` and `identity1` in the log and have to guess.

The log also starts with a few `new format string: latency, ...` lines carrying `%s` and `%lu` placeholders. A parser that only filters on `latency,` will see them, so make it match digits after `time=(guint64)` and they drop out on their own.

## The stats script

I parse with awk. It needs no Python and runs anywhere the log lands:

```awk
# stats.awk — per-sink min/median/p95/max of the latency tracer, in ms
/:: latency,/ {
  match($0, /sink-element=\(string\)[^,]+/); s = substr($0, RSTART+21, RLENGTH-21)
  match($0, /time=\(guint64\)[0-9]+/);       t = substr($0, RSTART+14, RLENGTH-14) / 1e6
  n[s]++; v[s, n[s]] = t
}
END {
  for (s in n) {
    k = n[s]; for (i = 1; i <= k; i++) a[i] = v[s, i]
    asort(a, b, "@val_num_asc")
    printf "%-12s n=%d min=%.2f median=%.2f p95=%.2f max=%.2f\n",
           s, k, b[1], b[int(k*0.5)+1], b[int(k*0.95)], b[k]
    delete a; delete b
  }
}
```

`gawk -f stats.awk trace.log`. The offsets are the lengths of `sink-element=(string)` (21) and `time=(guint64)` (14). The first version I wrote had them off by one, which cut the leading digit off every number and made a 10 ms pipeline look like 0.1 ms. Check one value by hand against the raw log before you trust the table.

## Baseline: source to sink

```bash
gst-launch-1.0 videotestsrc name=src is-live=true num-buffers=300 \
  ! identity name=proc sleep-time=10000 \
  ! fakesink name=final_sink
```

`identity sleep-time=10000` stands in for 10 ms of processing.

| sink | min | median | p95 | max |
|---|---|---|---|---|
| final_sink | 10.06 | 10.12 | 10.22 | 10.37 |

All values are in ms. That's 10 ms of fake work plus about 0.1 ms of pipeline.

## The midpoint: tee straight into two sinks

Now I add a "display" branch that costs 20 ms and renders against the clock, and a `checkpoint` sink right after `proc`. The checkpoint is the number I care about. It should read about 10 ms.

```bash
gst-launch-1.0 videotestsrc name=src is-live=true num-buffers=300 \
  ! identity name=proc sleep-time=10000 ! tee name=tap \
  tap. ! identity name=display_work sleep-time=20000 ! fakesink name=display sync=true \
  tap. ! fakesink name=checkpoint sync=false
```

**This one hung.** One `latency` record for `display`, then nothing, until I killed it. With no queues, `tee` pushes both branches from the source's streaming thread, one after the other. The display sink has `sync=true`, so it holds the first buffer waiting for preroll. The checkpoint never gets a buffer, so it never prerolls, so the pipeline never reaches PLAYING. It's the classic tee-without-queues deadlock, and it shows up even with a live source.

To get numbers at all, I set `async=false` on the display sink so it doesn't take part in preroll. Then I ran it twice, once with the display branch linked first and once with the checkpoint linked first:

| run | sink | min | median | p95 | max |
|---|---|---|---|---|---|
| display linked first | checkpoint | 30.43 | **33.01** | 33.15 | 53.34 |
| display linked first | display | 30.20 | 30.33 | 30.49 | 30.62 |
| checkpoint linked first | checkpoint | 10.12 | 10.19 | 10.31 | 10.48 |
| checkpoint linked first | display | 30.23 | 30.35 | 30.51 | 30.65 |

Same pipeline, same elements. The checkpoint reads 33 ms or 10 ms depending on **which branch I wrote first** in the launch line. `tee` pushes to its src pads in request order, in one thread. If the display branch comes first, the checkpoint waits for its 20 ms of work and its clock wait. Your midpoint number then reports the display branch's cost. That's the "branch interference" I was trying to avoid.

Linking the tap first happens to work here, but only by accident of pad order. Add another element, or let a bin request pads in a different order, and you're back to 33 ms.

```text
checkpoint latency, 2 ms bins

display linked first
   30-32 ms |#                                        1
   32-34 ms |######################################## 298
   52-54 ms |#                                        1

checkpoint linked first
   10-12 ms |######################################## 300
```

## The decoupled tap

Put a queue on **both** branches. Each queue gets its own streaming thread, so the branches stop blocking each other:

```text
src -> proc -> main_queue -> tee -+-> tap_queue     -> checkpoint (fakesink sync=false)
                                  |
                                  +-> display_queue -> display_work -> display (sync=true)
```

```bash
gst-launch-1.0 videotestsrc name=src is-live=true num-buffers=300 \
  ! identity name=proc sleep-time=10000 ! queue name=main_queue ! tee name=tap \
  tap. ! queue name=tap_queue ! fakesink name=checkpoint sync=false \
  tap. ! queue name=display_queue ! identity name=display_work sleep-time=20000 \
       ! fakesink name=display sync=true async=false
```

`sync=false` on the checkpoint matters. It makes the sink take buffers as they arrive instead of waiting for their render time, so it never holds anything up.

| sink | min | median | p95 | max |
|---|---|---|---|---|
| checkpoint | 10.20 | **10.36** | 10.53 | 10.74 |
| display | 30.47 | 40.16 | 40.32 | 40.78 |

```text
decoupled tap, 2 ms bins

checkpoint
   10-12 ms |######################################## 300

display
   30-32 ms |#                                        1
   38-40 ms |#                                        2
   40-42 ms |######################################## 297
```

The checkpoint is back to 10.36 ms, within 0.25 ms of the plain source-to-sink baseline, and it doesn't depend on link order. The two queues add about 0.1 ms each.

The display branch got slower: 40 ms instead of 30. The element records explain it:

| element | median ms |
|---|---|
| proc | 10.13 |
| main_queue | 0.10 |
| tap_queue | 0.06 |
| display_queue | 9.74 |
| display_work | 20.13 |

`display_queue` holds each buffer for about 10 ms. That time is the display thread still blocked in the clock wait for the previous frame. Before, that wait landed on everyone. Now it lands only on the branch that caused it, which is the point.

## Plotting

The original version of this plotter, from my notes, did parse the 1.24 log. It only worked by luck, though: it matched `latency,` inside `element-latency,` lines and the format-string lines, and relied on its regex failing on them. This version filters on `:: latency,`, which matches only the per-buffer records. I ran it in the same container:

```python
import re
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


def plot_specific_sink(filename, target_sink_name):
    latencies = []
    pattern = re.compile(r"sink-element=\(string\)([\w]+).*?time=\(guint64\)(\d+)")
    with open(filename) as f:
        for line in f:
            if ":: latency," not in line:
                continue
            m = pattern.search(line)
            if m and m.group(1) == target_sink_name:
                latencies.append(int(m.group(2)) / 1e6)
    if not latencies:
        sys.exit(f"no latency records for sink '{target_sink_name}'")
    plt.figure(figsize=(10, 6))
    plt.plot(latencies, label=f"src -> {target_sink_name}")
    plt.xlabel("buffer")
    plt.ylabel("latency (ms)")
    plt.grid(True)
    plt.legend()
    plt.savefig(f"latency_{target_sink_name}.png")


if __name__ == "__main__":
    plot_specific_sink(sys.argv[1], sys.argv[2])
```

`python3 plot_latency.py trace.log checkpoint`. The `Agg` backend lets it run in a container with no display.

## Reproduce

```dockerfile
FROM ubuntu:24.04
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    gstreamer1.0-tools gstreamer1.0-plugins-base gstreamer1.0-plugins-good gawk \
 && rm -rf /var/lib/apt/lists/*
```

```bash
docker build -t gst-latency .
# stats.awk from above in the current directory
docker run --rm -v "$PWD":/w -w /w gst-latency bash -c '
  export GST_DEBUG="GST_TRACER:7" GST_TRACERS="latency(flags=pipeline+element)" GST_DEBUG_NO_COLOR=1
  gst-launch-1.0 videotestsrc name=src is-live=true num-buffers=300 \
    ! identity name=proc sleep-time=10000 ! queue name=main_queue ! tee name=tap \
    tap. ! queue name=tap_queue ! fakesink name=checkpoint sync=false \
    tap. ! queue name=display_queue ! identity name=display_work sleep-time=20000 \
         ! fakesink name=display sync=true async=false 2> trace.log > /dev/null
  gawk -f stats.awk trace.log'
```

On real hardware, swap `videotestsrc` and the `identity` stand-ins for your camera source and real elements. The structure stays the same: a tee at the point you care about, a queue on every branch, and a `sync=false` fakesink as the checkpoint.
