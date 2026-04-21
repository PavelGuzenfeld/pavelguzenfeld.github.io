---
title: "Building a Template-Matching Tracker on an STM32H750: What Worked, What Didn't"
date: 2026-04-21
draft: false
tags: ["ARM", "C", "C++", "embedded", "debugging", "hardware-testing", "Docker", "Linux", "performance"]
keywords: ["STM32H750 camera tracker", "OV7725 DCMI STM32", "USB CDC STM32H7 tutorial", "template matching tracker embedded", "SAD pyramid tracker Cortex-M7"]
cover:
  image: /images/posts/stm32h7-tracker.png
  alt: "Building a Template-Matching Tracker on an STM32H750"
categories: ["deep-dive"]
summary: "A long, honest retrospective on turning a WeAct STM32H750 board, a cheap OV7725 IR camera, and an Xbox controller into a live template-matching tracker. Every dead end, every wrong assumption, every fix — and what I'd do differently next time."
ShowToc: true
---

## Solution architecture

End-to-end, the system looks like this:

```
┌──────────────────────────── STM32H750 ────────────────────────────┐
│                                                                   │
│   ┌────────┐   DCMI     ┌─────────────┐       ┌───────────────┐   │
│   │ OV7725 │ ────────▶  │ framebuffer │ ────▶ │   SAD tracker │   │
│   │  (DVP) │   12 MHz   │ 160×120     │       │ 2-level pyramid│   │
│   │ SCCB   │ ◀────── XCLK (MCO1)      │       │  α-β filter   │   │
│   └────────┘            │ AXI SRAM    │       │  flood-fill   │   │
│                         └─────┬───────┘       │  segmentation │   │
│                               │               └────────┬──────┘   │
│                        SPI4 (ST7735)                   │          │
│                               │                        │ BB       │
│                               ▼                        ▼          │
│                        ┌─────────────┐         ┌────────────────┐ │
│                        │ 0.96" LCD   │         │ USB CDC device │ │
│                        │ preview+BB  │         │ /dev/ttyACM0   │ │
│                        └─────────────┘         └───────┬────────┘ │
└───────────────────────────────────────────────────────┼──────────┘
                                                        │
                                                  USB-C │
                                                        ▼
                           ┌────────────────── PC host ─────────────────┐
                           │ pygame + pyserial + Xbox controller        │
                           │  · live RGB565 preview, BB overlay         │
                           │  · left stick → crosshair (XY=)            │
                           │  · A/B → lock/unlock (L/U)                 │
                           │  · right stick → SEG / RS                  │
                           │  · DPad → match tolerance (TOL)            │
                           │  · triggers → velocity clamp (VC)          │
                           └────────────────────────────────────────────┘
```

Two data paths run concurrently over the single USB-C cable:

- **Uplink (board → PC), text**: one `BB,L=…,x=…,y=…,w=…,h=…,fps=…\r\n`
  line per frame. Small, human-readable, parseable with one line of Python.
- **Uplink (board → PC), binary**: every Nth frame a packet framed by
  `FR\r\nSZ=<bytes>\r\n<raw pixels>\r\nEF\r\n` carries the visible 160×80
  RGB565 strip. Host switches into binary mode on `FR`, reads exactly
  `SZ` bytes, returns to line mode.
- **Downlink (PC → board), text**: short `KEY=VALUE\n` commands
  (`XY=85,40`, `TOL=3000`, `L`, `U`, `V=0`, `SEG=8`, `RS=10`…) the MCU
  parses in the main loop.

Everything runs on a single Cortex-M7 core at 240 MHz — no RTOS, no
threads, just an interrupt-driven DCMI/DMA/USB frontline feeding a
vanilla `while(1)` tracker loop. Total firmware ~94 KB.

## Starting point

The bench the day I decided to do this:

- WeAct MiniSTM32H7xx — STM32H750VBT6, 480 MHz Cortex-M7, 1 MB RAM, 128 KB
  internal flash plus 8 MB QSPI, onboard 0.96" ST7735 SPI LCD, 24-pin DVP
  camera FFC, USB-C, SD slot. $15 board.
