---
title: "Fixing a GStreamer Bug: Why shmsink Always Exits with Code 1"
date: 2026-03-24
draft: false
tags: ["GStreamer", "debugging", "shared-memory", "C", "open-source", "contributing"]
keywords: ["GStreamer shmsink exit code 1", "GStreamer shared memory pipeline error", "shmsink race condition fix"]
categories: ["deep-dive"]
summary: "A 2-line fix for a race condition in GStreamer's shmsink that causes every pipeline using shared memory to exit with an error. How I found it, proved it, and verified the fix with sanitizers."
ShowToc: true
---

## The Bug

Every GStreamer pipeline using `shmsink` exits with code 1 and an error message, even when it runs perfectly fine:

```
Got EOS from element "pipeline0".
Setting pipeline to NULL ...
ERROR: from element /GstPipeline:pipeline0/GstShmSink:shmsink0: Failed waiting on fd activity
gst_poll_wait returned -1, errno: 16
Freeing pipeline ...
```

The video plays correctly. The data transfers through shared memory. Everything works — and then on shutdown, an error. Exit code 1. CI pipelines fail. Monitoring tools report crashes. Users file [bug reports](https://gitlab.freedesktop.org/gstreamer/gstreamer/-/issues/4487).

## Reproducing It

Minimal reproduction — no special hardware, no complex pipeline:

```bash
gst-launch-1.0 videotestsrc num-buffers=30 ! \
  video/x-raw,format=I420,width=320,height=240,framerate=10/1 ! \
  shmsink wait-for-connection=false socket-path=/tmp/testsock \
  shm-size=2000000 sync=false
echo "Exit code: $?"
# Output: Exit code: 1
```

Every time. On every platform. Since at least GStreamer 1.22.

## Finding the Cause

The error message gives us the exact location: `gstshmsink.c:842` in `pollthread_func`. And a critical clue: `errno: 16`.

Errno 16 is `EBUSY`. Not `EPERM`, not `EIO` — `EBUSY`.

I searched GStreamer's own source for what returns `EBUSY`:

```c
// gst/gstpoll.c, line 1699-1705
/**
 * gst_poll_set_flushing:
 *
 * When @flushing is %TRUE, this function ensures that current
 * and future calls to gst_poll_wait() will return -1, with
 * errno set to EBUSY.
 */
```

And there it is. `gst_poll_set_flushing()` *intentionally* makes `gst_poll_wait()` return -1 with `EBUSY`. It's a designed mechanism for waking up blocked poll threads during shutdown.

Now look at who calls `gst_poll_set_flushing()`:

```c
// gstshmsink.c, line 610-615
static gboolean
gst_shm_sink_stop (GstBaseSink *bsink)
{
    GstShmSink *self = GST_SHM_SINK (bsink);
    self->stop = TRUE;
    gst_poll_set_flushing (self->poll, TRUE);  // <-- triggers EBUSY
    ...
    g_thread_join (self->pollthread);
```

`stop()` sets `self->stop = TRUE`, then flushes the poll to wake up the poll thread. The poll thread is supposed to see `self->stop` and exit cleanly.

But the poll thread checks things in the wrong order:

```c
// gstshmsink.c, line 835-846
while (!self->stop) {
    do {
        rv = gst_poll_wait (self->poll, timeout);
    } while (rv < 0 && errno == EINTR);

    if (rv < 0) {
        // ← Posts GST_ELEMENT_ERROR here!
        // ← Never checks self->stop!
        GST_ELEMENT_ERROR (self, RESOURCE, READ, ...);
        return NULL;
    }

    if (self->stop)      // ← Too late, error already posted
        return NULL;
```

The race:

1. `stop()` sets `self->stop = TRUE`
2. `stop()` calls `gst_poll_set_flushing(TRUE)`
3. `gst_poll_wait()` returns -1 with `EBUSY`
4. The retry loop only handles `EINTR`, not `EBUSY` — falls through
5. `rv < 0` is true → posts `GST_ELEMENT_ERROR` **before** checking `self->stop`
6. Error is on the bus. Pipeline exit code is 1.

## The Fix

Two lines:

```c
if (rv < 0) {
    if (self->stop)        // ← Added: check before posting error
        return NULL;
    GST_ELEMENT_ERROR (self, RESOURCE, READ,
        ("Failed waiting on fd activity"),
        ("gst_poll_wait returned %d, errno: %d", rv, errno));
    return NULL;
}
```

If the poll was woken up because we're shutting down (`self->stop` is true), just return without posting an error. If it's a real error (not a shutdown), post the error as before.

## Proving the Fix

### Side-by-side comparison

I built GStreamer from source in Docker, ran the reproduction pipeline, applied the fix, rebuilt just the shm plugin, and ran again:

```
=== BEFORE FIX ===
Got EOS from element "pipeline0".
Setting pipeline to NULL ...
ERROR: Failed waiting on fd activity
gst_poll_wait returned -1, errno: 16
Freeing pipeline ...
BEFORE: exit 1

=== AFTER FIX ===
Got EOS from element "pipeline0".
Setting pipeline to NULL ...
Freeing pipeline ...
AFTER: exit 0
```

### AddressSanitizer

Built with `-fsanitize=address`, ran the same pipeline before and after. No memory errors in either case — the bug is a logic error, not a memory error. ASAN confirms the fix doesn't introduce any new memory issues.

### ThreadSanitizer

Built with `-fsanitize=thread`. Both before and after show ~30 data race warnings — all in GStreamer core (`gstpoll.c`, `gstpad.c`, `gstbus.c`, `gsttask.c`). These are pre-existing races in the framework, not from the shm plugin.

One TSAN warning is directly relevant: `gstshmsink.c:614 in gst_shm_sink_stop` — the access to `self->stop` without a memory barrier. This is the root cause of the race, and our fix handles its consequence (the spurious error). The underlying lack of a barrier on `self->stop` is a separate pre-existing issue.

## Why This Matters

`shmsink` and `shmsrc` are GStreamer's built-in mechanism for inter-process video sharing. Every pipeline that uses shared memory IPC hits this bug:

- CI/CD systems that check exit codes see failures on perfectly working pipelines
- Process supervisors restart containers that exited "with an error"
- Logging systems fill up with false error messages
- Users doubt whether their pipeline actually works

The fix is 2 lines. The investigation took longer than the fix — which is usually how debugging works.

## Links

- **MR:** [!11109](https://gitlab.freedesktop.org/gstreamer/gstreamer/-/merge_requests/11109)
- **Issue:** [#4487](https://gitlab.freedesktop.org/gstreamer/gstreamer/-/issues/4487)
- **The 2-line diff:** [commit](https://gitlab.freedesktop.org/PavelGuzenfeld/gstreamer/-/commit/fix-shmsink-exit-code)

---

**Related:**
- [Anatomy of Four GStreamer Shared Memory Bugs](/posts/anatomy-of-gstreamer-shm-bugs/)
- [Zero-Copy Video on Jetson: Building gst-nvmm-cpp and Contributing to GStreamer](/posts/gst-nvmm-cpp-zero-copy-video-jetson/)
- [GStreamer and video pipeline consulting](/consulting/)
