---
title: 'ASan on a GStreamer Plugin When the Host Binary Has No ASan'
date: 2026-10-20
draft: true
tags:
- ASan
- GStreamer
- debugging
- GCC
- C
- ROS2
- Linux
keywords:
- AddressSanitizer GStreamer plugin
- ASan runtime does not come first in initial library list
- LD_PRELOAD libasan gst-launch
- gcc -print-file-name=libasan.so
- ASan dlopen shared library
- GST_PLUGIN_PATH sanitizer
- colcon AddressSanitizer CMAKE_CXX_FLAGS
- clang shared-libasan libclang_rt.asan
categories:
- deep-dive
summary: You built your GStreamer plugin with -fsanitize=address and gst-launch-1.0
  says the element doesn't exist. The runtime has to be in the process before
  anything else. One LD_PRELOAD fixes it, and one repeated -D flag quietly turns
  ASan off in colcon builds.
ShowToc: true
---

I keep doing this. I build a plugin with `-fsanitize=address`, run it under the stock `gst-launch-1.0`, and get this:

```
==4532==ASan runtime does not come first in initial library list; you should either link runtime to your application or manually preload it with LD_PRELOAD.
==4533==ASan runtime does not come first in initial library list; you should either link runtime to your application or manually preload it with LD_PRELOAD.
WARNING: erroneous pipeline: no element "myfilter"
```

Two PIDs, because the plugin scanner (`gst-plugin-scanner`) is its own process, and it dies too. So GStreamer never registers the element and you get "no element". Nothing about memory bugs yet.

Everything below was run in an `ubuntu:24.04` container: GCC 13.3.0, clang 18.1.3, GStreamer 1.24.2, CMake 3.28.3.

## The bug I planted

A tiny element with a chain function that reads one byte past a 16-byte heap block:

```c
static GstFlowReturn my_filter_chain(GstPad *pad, GstObject *parent, GstBuffer *buf) {
  MyFilter *self = MY_FILTER(parent);
  GstMapInfo map;
  gst_buffer_map(buf, &map, GST_MAP_READ);
  guint8 *header = malloc(16);
  memcpy(header, map.data, 16);
  for (int i = 0; i <= 16; ++i)
    self->checksum += header[i];
  gst_buffer_unmap(buf, &map);
  free(header);
  return gst_pad_push(self->srcpad, buf);
}
```

The `checksum` field matters. My first version just did `memcpy(header, map.data, 17)` and freed it. At `-O1` GCC threw the whole malloc/memcpy/free away as dead code and ASan had nothing to report. A planted bug has to feed something the compiler can't drop.

Build:

```bash
gcc -shared -fPIC -g -O1 -fsanitize=address -fno-omit-frame-pointer \
    myfilter.c -o plugins/libmyfilter.so $(pkg-config --cflags --libs gstreamer-1.0)
```

`ldd` shows the plugin now needs `libasan.so.8`. The host doesn't.

## Why the order matters

ASan replaces `malloc`, `free`, `memcpy`, `pthread_create` and friends. Those interceptors only work if the runtime is loaded before libc's versions get bound. A binary built with ASan gets that for free, since the runtime is linked first. A plugin loaded by `dlopen()` arrives far too late:

```
without LD_PRELOAD                         with LD_PRELOAD
------------------                         ---------------
gst-launch-1.0  (no ASan)                  gst-launch-1.0  (no ASan)
 |- libasan.so        <- missing            |- libasan.so   <- preloaded, first
 |- libc.so.6  malloc/free already bound    |- libc.so.6    interceptors win
 |- libgstreamer-1.0.so                     |- libgstreamer-1.0.so
 |   ...                                    |   ...
 `- dlopen(libmyfilter.so)                  `- dlopen(libmyfilter.so)
      needs libasan.so.8                         needs libasan.so.8 -> already there
      -> ASan checks the init order,
         finds it is not first, aborts
```

