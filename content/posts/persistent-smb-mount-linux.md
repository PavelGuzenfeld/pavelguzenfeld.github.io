---
title: Persistent SMB Shares on Linux — From Manual Mount to Automount on Access
date: 2026-03-24
draft: false
tags:
- Linux
- SMB
- CIFS
- systemd
- Nautilus
- networking
- DevOps
keywords:
- mount SMB share Linux fstab
- persistent CIFS mount systemd
- SMB automount Linux
cover:
  image: /images/posts/smb-linux.png
  alt: Persistent SMB Shares on Linux
categories:
- deep-dive
summary: A step-by-step guide to mounting SMB/CIFS network shares on Linux — from
  one-off access in a file manager to persistent fstab entries with systemd automount
  that connect only when needed and gracefully handle VPN disconnects.
ShowToc: true
audio:
  pronunciation:
    SMB: S M B
    CIFS: ciffs
    smbclient: S M B client
    cifs-utils: ciffs utils
    fstab: F S tab
    /etc/fstab: etc slash F S tab
    systemd: system D
    systemctl: system C T L
    x-systemd.automount: X system D auto mount
    x-systemd.idle-timeout: X system D idle timeout
    /etc/smbcredentials: etc slash S M B credentials
    Nautilus: Nautilus
    Dolphin: Dolphin
    Thunar: Thunar
    Nemo: Nemo
    GVFS: G V F S
    gvfs-backends: G V F S backends
    noauto: no auto
    nofail: no fail
    iocharset=utf8: I O charset U T F eight
    uid=1000: U I D ten hundred
    gid=1000: G I D ten hundred
    smb://: S M B colon slash slash
    file://: file colon slash slash
    file:///: file triple slash
    NT_STATUS_ACCESS_DENIED: N T status access denied
    NT_STATUS_LOGON_FAILURE: N T status logon failure
    ADMIN$: admin dollar
    C$: C dollar
    IPC$: I P C dollar
    VPN: V P N
---

## The Situation

You have one or more SMB shares on your local network that you need to access regularly from a Linux workstation. You want them to:

1. Show up in your file manager sidebar.
2. Survive a reboot.
3. Not block the boot process when the server is unreachable (e.g., VPN is off).
4. Connect automatically when you navigate to the folder.

On Windows or macOS, you right-click "Map Network Drive" and you're done. On Linux, there are several layers to get right: packages, credentials, fstab, systemd, and file manager bookmarks. This post walks through each one.

---

## Step 0: Install the Required Packages

You need two things: a client to browse shares and a mount helper for CIFS.

```bash
sudo apt install -y smbclient cifs-utils
```

- **`smbclient`** — command-line tool to list and access SMB shares (like an FTP client for SMB).
- **`cifs-utils`** — provides `mount.cifs`, required for mounting shares via `mount` or `fstab`.

Without `cifs-utils`, mount attempts will fail with a cryptic "cannot mount read-only" error — the kernel has CIFS support but no userspace helper to parse mount options.

---

## Step 1: Discover Available Shares

Before mounting, find out what's available on the server:

```bash
# Anonymous access
smbclient -L //SERVER -N

# With credentials
smbclient -L //SERVER -U YOUR_USER

# With a domain
smbclient -L //SERVER -U DOMAIN/YOUR_USER
```

You'll see output like:

```
Sharename       Type      Comment
---------       ----      -------
documents       Disk      Shared documents
projects        Disk      Project files
IPC$            IPC       Remote IPC
```

Shares ending in `$` (like `ADMIN$`, `C$`, `IPC$`) are hidden administrative shares — you typically don't need these.

**Verify access** to a specific share before trying to mount it:

```bash
smbclient //SERVER/SHARE_NAME -U DOMAIN/YOUR_USER -c 'ls'
```

If this fails with `NT_STATUS_ACCESS_DENIED`, the share requires different credentials or permissions — fix that before proceeding.

---

## Step 2: Quick Access via File Manager

The fastest way to access an SMB share is through your file manager's address bar.