- A generic 3 MP IR-sensitive camera module with 4 corner IR LEDs, plugged
  into the DVP FFC.
- Xbox controller, Linux host, Docker.

No external debugger, no USB-UART bridge, nothing else.

The idea was simple: the MCU runs the tracker, the PC hosts the joystick
and viewer. MCU sees → detects → emits bounding boxes. PC runs a small
Python app that reads the BB stream, displays the live camera feed, and
drives the tracker's tunables from the joystick. "Pan-tilt / fire" was on
the initial plan and got cut — no mechanics, no fire. The goal collapsed
to: **see, lock, follow, report**.

## Build infrastructure

Docker-first from day one. The whole toolchain lives in one Ubuntu 24.04
image with `gcc-arm-none-eabi`, `cmake`, `ninja`, `dfu-util`, `stlink-tools`.
Nothing is installed on the host except `docker` and `make`. This was
probably the single highest-ROI decision on the whole project, because
when I eventually broke things, I never had to wonder whether the
toolchain itself had drifted.

CMake + `FetchContent` pulls in CMSIS, ST's HAL, and the STM32 USB device
middleware. No submodules, no `git-lfs`, nothing cute. The moment something
CMake-related got hairy (after about 20 commits), I knew exactly where to
look. Lesson from prior projects: do not mix `FetchContent` with `ExternalProject`.
One or the other.

For flashing: USB DFU only. The board has no ST-Link header populated and
I wasn't going to solder one. The STM32 ROM bootloader on H750 supports
DFU over USB-C out of the box. Tap BOOT0 + RESET, `dfu-util` writes the
binary, board resets into firmware. A `make flash-dfu` target runs
`dfu-util` from inside the Docker container with `--privileged
-v /dev/bus/usb:/dev/bus/usb` so the host tool install is still zero.

## Phase 0 and 1 — blinky and clocks

Got Phase 0 done in an evening. Minimal register-level code: set MODER,
bang ODR, busy-wait. The first green blink was the only unambiguous
feedback I'd have for a long time, which turned out to be important.

Phase 1 was 480 MHz PLL + SysTick + USART1 "printf". This is where I made
my first big tactical mistake, which I'll get to shortly. The clock code
worked first try — HSE at 25 MHz, PLLM=5, PLLN=192, PLLP=2, flash latency
4, VOS0 + overdrive. Verifiable indirectly by the LED blink rate matching
the commanded SysTick period.

USART1 printf worked too, but I didn't have a USB-UART bridge. Every log
message I wrote went into the void. I told myself the board had a working
UART and I'd wire a bridge later. I did not wire a bridge. This mattered.

**What worked**: the Docker toolchain, CMake scaffold, DFU flash, the
plain blinky.

**What didn't**: trusting that I could debug without a serial console.

## Phase 2 — sensor bring-up from hell

This was the longest, stupidest phase. It took multiple iterations over
hours to confirm that a known-working camera sensor was reachable on I²C.

The sequence I went through:

1. **Hand-rolled SCCB driver** in C++. Wrote `hw::I2C` with `write`,
   `read`, `write_read` (repeated-start) methods using direct register
   banging. Probe function tried OV2640, OV5640, OV7670 chip-ID
   addresses. Got NACK on everything.
2. **MCLK discovery.** OV-series sensors won't respond on SCCB without a
   running XCLK. Generated 25 MHz on PA8 via MCO1 sourced from HSE. Still
   NACK.
3. **PWDN control.** WeAct silkscreen said `SB1: DVP_PWDN -> A7`. Drove
   PA7 low. Still NACK.
4. **Fixed a glitch on PWDN** — my `Pin` class's `configure_output()`
   called `set(false)` which for an active-low pin *drives HIGH*, then
   I'd call `set(true)` to go low. Brief HIGH pulse at boot latched the
   OV2640 into standby per the datasheet. Fixed to write ODR low *before*
   flipping MODER to output. Still NACK.
5. **MCLK frequency experiments**. Tried 25 MHz (HSE/1), 24 MHz (PLL1Q/10),
   24 MHz (HSI48/2), 12 MHz (HSI48/4), 12 MHz via TIM1 PWM. Still NACK.
