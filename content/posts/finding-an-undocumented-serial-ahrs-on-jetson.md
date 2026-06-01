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

The unit here was an [Inertial Labs MiniAHRS](https://inertiallabs.com/ahrs/) — a compact industrial AHRS that streams orientation and calibrated sensor data over a serial link. (Its [datasheet](https://inertiallabs.com/wp-content/uploads/2023/03/MiniAHRS-Datasheet-rev2.10_October_2021.pdf) has the full spec.) Inertial Labs also publish an open-source [ROS driver and SDK](https://github.com/inertiallabs/inertiallabs-ros-pkgs), which — spoiler — became the Rosetta Stone for the whole exercise.

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

## The scripts

I distilled the hunt into two small scripts. The first sweeps every serial port and asks each one "who are you?" via the device-info command, reporting the port, baud, serial number and firmware string of any Inertial Labs unit it finds:

```bash
#!/bin/bash

# Find the serial port an Inertial Labs MiniAHRS is connected to.
#
# Scans the candidate tty devices, sends the Inertial Labs device-info command
# (0x12) to each and reports the port whose firmware identifies as a MiniAHRS,
# together with the baud rate, serial number (IDN) and firmware string.
#
# Needs read/write access to the serial devices. If the login user is not in
# the 'dialout' group, run as root or inside a container with the device mapped:
#   docker run --rm --network none --privileged --entrypoint bash \
#     -v /dev:/dev -v "$PWD/scripts:/scripts" <image> /scripts/minihrs_lookup.sh
#
# Usage: minihrs_lookup.sh [baud ...]
#   baud ...  optional baud rates to try (default: common Inertial Labs rates)
#
# Exit codes: 0 found, 1 no serial ports / access, 2 no MiniAHRS detected.

set -u

BAUDS=("$@")
if [ ${#BAUDS[@]} -eq 0 ]; then
    BAUDS=(921600 460800 230400 115200 57600 38400 9600)
fi

# Inertial Labs command frames: AA 55 00 00 <len_lo> <len_hi> <payload> <crc16_lo> <crc16_hi>
STOP=$'\xAA\x55\x00\x00\x07\x00\xFE\x05\x01'   # stop continuous output
INFO=$'\xAA\x55\x00\x00\x07\x00\x12\x19\x00'   # request device info (code 0x12)

PORTS=$(ls /dev/ttyUSB* /dev/ttyTHS* /dev/ttyACM* 2>/dev/null | sort -u)
if [ -z "$PORTS" ]; then
    echo "no serial ports found"
    exit 1
fi

FOUND=""
for port in $PORTS; do
    for baud in "${BAUDS[@]}"; do
        stty -F "$port" "$baud" raw -echo clocal -crtscts 2>/dev/null || continue

        cap=$(mktemp)
        ( timeout 1 cat "$port" > "$cap" 2>/dev/null ) &
        rp=$!
        sleep 0.2
        printf '%b' "$STOP" > "$port" 2>/dev/null; sleep 0.15
        printf '%b' "$INFO" > "$port" 2>/dev/null; sleep 0.15
        printf '%b' "$INFO" > "$port" 2>/dev/null
        wait $rp 2>/dev/null

        # The device-info reply is AA 55 01 12 <len> <INSDeviceInfo>; the struct
        # starts with IDN[8] (serial) and FW[40] (firmware string), both ASCII.
        info=$(python3 - "$cap" <<'PY'
import sys
d = open(sys.argv[1], 'rb').read()
i = d.find(b'\xaa\x55\x01\x12')
if i < 0 or i + 6 > len(d):
    sys.exit(1)
ln = d[i + 4] | (d[i + 5] << 8)
p = d[i + 6:i + 6 + (ln - 6)]
idn = p[0:8].split(b'\x00')[0].decode('latin1', 'replace')
fw = p[8:48].split(b'\x00')[0].decode('latin1', 'replace')
print(idn + "\t" + fw)
PY
)
        rm -f "$cap"

        if [ -n "$info" ]; then
            idn=${info%%$'\t'*}
            fw=${info#*$'\t'}
            echo "$port @ $baud : IDN=$idn  FW=$fw"
            if echo "$fw" | grep -qi "ahrs"; then
                FOUND="$port $baud"
            fi
            break
        fi
    done
done

if [ -n "$FOUND" ]; then
    set -- $FOUND
    echo "MiniAHRS found: port=$1 baud=$2"
    exit 0
fi

echo "no Inertial Labs MiniAHRS detected"
exit 2
```

The second commands the documented orientation format, decodes the packets and grades them against gravity — a quick pass/fail bench check:

```bash
#!/bin/bash

# Sanity-check an Inertial Labs MiniAHRS.
#
# Commands the documented IL_IMU_Orientation (0x33) output, decodes a few
# packets and verifies the readings are physically plausible for a unit that is
# sitting still:
#   * accelerometer magnitude is ~1 g
#   * gyro magnitude is near zero
# Prints a human-readable table of Heading/Pitch/Roll, gyro, accel and mag.
#
# Run with the unit stationary. Needs read/write access to the serial device
# (dialout group or root; see minihrs_lookup.sh for the container invocation).
#
# Note: this commands a runtime output format only and does not write to flash;
# the device returns to its configured auto-start format on power cycle.
#
# Usage: minihrs_sanity_test.sh [port] [baud]
#   port  serial device (e.g. /dev/ttyUSB2). If omitted, minihrs_lookup.sh is used.
#   baud  default 921600
#
# Exit codes: 0 pass, 1 fail / no access, 2 no MiniAHRS found.

set -u

PORT=${1:-}
BAUD=${2:-921600}
HERE=$(dirname "$0")

if [ -z "$PORT" ]; then
    res=$("$HERE/minihrs_lookup.sh" | grep "MiniAHRS found")
    PORT=$(echo "$res" | sed -n 's/.*port=\([^ ]*\).*/\1/p')
    BAUD=$(echo "$res" | sed -n 's/.*baud=\([0-9]*\).*/\1/p')
    if [ -z "$PORT" ]; then
        echo "no MiniAHRS found"
        exit 2
    fi
fi

stty -F "$PORT" "$BAUD" raw -echo clocal -crtscts 2>/dev/null || {
    echo "cannot open $PORT"
    exit 1
}

# stop any continuous output, then request IL_IMU_Orientation (0x33)
printf '\xAA\x55\x00\x00\x07\x00\xFE\x05\x01' > "$PORT"; sleep 0.25
timeout 0.15 cat "$PORT" >/dev/null 2>&1
cap=$(mktemp)
( timeout 1 cat "$PORT" > "$cap" 2>/dev/null ) &
rp=$!
sleep 0.1
printf '\xAA\x55\x00\x00\x07\x00\x33\x3A\x00' > "$PORT"; sleep 0.1
printf '\xAA\x55\x00\x00\x07\x00\x33\x3A\x00' > "$PORT"
wait $rp 2>/dev/null
printf '\xAA\x55\x00\x00\x07\x00\xFE\x05\x01' > "$PORT"   # leave the device idle

python3 - "$cap" "$PORT" "$BAUD" <<'PY'
import sys, struct, math

d = open(sys.argv[1], 'rb').read()
port, baud = sys.argv[2], sys.argv[3]

# IL_IMU_Orientation (0x33) payload, decoded per the Inertial Labs SDK:
#   Heading u16/100, Pitch i16/100, Roll i16/100, Gyro[3] i16/10 (deg/s),
#   Accel[3] i16/GA (g), Mag[3] i16 (raw counts).
# GA is the unit's accelerometer counts-per-g (gravity anchored, ~2000 here).
GA = 2000.0

def rd(b, o, fmt, scale):
    return struct.unpack_from('<' + fmt, b, o)[0] / scale, o + 2

pk = []
j = 0
while True:
    k = d.find(b'\xaa\x55\x01\x33', j)
    if k < 0 or k + 6 > len(d):
        break
    ln = d[k + 4] | (d[k + 5] << 8)
    if ln == 40 and k + 6 + 34 <= len(d):   # 0x33 data packet: 34-byte payload
        pk.append(d[k + 6:k + 6 + 34])
    j = k + 3

if not pk:
    print("FAIL: no orientation packets received from %s @ %s" % (port, baud))
    sys.exit(1)

print("MiniAHRS %s @ %s -- %d packets (IL_IMU_Orientation 0x33)" % (port, baud, len(pk)))
print(" Head  Pitch   Roll | Gyro X/Y/Z (dps)   | Accel X/Y/Z (g)        |A|")
print(" " + "-" * 70)

amags = []
gmax = 0.0
for pl in pk[:10]:
    o = 0
    H, o = rd(pl, o, 'H', 100); Pi, o = rd(pl, o, 'h', 100); Ro, o = rd(pl, o, 'h', 100)
    g = []
    for _ in range(3):
        v, o = rd(pl, o, 'h', 10); g.append(v)
    a = []
    for _ in range(3):
        v, o = rd(pl, o, 'h', GA); a.append(v)
    am = math.sqrt(sum(x * x for x in a))
    amags.append(am)
    gmax = max(gmax, max(abs(x) for x in g))
    print(" %5.1f %+6.1f %+6.1f | %+5.1f %+5.1f %+5.1f | %+6.3f %+6.3f %+6.3f %5.3f"
          % (H, Pi, Ro, g[0], g[1], g[2], a[0], a[1], a[2], am))

aavg = sum(amags) / len(amags)
ok = True
if not (0.85 <= aavg <= 1.15):
    print("FAIL: |Accel| %.3f g out of [0.85, 1.15]" % aavg)
    ok = False
if gmax > 5.0:
    print("FAIL: gyro %.1f dps too high (run with the unit stationary)" % gmax)
    ok = False

print("PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
PY
rc=$?
rm -f "$cap"
exit $rc
```

## Takeaways

A few things I'll carry to the next mystery-device hunt:

1. **Identify by behavior, not by label.** Generic USB-serial bridges tell you nothing. The protocol on the wire tells you everything — including, if you ask nicely, the model name.
2. **Never `2>/dev/null` a probe.** The error *is* the diagnosis. A `dialout` permission denial and a dead port are indistinguishable once you've muted the difference.
3. **Use the vendor's own SDK as documentation.** The open-source driver gave me the exact command frames, the checksum algorithm, and the field scaling — no reverse-engineering required.
4. **Let physics grade your work.** Gravity is a known-good signal sitting in every accelerometer. ~1 g at rest means your decode is honest.

The task that sounded like *"just read the sensor"* turned into a small lesson in observability: the hard part was never the wire — it was making sure I could trust what the wire was telling me.