**GNOME Files (Nautilus):**
1. Press `Ctrl+L` to open the location bar.
2. Type `smb://SERVER/SHARE_NAME` and press Enter.
3. Enter your domain, username, and password when prompted.

**KDE Dolphin / XFCE Thunar / Cinnamon Nemo:**
Same approach — type the `smb://` URL in the address bar.

This uses GVFS under the hood and requires `gvfs-backends` (installed by default on most desktop Ubuntu/Fedora). It works but doesn't survive a reboot and won't show up as a regular path under `/mnt`.

---

## Step 3: Store Credentials Securely

For persistent mounts, store your credentials in a file that only root can read:

```bash
sudo bash -c 'cat > /etc/smbcredentials' <<EOF
username=YOUR_USER
password=YOUR_PASS
domain=YOUR_DOMAIN
EOF
sudo chmod 600 /etc/smbcredentials
```

The `chmod 600` ensures only root can read this file. Never put credentials directly in `/etc/fstab` — anyone who can read fstab (every user on the system) would see them.

If your share allows anonymous access, you won't need a credentials file — use `guest,sec=none` as mount options instead.

---

## Step 4: Create the Mount Point

```bash
sudo mkdir -p /mnt/my_share
```

Pick a path that makes sense. Common conventions:
- `/mnt/share_name` — traditional location
- `/media/share_name` — more common for removable media
- `/srv/share_name` — if it's a data source for services

---

## Step 5: Add the fstab Entry

### Basic (mount at boot)

```bash
echo '//SERVER/SHARE_NAME /mnt/my_share cifs credentials=/etc/smbcredentials,uid=1000,gid=1000,iocharset=utf8,nofail 0 0' | sudo tee -a /etc/fstab
```

Key options:
| Option | Purpose |
|--------|---------|
| `credentials=` | Path to the credentials file |
| `uid=1000,gid=1000` | Files appear owned by your user (check your UID with `id -u`) |
| `iocharset=utf8` | Proper handling of non-ASCII filenames |
| `nofail` | Don't block boot if the server is unreachable |

### With Automount (recommended)

The basic approach tries to mount at boot — if the server is unreachable (VPN off, server down), the mount silently fails. You'd then need to run `sudo mount -a` manually after connecting.

A better approach uses systemd automount — the share mounts only when you access the directory:

```bash
echo '//SERVER/SHARE_NAME /mnt/my_share cifs credentials=/etc/smbcredentials,uid=1000,gid=1000,iocharset=utf8,noauto,x-systemd.automount,x-systemd.idle-timeout=60,nofail 0 0' | sudo tee -a /etc/fstab
```

The additional options:

| Option | Purpose |
|--------|---------|
| `noauto` | Don't mount at boot |
| `x-systemd.automount` | systemd creates a trigger — first access to the directory initiates the mount |
| `x-systemd.idle-timeout=60` | Unmount after 60 seconds of inactivity |

This is the best approach when you're not always on the same network. The directory appears to exist, and the actual SMB connection only happens when something reads from it.

After editing fstab, reload systemd:

```bash
sudo systemctl daemon-reload
sudo mount -a
```

Verify:

```bash
ls /mnt/my_share
```

---

## Step 6: Add a File Manager Bookmark

The mount at `/mnt/my_share` works from the terminal, but won't appear in your file manager sidebar by default. Fix that:

```bash
echo "file:///mnt/my_share" >> ~/.config/gtk-3.0/bookmarks
```

Note the **three slashes** in `file:///` — `file://` is the protocol, and the third `/` is the root of the filesystem path. Two slashes will result in a broken bookmark.

Close and reopen your file manager. The share now appears in the sidebar.

---

## Putting It All Together: A Setup Script

Here's a reusable script that handles everything — install, credentials, fstab (with automount), and bookmarks. It's idempotent: safe to run multiple times.

