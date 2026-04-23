---
title: "Cleaning Up, Pipelining, and Bake-Testing the STM32H750 Tracker"
date: 2026-04-23
draft: false
tags: ["ARM", "C++", "embedded", "debugging", "Docker", "Linux", "performance", "benchmarking", "zero-copy", "optimization"]
keywords: ["STM32H7 SPI DMA LCD", "DCMI double buffering STM32H7", "MOSSE vs SAD tracker comparison", "STM32H750 tracker performance", "MCU tracker benchmarking"]
cover:
  image: /images/posts/stm32h7-tracker.png
  alt: "Cleaning Up, Pipelining, and Bake-Testing the STM32H750 Tracker"
categories: ["deep-dive"]
summary: "A sequel to the first STM32H750 tracker post. After the C++ port was proven in production, I spent a week of evenings cutting dead vendor code, splitting the algorithm out to host for unit tests, wiring the LCD SPI through DMA to let the CPU run the tracker in parallel with the blit, unlocking the camera's real frame rate, chasing a subtle BB-drift bug back to a too-wide SAD search, and finally building an offline A/B harness that compares SAD, NCC, and MOSSE on four synthetic scenarios so the next tracker port is a data decision, not a vibes one."
ShowToc: true
---

The [first post](/posts/stm32h7-ov7725-template-matching-tracker/)
ended with the C++ port working end-to-end, byte-identical firmware
compared to the C baseline, and `master` tracking the C++ tree.
Everything worked. It was also messy in the way things are when
they've just started working: the WeAct BSP shipped drivers for four
different image sensors, only one of which was on the board; a Python
venv had accidentally gotten committed to the repo; the LCD per-frame
blit was polled SPI and wasted ~10 ms of every frame; the tracker
algorithm was welded to HAL headers and impossible to unit-test; and
the only way to evaluate alternative tracker algorithms was to dream
about what they might do.

This post is what happened next — about a week of evenings. No single
headline win, just a bunch of systematic cleanup that now makes the
whole thing feel like a real project instead of a prototype.

## Cleaning up the vendor code

First pass: delete what wasn't doing any work.

The WeAct SDK ships with camera drivers for **OV2640, OV5640, OV7670,
and OV7725**. My board has the OV7725 — the other three shipped as
part of the BSP's "try every sensor on the I²C bus" probe dispatcher.
Removed them. `lib/weact_camera/` went from 11 files to 4, and the
`Camera_Init_Device` dispatcher shrunk from a 4-sensor cascade to a
direct OV7725 probe + init. **~3,000 lines of dead sensor code out**,
and `Camera_WriteRegList` / `Camera_Reset` became orphans to delete
with them.

Similar pass on the LCD side:

- `LCD_Test` was a factory-demo boot animation — WeAct logo, 3-second
  key wait, brightness ramp, "WeAct Studio / STM32H7xx" branding —
  that main.c was calling as its LCD initialiser. Every line of text
  in that sequence was immediately overwritten by `FillRect(BLACK)`
  three seconds later. Replaced with a stripped `LCD_Init` that does
  driver bring-up and nothing else. Boot is **~3 seconds faster**.