6. **Pull-up configuration.** Toggled internal pull-ups on PB8/PB9 on and
   off. Still NACK.
7. **I²C timing tuning.** Hand-calculated TIMINGR, tried WeAct's verbatim
   `0x40805E8A` value, dropped SCL from 100 kHz to 50 kHz. Still NACK.
8. **Bus recovery sequence.** Manually toggled SCL 9 times to unstick any
   slave. Still NACK.
9. **Full HAL_I2C swap.** Tore out my hand-rolled register code, pulled
   in ST's `stm32h7xx_hal_i2c.c`, rewrote `hw::I2C` as a thin wrapper
   around `HAL_I2C_*`. Still NACK.

At this point I was many hours and a branch-full of commits in. I'd been
debugging with LED blink codes because I still had no serial bridge. The
user of this project — me — got fed up and told me so, in exactly as
many words. Which in hindsight was correct: **blink-count debugging is
an anti-pattern past about three possible states**.

Two things finally broke the deadlock:

### 1. Ground truth via the factory demo

Rather than keep guessing, I downloaded WeAct's own precompiled
`08-DCMI2LCD0_96.hex` — a camera-to-LCD demo they ship for this exact
board, converted it to `.bin`, flashed it. The onboard LCD immediately
showed a live camera image with an FPS counter.

This was an important moment. It proved:

- The hardware works.
- The camera works.
- The FFC is seated correctly.
- The LCD works.
- Nothing is damaged.

Everything wrong was in my code. That eliminates about 80% of the
solution space.

### 2. The real bug: the startup vector table

With confirmation that nothing was broken, I kept diffing my code against
WeAct's `08-DCMI2LCD/Src/main.c` byte-for-byte. Eventually I tried using
ST's full `startup_stm32h750xx.s` from `cmsis_device_h7/Source/Templates/gcc/`
instead of my own minimal startup assembly.

My custom startup had only the 16 Cortex-M core exception vectors —
Reset, NMI, HardFault, …, SysTick. **Everything else was off the end of
the vector table.** The moment any peripheral IRQ fired (I²C, DCMI, DMA,
USB, you name it), the CPU jumped to whatever happened to be in flash
past the vector table. That is almost always an invalid instruction,
which triggers a HardFault, which on my startup jumped back to the
InfiniteLoop default handler.

This manifested as "HAL_I2C_Start_DMA hangs". It wasn't hanging; it was
returning instantly and then the first DMA complete IRQ was crashing the
CPU into a hardfault spin.

I have done embedded work for years and still got bitten by this. The
standard ST startup file has the full ~150-entry vector table with weak
aliases to Default_Handler for every peripheral, which is exactly what
you want by default. Rolling my own to save a few hundred lines was an
unforced error.

## Pivoting to C

After the vector table fix, sensor probe still failed in a couple more
small ways (DMA buffer in DTCM instead of AXI SRAM; WeAct's `camera.c`
had an `#include "lcd.h"` nested inside a function body that broke the
host-side build tools). Each one was quick to find because the symptoms
were now specific, not generic.

At some point I made a bigger decision: abandon C++ and start fresh in C,
on top of WeAct's actual source tree. My C++ abstractions were clean in
isolation — `hw::Pin`, `hw::I2C`, `hw::Camera` — but they were adding
*nothing* that C wasn't already giving me through HAL, and they were
making every "match WeAct exactly" diff harder to read.

I wiped `src/*.cpp` and `include/hw/*.hpp`, copied WeAct's `gpio.c`,
`spi.c`, `i2c.c`, `tim.c`, `dma.c`, `dcmi.c`, `stm32h7xx_it.c`,
`stm32h7xx_hal_msp.c`, and their ST7735 BSP and camera BSP wholesale
into `lib/weact_*`. Wrote a single C `main.c` that mirrored their
`MPU_Config` + `SystemClock_Config` + `MX_*_Init` sequence verbatim,
plus my probe / tracker logic on top.