## The fix

Preload the exact runtime your compiler linked against. Don't guess the path, ask GCC:

```bash
$ gcc -print-file-name=libasan.so
/usr/lib/gcc/x86_64-linux-gnu/13/libasan.so

GST_PLUGIN_PATH=$PWD/plugins \
LD_PRELOAD=$(gcc -print-file-name=libasan.so) \
gst-launch-1.0 videotestsrc num-buffers=1 ! myfilter ! fakesink
```

`LD_PRELOAD` is inherited, so the plugin scanner subprocess gets it too. Now the real bug shows up (trimmed):

```
==4536==ERROR: AddressSanitizer: heap-buffer-overflow on address 0x502000020cc0 ...
READ of size 1 at 0x502000020cc0 thread T2 (videotestsrc0:s)
    #0 0x700537b4385d in my_filter_chain /work/myfilter.c:27
    #1 0x70053893b8eb  (/lib/x86_64-linux-gnu/libgstreamer-1.0.so.0+0x968eb)
    #2 0x70053893ed95  (/lib/x86_64-linux-gnu/libgstreamer-1.0.so.0+0x99d95)
    #3 0x70053893f3e3 in gst_pad_push (/lib/x86_64-linux-gnu/libgstreamer-1.0.so.0+0x9a3e3)

0x502000020cc0 is located 0 bytes after 16-byte region [0x502000020cb0,0x502000020cc0)
allocated by thread T2 (videotestsrc0:s) here:
    #0 0x700538afa9c7 in malloc ../../../../src/libsanitizer/asan/asan_malloc_linux.cpp:69
    #1 0x700537b4373c in my_filter_chain /work/myfilter.c:24
```

Line 27 is the `<= 16` loop, line 24 is the `malloc`. That's the whole point of the exercise.

One trap: if you ran the broken command first, GStreamer cached the failed plugin in its registry. Delete `~/.cache/gstreamer-1.0/registry.*.bin` or point `GST_REGISTRY` at a fresh file. Otherwise the preloaded run can still say "no element".

## Leak checking

My old notes always had `ASAN_OPTIONS=detect_leaks=0`, with the idea that GLib and the plugin registry would bury you in leaks you don't own. I checked that this time. On GStreamer 1.24 a clean pipeline (`videotestsrc ! myfilter ! fakesink`, also with `videoconvert`, also `gst-inspect-1.0`) exits with zero leak reports. To make sure LeakSanitizer was actually running, I removed the `free(header)` and got:

```
Direct leak of 480 byte(s) in 30 object(s) allocated from:
    #0 ... in malloc ../../../../src/libsanitizer/asan/asan_malloc_linux.cpp:69
    #1 ... in my_filter_chain /work/leak.c:24
SUMMARY: AddressSanitizer: 480 byte(s) leaked in 30 allocation(s).
```

30 buffers, 16 bytes each. So I keep leaks on now. I'd reach for `detect_leaks=0` only when the host is a big app that leaks on exit and the noise hides the report I care about.

The same notes had this:

```bash
export ASAN_OPTIONS=new_delete_type_mismatch=0
export ASAN_OPTIONS=halt_on_error=0
export ASAN_OPTIONS=verbosity=1
```

That's three assignments, so only the last one counts. Options go in one variable, separated by colons:

```bash
export ASAN_OPTIONS=detect_leaks=0:halt_on_error=0:verbosity=1
```

Also note that `halt_on_error=0` only does anything if the code was built with `-fsanitize-recover=address`.

## colcon / CMake: the flag that turns ASan off

This is the colcon line I had saved for a ROS 2 package:

```bash
colcon build --cmake-args -DCMAKE_BUILD_TYPE=RelWithDebInfo \
  -DCMAKE_EXE_LINKER_FLAGS="-lasan" \
  -DCMAKE_CXX_FLAGS="-fsanitize=address" \
  -DCMAKE_EXE_LINKER_FLAGS="-fsanitize=address" \
  -DCMAKE_CXX_FLAGS="-Wno-error=maybe-uninitialized"
```

