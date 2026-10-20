---
title: 'From GStreamer PTS to std::chrono::steady_clock'
date: 2026-10-20
draft: false
cover:
  image: /images/posts/gstreamer-pts-to-steady-clock.png
  alt: 'Converting a GStreamer buffer PTS plus base_time into a std::chrono::steady_clock time point'
tags:
- GStreamer
- C++
- video-processing
- Linux
- Docker
keywords:
- GStreamer buffer timestamp to system clock
- GStreamer PTS to steady_clock
- gst_element_get_base_time running time
- GST_CLOCK_TYPE_MONOTONIC
- correlate GStreamer timestamp with sensor data
- MPEG-TS PTS 90 kHz 3600 seconds offset
- mpegtsmux TS_MUX_CLOCK_BASE
categories:
- how-to
summary: A buffer's PTS is running time, not wall time. Add the pipeline's base time and you get
  the clock time the frame was captured at. With the monotonic system clock that is a
  std::chrono::steady_clock time point you can compare to IMU or telemetry timestamps directly.
ShowToc: true
---

Sooner or later you need to know when a frame was captured, in the same time base as everything else in the process: IMU samples, telemetry, a tracker's own timestamps. `GST_BUFFER_PTS` looks like it should answer that. It doesn't, at least not by itself.

## What PTS actually is

For a live source, the PTS is **running time**: nanoseconds since the pipeline went to PLAYING, not since boot or the epoch. To get back to clock time, add the pipeline's **base time**, which is the clock reading at the moment the pipeline started running:

```text
                 base_time                     base_time + running_time       now()
                     |                                     |                    |
clock  --------------+-------------------------------------+--------------------+------->
(monotonic,          |<------------ running_time --------->|<------ age ------->|
 ns since boot)      |   (= PTS, for a live source with    |  (capture -> probe)
                     |    a segment starting at 0)         |
              pipeline went                         frame captured        your callback
                PLAYING
```

In code:

```cpp
clock_time = base_time + gst_segment_to_running_time(segment, GST_FORMAT_TIME, pts);
```

Using `gst_segment_to_running_time` instead of a raw `pts` costs nothing. It keeps the formula right when the segment doesn't start at zero, for example after a seek or behind a demuxer.

## Make the clock monotonic

`base_time + running_time` is in the pipeline clock's time base. If that clock is GStreamer's system clock in **monotonic** mode, it reads `CLOCK_MONOTONIC`. That's the same clock libstdc++'s `std::chrono::steady_clock` reads on Linux, so you can build a `steady_clock::time_point` straight from the nanoseconds.

```cpp
GstClock *clock = gst_system_clock_obtain();
g_object_set(clock, "clock-type", GST_CLOCK_TYPE_MONOTONIC, nullptr);
gst_pipeline_use_clock(GST_PIPELINE(pipeline), clock);
gst_object_unref(clock);
```

On GStreamer 1.24, `gst_system_clock_obtain()` already returns a monotonic clock; I checked, and `clock-type` reads 1. The `gst_pipeline_use_clock` call is the part that matters. Without it the pipeline picks a clock on its own, and an audio sink can provide one, which the pipeline usually prefers. Then your `base_time` lives in a different time base and the arithmetic quietly breaks.

Two caveats:

- `gst_system_clock_obtain()` returns a process-wide singleton. Changing `clock-type` changes it for every pipeline in the process.
- For a camera, the PTS is only as good as the source's timestamp. `v4l2src` uses the driver's buffer timestamp when the driver gives a monotonic one, and the dequeue time otherwise. Either way that's usually when the frame finished arriving, not mid-exposure. The math below recovers that moment, not the shutter time.

## A program that checks it

The program puts a pad probe on the sink and, for each buffer, prints PTS, running time, base time, the computed capture time and `steady_clock::now()` taken inside the probe. `identity sleep-time=5000` adds 5 ms between source and probe, so the "age" column should come out a little over 5 ms if the mapping is right.

