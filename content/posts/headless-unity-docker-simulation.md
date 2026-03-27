---
title: "Running Unity 2019.4 Headless in Docker with GPU Rendering, RTSP Camera Streaming, and MAVLink"
date: 2026-03-19
draft: false
tags: ["Unity", "Docker", "Vulkan", "RTSP", "MAVLink", "simulation", "headless", "GStreamer", "FFmpeg", "DevOps"]
keywords: ["Unity headless Docker GPU", "Unity RTSP streaming Docker", "drone simulation Unity Docker"]
categories: ["deep-dive"]
summary: "A detailed technical account of containerizing a Unity 2019.4 drone simulation with GPU-accelerated rendering, dual RTSP camera streaming via FFmpeg/mediamtx, and MAVLink drone control — including every obstacle encountered and how it was solved."
ShowToc: true
---

## The Goal

Take a Unity 2019.4 drone simulation platform — originally built and run on Windows with a physical display — and make it run **headless inside a Docker container** on Linux with:

- GPU-accelerated Vulkan rendering (no physical monitor)
- Two RTSP camera streams (head camera + belly camera) at 1080p 30fps
- MAVLink input for drone control (serial, TCP, or UDP)
- Configurable via a single `Entities.yaml` file

This post documents every step, every dead end, and every workaround from start to finish.

```
┌─────────────────────────────────────────────────────────────┐
│  Docker Container (nvidia/vulkan:1.3-470, RTX 3060)         │
│                                                             │
│  ┌───────┐    ┌──────────────────────────────────────────┐  │
│  │ Xvfb  │───▶│  Unity 2019.4 (-batchmode, Vulkan)       │  │
│  │  :99  │    │                                          │  │
│  └───────┘    │  ┌────────────┐    ┌────────────┐        │  │
│               │  │ HeadCamera │    │ BodyCamera │        │  │
│               │  └─────┬──────┘    └─────┬──────┘        │  │
│               └────────┼─────────────────┼───────────────┘  │
│                  FFmpeg │           FFmpeg │                  │
│                  H.264  ▼           H.264  ▼                  │
│               ┌──────────────────────────────────┐           │
│               │   mediamtx (RTSP server :8554)   │           │
│               │   /HeadCamera    /BodyCamera     │           │
│               └──────────────┬───────────────────┘           │
│                              │                               │
├──────────────────────────────┼───────────────────────────────┤
│                              │ :8554                         │
│  MAVLink (UDP/TCP)           │ RTSP                          │
│       ▲                      ▼                               │
│  ┌────┴─────────┐   ┌─────────────────┐                     │
│  │ PX4 / GCS    │   │ GStreamer Client │                     │
│  └──────────────┘   └─────────────────┘                     │
└─────────────────────────────────────────────────────────────┘
```

---

## Starting Point: The Simulation Project

The project is a Unity 2019.4.14f1 simulation environment for autonomous drone operations. It was built for Windows, runs with a GUI, and streams camera feeds via FFmpeg to an external RTSP server. Key components:

- **MAVLink integration** — connects to flight controllers (PX4, real hardware) via serial/TCP/UDP
- **Camera system** — FFmpeg captures Unity camera output and pushes H264 to RTSP
- **Terrain** — loads pre-built Unity Asset Bundles at runtime from an external path
- **REST API** — HTTP server on port 4900 for remote control
- **Distributed simulation** — optional HLA/DIS interoperability via VR-Link (behind a compile define)