Each `-D` sets a cache variable, and repeating one just overwrites it. Here's what CMake 3.28 actually ends up with:

```
-- CXX_FLAGS=[-Wno-error=maybe-uninitialized]
-- EXE_LINKER_FLAGS=[-fsanitize=address]
```

Nothing gets compiled with `-fsanitize=address`. The executables still link the runtime, so ASan starts and the intercepted calls (`memcpy`, `malloc`, `free`) are still checked. That is enough to make you think it works. Plain loads and stores in your own code are not instrumented, so an overflow like the `<= 16` loop above goes unreported. Put everything for one variable in one string:

```bash
colcon build --packages-select my_ros_pkg --cmake-args \
  -DCMAKE_BUILD_TYPE=RelWithDebInfo \
  -DCMAKE_CXX_FLAGS="-fsanitize=address -fno-omit-frame-pointer -Wno-error=maybe-uninitialized" \
  -DCMAKE_EXE_LINKER_FLAGS="-fsanitize=address" \
  -DCMAKE_SHARED_LINKER_FLAGS="-fsanitize=address"
```

`CMAKE_SHARED_LINKER_FLAGS` is what ROS 2 component libraries and plugins need. If the node runs inside a container process that wasn't built with ASan, you're back to the `LD_PRELOAD` case above. The `-lasan` is redundant once `-fsanitize=address` is on the link line.

## Clang is different

Clang doesn't use `libasan.so`. Its runtime is `libclang_rt.asan-<arch>.so`, and by default clang links it *statically* into executables. A `.so` built with plain `-fsanitize=address` has no `NEEDED` entry for any ASan runtime. It just has 17 undefined `__asan_*` symbols and expects the executable to provide them. To get a plugin that names its runtime, add `-shared-libasan`:

```bash
clang -shared -fPIC -g -O1 -fsanitize=address -shared-libasan -fno-omit-frame-pointer \
      myfilter.c -o cplug/libmyfilter.so $(pkg-config --cflags --libs gstreamer-1.0)

$ readelf -d cplug/libmyfilter.so | grep asan
 0x0000000000000001 (NEEDED)  Shared library: [libclang_rt.asan-x86_64.so]
```

That file isn't on the loader path, so preload it by full path, and ask clang where it lives:

```bash
LD_PRELOAD=$(clang -print-file-name=libclang_rt.asan-x86_64.so) \
GST_PLUGIN_PATH=$PWD/cplug \
gst-launch-1.0 videotestsrc num-buffers=1 ! myfilter ! fakesink
```

```
ERROR: AddressSanitizer: heap-buffer-overflow on address 0x50200001fcc0 ...
READ of size 1 at 0x50200001fcc0 thread T2 (videotestsrc0:s)
    #0 0x746576d08add in my_filter_chain /work/myfilter.c:27:23
```

Mixing them doesn't work. A clang-built plugin with the GCC runtime preloaded fails to load:

```
Failed to load plugin '/work/cplug/libmyfilter.so': libclang_rt.asan-x86_64.so: cannot open shared object file: No such file or directory
```

The two runtimes are not interchangeable anyway. Preload the runtime from the same compiler that built the plugin.

## Cheat sheet

```bash
# GCC-built plugin, stock host binary
LD_PRELOAD=$(gcc -print-file-name=libasan.so) \
GST_PLUGIN_PATH=/path/to/plugins \
GST_REGISTRY=/tmp/asan-registry.bin \
gst-launch-1.0 ...

# clang-built plugin (compiled with -shared-libasan)
LD_PRELOAD=$(clang -print-file-name=libclang_rt.asan-x86_64.so) ...

# multiple options: one variable, colon separated
ASAN_OPTIONS=detect_leaks=1:verbosity=1
```
