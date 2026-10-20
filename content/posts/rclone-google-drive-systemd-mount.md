---
title: Mounting a Google Drive Folder on Linux with rclone and a systemd User Service
date: 2026-10-20
draft: false
cover:
  image: /images/posts/rclone-google-drive-systemd-mount.png
  alt: 'Mounting a Google Drive folder on Linux with rclone mount and a systemd user service'
tags:
- Linux
- systemd
- Google
- networking
- DevOps
keywords:
- rclone mount google drive linux
- rclone systemd user service
- rclone Type=notify
- rclone vfs-cache-mode full
- mount google drive folder at login
- fusermount3 rclone unmount
categories:
- deep-dive
summary: A Google Drive folder that shows up as a normal directory every time I log
  in, using rclone mount, FUSE and a systemd user service. No root, no fstab, and a
  unit file that passes systemd-analyze verify.
ShowToc: true
---

## Why

I already wrote up [persistent SMB shares](/posts/persistent-smb-mount-linux/). Same itch, different backend: I keep a folder of PDFs and reference docs on Google Drive, and I want it at `~/gdrive` like any other directory. I don't want a sync client copying the whole drive, and I don't want to remember to mount it.

rclone does this. `rclone mount` exposes a remote as a FUSE filesystem, and a systemd **user** service starts it at login. No root, nothing in `/etc/fstab`.

## What the data path looks like

```
  your app (evince, ls, cp ...)
          |  read()/write()
          v
  +----------------+        kernel
  |  FUSE (/dev/fuse)
  +----------------+
          |
          v
  +----------------------------+     user space, runs as you
  | rclone mount               |
  |   VFS layer                |
  |   --vfs-cache-mode full    |---> ~/.cache/rclone  (local copies of
  +----------------------------+                       files you opened)
          |  HTTPS
          v
  Google Drive API
```

Reads go through the VFS cache. With `--vfs-cache-mode full`, rclone keeps local copies of the parts of files you actually open, so seeking inside a big PDF doesn't re-download it every time, and apps that need random-access writes work. Without a cache mode, some apps fail on writes because Drive objects can't be modified in place.

## Step 1: Install rclone and FUSE

Your distro's package works:

```bash
sudo apt install -y rclone fuse3
```

The packaged version can lag a lot. Debian trixie ships rclone 1.60, while the upstream release I checked against was 1.75.2. If you want the current one, rclone publishes `.deb`/`.rpm` files and static binaries on its downloads page. There's also an install script, `curl https://rclone.org/install.sh | sudo bash`, which is what I used originally. Read it before piping it into a root shell.

`fuse3` gives you `fusermount3`, which rclone needs to set up and tear down the mount.

## Step 2: Create the Drive remote

```bash
rclone config create gdrive drive scope=drive
```

This opens a browser for the Google OAuth flow and writes a remote called `gdrive` into `~/.config/rclone/rclone.conf`. On a headless box, run it with `config_is_local=false`. rclone then gives you a command to run on a machine with a browser and paste the result back.

My old notes used `--auth-only` here. That flag doesn't exist on `config create` in rclone 1.75.2. It fails with `unknown flag: --auth-only`.

Check it worked:

```bash
rclone listremotes
rclone lsd gdrive:
```

## Step 3: The user service

`~/.config/systemd/user/rclone-gdrive.service`:

```ini
[Unit]
Description=rclone mount of Google Drive
Wants=network-online.target
After=network-online.target

[Service]
Type=notify
ExecStartPre=/usr/bin/mkdir -p %h/gdrive
ExecStart=/usr/bin/rclone mount gdrive:/FOLDER %h/gdrive \
    --config %h/.config/rclone/rclone.conf \
    --cache-dir %h/.cache/rclone \
    --vfs-cache-mode full \
    --vfs-cache-max-size 20G
ExecStop=/usr/bin/fusermount3 -u %h/gdrive
Restart=on-failure
RestartSec=10

[Install]
WantedBy=default.target
```

The parts that matter:

| Line | Why |
|------|-----|
| `Type=notify` | rclone tells systemd when the mount is actually up, so anything ordered after this unit sees the files right away |
| `%h` | systemd's specifier for your home dir. `~` doesn't expand inside unit files |
| `--config`, `--cache-dir` | rclone's own docs say to pass these as absolute paths under systemd, since the environment is minimal |
| `gdrive:/FOLDER` | replace with your folder. `gdrive:` alone mounts the whole drive |
| `--vfs-cache-max-size 20G` | caps the local cache. Without it, the cache only shrinks by age |
| `ExecStop=... fusermount3 -u` | clean unmount when the service stops |

I dropped `--allow-non-empty`, which my original note had. It lets you mount over a directory that already has files in it, and those files then silently vanish behind the mount. If the mount point isn't empty, I'd rather the service fail and tell me.

Use the absolute path from `which rclone` in `ExecStart`. If you installed upstream to `/usr/bin`, the line above is fine. If it's in `~/.local/bin`, change it.

Before enabling, check the unit:

```bash
systemd-analyze --user verify ~/.config/systemd/user/rclone-gdrive.service
```

This file passes clean. A unit with a typo like `Type=notifyy` or a relative `ExecStart` fails here with a clear message instead of at login.

## Step 4: Enable it

```bash
systemctl --user daemon-reload
systemctl --user enable --now rclone-gdrive.service
systemctl --user status rclone-gdrive.service
ls ~/gdrive
```

User services start when you log in and stop when your last session ends. If you want the mount to exist without a login session, for example on a server, enable lingering:

```bash
loginctl enable-linger "$USER"
```

## Day to day

```bash
systemctl --user restart rclone-gdrive.service
journalctl --user -u rclone-gdrive.service -f
fusermount3 -u ~/gdrive
```

Flags I reach for:

| Flag | Effect |
|------|--------|
| `--read-only` | no writes at all; writes fail silently, so only use it when you mean it |
| `--vfs-cache-mode writes` | cache only files opened for writing; less disk, more re-downloads on read |
| `--vfs-cache-max-age 24h` | keep cached files longer than the 1h default |
| `--dir-cache-time 5m` | how long directory listings are trusted (default 5m) |

## Troubleshooting

**"directory already mounted" or "transport endpoint is not connected".** A previous rclone died without unmounting. `fusermount3 -u ~/gdrive` (add `-z` if it's busy), then restart the service.

**`fusermount3: mount failed: Permission denied`.** On some distros AppArmor confines `fusermount3`. rclone's mount help covers this case, and the fix depends on your AppArmor profile.

**Works from a terminal, fails as a service.** Almost always a path. Use absolute paths for the binary, `--config` and `--cache-dir`.

**Token expired.** `rclone config reconnect gdrive:` redoes the OAuth flow without recreating the remote.

## Summary

| Approach | Root needed | Starts at login | Local disk |
|----------|:-:|:-:|---|
| Sync client | no | yes | full copy |
| `rclone mount` by hand | no | no | cache only |
| `rclone mount` + systemd user service | no | yes | cache only, capped |

One unit file, one `enable --now`, and the folder is just there.
