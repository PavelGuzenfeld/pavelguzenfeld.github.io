---
title: "Linux Multi-Monitor Setup — A Practical Guide to xrandr, Lid Close, and Persistent Configuration"
date: 2026-03-23
draft: false
tags: ["Linux", "xrandr", "multi-monitor", "systemd", "X11", "Wayland", "DevOps"]
keywords: ["Linux multi monitor xrandr", "disable laptop screen Linux", "xrandr persistent configuration"]
cover:
  image: /images/posts/linux-multimonitor.png
  alt: "Linux Multi-Monitor Setup with xrandr"
categories: ["deep-dive"]
summary: "A hands-on walkthrough of configuring multiple monitors on Linux — from identifying displays with xrandr, turning off the laptop screen, ignoring lid close, to making it all survive a reboot. Every command explained."
ShowToc: true
---

## The Situation

I dock my laptop at a desk with two external monitors connected through a USB-C hub. The laptop screen becomes redundant — it sits at a weird angle, its resolution doesn't match the externals, and it wastes GPU cycles rendering a desktop I never look at. What I want is simple:

1. Turn off the laptop screen.
2. Use only the two external monitors.
3. Close the laptop lid without the system suspending.
4. Have all of this survive a reboot.

On macOS or Windows, this is a settings panel. On Linux, it's a set of tools you chain together — and the answer depends on whether you're running X11 or Wayland. This post covers both, with a focus on X11 (still the more common setup for docked workstations in 2026).

---

## Step 0: Figure Out Your Display Server

Before touching anything, find out what display protocol your session is using:

```bash
echo $XDG_SESSION_TYPE
```

You'll get one of:

| Output | Meaning |
|--------|---------|
| `x11` | X Window System (Xorg) |
| `wayland` | Wayland compositor (GNOME, KDE, Sway, etc.) |
| `tty` | Console session (no GUI) |

This matters because the tools are different. X11 uses `xrandr`. Wayland uses compositor-specific tools — `gnome-display-settings`, `wlr-randr`, `swaymsg`, or `kscreen-doctor` depending on your desktop environment.

**If you're unsure:** most Ubuntu/Debian installs with NVIDIA GPUs default to X11. Fedora and recent Ubuntu with Intel/AMD default to Wayland.

---

## Step 1: Install the Tools

### For X11

```bash
# xrandr is usually pre-installed, but just in case
sudo apt install x11-xserver-utils

# arandr — a visual GUI for xrandr (optional but useful)
sudo apt install arandr
```

`xrandr` is the command-line tool. `arandr` is a drag-and-drop GUI that generates xrandr scripts — handy for positioning monitors visually.

### For Wayland (GNOME)

GNOME's built-in Settings > Displays panel handles most configuration. For scripting:

```bash
# gnome-randr is a community tool that mimics xrandr syntax on Wayland
pip install gnome-randr

# or for wlroots-based compositors (Sway, Hyprland, etc.)
sudo apt install wlr-randr
```

### For Lid Close Behavior

Lid behavior is managed by `systemd-logind`, which is installed on every modern Linux distribution. No extra packages needed.

---

## Step 2: Identify Your Monitors

### X11

```bash
xrandr --listmonitors
```

Example output from my setup:

```
Monitors: 3
 0: +*eDP-1 1920/344x1080/193+0+0  eDP-1
 1: +DVI-I-3-2 1920/521x1080/293+3840+0  DVI-I-3-2
 2: +DVI-I-2-1 1920/521x1080/293+1920+0  DVI-I-2-1
```

Here's what each field means:

| Field | Example | Meaning |
|-------|---------|---------|
| Index | `0:` | Monitor number |
| Flags | `+*` | `+` = active, `*` = primary |
| Name | `eDP-1` | Output connector name |
| Resolution | `1920/344x1080/193` | Pixels / physical mm |
| Position | `+0+0` | X,Y offset in the virtual screen |

The naming convention tells you the connector type:

| Prefix | Connector |
|--------|-----------|
| `eDP` | Embedded DisplayPort (laptop screen) |
| `HDMI` | HDMI |
| `DP` | DisplayPort |
| `DVI-I` | DVI (often through a hub/dock) |
| `VGA` | VGA (legacy) |

**Your laptop screen is almost always `eDP-1`.** This is the one you want to turn off.

For more detail, run `xrandr` without flags — it dumps every output, its supported resolutions, and current state:

```bash
xrandr
```

```
eDP-1 connected primary 1920x1080+0+0 (normal left inverted right x axis y axis) 344mm x 193mm
   1920x1080     60.01*+  60.01    59.97    59.96    48.00
   1680x1050     59.95    59.88
   ...
DVI-I-2-1 connected 1920x1080+1920+0 (normal left inverted right x axis y axis) 521mm x 293mm
   1920x1080     60.00*+
   ...
DVI-I-3-2 connected 1920x1080+3840+0 (normal left inverted right x axis y axis) 521mm x 293mm
   1920x1080     60.00*+
   ...
```

### Wayland (GNOME)

```bash
gnome-randr
# or
wlr-randr
```

The output is similar — connector names, resolutions, positions.

---

## Step 3: Turn Off the Laptop Screen

### X11

```bash
xrandr --output eDP-1 --off
```

That's it. The laptop screen goes dark immediately. Your mouse cursor and windows shift to the remaining monitors.

To bring it back:

```bash
xrandr --output eDP-1 --auto
```

`--auto` re-enables the output at its preferred resolution and places it at a default position.

### Wayland (GNOME)

```bash
gnome-randr modify eDP-1 --off
# or via the Settings GUI: Settings > Displays > toggle off the laptop display
```

### Wayland (Sway / wlroots)

```bash
swaymsg output eDP-1 disable
# or
wlr-randr --output eDP-1 --off
```

---

## Step 4: Arrange Your External Monitors

With the laptop screen off, you'll want to position the external monitors relative to each other.

### Understanding the Coordinate System

Linux uses a virtual screen — a large canvas where each monitor occupies a rectangle. The `--pos` flag sets the top-left corner of each monitor in pixels:

```
(0,0)──────────(1920,0)──────────(3840,0)
  │                │                 │
  │   Monitor 1    │   Monitor 2     │
  │  1920x1080     │   1920x1080     │
  │                │                 │
(0,1080)──────(1920,1080)──────(3840,1080)
```

### Side-by-Side Configuration

```bash
# Left monitor at position (0,0), right monitor starts where the left one ends
xrandr \
  --output DVI-I-2-1 --mode 1920x1080 --pos 0x0 --primary \
  --output DVI-I-3-2 --mode 1920x1080 --pos 1920x0 \
  --output eDP-1 --off
```

The `--primary` flag tells your desktop environment which monitor gets the panel/taskbar and where notifications appear.

### Stacked (Top-Bottom) Configuration

```bash
xrandr \
  --output DVI-I-2-1 --mode 1920x1080 --pos 0x0 --primary \
  --output DVI-I-3-2 --mode 1920x1080 --pos 0x1080 \
  --output eDP-1 --off
```

### Mirror Mode

```bash
xrandr \
  --output DVI-I-2-1 --mode 1920x1080 --pos 0x0 --primary \
  --output DVI-I-3-2 --mode 1920x1080 --same-as DVI-I-2-1 \
  --output eDP-1 --off
```

### Using arandr (the Visual Way)

If coordinate math isn't your thing:

```bash
arandr
```

This opens a GUI where you drag monitor rectangles around. When you're happy with the layout, click **Layout > Save As** — it generates a shell script with the exact `xrandr` commands. You can then use that script for automation (see Step 7).

---

## Step 5: Set Resolution and Refresh Rate

Sometimes your monitor supports multiple resolutions or refresh rates:

```bash
# List available modes for a specific output
xrandr --output DVI-I-2-1 --verbose
```

To set a specific mode:

```bash
# Set resolution
xrandr --output DVI-I-2-1 --mode 2560x1440

# Set resolution AND refresh rate
xrandr --output DVI-I-2-1 --mode 2560x1440 --rate 144
```

### Adding a Custom Resolution

If your monitor supports a resolution that xrandr doesn't list (common with unusual displays or KVM switches), you can add it manually:

```bash
# Generate the modeline
cvt 2560 1440 60
# Output: Modeline "2560x1440_60.00"  312.25  2560 2752 3024 3488  1440 1443 1448 1493 -hsync +vsync

# Create a new mode
xrandr --newmode "2560x1440_60" 312.25 2560 2752 3024 3488 1440 1443 1448 1493 -hsync +vsync

# Add it to the output
xrandr --addmode DVI-I-2-1 "2560x1440_60"

# Use it
xrandr --output DVI-I-2-1 --mode "2560x1440_60"
```