```cpp
#include <gst/gst.h>

#include <chrono>
#include <cstdio>

using steady = std::chrono::steady_clock;

static steady::time_point to_steady(GstClockTime clock_time)
{
    return steady::time_point{std::chrono::nanoseconds{clock_time}};
}

static GstPadProbeReturn on_buffer(GstPad *pad, GstPadProbeInfo *info, gpointer pipeline)
{
    auto const now = steady::now();
    GstBuffer *buffer = GST_PAD_PROBE_INFO_BUFFER(info);
    GstClockTime const pts = GST_BUFFER_PTS(buffer);
    GstClockTime const base_time = gst_element_get_base_time(GST_ELEMENT(pipeline));

    GstEvent *seg_event = gst_pad_get_sticky_event(pad, GST_EVENT_SEGMENT, 0);
    GstSegment const *segment = nullptr;
    gst_event_parse_segment(seg_event, &segment);
    guint64 const running_time = gst_segment_to_running_time(segment, GST_FORMAT_TIME, pts);
    gst_event_unref(seg_event);

    auto const captured = to_steady(base_time + running_time);
    auto const age_us = std::chrono::duration_cast<std::chrono::microseconds>(now - captured).count();
    std::printf("pts=%10.3f ms  running=%10.3f ms  base=%14.3f ms  clock=%14.3f ms  now=%14.3f ms  age=%6lld us\n",
                pts / 1e6, running_time / 1e6, base_time / 1e6, (base_time + running_time) / 1e6,
                std::chrono::duration<double, std::milli>(now.time_since_epoch()).count(),
                static_cast<long long>(age_us));
    return GST_PAD_PROBE_OK;
}

int main(int argc, char **argv)
{
    gst_init(&argc, &argv);
    GstElement *pipeline = gst_parse_launch(
        "videotestsrc is-live=true num-buffers=10 ! video/x-raw,framerate=30/1 "
        "! identity name=work sleep-time=5000 ! fakesink name=sink sync=false",
        nullptr);

    GstClock *clock = gst_system_clock_obtain();
    g_object_set(clock, "clock-type", GST_CLOCK_TYPE_MONOTONIC, nullptr);
    gst_pipeline_use_clock(GST_PIPELINE(pipeline), clock);
    gst_object_unref(clock);

    GstElement *sink = gst_bin_get_by_name(GST_BIN(pipeline), "sink");
    GstPad *pad = gst_element_get_static_pad(sink, "sink");
    gst_pad_add_probe(pad, GST_PAD_PROBE_TYPE_BUFFER, on_buffer, pipeline, nullptr);
    gst_object_unref(pad);
    gst_object_unref(sink);

    gst_element_set_state(pipeline, GST_STATE_PLAYING);
    GstBus *bus = gst_element_get_bus(pipeline);
    GstMessage *msg = gst_bus_timed_pop_filtered(bus, GST_CLOCK_TIME_NONE,
                                                 static_cast<GstMessageType>(GST_MESSAGE_EOS | GST_MESSAGE_ERROR));
    gst_message_unref(msg);
    gst_object_unref(bus);
    gst_element_set_state(pipeline, GST_STATE_NULL);
    gst_object_unref(pipeline);
}
```

Output from GStreamer 1.24.2 in an `ubuntu:24.04` container on an i7-12700H:

```text
pts=     1.685 ms  running=     1.685 ms  base=  23769070.458 ms  clock=  23769072.143 ms  now=  23769077.240 ms  age=  5097 us
pts=    35.019 ms  running=    35.019 ms  base=  23769070.458 ms  clock=  23769105.476 ms  now=  23769110.724 ms  age=  5247 us
pts=    68.352 ms  running=    68.352 ms  base=  23769070.458 ms  clock=  23769138.809 ms  now=  23769144.138 ms  age=  5328 us
pts=   101.685 ms  running=   101.685 ms  base=  23769070.458 ms  clock=  23769172.143 ms  now=  23769177.388 ms  age=  5244 us
pts=   135.019 ms  running=   135.019 ms  base=  23769070.458 ms  clock=  23769205.476 ms  now=  23769210.653 ms  age=  5177 us
pts=   168.352 ms  running=   168.352 ms  base=  23769070.458 ms  clock=  23769238.809 ms  now=  23769244.164 ms  age=  5354 us
pts=   201.685 ms  running=   201.685 ms  base=  23769070.458 ms  clock=  23769272.143 ms  now=  23769277.395 ms  age=  5252 us
pts=   235.019 ms  running=   235.019 ms  base=  23769070.458 ms  clock=  23769305.476 ms  now=  23769310.851 ms  age=  5375 us
pts=   268.352 ms  running=   268.352 ms  base=  23769070.458 ms  clock=  23769338.809 ms  now=  23769344.076 ms  age=  5266 us
pts=   301.685 ms  running=   301.685 ms  base=  23769070.458 ms  clock=  23769372.143 ms  now=  23769377.293 ms  age=  5149 us
```

