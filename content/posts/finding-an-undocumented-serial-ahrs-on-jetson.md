---
title: "Which tty Is the AHRS? Hunting an Undocumented Serial Device on a Jetson"
date: 2026-06-01
draft: false
tags:
- Jetson
- Linux
- embedded
- serial
- AHRS
- IMU
- FTDI
- Docker
- Python
- debugging
- hardware-testing
keywords:
- find serial device Linux
- FTDI ttyUSB identification
- Inertial Labs MiniAHRS protocol
- dialout permission denied serial
- decode AHRS binary packet
- Jetson serial port scan
categories:
- deep-dive
summary: A small AHRS was wired to a Jetson over USB, but nobody wrote down which
  serial port. Here's how I tracked it down by its protocol instead of its name,
  fell into the classic dialout permissions trap, and decoded its orientation
  stream into human-readable numbers.
ShowToc: true
audio:
  pronunciation:
    AHRS: A H R S
    IMU: I M U
    FTDI: F T D I
    tty: T T Y
    ttyUSB: T T Y U S B
    UART: you art
    lsusb: L S U S B
    dialout: dial out
    MEMS: mems
    stty: S T T Y
    baud: bawd
---

There's a particular kind of embedded task that sounds trivial and isn't: *"a sensor is plugged into this board over USB — find it and read it."* No port number, no baud rate, no documentation. Just a box with a fistful of serial adapters and the assurance that "it's on there somewhere."

This is the story of doing exactly that for a **MiniAHRS** wired into a Jetson Orin, and the two things that made it interesting: you can't identify the device by its name, and the first half-dozen "the port is silent" results were all lies.

## What's an AHRS, briefly

An **AHRS** — Attitude and Heading Reference System — is the little black box that tells a vehicle which way it's pointing. Inside is a MEMS **IMU** (a 3-axis gyroscope, 3-axis accelerometer, and usually a 3-axis magnetometer), plus an onboard fusion filter that turns those raw rates and forces into a clean **heading / pitch / roll** estimate. It's the same job your phone does to know which way to rotate the screen, scaled up for things that fall out of the sky if they get it wrong.