```bash
#!/bin/bash
set -e

BOOKMARK_FILE="$HOME/.config/gtk-3.0/bookmarks"
mkdir -p "$(dirname "$BOOKMARK_FILE")"

# Install cifs-utils if missing
if ! dpkg -s cifs-utils &>/dev/null; then
    echo "Installing cifs-utils..."
    sudo apt install -y cifs-utils
fi

mount_share() {
    local SHARE="$1"
    local MOUNT_POINT="$2"
    local MOUNT_OPTS="$3"
    local NAME="$4"

    echo ""
    echo "=== Setting up $NAME ==="

    sudo mkdir -p "$MOUNT_POINT"

    # Remove old fstab entry if present, then add correct one
    local FSTAB_LINE="$SHARE $MOUNT_POINT cifs $MOUNT_OPTS,uid=$(id -u),gid=$(id -g),iocharset=utf8,noauto,x-systemd.automount,x-systemd.idle-timeout=60,nofail 0 0"
    if grep -qF "$SHARE" /etc/fstab; then
        sudo sed -i "\|$SHARE|d" /etc/fstab
        echo "Removed old fstab entry"
    fi
    echo "$FSTAB_LINE" | sudo tee -a /etc/fstab >/dev/null
    echo "Added fstab entry with automount"

    # Reload and mount
    sudo systemctl daemon-reload
    sudo mount -a

    # Verify
    if mountpoint -q "$MOUNT_POINT"; then
        echo "Success! $NAME mounted at $MOUNT_POINT"
    else
        echo "ERROR: $NAME mount failed. Check dmesg for details."
    fi

    # Add Nautilus sidebar bookmark
    local BOOKMARK="file://$MOUNT_POINT"
    if ! grep -qF "$BOOKMARK" "$BOOKMARK_FILE" 2>/dev/null; then
        echo "$BOOKMARK" >> "$BOOKMARK_FILE"
        echo "Added $NAME bookmark to file manager sidebar"
    else
        echo "Bookmark already exists"
    fi
}

# --- Create credentials file if needed ---
CRED_FILE="/etc/smbcredentials"
if [ ! -f "$CRED_FILE" ]; then
    read -p "SMB Username: " SMB_USER
    read -sp "SMB Password: " SMB_PASS
    echo
    read -p "Domain: " SMB_DOMAIN

    sudo bash -c "cat > $CRED_FILE" <<EOF
username=$SMB_USER
password=$SMB_PASS
domain=$SMB_DOMAIN
EOF
    sudo chmod 600 "$CRED_FILE"
    echo "Credentials saved to $CRED_FILE"
fi

# --- Mount shares ---
mount_share "//SERVER/SHARE1" "/mnt/share1" "credentials=$CRED_FILE" "Share 1"
mount_share "//SERVER/SHARE2" "/mnt/share2" "credentials=$CRED_FILE" "Share 2"

echo ""
echo "=== All done! ==="
```

Customize the `mount_share` calls at the bottom for your shares. The script handles both fresh installs and updates to existing mounts.

---

## Troubleshooting

### "cannot mount read-only"
Install `cifs-utils` — this error means the mount helper is missing.

### `NT_STATUS_ACCESS_DENIED`
Wrong credentials, wrong domain, or the share requires specific permissions. Test with `smbclient` first.

### `NT_STATUS_LOGON_FAILURE`
Authentication failed. Check:
- Is the domain correct? Try with and without it.
- Is the password for this specific server (not your Linux login)?
- Some shares allow anonymous access — try `-N` flag with `smbclient`.

### Mount works but file manager bookmark shows error
Check that the bookmark path has three slashes: `file:///mnt/...` not `file://mnt/...`.

### Shares don't mount after reboot (without automount)
If VPN wasn't connected at boot, `nofail` let the system start without mounting. Run `sudo mount -a` after connecting, or switch to the automount approach.

### Permission denied on mounted files
Adjust `uid` and `gid` in the fstab options to match your user. Check with `id -u` and `id -g`.

---

## Summary

| Approach | Survives Reboot | Needs VPN at Boot | Auto-connects |
|----------|:-:|:-:|:-:|
| File manager `smb://` URL | No | N/A | No |
| fstab with `nofail` | Yes | Yes (or fails silently) | At boot only |
| fstab with `x-systemd.automount` | Yes | No | On access |

The automount approach gives you the best of all worlds: the shares appear as regular directories, connect only when needed, disconnect when idle, and never block your boot process.