**The camera was detected on the next flash.** `OV7725 id=7721` on the
LCD. Not OV2640 — OV7725, which shares the same SCCB address but different
ID bytes. Probing OV7670 first and matching `0x7721` to OV7725 is a
one-liner in the probe.

The core lesson of this phase: **when fighting a vendor's ecosystem,
match their conventions first and innovate later**. If WeAct's CubeMX
output compiles and runs, get to that baseline in your own build system
before deviating. Don't rewrite their init code "more elegantly" until
it boots.

**What worked better this time**: pure C on WeAct's scaffold.
**What worked worse the first time**: C++ abstractions on a hand-rolled
CMSIS base that was subtly broken in a place I couldn't see.

## Phase 3 — DCMI + LCD display

Trivial after the pivot. WeAct's `Camera_Init_Device` auto-probes OV7670 /
OV2640 / OV7725 / OV5640 and calls the right `ov*_init`. DCMI in
continuous DMA mode writes into a `uint16_t pic[160][120]` buffer
(RGB565) in a special `.dma_buffer` linker section I added to AXI SRAM —
DMA1 can't reach DTCM on H7 because DTCM sits on the M7 core's TCM bus,
not on the AXI fabric.

The main loop checks a `DCMI_FrameIsReady` flag set from the DCMI ISR,
blits the middle 80 rows of the 160×120 frame to the 0.96" landscape
LCD, and updates an FPS counter. Steady ~23 FPS.

The board now showed a live camera preview. This was the first moment
where I stopped being blind and could see what the code was actually
seeing.

## Phase A — template matching tracker

Started simple: lock a target by pressing K1, track it, draw a red box.
Three versions, in order:

### Color matching
Sample the pixel under the crosshair at lock; each frame, find the
centroid of pixels within some Manhattan distance in RGB565 of the
sampled color. Bounding box = min/max of matched pixels.

Failed predictably. Anything in the scene with similar color pulled the
box to it. Move the camera away from the locked target and the box ends
up on a patch of wall with the same hue. Not surprising; colors aren't
objects.

### SAD template matching
At lock, snapshot a 16×16 grayscale patch (cheap luma = R5 + G6 + B5 from
RGB565). Each frame, search a ±20 pixel window around the last known
position for the position that minimizes sum-of-absolute-differences to
the stored template. Early-exit the inner SAD loop when the running sum
already exceeds the current best.

This worked much better. The box actually tracked specific objects. But
it had two failure modes:

- **Fast motion** — if the target moved more than ±20 px between frames,
  it escaped the search window and the next best SAD minimum was some
  unrelated patch. The box teleported.
- **Featureless scenes** — if the 16×16 patch under the crosshair
  happened to land on a uniform surface, every candidate position in the
  search window had similar SAD, and the argmin jittered randomly.

### SAD + velocity prediction + confidence gate
Added an EMA-smoothed velocity vector. Next-frame search window centred
on `cx + vx` rather than `cx` alone, so steady camera pans stayed inside
the window. Clamped frame-to-frame displacement to guard against false
matches teleporting the state.

Also added a confidence gate: track the second-best SAD during the
search; require the best to be distinctly better than the second-best
(best < 0.75 × second) to accept the new position. On ambiguous frames,
hold the previous position instead of flipping between similar patches.

**This made things worse in an interesting way.** The 0.75 threshold was
too strict. On real targets the SAD surface often has two or three
similar-scoring candidates per frame from sensor noise and sub-pixel
aliasing. The gate fired almost every frame. The box got "stuck" and
refused to follow actual target motion.

Backed the threshold out to 0.9 (only reject genuinely ambiguous frames
where best and second are nearly equal), and that worked. The lesson:
**gating is a safety net, not a primary filter**. Tune it so it fires
rarely; if it's firing often, your primary estimator is the problem.

### Segmentation-at-lock

The remaining weakness: the BB was a fixed 16×16 regardless of actual
target size. I added a 4-connected BFS flood fill at lock time: from the
aim point, accept neighbour pixels whose luma is within `SEG_TOL` of the
seed pixel. If the resulting component size is between 30 and 1800
pixels, use its centroid as the lock point and its axis-aligned bounding
box as the drawn BB size. Static 1600-byte visited bitmap and 4 KB BFS
queue, all in `.bss`.