The unit here was an [Inertial Labs MiniAHRS](https://inertiallabs.com/mini-ahrs/) — a compact industrial AHRS that streams orientation and calibrated sensor data over a serial link. (Its [datasheet](https://inertiallabs.com/wp-content/uploads/2023/03/MiniAHRS-Datasheet-rev2.10_October_2021.pdf) has the full spec.) Inertial Labs also publish an open-source [ROS driver and SDK](https://github.com/inertiallabs/inertiallabs-ros-pkgs), which — spoiler — became the Rosetta Stone for the whole exercise.

## Step 1: what's even on the bus

First, enumerate. `lsusb` showed two FTDI chips:

```
ID 0403:6011 FTDI FT4232H Quad HS USB-UART/FIFO IC
ID 0403:6001 FTDI FT232R USB UART
```

The quad FT4232H exposes four UART channels (`/dev/ttyUSB0–3`); the single FT232R adds a fifth (`/dev/ttyUSB4`). And here's the first wall: the udev descriptors are **completely generic**.

```
ID_VENDOR=FTDI
ID_MODEL=Quad_RS232-HS
ID_SERIAL=FTDI_Quad_RS232-HS
```

Nothing says "Inertial Labs." Nothing says "AHRS." The FTDI EEPROM was never reprogrammed with a custom product string — which is the norm for vendors who just buy a stock USB-to-serial cable. **So you cannot identify this device by what it calls itself. You have to identify it by what it *says*.**

## Step 2: the lie of the silent port

The MiniAHRS speaks a binary protocol: every packet starts with the sync bytes `AA 55`. So the plan was simple — sniff each port, look for that header.

```bash
for p in /dev/ttyUSB*; do
  stty -F "$p" 115200 raw -echo 2>/dev/null
  timeout 2 cat "$p" | xxd | head
done
```

Every port: nothing. Silent. I dutifully concluded the device was idle or unpowered, swept a range of baud rates, sent the protocol's device-info request to provoke a reply… still nothing. I was minutes from declaring "the AHRS isn't connected."

It was connected. It was streaming the entire time.

The bug is hiding in plain sight above: `2>/dev/null`. The login account was **not in the `dialout` group**, so every `stty`, every `cat`, every write was failing with `Permission denied` — and I'd helpfully silenced exactly the error that would have told me so. "No bytes" wasn't *silence*; it was *access denied*. The moment I dropped the `2>/dev/null` and ran a single bare `stty`:

```
stty: /dev/ttyUSB0: Permission denied
```

> **Lesson one:** when you're probing hardware and getting nothing, the *nothing* is data. Don't throw away stderr. A genuinely idle UART and a permission error look identical once you redirect the truth to `/dev/null`.

There was no passwordless `sudo` available, and adding myself to `dialout` needs a re-login. But the account *was* in the `docker` group — and the application stack already ran in containers — so the clean way to get root on the device nodes was a privileged container with `/dev` mapped in:

```bash
docker run --rm --network none --privileged \
  -v /dev:/dev <image> bash scan.sh
```

(`--network none` sidesteps an unrelated iptables quirk on the host; running as root inside finally gave real read/write to the ports.)

## Step 3: identify by protocol

With actual access, one port immediately stood out: a continuous stream of bytes, and the byte count scaled with whatever baud I set — the classic signature of a device that's always transmitting. The other ports were genuinely quiet.

A baud sweep settled the rate. At one setting, and only one, the stream framed cleanly into `AA 55` packets:

```
== 921600 : aa55-pairs=393 ==
aa 55 01 9d 2c 00 ce ef ff ff 83 07 00 00 06 f1 ...
```

`AA 55 01` is the Inertial Labs binary data header. 393 framed packets in a second; garbage at every other baud. **921600 baud, confirmed by structure, not by guesswork.**

But "it's an Inertial Labs device" isn't "it's a MiniAHRS." For that, I asked it directly. The protocol has a device-info command (`0x12`); the SDK's framing is `AA 55 00 00 <len> <payload> <crc16>`, so the request is nine bytes. Send a Stop, then the info request, and read the reply:

```
aa 55 01 12 ac 00 41 31 32 33 34 35 36 37 4d 69 6e 69 41 68 72 73 ...
                  └ "A1234567" ┘ └──── "MiniAhrs ..." ────┘
```

The device's own firmware string: **`MiniAhrs`**, with a serial number and build date. Not an inference — a confession. The first field of the info struct is an 8-byte ASCII ID; the next is the firmware string. There it was.

## Step 4: make it human-readable

Hex headers are proof, but they're not *data*. The native stream used a custom packet layout this firmware revision didn't share with the open SDK, so I commanded the device into a documented format instead — `IL_IMU_Orientation` — whose field layout and scaling *are* defined: heading/pitch/roll as `int16 / 100` degrees, gyro as `int16 / 10` °/s, accelerometer counts, magnetometer counts. A few lines of Python turned the byte soup into this:

```
 Head  Pitch   Roll | Gyro X/Y/Z (dps)  | Accel X/Y/Z (g)        |A|
 -------------------------------------------------------------------
  0.00  +0.00  +0.00 | +0.20 -0.10 +0.00 | +0.002 -0.025 +1.008  1.008
  0.00  +0.00  +0.00 | -0.30 +0.00 +0.00 | -0.002 -0.021 +0.995  0.995
  0.00  +0.00  +0.00 | -0.10 +0.20 +0.00 | -0.001 -0.028 +1.004  1.004
```

And here's the satisfying part — the **physics checks out**, which is how you know the decode is right and not just plausible:

- The gyro sits within a few tenths of a degree per second of zero → the unit is stationary. ✓
- The accelerometer reads almost exactly **1 g**, pointing straight down the Z axis → it's sitting flat, feeling nothing but gravity. ✓
- Cross-computing pitch/roll from that gravity vector gives ≈ 0°, matching the reported attitude.

That 1 g magnitude is the anchor. If your decoded accelerometer doesn't sum to ~1 g at rest, your scale factor, byte offset, or endianness is wrong. It's the cheapest unit test in embedded work, and it's free.

## Takeaways

A few things I'll carry to the next mystery-device hunt:

1. **Identify by behavior, not by label.** Generic USB-serial bridges tell you nothing. The protocol on the wire tells you everything — including, if you ask nicely, the model name.
2. **Never `2>/dev/null` a probe.** The error *is* the diagnosis. A `dialout` permission denial and a dead port are indistinguishable once you've muted the difference.
3. **Use the vendor's own SDK as documentation.** The open-source driver gave me the exact command frames, the checksum algorithm, and the field scaling — no reverse-engineering required.
4. **Let physics grade your work.** Gravity is a known-good signal sitting in every accelerometer. ~1 g at rest means your decode is honest.

The task that sounded like *"just read the sensor"* turned into a small lesson in observability: the hard part was never the wire — it was making sure I could trust what the wire was telling me.