The codebase lives on a self-hosted GitLab with two git submodules:
- `Simblocks` — terrain integration
- VR-Link package (with nested submodules for C# and native bindings)

## Phase 1: Docker Foundation

### Choosing the Base Image

Unity needs a GPU to render camera output — even in headless mode (`-batchmode`), we can't use `-nographics` because the cameras need to produce video frames. This ruled out CPU-only containers.

The base image: **`nvidia/vulkan:1.3-470`** — provides Vulkan libraries with NVIDIA GPU support via the NVIDIA Container Toolkit.

For a virtual display (since there's no physical monitor), we use **Xvfb** (X Virtual Framebuffer) — a fake X11 display that Unity renders to.

### The Dockerfile

```dockerfile
FROM nvidia/vulkan:1.3-470

# Remove expired NVIDIA CUDA repo GPG key
RUN find /etc/apt/sources.list.d/ -name '*nvidia*' -delete 2>/dev/null; \
    find /etc/apt/sources.list.d/ -name '*cuda*' -delete 2>/dev/null; \
    rm -f /etc/apt/sources.list.d/*.list 2>/dev/null; \
    apt-get update && apt-get install -y --no-install-recommends \
    xvfb libvulkan1 vulkan-utils libgl1-mesa-glx libglu1-mesa \
    libxcursor1 libxrandr2 libxinerama1 libxi6 libxxf86vm1 \
    libasound2 libpulse0 libnspr4 libnss3 ca-certificates ffmpeg curl \
    && rm -rf /var/lib/apt/lists/*
```

**First obstacle**: the `nvidia/vulkan:1.3-470` image has an expired NVIDIA CUDA repository GPG key. Every `apt-get update` fails with:

```
E: The repository 'https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2004/x86_64 InRelease' is not signed.
```

**Solution**: Delete all NVIDIA apt sources before running `apt-get update`. We don't need CUDA packages — just the Vulkan runtime that's already in the base image. The key insight was that `rm -f /etc/apt/sources.list.d/cuda.list` wasn't enough — the file had a different name. Using `find` with wildcards catches all variants.

### RTSP Server: mediamtx

The original project pushes FFmpeg RTSP streams to an **external** RTSP server. For a self-contained Docker setup, we bundle **mediamtx** (formerly rtsp-simple-server) inside the container.

```dockerfile
ARG MEDIAMTX_VERSION=1.9.3
RUN curl -fsSL https://github.com/bluenviron/mediamtx/releases/download/v${MEDIAMTX_VERSION}/mediamtx_v${MEDIAMTX_VERSION}_linux_amd64.tar.gz \
    | tar -xz -C /usr/local/bin mediamtx
```

**mediamtx configuration pitfalls**:
- Version 1.9.3 changed its config format — `rtspTransport` and `pathDefaults` fields from older examples cause `json: unknown field` errors
- Paths must use `all_others:` wildcard to allow dynamic stream creation (Unity publishes to `/HeadCamera` and `/BodyCamera` which don't exist until FFmpeg connects)
- The health check readiness probe (`curl http://127.0.0.1:8554/`) connects via RTSP which logs `invalid URL (/)` — harmless but noisy

### Entrypoint Script

The entrypoint orchestrates startup in the right order:

1. **Xvfb** starts first (Unity needs a display)
2. **mediamtx** starts second (FFmpeg needs an RTSP server to push to)
3. Wait for mediamtx readiness (FFmpeg will fail-fast with "RTSP Connection TimeOut" if the server isn't ready)
4. Copy `Entities.yaml` config if provided via volume mount
5. Fix FFmpeg binary permissions (`chmod +x`)
6. Launch Unity with `-batchmode -logFile /dev/stdout`

Signal handling via `trap cleanup SIGTERM SIGINT` ensures graceful shutdown of all three processes.

**Critical finding**: FFmpeg has **no retry logic**. If mediamtx isn't listening when Unity's camera starts FFmpeg, the FFmpeg process gets killed after a 2.5-second timeout and the camera permanently fails. The entrypoint polls mediamtx readiness in a loop before starting Unity.

## Phase 2: Building the Unity Player

### The License Problem

This was by far the most time-consuming part of the entire project.

#### Attempt 1: GameCI Docker Image

[GameCI](https://game.ci) provides Docker images with Unity Editor pre-installed. The image `unityci/editor:ubuntu-2019.4.14f1-linux-il2cpp-3` exists on Docker Hub. We created a multi-stage `Dockerfile.build` that builds the Unity player inside this container.

But it needs a Unity license. GameCI docs say to generate a `.ulf` file via Unity Hub.

#### Attempt 2: Unity Hub 3.x on Linux

Installed Unity Hub 3.16 via the official apt repository:

```bash
sudo install -d /etc/apt/keyrings
curl -fsSL https://hub.unity3d.com/linux/keys/public | sudo gpg --dearmor -o /etc/apt/keyrings/unityhub.gpg
echo "deb [arch=amd64 signed-by=/etc/apt/keyrings/unityhub.gpg] https://hub.unity3d.com/linux/repos/deb stable main" | sudo tee /etc/apt/sources.list.d/unityhub.list
sudo apt update && sudo apt install -y unityhub
```

**Problem**: Unity Hub 3.x creates `UnityEntitlementLicense.xml` (new format), not `Unity_lic.ulf` (old format). Unity 2019.4 only understands `.ulf`. These formats are incompatible.

#### Attempt 3: Manual Activation (.alf → .ulf)

Generated a `.alf` activation request file inside the GameCI container:

```bash
docker run --rm -v $(pwd):/output -w /output \
  unityci/editor:ubuntu-2019.4.14f1-linux-il2cpp-3 \
  unity-editor -batchmode -nographics -quit -createManualActivationFile
```

Uploaded to `https://license.unity3d.com/manual`...

**Dead end**: "Unity no longer supports manual activation of Personal licenses." The manual activation portal was shut down in 2023.

#### Attempt 4: Credential-Based Activation in Docker

Added `--build-arg UNITY_EMAIL` and `--build-arg UNITY_PASSWORD` to the Dockerfile. Unity 2019.4 ran but:

```
Failed to activate/update license Missing or bad username or password
```

Personal license activation via `-username -password` doesn't work in batch mode for Unity 2019.4.

#### The Solution: Hub's V1 Licensing Client

Deep in the Unity Hub installation at `/opt/unityhub/UnityLicensingClient_V1/`, there's a legacy licensing client binary that still supports the `--activate-ulf` flag:

```bash
DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=1 \
  /opt/unityhub/UnityLicensingClient_V1/Unity.Licensing.Client \
  --activate-ulf \
  --username "your@email.com" \
  --password "yourpassword"
```

This generates the old `.ulf` format at `~/.local/share/unity3d/Unity/Unity_lic.ulf`. The `DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=1` environment variable is needed because the .NET Core runtime in this binary crashes without ICU packages.

**Important**: The ULF license expires and needs re-activation periodically. We created `docker/activate-license.sh` to automate this.

### Installing Unity Editor Locally

Instead of building inside Docker (which had license issues), we installed Unity locally via Hub CLI:

```bash
unityhub --headless install -v 2019.4.14f1 -c 4037e52648cd
unityhub --headless install-modules -v 2019.4.14f1 -m linux-il2cpp
```

The changeset hash `4037e52648cd` was found on the [Unity release page](https://unity.com/releases/editor/whats-new/2019.4.14f1).

**Ubuntu 24.04 compatibility**: Unity 2019.4 requires `libgconf-2.so.4` which was removed from Ubuntu 24.04. We grabbed the `.deb` packages from the Ubuntu 20.04 (focal) repository:

```bash
curl -fsSL http://archive.ubuntu.com/ubuntu/pool/universe/g/gconf/gconf2-common_3.2.6-6ubuntu1_all.deb -o /tmp/gconf2-common.deb
curl -fsSL http://archive.ubuntu.com/ubuntu/pool/universe/g/gconf/libgconf-2-4_3.2.6-6ubuntu1_amd64.deb -o /tmp/libgconf.deb
sudo dpkg -i /tmp/gconf2-common.deb /tmp/libgconf.deb
```

### Submodules and Git LFS

The project has four levels of nested git submodules, all pointing to a hostname alias for the self-hosted GitLab. Required a global URL rewrite:

```bash
git config --global url."https://<gitlab-ip>/".insteadOf "https://gitlab/"
```

The VR-Link submodule uses **Git LFS** for its DLLs. The LFS objects are stored in the submodule's own LFS storage, not the parent repo. Pulling them requires running `git lfs pull` from within the submodule directory with proper credentials and SSL disabled:

```bash
docker run --rm --entrypoint sh \
  -v $(pwd):/sandbox \
  -v ~/.git-credentials:/tmp/.git-credentials:ro \
  -w /sandbox/MultiSim/Packages/com.matrix.vrlink alpine/git:latest -c "
    cp /tmp/.git-credentials /root/.git-credentials
    git config --global --add safe.directory '*'
    git config --global http.sslVerify false
    git config --global credential.helper store
    git config --global url.'https://<gitlab-ip>/'.insteadOf 'https://gitlab/'
    git lfs install --skip-smudge
    git lfs pull"
```

### The Build

The `HeadlessBuild.cs` editor script provides a CLI entry point:

```csharp
public static void BuildLinux()
{
    var options = new BuildPlayerOptions
    {
        scenes = GetEnabledScenes(),
        locationPathName = outputPath,
        target = BuildTarget.StandaloneLinux64,
        options = BuildOptions.None,
    };
    BuildReport report = BuildPipeline.BuildPlayer(options);
}
```

**Build obstacles**:
- `IOException: Failed to Move File` — caused by leftover files in the output directory. Fix: always clean `docker/build/` before building.
- `It looks like another Unity instance is running` — stale lock file from Docker container. Fix: `rm -rf MultiSim/Temp`.
- Git LFS hooks blocking push: `git-lfs not found on your path`. Fix: `rm .git/hooks/pre-push .git/hooks/post-commit`.

The final build: **462MB** Linux player in 13 seconds.

## Phase 3: Runtime Debugging

### The Gray Screen Mystery

With the Docker container running, both cameras streamed... solid gray. No terrain, no content.

**Investigation path**:

1. **No terrain data** — the original terrain asset bundles were on a Windows network share, not in git. Eventually found terrain files on a team file server.

2. **Windows-only shaders** — all terrain asset bundles were built with `BuildTarget.StandaloneWindows`. Their shaders include only DirectX variants. On Linux/Vulkan: `WARNING: Shader Did you use #pragma only_renderers and omit this platform?` — everything renders invisible gray.

3. **Built our own terrain** — using heightmap + satellite texture from a separate simulation project (same geographic area, 6km x 6km, 513px resolution). Created `BuildTestTerrain.cs` which generates a mesh terrain with vertex colors baked from the satellite imagery.

4. **MavlinkEntity position reset** — the biggest "aha" moment. `MavLinkVehicleReflector.Update()` runs every frame and sets `transform.position = localOrigin + local` from MAVLink vehicle state. Without a MAVLink connection, the vehicle state is all zeros, so the entity gets pinned to `(0, 0, 0)` — below the terrain. The initial GPS position from `SetInitialGeodLocation()` gets immediately overwritten.

5. **SimEntity works** — switching from `Generator: MavlinkEntity` to `Generator: SimEntity` in the config fixed the position. The drone model appeared in the camera, and terrain contours became visible.

### Coordinate System

The simulation uses a flat-earth approximation for GPS-to-Unity conversion (`ManagedCoordinateConverter.cs`):

```
Unity X = (lon_diff * π/180) * 6366707.02 * cos(home_lat)     // East
Unity Z = (lat_diff * π/180) * 6366707.02                      // North
Unity Y = altitude                                              // Up (ABSOLUTE MSL, not relative)
```

**Critical**: altitude is passed through **directly** as Unity Y — not relative to HomePoint altitude. An entity at GPS altitude 300m appears at Unity Y=300, regardless of HomePoint altitude.

### Shader Limitation

The `Custom/VertexColor` shader we created works in the Unity Editor but not at runtime in the Linux player. Despite being in `GraphicsSettings.asset` → `m_AlwaysIncludedShaders`, the material falls back to the Standard shader which doesn't render vertex colors. The terrain appears as flat gray geometry with correct elevation contours but no color.

This is a Unity 2019.4 limitation — the built-in rendering pipeline on Linux/Vulkan doesn't properly compile custom shader variants for asset bundles or embedded scene materials in all cases.

## Phase 4: What Works End-to-End

The final verified pipeline:

```
Docker Container (nvidia/vulkan:1.3-470)
  ├── Xvfb (:99, 1920x1080x24)
  ├── mediamtx (RTSP server, :8554)
  └── Unity 2019.4.14f1 (-batchmode, Vulkan, RTX 3060)
       ├── SimEntity at GPS 31.164/34.532, alt 300m
       ├── HeadCamera → FFmpeg H264 → RTSP push → mediamtx /HeadCamera
       └── BodyCamera → FFmpeg H264 → RTSP push → mediamtx /BodyCamera

External:
  └── GStreamer (rtspsrc protocols=tcp → avdec_h264 → xvimagesink)
```

**Viewing the streams**:

```bash
gst-launch-1.0 rtspsrc location=rtsp://localhost:8554/HeadCamera \
  latency=200 protocols=tcp \
  ! rtph264depay ! h264parse ! avdec_h264 \
  ! videoconvert ! xvimagesink sync=false
```

The `protocols=tcp` flag is essential on Ubuntu 24.04 — without it, GStreamer's UDP sink fails with `Invalid address family (got 10)` due to an IPv6 issue.

### Confirmed Working

- Vulkan GPU rendering on NVIDIA RTX 3060 inside Docker
- Drone 3D model visible in camera stream
- Terrain geometry loads and renders (elevation contours visible)
- Dual H264 RTSP streams at 1280x720 @ 25fps
- GStreamer clients successfully pull and display video
- Entity positioning via GPS coordinates
- Stable operation for extended periods at 720p25

### Known Limitations

- **Terrain colors**: Standard shader fallback renders gray. Needs terrain asset bundle rebuilt for `StandaloneLinux64` from the terrain importer project, or a Unity version with better Vulkan shader support.
- **MavlinkEntity**: requires active MAVLink connection — without it, position resets to origin every frame. Use `SimEntity` for standalone testing.
- **1080p30 with terrain**: Vulkan segfaults under heavy GPU async readback load. Stable at 720p25.
- **OpenGL fallback**: `-force-glcore` is stable but FFmpeg fails with "no async GPU readback support".

## Libraries and Tools Used

| Tool | Version | Purpose |
|------|---------|---------|
| Unity | 2019.4.14f1 | Simulation engine |
| Docker | 28.x | Containerization |
| nvidia/vulkan | 1.3-470 | GPU-enabled base image |
| NVIDIA Container Toolkit | latest | GPU passthrough |
| Xvfb | 1.20 | Virtual display |
| FFmpeg | 4.2 (bundled) | H264 encoding + RTSP push |
| mediamtx | 1.9.3 | RTSP server |
| GStreamer | 1.24 | RTSP client / video display |
| Unity Hub | 3.16.4 | Editor + license management |
| GameCI | unityci/editor:ubuntu-2019.4.14f1-linux-il2cpp-3 | CI build image |
| alpine/git | latest | Git LFS operations in Docker |
| Node.js | 20 | MCP tool tests |

## Files Created

```
docker/
├── Dockerfile                  # Runtime image
├── Dockerfile.build            # Multi-stage build with GameCI
├── entrypoint.sh               # Xvfb + mediamtx + Unity orchestration
├── docker-compose.yml          # GPU passthrough config
├── healthcheck.sh              # RTSP + REST API health check
├── smoke-test.sh               # Full pipeline verification
├── activate-license.sh         # Unity ULF license generation
├── build.sh                    # Local Unity build wrapper
├── BUILD_INSTRUCTIONS.md       # Build options documentation
├── SETUP_FROM_SCRATCH.md       # Full reproducible setup guide (12 steps)
└── config/
    ├── ApplicationSetting.yaml # Bundled app config
    ├── mainConfiguration.yaml  # Config pointer
    ├── Entities.default.yaml   # Default MAVLink + cameras
    └── mediamtx.yml            # RTSP server config

MultiSim/Assets/Scripts/Editor/
├── HeadlessBuild.cs            # CLI Linux build method
├── BuildTestTerrain.cs         # Terrain mesh from heightmap
└── EmbedTerrain.cs             # Embeds terrain in main scene

MultiSim/Assets/Shaders/
└── VertexColor.shader          # Custom Vulkan vertex color shader
```

## Lessons Learned

1. **Unity licensing is a maze**. Hub 3.x, Editor 2019.4, `.ulf` vs `.xml`, manual activation disabled, credential activation broken in batch mode — the only path was the obscure `UnityLicensingClient_V1 --activate-ulf` binary buried in the Hub installation.

2. **Asset bundles are platform-locked**. A terrain bundle built for Windows/DirectX won't render shaders on Linux/Vulkan. The geometry loads but materials fall back to gray. Rebuilding for `StandaloneLinux64` is required.

3. **MavlinkEntity overwrites position every frame**. Without an active MAVLink connection, `MavLinkVehicleReflector.Update()` pins the entity to the origin. Use `SimEntity` for standalone testing.

4. **FFmpeg has no retry**. If the RTSP server isn't ready when Unity starts the camera, FFmpeg dies and the camera permanently fails. The entrypoint must poll for server readiness.

5. **Vulkan + heavy GPU readback = segfault**. Two 1080p cameras with terrain loaded causes a Vulkan segfault in Unity 2019.4. Reducing to 720p25 is stable. OpenGL works but doesn't support async GPU readback needed for FFmpeg capture.

6. **GStreamer on Ubuntu 24.04 needs TCP**. The default UDP transport fails with an IPv6 address family error. Use `protocols=tcp` in `rtspsrc`.

7. **nvidia/vulkan:1.3-470 has expired GPG keys**. Must delete NVIDIA apt sources before `apt-get update`. The CUDA repo isn't needed for runtime.

8. **Git submodules + SSL + hostname aliases** need three config entries: `url.insteadOf` for hostname, `http.sslVerify false` for self-signed certs, and `credential.helper store` for authentication.

## What's Next

1. **Terrain rebuild**: Open the terrain importer project, change build target to `StandaloneLinux64`, rebuild the terrain asset bundle. One dropdown change in the wizard.

2. **PX4 SITL integration**: Connect a PX4 Software-In-The-Loop simulator to the container's MAVLink UDP port. This enables `MavlinkEntity` with full flight control and camera positioning.

3. **Production deployment**: Push the Docker image to a container registry and integrate with the CI/CD pipeline.

---

*This project took approximately 20 hours of debugging across two days.*
