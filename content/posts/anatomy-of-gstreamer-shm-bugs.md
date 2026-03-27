---
title: "Anatomy of Four GStreamer Shared Memory Bugs"
date: 2026-03-24
draft: false
tags: ["GStreamer", "debugging", "shared-memory", "C", "concurrency", "open-source"]
keywords: ["GStreamer shmsink bug", "GStreamer shared memory race condition", "shmsrc use after free"]
categories: ["deep-dive"]
summary: "Four bugs in GStreamer's shmsink/shmsrc elements — a race condition, a use-after-free, a wrong-pointer dereference, and a page alignment mismatch. What they have in common, how to find them, and what they teach about writing correct GStreamer elements."
ShowToc: true
---

## Introduction

I recently fixed four bugs in GStreamer's shared memory subsystem — `shmsink`, `shmsrc`, the shm pipe protocol, and `GstShmAllocator`. Each bug is different, but they share a common theme: the contract between what the code promises and what the hardware or OS actually does.

This post walks through each bug, how I found the root cause, and what general lessons they offer for anyone writing GStreamer elements — especially elements that manage hardware resources, shared memory, or cross-thread communication.

The bugs, in order of subtlety:

1. **The Exit Code Bug** — a race between shutdown and error reporting
2. **The Hang Bug** — a wrong pointer and a use-after-free in the shm pipe protocol
3. **The Flaky Test** — a shutdown ordering problem that only manifests under load
4. **The Page Alignment Bug** — a mismatch between what the OS allocates and what GStreamer reports

## Bug 1: The Exit Code Race