This was a big qualitative jump in lock quality. The box now wraps the
actual object outline at lock, and the SAD template is captured at the
object's centroid (where texture is usually strongest) rather than
wherever the user happened to aim. Plus periodic re-segmentation every
~10 frames lets the BB resize as the object grows or shrinks in frame.

### Pyramid search

To handle faster motion without making the fine SAD pass impossibly
slow, I added a 2-level pyramid:

- Build a half-res luma image (80×40) each frame by 2×2 averaging.
- Build a half-res template (8×8) at lock time.
- Coarse pass: search ±25 pixels in half-res = effective ±50 pixels in
  full res.
- Fine pass: ±4 pixels in full res, centred on `2 × coarse_best`.

Total ops per frame: ~186k vs. ~246k at ±20 single-level. Faster AND 2.5×
the effective search radius.

### Alpha-beta filter

Finally, replaced the separate position and velocity EMAs with a proper
α-β state update:

    innovation = measurement - prediction        (prediction = cx + vx)
    cx += α × innovation                         (α = 1/2)
    vx += β × innovation                         (β = 1/4)

Using the prediction as the baseline makes the tracker lag-free on steady
motion, which the previous `cx = (cx + best_cx) / 2` pattern was not —
that averaged against the *previous* position, so a target moving at
constant velocity always looked "behind" by half its velocity.

This is half of a Kalman filter (the other half being a proper
covariance update, which you don't really need for a 2-state toy
tracker).

## What I tried and backed out

Not every idea was a keeper.

### Template appearance update (backed out)
After each confident match, blend 1/32 of the current matched patch into
the stored template. In theory, handles slow appearance changes (lighting,
small rotation). In practice, combined with the confidence gate and
position EMA, made the tracker too sticky — it would "adapt" to whatever
false match got accepted, and then never recover. Reverted to a static
template captured at lock.

Could be re-enabled with a much tighter gate on which matches are allowed
to update, but at that point the complexity starts dwarfing the benefit.

### Internal pull-ups on I²C (twice, in both directions)
I enabled them, then disabled them ("NOPULL" — WeAct uses NOPULL in one
demo), then re-enabled them because WeAct uses PULLUP in the *actually-
working* demo. The first research pass looked at the wrong reference.
Lesson: read the reference you're going to copy, not a different reference
for the same board.

### Hand-rolled startup.s
The root cause of Phase 2's agony. Only keep your own startup if you have
a specific reason (dual-core, custom memory layout, specific vector table
edits). Otherwise use the CMSIS template. I knew this and did it anyway.

### USB_OTG_HS (wrong peripheral)
H7 has two USB controllers: `USB1_OTG_HS` (can do HS with ULPI PHY) and
`USB2_OTG_FS` (FS-only). Both can appear on PA11/PA12 AF10. I picked HS
first because "bigger is better." Enumeration never happened. WeAct's
reference uses FS. Switched, it worked. Lesson: peripheral selection on
H7 is non-obvious; diff against the known-working reference.

## Phase B — USB CDC + Python host

Once Phase 3's camera pipeline stabilised, USB CDC went in as the second
major subsystem. I made the same mistakes I'd made with the sensor — wrong
peripheral, wrong clock path — but this time the diagnostic loop was
fast because I had the LCD up and running as a text display.

Real logs on the LCD are not as good as real logs over USB, but they are
infinitely better than blink counting. Debug breakthroughs on this project
followed a consistent pattern: a step up in diagnostic bandwidth (LED →
LCD → USB CDC) lined up with a step up in progress.

The CDC stack is ST's Middlewares/ST/STM32_USB_Device_Library. ~500 lines
of app-side glue (`usbd_conf.c`, `usbd_desc.c`, `usbd_cdc_if.c`,
`usb_device.c`) and the board enumerates as `/dev/ttyACM0` with VID
`0x1209` PID `0x0001` (pid.codes test range).