- `LCD_Light` fade animation, `LCD_SoftPWM*` family (the soft PWM
  fallback wired up via `Camera_XCLK_Set`, which I'd already removed),
  the 647-line `logo_160_80.c` splash bitmap — all orphaned,
  all deleted.
- `font.h` shipped with five bitmaps: two Chinese glyph tables, a QQ
  messenger logo, and two ASCII fonts. The Chinese and QQ ones
  weren't referenced anywhere — linker GC was already dropping them
  from flash, but they were cluttering source. **−218 lines** of pure
  source hygiene, zero flash impact.

And then: the Python virtualenv.

`git ls-files | wc -l` said the repo had 3,478 files. `git ls-files |
grep -v "\.venv" | wc -l` said 47. The other 98.6% was an accidentally
committed Python venv under the repo root — bytecode caches and
numpy/pygame source that `pip install` had produced for the host
tuner during an earlier session. `git rm --cached -r .venv` +
`.gitignore` entry fixed it. Annoying churn in the commit, but the
clone is now ~40 MB smaller.

Last cut: `ov7725.c` → `ov7725.cpp`. This was the final `.c` file of
"our own code" — after it moved, every source file under `src/` and
`lib/weact_*/` that we authored or substantially rewrote was C++. The
remaining C files (`ov7725_regs.c`, `st7735.c`, `st7735_reg.c`,
and the CubeMX-generated peripheral inits in `src/*.c`) are either
vendor-verbatim drivers or CubeMX output that regenerates from the
`.ioc` — converting them would've been costume jewellery.

Cumulative: **~4,200 lines deleted, flash text from 112 KB to 86 KB
(24% smaller)**, and the remaining tree maps cleanly to "our code
(C++)" and "not our code (C)."

## Splitting the tracker out for host tests

The second big theme was splitting the tracker algorithm off from
everything it was welded to.

`main.cpp` was 870 lines of bundled concerns:

- MCU bring-up (MPU, cache, clocks)
- DCMI frame callback
- LCD drawing helpers
- CDC protocol (command parser + streamer)
- the *actual tracker* (pyramid SAD, flood-fill, α-β update, template
  capture)

Worse, the tracker called `HAL_GPIO_ReadPin(KEY_GPIO_Port, KEY_Pin)`
directly for K1 edge detection — a hard HAL dependency that meant the
algorithm couldn't be built without arm-none-eabi. There was no way
to unit-test anything.

Fixed by creating `lib/tracker/tracker.{hpp,cpp}` — pure algorithm,
no HAL includes, zero STM32 headers. The signature changed from
`tracker_update()` reading module-scope volatile globals to a clean
`tracker_step(Tracker&, const uint16_t*, TrackerInputs&, TrackerParams&)`
where `TrackerInputs` includes a plain `bool key_pressed` that the
caller fills in. MCU init, DCMI glue, LCD drawing, CDC protocol —
all stayed in `main.cpp`. No RTOS, no abstraction layer; just one
hard boundary between "HAL-bound" and "pure math."

Then added a second Docker image under `tests/` — plain Ubuntu +
g++ + cmake, no arm-none-eabi — that compiles `lib/tracker/tracker.cpp`
against an assertion-based test runner. Nine tests covering luma
conversion edges, template capture centring, seg-flood on uniform
squares + luma boundaries, half-res averaging, lock/unlock transitions,
and force-flag consumption.

`make test` runs the full suite in the test container in under a
second. `make build` still cross-compiles the firmware in the other
container. Two build targets, one algorithm source, zero shared state
between the environments. If someone accidentally adds a HAL include
under `lib/tracker/`, the x86 build breaks immediately, which is the
point.

The **roadmap item I'd written as "host-buildable tracker unit tests"
four months ago** got ticked on a Tuesday evening without anyone
having to write an abstraction layer.

## LCD SPI DMA + DCMI double-buffering

The `main.cpp` main loop used to look like this:

```cpp
while (1) {
    if (DCMI_FrameIsReady) {
        ST7735_FillRGBRect(vis, 160, 80);       // polled SPI, ~10 ms
        tracker_step(...);                       // ~5 ms
        // overlays + CDC + command poll
    }
}
```

At ~20 MHz SCK, pushing 25,600 bytes of RGB565 per frame through
polled `HAL_SPI_Transmit` burns ~10 ms of CPU time that's genuinely
doing nothing but spinning on TXE. At 25 FPS the budget is 40 ms per
frame; we're 25% of the budget in wait-on-peripheral alone. The
tracker compute is independent — the two steps were serialised
purely because I'd written the loop that way.

Fix: one big DMA for the blit. `ST7735_FillRGBRect` is a row-by-row
loop (80 polled transfers of 320 bytes each, with `SetCursor`
between), which blocks the CPU even if each row's data transfer is
on DMA. The fix that actually helps is to bypass it: one
`SetCursor(0, 0)` + one single 25,600-byte DMA that relies on the
ST7735's auto-increment to fill the window linearly. The CPU is free
for the entire duration, and — critically — the loop can interleave:

```cpp
LCD_BlitStart(vis, 25600);                  // DMA, ~1 µs CPU
tracker_step(...);                          // ~5 ms in parallel
LCD_BlitWait();                             // spin for the rest
```

Plumbing: `DMA1_Stream1` (Stream0 is DCMI) wired to SPI4 TX via
`__HAL_LINKDMA`, IRQ handlers for DMA and SPI defined in `lcd.cpp`
with `extern "C"` to override the weak symbols in the startup file,
and a `HAL_SPI_TxCpltCallback` that releases CS and clears the busy
flag. D-cache clean on the source buffer before the DMA reads it
(AXI SRAM is write-back cacheable in the default MPU layout). The
whole change is ~80 lines in `lcd.cpp`.

The visible tearing issue made me take the next step: **DCMI
double-buffering**. The single `pic[]` buffer was both the DMA target
and the LCD read source. Tearing was usually invisible because polled
SPI was slow enough that by the time we finished blitting, DCMI had
already started overwriting rows we were done with. With the blit
async, the margin shrunk and the race became real. Converted `pic`
to `pic[2][FRAME_W][FRAME_H]`, doubled the DMA length so DMA wraps
every two frames, added `DCMI_LastFilled` toggled in the frame-event
ISR:

```cpp
void HAL_DCMI_FrameEventCallback(DCMI_HandleTypeDef*) {
    // ... FPS counter ...
    DCMI_LastFilled ^= 1;
    DCMI_FrameIsReady = 1;
}
```

Main loop snapshots `idx = DCMI_LastFilled` at the top and reads
`&pic[idx][20][0]` for the whole iteration. DCMI writes the other
half; no overlap regardless of timing.

**+38,400 bytes BSS** (the second frame buffer), still trivially fits
in the 512 KB AXI SRAM.

## Text-only LCD, event-flag dashboard

With the DMA path working I realised something else: the whole point
of displaying video on the on-board LCD was "nice for standalone
use," but in practice I'm always tethered to the host which has
the full CDC stream. The duplicated blit was a nice-to-have that
cost 10 ms of CPU per frame.

Deleted the per-frame LCD blit. The 0.96" panel is now log-only —
status text showing active profile, FPS, lock state, and coordinates
when locked. SPI4 stays idle between the rare dashboard updates.

At which point the dashboard's update rate itself started bothering
me. Updating a text line at 25 Hz is pointless — a human reads at
maybe 2–5 Hz. Also, the FPS counter only changes once per second
(the DCMI ISR computes `count/second` and stores it). So I added an
event flag:

```cpp
volatile uint8_t flag_status_dirty = 1;

// ISR: FPS tick rolled over
if (HAL_GetTick() - tick >= 1000) { Camera_FPS = count; count = 0;
                                    flag_status_dirty = 1; }

// main loop: tracker lock state flipped
const bool was_locked = g_trk.locked;
tracker_step(...);
if (g_trk.locked != was_locked) flag_status_dirty = 1;

// main loop bottom
if (flag_status_dirty) {
    flag_status_dirty = 0;
    snprintf(buf, ...);
    LCD_ShowString(...);
}
```

LCD updates dropped from 25 Hz to ~1–2 Hz (FPS tick + lock transitions).
Per-frame overheads dropped correspondingly. The point isn't
microseconds — it's that **the code now says what the rates actually
are**. One main loop, multiple conceptual "loops" each running at its
own natural rate, all dispatched from the top level via flags.

This is what "different loops for different concerns" means on a
single-core MCU: not an RTOS, just one `while (1)` with enough
self-discipline to run each branch only when its flag is set.

## Unlocking the camera frame rate

After all the above, the firmware was visibly leaner and the main
loop's CPU use dropped a lot. But `BB,…,fps=25` kept showing up on
every status line. What gives?

The OV7725 at our settings can theoretically do 113 FPS at QQVGA.
The bottleneck was AEC + a banding filter + night-mode auto frame
rate all conspiring to snap the frame period to 50/60 Hz mains
harmonics and stretch it in low light. Added
`ov7725_unlock_fps()`:

```cpp
uint8_t reg;
ov7725_RD_Reg(COM8, &reg);
reg &= ~COM8_BANDF_EN;      // drop banding filter
ov7725_WR_Reg(COM8, reg);

ov7725_RD_Reg(COM5, &reg);
reg &= ~COM5_AFR;           // drop night-mode auto frame rate
ov7725_WR_Reg(COM5, reg);
```

Called right after `Camera_Init_Device`. AEC/AGC stay on so exposure
still adapts to brightness, just without the quantisation. Typical
indoor light went from ~25 FPS to ~37 FPS. In bright light (desk lamp
on the target) it climbs past 60.

The remaining ceiling is AEC exposure time: in dim rooms the sensor
picks ~20 ms of integration, which forces frame period up. Option
for later: disable AEC outright, set manual exposure + gain, expose
both via CDC for tuning. **For now the rough-cut throttle disable is
enough** and the honest ~37 FPS is already smoother than the old 25.

## A bug that looked like physics

Then the user (me, wearing a different hat) reported something
odd. Lock on a small object. Push a second object into the field
of view from *outside* the bounding box, slowly, from bottom to
top. The BB drifts upward, even though every pixel inside the BB
is unchanged.

First instinct: that's impossible, nothing inside the template
changed. Second instinct, after an hour of staring: oh.

The SAD search window is ±25 at half-resolution — effectively ±50
full-resolution. On an 80-pixel-tall strip that's basically "scan the
entire vertical range every frame for the best template match."
Because the template is 16×16 of a low-texture target, SAD isn't very
discriminative. When a new object enters the search window, even at
a position far from the current lock, its SAD score can be
*lower* than the static target's — especially if the target has soft
edges that pick up a bit of background blur. The tracker obediently
moved toward the new match.

What it **looked like** from outside: BB drifting up because
"something" pulled on it, even though the something wasn't inside
the BB.

The fix is two lines. Compute the jump between the SAD winner and the
α-β prediction; if it exceeds `max_jump` in either axis, reject the
measurement and hold position:

```cpp
const int  jump_x  = abs_i(best_cx - pred_cx);
const int  jump_y  = abs_i(best_cy - pred_cy);
const bool too_far = (jump_x > params.max_jump) || (jump_y > params.max_jump);

if (sad <= max_match_sad && !ambiguous && !too_far) {
    // accept the measurement
} else {
    // lost this frame: decay velocity, increment lost counter
}
```

Default `max_jump = 12` pixels, configurable via `MJ=<n>` CDC command
so the operator can trade sticky-vs-nimble live. Tracker now ignores
distractors it previously followed, and the BB stays put while the
target stays put. Clean fix, two lines, one test confirming the
regression on hardware.

The **deeper point** is that the wide SAD search was technically
correct — it's what every textbook template matcher does — but
failed the real-world constraint that a human operator is gently
framing targets, not chasing ICBMs. The search radius should
reflect the expected target dynamics. Too narrow and you lose fast
targets; too wide and you chase every distractor. The jump-rejection
gate lets you widen the search radius (useful for re-acquisition
after a loss) while staying sticky during normal tracking, because
the α-β prediction handles the common case.

## Profiles + DPad cycling

Once `max_jump` was a parameter, it joined the growing pile: `TOL`
(max SAD tolerance), `VC` (velocity clamp), `SEG` (segmentation luma
window), `RS` (re-segmentation interval), `MJ`. Five knobs, each
with a "good value for slow targets" and a "good value for fast
targets" that are both wrong in the other case. Nobody wants to
tune five parameters every time they switch what they're tracking.

So: tracker profiles. Four presets, stored in a const table:

```cpp
struct TrackerProfile {
    const char*   name;      // 4-char label for LCD
    TrackerParams params;
};

static const TrackerProfile PROFILES[] = {
    { "GENT", { ... strict everything ... } },
    { "NORM", { ... current defaults   ... } },
    { "FAST", { ... permissive         ... } },
    { "ACQR", { ... wide-open          ... } },
};
```

CDC command `PROF=NEXT | PROF=PREV | PROF=<idx>` swaps `g_params`
wholesale; the status line picks up the active profile name so the
LCD reads `NORM 37F L=80,40` or `FAST 55F K1=lock`. Host side, DPad
left/right is wired to send `PROF=PREV` / `PROF=NEXT` with
edge-detection so holding a direction doesn't spam. Individual
single-param commands still work, so you can pick a preset and then
tune on top.

A micro feature, but it's the kind of thing that makes the tracker
feel like a tool instead of a parameter sheet.

## Host script that survives reality

One more small thing. The Python tuner crashed every single time I
reflashed the board:

```python
ser = serial.Serial(args.port, args.baud, timeout=0.05)
# ... later ...
ser.read(4096)                               # SerialException: device disappeared
```

Pushed the serial handle behind a `SerialLink` class with exponential
backoff: 0.5 s → 1 s → 2 s → … capped at 30 s. `read()` blocks and
reconnects when the port vanishes; `write()` is best-effort and
returns 0 when the port is down so the pygame main thread never
stalls. Console now prints:

```
[ser] connect failed: [Errno 2] could not open port ...; retry in 0.5s
[ser] connect failed: ...; retry in 1.0s
[ser] connected /dev/ttyACM0
```

You unplug, wiggle a cable, reflash, and the tuner window stays
live; the feed picks back up the moment the board re-enumerates. This
is the single dev-ergonomics improvement that has saved me the most
real wall time in this whole round.

## Offline A/B benchmark: SAD vs NCC vs MOSSE

With the algorithm split into `lib/tracker/` and test-harness-shaped,
the next question was: **which tracker do I port next?**

The roadmap had five candidates (MeanShift, MOSSE, KCF, CSRT, deep
learning) and the classic engineering answer is "MOSSE — best
effort/benefit ratio." That answer is right, but it was also
vibes-based. I wanted to see actual IoU-vs-ground-truth curves
before committing to a two-week port.

So I built an offline A/B harness under `tests/ab/`:

- A third Docker image (Python + numpy + matplotlib, no OpenCV — so
  each tracker implementation is a Python file you can actually read)
- Synthetic scenario generator for 160×80 RGB565 clips at 200 frames
  each. Four scenarios: **linear motion** (baseline),
  **scaling** (target grows/shrinks), **morphing** (shape
  changes: circle → ellipse → diamond → square), **distractor**
  (lookalike enters from outside the BB). Ground-truth BB written
  alongside each frame.
- Three tracker implementations with a common interface:
  - **SAD** — direct port of `lib/tracker/` (pyramid SAD + α-β +
    jump rejection).
  - **NCC** — normalised cross-correlation, expected to be
    brightness-invariant.
  - **MOSSE** — classic Bolme 2010 correlation filter. 32×32 patch,
    FFT-domain filter, PSR confidence gate, on-line learning rate
    0.125.
- A runner that runs each (tracker, scenario) pair, scores per-frame
  IoU, emits CSVs + IoU-curve plots + a compute-time bar chart, and
  writes a full report in `docs/AB_TRACKER_REPORT.md`.

One `make ab-test` command regenerates everything.

The results were instructive:

| Tracker | Scenario      | mean IoU | success | lost at | mean ms | host FPS |
|---------|---------------|---------:|--------:|--------:|--------:|---------:|
| SAD     | linear_motion | 0.76     | 1.00    |    —    | 3.95    |   253    |
| NCC     | linear_motion | 0.76     | 1.00    |    —    | 25.08   |    40    |
| MOSSE   | linear_motion | 1.00     | 1.00    |    —    | 0.23    |  4,323   |
| SAD     | scaling       | 0.27     | 0.08    |    31   | 4.24    |   236    |
| NCC     | scaling       | 0.24     | 0.06    |    26   | 27.60   |    36    |
| MOSSE   | scaling       | 0.30     | 0.17    |    31   | 0.11    |  8,721   |
| SAD     | morphing      | 0.69     | 1.00    |    —    | 4.35    |   230    |
| NCC     | morphing      | 0.69     | 1.00    |    —    | 27.23   |    37    |
| MOSSE   | morphing      | 0.69     | 1.00    |    —    | 0.14    |  7,036   |
| SAD     | distractor    | 1.00     | 1.00    |    —    | 4.36    |   229    |
| NCC     | distractor    | 1.00     | 1.00    |    —    | 27.35   |    37    |
| MOSSE   | distractor    | 1.00     | 1.00    |    —    | 0.17    |  5,728   |

Takeaways:

1. **MOSSE is ~20× faster than SAD** and ~130× faster than NCC on
   this host. The complexity advantage scales to the M7 too — one
   FFT pair beats `(2·search_r + 1)²` pointwise kernel evaluations as
   soon as the search window is nontrivial. Port is the right next
   move.
2. **All three survive the distractor scenario with IoU 1.0**. The
   jump-rejection gate we added for the drift bug does its job on
   SAD and NCC; MOSSE's PSR confidence does the same thing
   algorithmically. The lesson generalises: you need some
   confidence signal to reject "suspiciously good" matches.
3. **All three fail equally badly on scaling** (6–17% success). None
   of them does scale estimation. The template was sized at lock
   time and stayed that size; the ground truth grew and shrank. This
   is exactly the thing the firmware's `reseg_every` periodic
   re-segmentation addresses on-MCU, and it was missing from the
   Python port — the next pass will either add multi-scale templates
   or port the re-seg over.
4. **Morphing looks mid at 0.69** for all three, but actually that's
   not a tracker failure — the centre stays pinned, and the reported
   BB (fixed-size from init) just doesn't match the morphing
   ground-truth BB. IoU between a fixed square and a same-centred
   ellipse caps around 0.69.
5. **NCC's lighting-robustness advantage never shows** because the
   synthetic clips don't simulate lighting changes. That's a fair
   note to add: without camera-noise and illumination-shift
   scenarios, NCC's claim is untested and it's paying 7× SAD's
   compute for nothing.

The plots — per-frame IoU curves for each scenario + compute bar
chart — live in `tests/ab/results/plots/`. The full report
(`docs/AB_TRACKER_REPORT.md`) spells out methodology, reproducibility
steps, and what I'd add to the harness next.

**What this bought me** is not "the answer" but the ability to *have*
an answer. Before the A/B harness, "which tracker next?" was a coffee
conversation. Now it's a file I can send someone, and they can run it
themselves, and disagree with the scenarios I picked, and contribute
new ones. That's a different category of decision-making than I had
before.

## Takeaways

1. **Cleanup is a feature.** Deleting ~4,000 lines of vendor cruft
   was the single highest-ROI week's work on this project. The
   remaining code now actually fits in my head.
2. **Move the boundary between "our code" and "vendor code" early
   and keep it rigid.** Every time I made something C++-flavoured
   that straddled the boundary, it cost me. Every time I let our
   code be C++ and vendor code be C with `extern "C"` guards, it
   worked.
3. **Unit-testability is a design property, not a testing one.** The
   tracker algorithm became testable the moment it stopped calling
   `HAL_GPIO_ReadPin` — not the moment I wrote the first test. All
   the tests followed trivially once the coupling was broken.
4. **DMA wins are shape wins, not flag wins.** Switching an API call
   from blocking to DMA doesn't help unless you also restructure
   the caller to use the saved time. The LCD blit only started
   saving real wall time once I moved `tracker_step` into the DMA
   window.
5. **Flag-driven main loops are the poor person's RTOS and that's
   fine.** No scheduler, no stack budget for multiple tasks, no
   priority inversion risk — just `if (flag_x) { handle_x(); }`
   repeating at the top level. Each subsystem runs only when its
   flag is set, at its own natural rate, and the intent is legible
   to the next reader.
6. **A bug that "looks like physics" is always a missing
   constraint.** The BB-drift report didn't make sense until I
   realised the SAD search radius was allowing a constraint that
   the operator's intuition forbade: "the target shouldn't teleport."
   Encoding that as jump rejection fixed it in two lines.
7. **Build the A/B harness before picking the next algorithm.** The
   cost is a weekend; the benefit is every future algorithm choice
   on this repo is now a data decision instead of an argument.

## What's next

From the refreshed roadmap:

- **Port MOSSE to the M7.** The A/B numbers say this is the clearest
  win. Needs CMSIS-DSP FFT (`arm_cfft_f32`), ~200 lines of C++, keeps
  the jump-rejection + PSR confidence gates we proved work.
- **Multi-scale templates** to fix the scaling failure case. Cheap
  on MOSSE (3× FFTs); expensive on SAD. Ordering this after the
  MOSSE port makes sense.
- **GitHub Actions CI** — `make build` + `make test` + `make ab-test`
  on every push. Locks in everything above.
- **Camera-noise + illumination-shift scenarios** in the A/B harness,
  so NCC gets a fair shake and the MOSSE port has a representative
  test before it lands on hardware.

The whole repo, including the test + A/B harnesses, the report, and
the DCMI double-buffered firmware, is on GitHub at
[github.com/PavelGuzenfeld/stm32h7-tracker](https://github.com/PavelGuzenfeld/stm32h7-tracker).