**Issue:** [#4487](https://gitlab.freedesktop.org/gstreamer/gstreamer/-/issues/4487)
**MR:** [!11109](https://gitlab.freedesktop.org/gstreamer/gstreamer/-/merge_requests/11109)

### Symptom

Every pipeline using `shmsink` exits with code 1 and an error message, even when it runs perfectly:

```
Got EOS from element "pipeline0".
ERROR: Failed waiting on fd activity
gst_poll_wait returned -1, errno: 16
```

Video plays fine. Data transfers correctly. But the exit code says "error." CI pipelines fail. Monitoring tools restart containers.

### Root Cause

The `shmsink` element has a poll thread that waits for client connections and buffer ACKs. When the element shuts down, `gst_shm_sink_stop()` does two things:

```c
self->stop = TRUE;
gst_poll_set_flushing (self->poll, TRUE);
```

`gst_poll_set_flushing()` is documented in GStreamer's own source:

> "this function ensures that current and future calls to gst_poll_wait() will return -1, with errno set to EBUSY"

So the shutdown sequence is: set a flag, then wake up the poll thread by making its wait return an error. The poll thread is supposed to see the flag and exit cleanly.

But the poll thread checks things in the wrong order:

```c
while (!self->stop) {
    do {
        rv = gst_poll_wait (self->poll, timeout);
    } while (rv < 0 && errno == EINTR);

    if (rv < 0) {
        // Posts GST_ELEMENT_ERROR here!
        // Never checks self->stop first!
        GST_ELEMENT_ERROR (...);
        return NULL;
    }

    if (self->stop)      // Too late — error already posted
        return NULL;
```

The retry loop handles `EINTR` (signal interruption) but not `EBUSY` (flushing). The `EBUSY` return falls through to the error handler, which posts `GST_ELEMENT_ERROR` before checking `self->stop`.

### Fix

Two lines:

```c
if (rv < 0) {
    if (self->stop)        // Check before posting error
        return NULL;
    GST_ELEMENT_ERROR (...);
    return NULL;
}
```

### How I Found It

The error message included `errno: 16`. Errno 16 is `EBUSY`. I searched GStreamer's source for what returns `EBUSY` and found `gst_poll_set_flushing()` — which is called by the shutdown path. The race was visible from reading the two functions side by side.

### General Lesson

**When using a "wake up and check" pattern, always check the reason for wakeup before treating it as an error.** This applies to any code that uses `poll()`, `select()`, condition variables, or event loops with a shutdown flag. The flag and the wakeup mechanism are separate — the handler must check both.

In GStreamer specifically: if your element has a background thread that calls `gst_poll_wait()`, always check for the flushing/stop condition before posting errors. `EBUSY` from `gst_poll_wait()` is not an error — it's a designed shutdown mechanism.

## Bug 2: The Hang (Wrong Pointer + Use-After-Free)

**Issue:** [#4346](https://gitlab.freedesktop.org/gstreamer/gstreamer/-/issues/4346)
**Original MR:** [!8766](https://gitlab.freedesktop.org/gstreamer/gstreamer/-/merge_requests/8766) (by @thunderspoonextreme)

### Symptom

`shmsink` hangs indefinitely when shared memory fills up. If the consumer (`shmsrc`) doesn't pull data fast enough, the producer blocks forever and never recovers — even after the consumer starts reading again.

### Root Cause

Two bugs in the same function — `sp_client_recv_finish()` in `shmpipe.c`:

```c
int sp_client_recv_finish (ShmPipe *self, char *buf)
{
    ShmArea *shm_area = NULL;

    // Find which shm_area contains this buffer
    for (shm_area = self->shm_area; shm_area; shm_area = shm_area->next) {
        if (buf >= shm_area->shm_area_buf &&
            buf < shm_area->shm_area_buf + shm_area->shm_area_len)
            break;
    }

    offset = buf - shm_area->shm_area_buf;

    sp_shm_area_dec (self, shm_area);      // BUG 2: may free shm_area!

    cb.payload.ack_buffer.offset = offset;
    return send_command (self->main_socket, &cb, COMMAND_ACK_BUFFER,
        self->shm_area->id);               // BUG 1: wrong pointer!
}
```

**Bug 1: Wrong pointer.** The loop finds the correct `shm_area` for the buffer, but line 767 uses `self->shm_area->id` — the HEAD of the linked list, not the area we found. When there are multiple shm areas (which happens when the pool grows), the ACK goes to the wrong area. The producer thinks the wrong area's buffer was freed, the actual area's buffer is never freed, and the producer blocks waiting for space that will never be reclaimed.

**Bug 2: Use-after-free.** `sp_shm_area_dec()` decrements the use count and frees the area if it drops to zero. But `send_command` on the next line reads `shm_area->id` — from memory that may have just been freed.

### Fix

Save the area ID before decrementing, and use the correct variable:

```c
int shm_area_id = shm_area->id;    // Save before potential free

sp_shm_area_dec (self, shm_area);   // May free shm_area

return send_command (self->main_socket, &cb, COMMAND_ACK_BUFFER,
    shm_area_id);                    // Use saved id, not self->shm_area->id
```

There's also a third part: removing the fallback in `gstshmsink.c` that allocates system memory when shm is full. This fallback means the buffer isn't actually in shared memory, which breaks the protocol — the consumer expects to find the data in the shared region.

### How I Found It

The original contributor (@thunderspoonextreme) found the wrong-pointer bug by implementing a clean-room version of the shm protocol and noticing the ACK went to the wrong area. I reproduced the hang (`videotestsrc ! shmsink shm-size=22500 sync=true`, no consumer, wait 4 seconds — producer blocks), then verified the fix resolves it.

### General Lesson

**After calling a function that may free a resource, never access that resource again.** This is a classic use-after-free pattern. The fix is always the same: save any values you need before the call that may free.

**Use the variable you computed, not a "convenient" alternative.** The code found the right `shm_area` via a loop, then ignored it and used `self->shm_area` (the list head) because it was shorter to type. In linked list code, the head is almost never the node you want.

## Bug 3: The Flaky Test

**Issue:** [#790](https://gitlab.freedesktop.org/gstreamer/gstreamer/-/issues/790)
**MR:** [!11126](https://gitlab.freedesktop.org/gstreamer/gstreamer/-/merge_requests/11126)

### Symptom

The `test_shm_live` test intermittently times out in CI. Sometimes it passes, sometimes it hangs for 20+ seconds until the test framework kills it.

### Root Cause

Two problems in the test itself:

**Problem 1: Shutdown ordering.** The test stops the producer before the consumer:

```c
gst_element_set_state (producer, GST_STATE_NULL);  // blocks if shm full!
gst_element_set_state (consumer, GST_STATE_NULL);
```

If shm is full when the producer tries to stop, the poll thread blocks waiting for buffers to be freed. But the consumer hasn't been stopped yet — and the consumer is the only thing that can free the buffers by sending ACKs. Deadlock.

**Problem 2: Unbounded wait.** The test waits for the consumer to preroll with no timeout:

```c
gst_element_get_state (consumer, NULL, NULL, GST_CLOCK_TIME_NONE);
```

`GST_CLOCK_TIME_NONE` means "wait forever." If the producer fills shm and blocks before the consumer connects, the consumer has nothing to preroll with. Neither side can make progress.

### Fix

```c
// Bounded timeout instead of infinite wait
state_res = gst_element_get_state (consumer, NULL, NULL, 5 * GST_SECOND);

// Stop consumer first so it releases shm buffers
state_res = gst_element_set_state (consumer, GST_STATE_NULL);
state_res = gst_element_set_state (producer, GST_STATE_NULL);
```

### How I Found It

The timeout report said line 219 — which is `gst_element_set_state(producer, GST_STATE_NULL)`. The producer blocks during shutdown. Combined with knowledge of Bug 2 (shm can fill up and block the poll thread), the shutdown ordering issue was obvious.

### General Lesson

**In tests that involve producer/consumer pairs, always stop the consumer first.** The consumer holds references to shared resources. If the producer tries to shut down while those resources are held, it may block waiting for them to be released.

**Never use infinite timeouts in tests.** `GST_CLOCK_TIME_NONE`, `INFINITE`, `-1` — these turn intermittent bugs into permanent CI hangs. Always use a bounded timeout, even if it's generous (5-10 seconds). A test that fails with "timeout" is better than a test that hangs the CI runner for 10 minutes.

## Bug 4: The Page Alignment Mismatch

**Issue:** [#4406](https://gitlab.freedesktop.org/gstreamer/gstreamer/-/issues/4406)
**MR:** [!11118](https://gitlab.freedesktop.org/gstreamer/gstreamer/-/merge_requests/11118)

### Symptom

`GstShmAllocator` reports a `maxsize` smaller than the actual usable memory region. For a 100-byte allocation, `maxsize` is 107 but the OS actually mapped 4096 bytes (one page).

### Root Cause

When you call `memfd_create()` + `ftruncate(fd, 107)` + `mmap()`, the OS rounds up to the page boundary. The mapped region is 4096 bytes, not 107. But `GstMemory.maxsize` is set to 107, so GStreamer thinks only 107 bytes are usable.

```c
gsize maxsize = size + params->prefix + params->padding;
// maxsize = 100 + 0 + 0 = 100
gsize align = params->align;
align |= gst_memory_alignment;
// align = 0 | 7 = 7
maxsize += align;
// maxsize = 107

ftruncate (fd, maxsize);    // OS rounds to 4096
// But GstMemory.maxsize = 107
```

### Fix

Round `maxsize` up to the page size so it reflects reality:

```c
gsize page_size = sysconf (_SC_PAGESIZE);
maxsize = GST_ROUND_UP_N (maxsize, page_size);
```

### How I Found It

The issue description pointed directly to the problem. Verification was a test program that allocates shm at various sizes and compares `mem->maxsize` to the page ceiling:

```
BEFORE:
  size=100   maxsize=107    page_ceil=4096   WASTED 3989 bytes
  size=5000  maxsize=5007   page_ceil=8192   WASTED 3185 bytes

AFTER:
  size=100   maxsize=4096   page_ceil=4096   OK
  size=5000  maxsize=8192   page_ceil=8192   OK
```

### General Lesson

**When wrapping OS resources in a higher-level API, make sure the metadata matches what the OS actually provides.** The OS allocated a full page; the API said only 107 bytes were available. This mismatch means users can't use memory they've already paid for.

This pattern applies beyond shared memory: GPU buffer allocation (actual stride vs reported stride), DMA-buf sizes, mmap regions — anywhere the kernel rounds up but your metadata doesn't.

## What These Bugs Have in Common

### 1. They're all at boundaries

Every bug is at the boundary between two systems:
- Bug 1: between the shutdown mechanism and the error handler
- Bug 2: between the linked list manager and the command sender
- Bug 3: between the producer lifecycle and the consumer lifecycle
- Bug 4: between the OS memory allocator and the GStreamer memory abstraction

Most bugs live at interfaces. The code inside each component is usually fine — it's the handoff between components that fails.

### 2. They're all about contracts

Each bug is a violation of an implicit contract:
- "If the poll returns an error, something went wrong" (actually, EBUSY means shutdown)
- "`self->shm_area->id` is the area we're working with" (actually, it's the list head)
- "Stopping the producer first is fine" (actually, the consumer holds resources)
- "`maxsize` bytes are available" (actually, the OS gave us more)

The contracts were never written down. They existed in the head of the original author and were violated by someone who didn't know them.

### 3. They're all invisible in unit tests

None of these bugs would be caught by a test that exercises the happy path. They require:
- A specific shutdown timing (Bug 1)
- Multiple shm areas — which only happens under memory pressure (Bug 2)
- A race between producer filling shm and consumer connecting (Bug 3)
- Comparing reported size against actual mapped size (Bug 4)

Happy-path tests are necessary but not sufficient. You also need:
- Shutdown tests (does it exit cleanly?)
- Stress tests (does it work under load?)
- Resource exhaustion tests (what happens when memory/fd/buffers run out?)
- Contract tests (does the metadata match reality?)

## How to Find These Bugs

### Read the error messages literally

Bug 1 gave us `errno: 16`. I looked up what errno 16 means (`EBUSY`), then searched the codebase for what returns `EBUSY`. The bug was three `grep` commands away from the symptom.

### Trace the resource lifecycle

Bug 2 involves a linked list of shm areas. I traced: who creates areas, who frees them, who reads their IDs, and in what order. The use-after-free was visible from the ordering: free first, read second.

### Reproduce before fixing

For every bug, I wrote a minimal reproduction case before writing the fix. For the hang: `videotestsrc ! shmsink shm-size=22500 sync=true` with no consumer. For the exit code: any `shmsink` pipeline. For the page alignment: a test program that compares `maxsize` to `sysconf(_SC_PAGESIZE)`.

If you can't reproduce it, you can't prove the fix works.

### Use sanitizers — but know their limits

AddressSanitizer caught nothing on Bug 1 (logic error, not memory error). ThreadSanitizer flagged the data race on `self->stop` in Bug 1, confirming the race exists. Neither sanitizer would catch Bug 4 (the page alignment mismatch is semantically wrong but not a memory error).

Sanitizers are powerful for memory bugs (Bug 2's use-after-free) but useless for logic bugs and contract violations. You still need to read the code and think.

## How to Avoid These Bugs in GStreamer Elements

1. **If your element has a background thread, handle flushing as a first-class shutdown path.** Check `self->stop` or `gst_pad_is_flushing()` before treating poll/wait errors as fatal.

2. **In linked list code, never use the list head when you mean a specific node.** Name your variables clearly: `found_area` vs `self->shm_area`.

3. **Save values before calling functions that may free the containing struct.** If `dec()` might free the object, read everything you need from it first.

4. **In tests, stop consumers before producers.** Consumers hold references to shared resources. Stopping the producer first can deadlock if those resources need to be released for shutdown to proceed.

5. **Never use infinite timeouts in tests.** Use `5 * GST_SECOND` or similar. A bounded timeout turns a hang into a clear failure.

6. **When wrapping OS resources, verify that your metadata matches what the OS actually provides.** Allocate, then measure. Don't assume.

## Links

- [!11109 — shmsink exit code fix](https://gitlab.freedesktop.org/gstreamer/gstreamer/-/merge_requests/11109)
- [!11118 — ShmAllocator page size](https://gitlab.freedesktop.org/gstreamer/gstreamer/-/merge_requests/11118)
- [!11126 — flaky test fix](https://gitlab.freedesktop.org/gstreamer/gstreamer/-/merge_requests/11126)
- [!8766 — shmsink hang fix](https://gitlab.freedesktop.org/gstreamer/gstreamer/-/merge_requests/8766) (original analysis by @thunderspoonextreme)
- [gst-nvmm-cpp](https://github.com/PavelGuzenfeld/gst-nvmm-cpp) — our GStreamer plugin for Jetson zero-copy video, where we first encountered many of these patterns