The board-side protocol is deliberately simple:

    BB,L=<0|1>,x=<cx>,y=<cy>,w=<w>,h=<h>,fps=<n>\r\n     one per frame
    FR\r\nSZ=<bytes>\r\n<raw RGB565 pixels>\r\nEF\r\n     binary frame

Host parses line-oriented, switches to binary mode when it sees `FR`,
reads exactly `SZ` bytes, returns to line mode on `EF`. The same CDC pipe
carries text BB updates and binary video frames.

Host side is a pygame + pyserial script. Xbox controller on the PC
drives a crosshair on the MCU's aim point (`XY=<x>,<y>\n`), A/B buttons
lock/unlock, right stick tunes segmentation tolerance and re-seg
interval, triggers adjust velocity clamp, DPad adjusts match tolerance.
A pygame window shows the decoded RGB565 stream scaled 4×, with the BB
overlaid in red.

One bug from this phase worth calling out: I sent the XY command as a
Python tuple, `maybe_send("XY", (int(ax), int(ay)))`, and the `send()`
function f-stringed the value, which rendered as `XY=(85, 40)` —
parentheses and a space in the middle. The MCU's `strtol` on `"(85, 40)"`
gives 0, silently, because there are no matching integer chars before the
parens. The crosshair on the LCD never moved. Took an hour to find. The
fix was a one-line change: format the tuple as `"x,y"` before passing it.

The generic takeaway: **silent parse failures on binary-ish protocols
are ruinous**. The MCU should have logged "parse error at char 0" but
didn't. If I were doing this again I'd add a minimal `OK` / `ERR`
response to every command so the host side can't silently drop stuff.

## What worked

- **Docker-first toolchain.** Never had a "works on my machine" moment.
- **Matching a working vendor demo before adding anything.** When you
  don't know if it's you or the chip, the question isn't "is my code
  right" but "can the known-good binary produce the behaviour I expect".
- **Using the LCD as a console.** A 160×80 4-line display is enough for
  debug output and removed an entire class of can't-see-what-happened
  failures.
- **SAD template matching + pyramid + segmentation + α-β.** Each layer
  earns its place. Leaving any one out degrades the tracker noticeably;
  none of them alone is sufficient.
- **Forcing the host protocol to be ASCII for control and binary only
  where bandwidth demands it.** Makes the protocol inspectable with
  `picocom` and `echo` when things go wrong.
- **Pivoting from C++ to C.** Halved the code, removed every "extern C"
  headache, made the diff against vendor reference code trivial.
- **Using an actual joystick instead of keyboard for tuning.** Analog
  inputs and immediate visual feedback let you tune a tracker 10× faster
  than with text commands.

## What didn't work

- **Custom startup.s with only core exceptions.** Caused silent hardfaults
  on peripheral IRQs that masqueraded as random hangs for hours.
- **Aggressive blink-code debugging.** Past "is it alive" and "did it
  crash at step N" there's nothing useful it can convey.
- **The first confidence gate at 0.75.** Too strict; the tracker locked
  up. Had to relax to 0.9.
- **Template appearance update at the same time as confidence gating.**
  Two filters compounding each other's mistakes produced a tracker that
  could accept nothing and move nowhere.
- **Picking USB_OTG_HS on H7.** Plausible reasons existed; wrong
  peripheral. Bright red WeAct main.c's `MX_USB_OTG_FS_PCD_Init` was
  telling me the answer in plain text.
- **Assuming internal pull-ups were fine when external ones were
  expected.** Worked OK electrically but `GPIO_NOPULL`-vs-`GPIO_PULLUP`
  flips changed reliability under fast camera panning. The "working"
  config is the one the vendor ships.
- **Relying on a USB-UART bridge that didn't exist.** Should have wired
  the LCD console as soon as Phase 1 ran. I burned most of a day because
  of this.

## What got worse at some point

- **Tracker after the 0.75 confidence gate** — strictly worse than
  without any gate. Tracker stopped following real motion to avoid
  imaginary ambiguity.