---

## Step 6: Ignore Lid Close

By default, Linux suspends the system when you close the laptop lid. For a docked setup with external monitors, this is exactly what you don't want.

The lid close behavior is controlled by `systemd-logind`. Edit its configuration:

```bash
sudo nano /etc/systemd/logind.conf
```

Find these lines (they may be commented out with `#`):

```ini
#HandleLidSwitch=suspend
#HandleLidSwitchExternalPower=suspend
#HandleLidSwitchDocked=ignore
```

Uncomment and set all three to `ignore`:

```ini
HandleLidSwitch=ignore
HandleLidSwitchExternalPower=ignore
HandleLidSwitchDocked=ignore
```

What each setting controls:

| Setting | When it applies |
|---------|-----------------|
| `HandleLidSwitch` | Default behavior (on battery) |
| `HandleLidSwitchExternalPower` | When plugged in to AC power |
| `HandleLidSwitchDocked` | When an external monitor or dock is detected |

Setting all three to `ignore` means the lid close event is completely disregarded regardless of power state or docking status.

Apply the change:

```bash
sudo systemctl restart systemd-logind
```

**Warning:** Restarting `systemd-logind` will kill your current graphical session on some distributions. If you're worried about that, a reboot is the safer option.

### Verify It Worked

```bash
grep -i "HandleLid" /etc/systemd/logind.conf
```

Expected output:

```
HandleLidSwitch=ignore
HandleLidSwitchExternalPower=ignore
HandleLidSwitchDocked=ignore
```

You can also check the runtime state:

```bash
loginctl show-session $(loginctl | grep $(whoami) | awk '{print $1}') -p HandleLidSwitch
```

### GNOME Override

GNOME has its own lid-close handler that can override `logind`. If closing the lid still suspends after the `logind.conf` change, disable the GNOME override:

```bash
# Check current setting
gsettings get org.gnome.settings-daemon.plugins.power lid-close-suspend-with-external-monitor

# Disable it
gsettings set org.gnome.settings-daemon.plugins.power lid-close-suspend-with-external-monitor false

# On older GNOME versions, the key might be different:
gsettings set org.gnome.settings-daemon.plugins.power lid-close-ac-action 'nothing'
gsettings set org.gnome.settings-daemon.plugins.power lid-close-battery-action 'nothing'
```

---

## Step 7: Make It Persistent Across Reboots

`xrandr` changes are session-only — they reset on reboot or logout. There are several ways to make them stick.

### Option A: Autostart Script (Simplest)

Create a script with your xrandr commands:

```bash
mkdir -p ~/.config/autostart
```

Create the script:

```bash
cat > ~/bin/monitor-setup.sh << 'SCRIPT'
#!/bin/bash
# Wait for displays to be available (USB-C hubs can be slow)
sleep 2

# Turn off laptop screen, configure externals side by side
xrandr \
  --output DVI-I-2-1 --mode 1920x1080 --pos 0x0 --primary \
  --output DVI-I-3-2 --mode 1920x1080 --pos 1920x0 \
  --output eDP-1 --off
SCRIPT
chmod +x ~/bin/monitor-setup.sh
```

Create a `.desktop` file to run it at login:

```bash
cat > ~/.config/autostart/monitor-setup.desktop << 'EOF'
[Desktop Entry]
Type=Application
Name=Monitor Setup
Exec=/home/YOUR_USERNAME/bin/monitor-setup.sh
X-GNOME-Autostart-enabled=true
EOF
```

Replace `YOUR_USERNAME` with your actual username.

### Option B: Xorg Configuration File (System-Wide)

For a more permanent, system-level configuration:

```bash
sudo nano /etc/X11/xorg.conf.d/10-monitors.conf
```

```
Section "Monitor"
    Identifier  "eDP-1"
    Option      "Ignore" "true"
EndSection

Section "Monitor"
    Identifier  "DVI-I-2-1"
    Option      "Primary" "true"
    Option      "Position" "0 0"
EndSection

Section "Monitor"
    Identifier  "DVI-I-3-2"
    Option      "Position" "1920 0"
EndSection
```

**Note:** The `Identifier` values must match the output names from `xrandr`. This method is more reliable than autostart scripts because it applies before the desktop environment loads, but it's less flexible — you can't easily toggle configurations.