The age stays between 5.1 and 5.4 ms on every buffer: the 5 ms `identity` sleep plus a few hundred microseconds of pipeline. The computed capture time and `steady_clock::now()` share a time base. You can see it in the numbers: `base` is about 23.7 million ms, which is time since the host booted.

The same program with `GST_CLOCK_TYPE_REALTIME` instead:

```text
pts=     1.698 ms  running=     1.698 ms  base=1792454789494.423 ms  clock=1792454789496.121 ms  now=  23781757.733 ms  age=-1792431007738387 us
```

`base` is now Unix-epoch time and `now()` is still time since boot, so the difference is meaningless. If your "latency" comes out as minus 56 years, this is why.

In the probe you'd keep `captured` as a `steady_clock::time_point` and hand it to whatever fuses frames with other sensors. Don't use `GstClockTime` for that.

## Using the source's base time instead of the pipeline's

Some code reads the base time from the source element instead of the pipeline:

```cpp
GstElement *src = gst_bin_get_by_name(GST_BIN(pipeline), "camera");
GstClockTime base_time = gst_element_get_base_time(src);
gst_object_unref(src);
```

That works too, because the pipeline distributes the same base time to every element when it goes to PLAYING. Read it from the pipeline; there's one less thing to look up by name.

## MPEG-TS and the 3600 seconds

If you record to MPEG-TS and later read the PES timestamps yourself, outside GStreamer, you meet a different unit and a strange offset. In my old notes I had this:

```python
def normalize_TS_pts_to_buffer_pts(pts):
    return int((pts / 90000 - 3600) * 10**9)
```

The `/ 90000` is the MPEG system clock: TS timestamps tick at 90 kHz. The `- 3600` comes from GStreamer's muxer. In `gst-plugins-bad/gst/mpegtsmux/gstbasetsmux.c`:

```c
#define TS_MUX_CLOCK_BASE (TSMUX_CLOCK_FREQ * 10 * 360)
```

That's 90000 × 3600 ticks. The muxer adds it to every PTS and DTS it writes, so a buffer with running time 0 goes on the wire as 3600 s. I checked with a 5-frame file:

```bash
gst-launch-1.0 -q videotestsrc num-buffers=5 ! video/x-raw,framerate=30/1 \
  ! x264enc ! mpegtsmux ! filesink location=t.ts
ffprobe -v error -select_streams v -show_entries packet=pts,pts_time -of csv t.ts
```

```text
packet,324000000,3600.000000
packet,324011999,3600.133322
packet,324005999,3600.066656
```

The first packet is at exactly 324,000,000 ticks, or 3600.000 s. So the old helper is right, but only under narrow conditions:

- It applies to raw PTS values you parse from a file **written by GStreamer's `mpegtsmux`**. Other muxers pick their own start offset.
- It maps back to the muxer's **input running time**, not to clock time. Add the recording pipeline's base time if you logged it.
- You don't need it at all if you read the file back with GStreamer. `tsdemux` takes the offset out. The same file through `tsdemux ! h264parse` gave a first frame with `pts: 0:00:00.191655556` and a segment starting at the same value, not 3600 s.

## Reproduce

```dockerfile
FROM ubuntu:24.04
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    gstreamer1.0-tools gstreamer1.0-plugins-base gstreamer1.0-plugins-good \
    libgstreamer1.0-dev g++ pkg-config \
 && rm -rf /var/lib/apt/lists/*
```

```bash
docker build -t gst-pts .
docker run --rm -v "$PWD":/w -w /w gst-pts bash -c \
  'g++ -std=c++20 -O2 -Wall -Wextra pts_clock.cpp -o /tmp/pts_clock \
     $(pkg-config --cflags --libs gstreamer-1.0) && /tmp/pts_clock'
```

For the MPEG-TS check, add `gstreamer1.0-plugins-bad gstreamer1.0-plugins-ugly ffmpeg` to the image.