- **Framebuffer access from USB streaming** — the blocking chunked
  `cdc_send` for frame packets ties up the CPU for ~40 ms per transmitted
  frame. Streaming at every-4th-frame interval brings effective FPS down
  from 23 to about 18. Worth it for the diagnostic channel, but a proper
  DMA-driven CDC TX path would reclaim that back.

## What got better in revisions

- **Tracker** — color → SAD → SAD+pyramid → SAD+pyramid+segmentation+α-β.
  Each step was a clear, reproducible improvement I could feel in seconds
  with the joystick.
- **Diagnostics** — LED → LED blink codes → LCD text → USB CDC → USB CDC
  + live video + joystick tuning. Each level was 3-10× faster to iterate
  on than the previous one.
- **Clock config** — my first PLL setup (480 MHz + VOS0 + 4-WS flash)
  was valid but over-ambitious. WeAct's demo uses 240 MHz sysclk + VOS0
  + 1-WS flash. The slower CPU clock is *plenty* for this workload and
  costs less power. Sometimes less is more.
- **Template size choice** — 16×16 grayscale bytes = 256 bytes template,
  256-byte SAD inner loop. Small enough to be fast, large enough to be
  distinctive. Tried bigger templates; not worth the ops budget.

## What I'd do differently next time

1. **LCD console first**, before any other peripheral beyond SysTick. A
   160×80 mono text console on the board is 200 lines of code and turns
   a half-day sensor-probe debug into a 10-minute one.
2. **CMSIS startup file, always.** Don't roll your own unless there is a
   concrete reason. The saved bytes aren't worth the silent IRQ hardfaults.
3. **Flash the vendor's working binary on day zero.** Before writing any
   of your own code, flash the factory demo. Confirm hardware is sane.
   If the vendor demo works, all later confusion is code. If it doesn't,
   don't waste your time fighting ghosts until you figure out why.
4. **Start in C on the vendor scaffold.** Only move to C++ for specific
   abstractions that pull weight — typed peripheral IDs, `constexpr`
   register values. Not namespaces-for-namespaces'-sake.
5. **Set up the USB-side host tooling early.** Having pygame + pyserial
   + a joystick in the loop makes tuning anything — not just tracking —
   a completely different experience.

## Current state

The tracker as committed: OV7725 → DCMI → 160×120 RGB565 in AXI SRAM →
ST7735 LCD display with FPS overlay → joystick-driven crosshair for
aim → K1/A force-lock with flood-fill segmentation at lock → template-
match tracking with pyramid search + α-β filter + periodic re-
segmentation → USB CDC stream of BB status + binary video frames →
Python + pygame tuner with live preview, BB overlay, joystick-driven
tunables.

~94 KB firmware. Hits ~20 FPS when streaming video, ~25 FPS BB-only.
Tracks pretty well on textured targets, loses lock cleanly on
occlusions, re-acquires when the target re-enters the search window.
Still not magical on low-texture targets (uniform-colored balls under
uniform light are hard); that's what a KCF or MOSSE correlation
tracker would help with, eventually.

## Notes on cost of abstraction

C++ didn't cost me cycles. It cost me *reading time*. Every time I
diffed my code against WeAct's reference, I had to mentally translate
namespaces, classes, and `constexpr` back to the C they were derived
from. On a project where the primary debugging tool is "is my init
identical to the known-working vendor init", that translation tax is
enormous.

If I'd been writing a self-contained library in isolation, the C++
wrappers would have paid for themselves. In a project where the critical
path is diffing against a vendor's C, they were a liability.

## Takeaways

1. **The factory binary is ground truth.** Use it.
2. **The CMSIS startup file is not optional.** Use it.
3. **Diagnostic bandwidth is the single biggest lever on debug speed.**
   Invest in it early.
4. **Match the vendor's conventions before you improve on them.**
5. **Simple filters + good measurements beat clever filters + bad
   measurements.** Every time.
6. **Analog joystick input for tuning analog parameters.** This is the
   single nicest dev tool on the project and I wish I'd built it on day
   one instead of day ten.

And one final one:

7. **Listen when the future user of your project tells you to stop
   screwing around with blink codes.** They're right.