### Option C: udev Rule (Automatic on Dock/Undock)

If you frequently dock and undock, a udev rule can automatically apply your configuration when the external monitors connect:

```bash
sudo nano /etc/udev/rules.d/95-monitor-hotplug.rules
```

```
ACTION=="change", SUBSYSTEM=="drm", RUN+="/home/YOUR_USERNAME/bin/monitor-setup.sh"
```

Then reload:

```bash
sudo udevadm control --reload-rules
```

**Caveat:** udev rules run as root without a display session, so you need to set the `DISPLAY` and `XAUTHORITY` environment variables in the script:

```bash
#!/bin/bash
export DISPLAY=:0
export XAUTHORITY=/home/YOUR_USERNAME/.Xauthority

sleep 2

xrandr \
  --output DVI-I-2-1 --mode 1920x1080 --pos 0x0 --primary \
  --output DVI-I-3-2 --mode 1920x1080 --pos 1920x0 \
  --output eDP-1 --off
```

### Option D: Wayland Persistent Configuration

On GNOME Wayland, `~/.config/monitors.xml` stores your display layout. GNOME's Settings > Displays GUI writes to this file automatically — no manual editing needed. Just arrange your monitors in the GUI and it persists.

On Sway, add to `~/.config/sway/config`:

```
output eDP-1 disable
output DVI-I-2-1 resolution 1920x1080 position 0,0
output DVI-I-3-2 resolution 1920x1080 position 1920,0
```

On Hyprland, add to `~/.config/hypr/hyprland.conf`:

```
monitor=eDP-1,disable
monitor=DVI-I-2-1,1920x1080@60,0x0,1
monitor=DVI-I-3-2,1920x1080@60,1920x0,1
```

---

## Step 8: Troubleshooting

### "xrandr: cannot find output eDP-1"

Your laptop panel might have a different name. Check all available outputs:

```bash
xrandr | grep " connected"
```

On some NVIDIA setups, the laptop screen appears as `LVDS-1` or `DP-0` instead of `eDP-1`.

### External Monitors Not Detected

```bash
# Check if the kernel sees the displays
ls /sys/class/drm/

# Force a re-probe
xrandr --auto

# Check dmesg for hotplug events
dmesg | tail -20
```

If using a USB-C hub, try:
- A different cable
- Connecting directly without the hub
- Checking if the hub requires DisplayPort Alt Mode (not all USB-C ports support it)

### Screen Goes Black After xrandr Command

You accidentally turned off all outputs. The fix depends on whether you can still type:

```bash
# Blind-type this to re-enable all outputs
xrandr --auto
```

If the terminal is on the screen that went dark, switch to a TTY with `Ctrl+Alt+F2`, log in, and run:

```bash
DISPLAY=:0 xrandr --auto
```

### NVIDIA-Specific Issues

NVIDIA's proprietary driver uses `nvidia-settings` instead of (or alongside) xrandr:

```bash
# Open NVIDIA's display configuration GUI
nvidia-settings

# Or from the command line — save current config to xorg.conf
sudo nvidia-settings --save-to-x-configuration-file
```

On NVIDIA systems, the output names may differ (`DP-0`, `DP-2`, `HDMI-0` instead of the usual `eDP-1` naming). Always verify with `xrandr --listmonitors`.

---

## Quick Reference

Here's the condensed cheat sheet for the entire setup:

```bash
# 1. Check your display server
echo $XDG_SESSION_TYPE

# 2. List monitors
xrandr --listmonitors

# 3. Turn off laptop screen
xrandr --output eDP-1 --off

# 4. Arrange externals side by side
xrandr \
  --output DVI-I-2-1 --mode 1920x1080 --pos 0x0 --primary \
  --output DVI-I-3-2 --mode 1920x1080 --pos 1920x0

# 5. Ignore lid close
sudo sed -i \
  -e 's/^#*HandleLidSwitch=.*/HandleLidSwitch=ignore/' \
  -e 's/^#*HandleLidSwitchExternalPower=.*/HandleLidSwitchExternalPower=ignore/' \
  -e 's/^#*HandleLidSwitchDocked=.*/HandleLidSwitchDocked=ignore/' \
  /etc/systemd/logind.conf
sudo systemctl restart systemd-logind

# 6. Bring laptop screen back (when undocking)
xrandr --output eDP-1 --auto
```
