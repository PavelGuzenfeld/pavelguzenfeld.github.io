---
title: Natural Skies and Satellite Terrain in a Headless Unity Simulation
date: 2026-04-04
draft: false
tags:
- Unity
- Docker
- terrain
- SRTM
- satellite
- skybox
- shader
- headless
- Vulkan
- RTSP
- FFmpeg
- NVENC
- simulation
keywords:
- Unity headless terrain satellite imagery
- SRTM heightmap Unity runtime
- Unity procedural skybox headless
- h264_nvenc Docker Unity
- world-space terrain shader Unity
cover:
  image: /images/posts/unity-satellite-terrain.png
  alt: Satellite terrain and natural sky in headless Unity simulation
categories:
- deep-dive
summary: How I replaced flat brown terrain and solid-color sky in a headless Unity
  6 Docker simulation with real satellite imagery, SRTM topography, and a custom panoramic
  skybox — all fully air-gapped, no runtime network dependency. Includes NVENC GPU
  encoding, custom shaders, and every dead end along the way.
ShowToc: true
audio:
  pronunciation:
    Unity: Unity
    Unity 6: Unity six
    SRTM: S R T M
    DTM: D T M
    ESRI: Ezri
    World Imagery: world imagery
    tile server: tile server
    ArcGIS: arc G I S
    arcgisonline.com: arc G I S online dot com
    TerrainData: terrain data
    Terrain.CreateTerrainGameObject: terrain dot create terrain game object
    TerrainCollider: terrain collider
    Skybox/Panoramic: skybox slash panoramic
    Custom/SkyboxPanoramic: custom skybox panoramic
    Custom/WorldSpaceTerrain: custom world space terrain
    Shader.Find: shader dot find
    RenderSettings.skybox: render settings dot skybox
    RenderSettings.fog: render settings dot fog
    GraphicsSettings.asset: graphics settings dot asset
    m_AlwaysIncludedShaders: M underscore always included shaders
    AmbientMode: ambient mode
    Resources.Load: resources dot load
    GetPixels: get pixels
    isReadable: is readable
    SimpleCameraCapture: simple camera capture
    CameraClearFlags: camera clear flags
    CameraClearFlags.SolidColor: camera clear flags solid color
    CameraClearFlags.Skybox: camera clear flags skybox
    LateUpdate: late update
    EnvironmentSetup: environment setup
    MonoBehaviour: mono behavior
    Vulkan: vulkan
    HDRP: H D R P
    Built-in RP: built in R P
    FFmpeg: F F mpeg
    ffmpeg: F F mpeg
    NVENC: N V enc
    h264_nvenc: H two six four N V enc
    libx264: lib X two six four
    RTSP: R T S P
    .hgt: dot H G T
    .hdr: dot H D R
    HDRI: H D R I
    Reinhard: Reinhard
    Poly Haven: Poly Haven
    GeoTIFF: geo tiff
    ApplicationSetting.yaml: application setting dot yaml
    UseInstalledFFmpeg: use installed F F mpeg
    tonemap: tone map
    createTonemapReinhard: create tone map Reinhard
    AsyncGPUReadback: async G P U readback
    RTX 3060: R T X thirty sixty
    WorldSpaceTerrain.shader: world space terrain dot shader
    SkyboxPanoramic.shader: skybox panoramic dot shader
    atan2: A tan two
    tex2Dlod: tex two D L O D
    tex2D: tex two D
    UnityCG.cginc: unity C G dot C G inc
    UnityObjectToClipPos: unity object to clip pos
    UnityObjectToWorldNormal: unity object to world normal
    unity_ObjectToWorld: unity object to world
    _WorldSpaceLightPos0: world space light pos zero
---

## Context

This is the third post in a series about running a Unity simulation headless in Docker:

1. [Running Unity Headless in Docker with GPU Rendering and RTSP Streaming](/posts/headless-unity-docker-simulation/) — got the simulation running with camera streams
2. [From Magenta to Desert: Fixing Cross-Platform Unity Terrain Rendering](/posts/unity6-terrain-rendering-cross-platform-asset-bundles/) — fixed broken shaders and materials from cross-platform asset bundles

After those posts, the simulation rendered correctly — buildings had textures, the streaming cameras showed proper imagery, and material shaders were fixed at runtime. But two things still looked terrible:

- **The sky**: a flat, solid blue rectangle. No sun, no clouds, no gradient.
- **The terrain beyond the asset bundle**: a uniform brown void extending to a hard edge where the mesh ended.

This post documents the journey from "functional but ugly" to "looks like a real desert" — entirely with baked assets that work in air-gapped environments.

```
Before:                                 After:
┌────────────────────────────┐   ┌────────────────────────────┐
│  SOLID BLUE                │   │   ☁   ☀    ☁              │
│                            │   │        sky gradient         │
│ ████████████████████████   │   │ ▲  ▲▲   ▲    hills        │
│ █ BROWN VOID ████████████  │   │  ╲╱ ╲╱ ╲╱  satellite      │
│ █ (flat solid color) █████ │   │  roads, wadis, terrain     │
│ ██ buildings ██████████████│   │  ██ buildings ████████████ │
└────────────────────────────┘   └────────────────────────────┘
```

## The Problems

### Problem 1: Solid Color Sky

The streaming cameras use `CameraClearFlags.Skybox`, which should render the skybox material behind all geometry. Unity's built-in `Skybox/Procedural` shader generates a sky gradient with a sun disc based on the scene's directional light.

**What I saw**: a uniform flat blue rectangle, identical from every angle.

**Root cause** (took hours to find): In `SimpleCameraCapture.LateUpdate()`, the camera properties were being forced **every frame** before rendering:

```csharp
// This ran every frame, overriding ANY skybox set by other scripts
camera.clearFlags = CameraClearFlags.SolidColor;
camera.backgroundColor = new Color(0.53f, 0.63f, 0.75f);
camera.farClipPlane = 600f;
```

This was leftover from an earlier workaround for magenta rendering. It overrode the skybox clear flags milliseconds before `camera.Render()`, so no skybox shader ever executed. The procedural sky was set up correctly — it just never rendered.

**Fix**: Remove the per-frame override. Let the camera's `clearFlags` be set once during initialization and stay as `Skybox`.

### Problem 2: Brown Terrain Void

The simulation uses a pre-built terrain asset bundle that covers a small area (~2km). Beyond the bundle's mesh edges, there was nothing — the camera rendered the ground color of the skybox, creating a hard brown band at the horizon.

**Attempts that failed**:
- **Fog matched to sky color** — terrain shaders from the bundle didn't support Unity's built-in fog, so the fog only affected some objects
- **Reducing camera far clip** — hid the brown band but also clipped visible buildings
- **Loading a 6-sided cubemap skybox** — the textures didn't load in headless builds, rendering magenta

## The Solution: Baked Environment Assets

### Step 1: Satellite Imagery from Tile Servers

I downloaded satellite imagery tiles from a public tile server (ESRI World Imagery) and stitched them into a single texture.

At zoom level 13, each tile covers ~5km. A 13x13 grid gives ~65km coverage:

```bash
# Calculate tile coordinates for a center point
# At zoom 13: x = floor((lon + 180) / 360 * 8192)
#              y = floor((1 - ln(tan(lat*pi/180) + 1/cos(lat*pi/180)) / pi) / 2 * 8192)

X_CENTER=4882
Y_CENTER=3159
ZOOM=13
RADIUS=6

for dy in $(seq -$RADIUS $RADIUS); do
  for dx in $(seq -$RADIUS $RADIUS); do
    x=$((X_CENTER + dx))
    y=$((Y_CENTER + dy))
    curl -sf "https://server.arcgisonline.com/ArcGIS/rest/services/\
World_Imagery/MapServer/tile/${ZOOM}/${y}/${x}" \
      -o "tile_${y}_${x}.jpg" &
  done
  wait
done
```

Stitching with Python (in Docker, since the host didn't have ImageMagick):

```python
from PIL import Image
GRID = 13
TILE_SIZE = 256
out = Image.new('RGB', (GRID * TILE_SIZE, GRID * TILE_SIZE))
for row, y in enumerate(range(Y_CENTER - 6, Y_CENTER + 7)):
    for col, x in enumerate(range(X_CENTER - 6, X_CENTER + 7)):
        tile = Image.open(f'tile_{y}_{x}.jpg')
        out.paste(tile, (col * TILE_SIZE, row * TILE_SIZE))
out.save('satellite.jpg', quality=90)
# Result: 3328x3328, ~3.6MB
```

### Step 2: SRTM Elevation Data

For real topography, I downloaded SRTM (Shuttle Radar Topography Mission) 30-meter resolution elevation data. SRTM tiles are freely available and cover most of the earth's surface.

```bash
# Download the SRTM tile (each tile covers 1 degree x 1 degree)
curl -fsSL "https://s3.amazonaws.com/elevation-tiles-prod/\
skadi/N31/N31E034.hgt.gz" -o N31E034.hgt.gz
gunzip N31E034.hgt.gz
# Result: 25MB, 3601x3601 grid of 16-bit elevations
```

Extract and convert to a Unity-compatible heightmap:

```python
import numpy as np
from PIL import Image

# Read SRTM .hgt (3601x3601, 16-bit big-endian signed integers)
with open('N31E034.hgt', 'rb') as f:
    data = f.read()
elevations = np.frombuffer(data, dtype='>i2').reshape((3601, 3601))

# Crop to area of interest (~33km around center)
# Convert lat/lon bounds to pixel coordinates
row_min, row_max = 2809, 3888  # derived from lat bounds
col_min, col_max = 1375, 2455  # derived from lon bounds
crop = elevations[row_min:row_max, col_min:col_max].copy()

# Replace voids, normalize to 0-255
crop[crop == -32768] = crop[crop != -32768].min()
normalized = ((crop - crop.min()) / (crop.max() - crop.min()) * 255).astype(np.uint8)
Image.fromarray(normalized, 'L').save('heightmap.png')
# Elevation range: 48m - 344m
```

**Important**: The heightmap texture must have `isReadable: 1` in its `.meta` file, otherwise Unity can't call `GetPixels()` at runtime:

```yaml
# heightmap.png.meta
TextureImporter:
  isReadable: 1
  textureCompression: 0  # no compression for accuracy
```

### Step 3: World-Space Terrain Shader

The naive approach of applying the satellite texture to terrain meshes with UV tiling created ugly repeating rectangular patches. The fix: a custom shader that maps texture coordinates based on **world position** instead of mesh UVs.

```hlsl
Shader "Custom/WorldSpaceTerrain"
{
    Properties
    {
        _MainTex ("Satellite Texture", 2D) = "white" {}
        _TerrainSize ("Terrain Size", Float) = 33000
    }
    SubShader
    {
        Tags { "RenderType"="Opaque" }
        Pass
        {
            CGPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #pragma multi_compile_fog
            #include "UnityCG.cginc"

            sampler2D _MainTex;
            float _TerrainSize;

            struct v2f
            {
                float4 pos : SV_POSITION;
                float2 uv : TEXCOORD0;
                float3 worldNormal : TEXCOORD1;
                UNITY_FOG_COORDS(2)
            };

            v2f vert(appdata_base v)
            {
                v2f o;
                o.pos = UnityObjectToClipPos(v.vertex);

                // UV from world position — no tiling artifacts
                float3 worldPos = mul(unity_ObjectToWorld, v.vertex).xyz;
                float halfSize = _TerrainSize * 0.5;
                o.uv.x = (worldPos.x + halfSize) / _TerrainSize;
                o.uv.y = (worldPos.z + halfSize) / _TerrainSize;

                o.worldNormal = UnityObjectToWorldNormal(v.normal);
                UNITY_TRANSFER_FOG(o, o.pos);
                return o;
            }

            fixed4 frag(v2f i) : SV_Target
            {
                fixed4 col = tex2D(_MainTex, i.uv);

                // Desert tint — shift greens toward sand
                float gray = dot(col.rgb, float3(0.3, 0.5, 0.2));
                float3 desert = float3(gray * 1.15, gray * 1.0, gray * 0.8);
                col.rgb = lerp(col.rgb, desert, 0.4);
                col.rgb *= 1.5; // midday brightness

                // Soft lighting
                float3 lightDir = normalize(_WorldSpaceLightPos0.xyz);
                float ndl = max(0.7, dot(i.worldNormal, lightDir));
                col.rgb *= ndl;

                UNITY_APPLY_FOG(i.fogCoord, col);
                return col;
            }
            ENDCG
        }
    }
}
```

Key design decisions:
- **World-space UVs**: Each position maps to a unique texture coordinate. No tiling, no repetition.
- **Desert tint**: The satellite imagery includes green agricultural areas that look out of place. A 40% blend toward warm sand tones fixes this.
- **High minimum lighting** (`max(0.7, ndl)`): prevents terrain from looking like evening/shadow.
- **Fog support**: `multi_compile_fog` ensures the shader participates in distance fog.

### Step 4: Runtime Environment Setup

A `MonoBehaviour` loads everything at runtime — no editor setup needed:

```csharp
public class EnvironmentSetup : MonoBehaviour
{
    void Start() { Invoke(nameof(Setup), 10f); } // after terrain bundle loads

    void Setup()
    {
        ApplySatelliteToBundle();  // retexture ground meshes
        SetupDTMTerrain();        // create 3D terrain backdrop
    }

    void ApplySatelliteToBundle()
    {
        Texture2D satellite = Resources.Load<Texture2D>("Terrain/satellite");
        Shader worldShader = Shader.Find("Custom/WorldSpaceTerrain");

        foreach (var renderer in FindObjectsByType<MeshRenderer>(FindObjectsSortMode.None))
        {
            Material[] mats = renderer.materials;
            for (int i = 0; i < mats.Length; i++)
            {
                if (mats[i].mainTexture != null) continue; // has texture, skip

                Color c = mats[i].color;
                bool isBuilding = (c.r > 0.6f && c.g > 0.6f && c.b > 0.6f)
                    || (Mathf.Abs(c.r - c.g) < 0.05f && Mathf.Abs(c.g - c.b) < 0.05f);

                if (isBuilding)
                    mats[i].color = new Color(0.65f, 0.63f, 0.60f); // concrete
                else
                {
                    mats[i] = new Material(worldShader);
                    mats[i].SetTexture("_MainTex", satellite);
                    mats[i].SetFloat("_TerrainSize", 33000f);
                }
            }
            renderer.materials = mats;
        }
    }

    void SetupDTMTerrain()
    {
        Texture2D heightmap = Resources.Load<Texture2D>("Terrain/heightmap");
        Texture2D satellite = Resources.Load<Texture2D>("Terrain/satellite");

        TerrainData td = new TerrainData();
        td.heightmapResolution = Mathf.ClosestPowerOfTwo(heightmap.width) + 1;
        td.size = new Vector3(33000, 296, 33000); // 296m = max - min elevation

        // Read heightmap into terrain
        int res = td.heightmapResolution;
        float[,] heights = new float[res, res];
        Color[] pixels = heightmap.GetPixels();
        for (int y = 0; y < res; y++)
            for (int x = 0; x < res; x++)
            {
                int px = Mathf.Clamp((int)((float)x / res * heightmap.width), 0, heightmap.width - 1);
                int py = Mathf.Clamp((int)((float)y / res * heightmap.height), 0, heightmap.height - 1);
                heights[y, x] = pixels[py * heightmap.width + px].grayscale;
            }
        td.SetHeights(0, 0, heights);

        // Position below the bundle terrain
        GameObject terrainGO = Terrain.CreateTerrainGameObject(td);
        terrainGO.transform.position = new Vector3(-16500, 43, -16500); // min_elev - offset

        // Remove collider to avoid physics interference
        Destroy(terrainGO.GetComponent<TerrainCollider>());
    }
}
```

### Step 5: Custom Panoramic Skybox Shader

Unity's built-in `Skybox/Panoramic` shader was stripped from headless builds because no material in the project referenced it. `Shader.Find("Skybox/Panoramic")` returned null at runtime.

**Solution 1** (didn't work): Create a `.mat` file in `Resources/` referencing the shader by its built-in fileID. The shader compiled but `Shader.Find` still returned null — the built-in shader stripping happens at a different stage.

**Solution 2** (worked): Write a custom equirectangular skybox shader:

```hlsl
Shader "Custom/SkyboxPanoramic"
{
    Properties
    {
        _MainTex ("Panorama", 2D) = "white" {}
        _Exposure ("Exposure", Range(0.1, 4.0)) = 1.0
        _Rotation ("Rotation", Range(0, 360)) = 0.0
    }
    SubShader
    {
        Tags { "Queue"="Background" "RenderType"="Background" "PreviewType"="Skybox" }
        Cull Off
        ZWrite Off
        Pass
        {
            CGPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #include "UnityCG.cginc"

            sampler2D _MainTex;
            float _Exposure;
            float _Rotation;

            struct v2f {
                float4 pos : SV_POSITION;
                float3 texcoord : TEXCOORD0;
            };

            v2f vert(appdata_base v)
            {
                v2f o;
                o.pos = UnityObjectToClipPos(v.vertex);
                // World-space direction for skybox sampling
                o.texcoord = mul((float3x3)unity_ObjectToWorld, v.vertex.xyz);
                return o;
            }

            fixed4 frag(v2f i) : SV_Target
            {
                float3 dir = normalize(i.texcoord);

                // Apply Y-axis rotation
                float rad = _Rotation * UNITY_PI / 180.0;
                float s = sin(rad), c = cos(rad);
                dir = float3(dir.x * c - dir.z * s, dir.y, dir.x * s + dir.z * c);

                // Equirectangular projection
                float2 uv;
                uv.x = atan2(dir.z, dir.x) / (UNITY_PI * 2.0) + 0.5;
                uv.y = asin(clamp(dir.y, -1.0, 1.0)) / UNITY_PI + 0.5;

                fixed4 col = tex2Dlod(_MainTex, float4(uv, 0, 0));
                col.rgb *= _Exposure;
                return col;
            }
            ENDCG
        }
    }
}
```

The key insight: `unity_ObjectToWorld` transforms the skybox mesh vertex positions to world-space directions. Without this transform, the shader sees object-space coordinates that don't account for the camera's orientation, producing a static texture that doesn't rotate with the camera.

**HDR to LDR conversion**: The HDRI panorama (`.hdr` Radiance format) didn't render correctly via Vulkan in headless mode. Converting to tone-mapped JPEG fixed it:

```python
import cv2
hdr = cv2.imread('sky.hdr', cv2.IMREAD_ANYDEPTH | cv2.IMREAD_ANYCOLOR)
tonemap = cv2.createTonemapReinhard(gamma=1.5, intensity=0.5, light_adapt=0.6)
ldr = tonemap.process(hdr)
ldr = (ldr * 255).clip(0, 255).astype('uint8')
cv2.imwrite('sky_ldr.jpg', ldr)
```

## NVENC GPU Encoding

The simulation runs 3 RTSP camera streams at 1920x1080@30fps. With CPU encoding (`libx264`), each FFmpeg process consumed ~49% CPU (1.5 cores total for 3 streams).

### The Problem

The bundled FFmpeg binary didn't have NVENC support:

```bash
$ /opt/build/ffmpeg -encoders | grep nvenc
# (nothing)
$ /opt/build/ffmpeg -hwaccels
# vdpau, vaapi — no cuda/nvenc
```

But the system FFmpeg (from `apt`) did:

```bash
$ ffmpeg -encoders | grep nvenc
V..... h264_nvenc   NVIDIA NVENC H.264 encoder
```

### The Fix

The simulation code had a `UseInstalledFFmpeg` config flag that switches between the bundled and system FFmpeg:

```yaml
# ApplicationSetting.yaml
ApplicationSetting:
  UseInstalledFFmpeg: true  # use system ffmpeg with NVENC
```

And the streaming config:

```json
{
  "GeneralSettings": "-y -f rawvideo -vcodec rawvideo -pixel_format rgba -colorspace bt709",
  "PresetSettings": "-pix_fmt yuv420p -c:v h264_nvenc -preset llhp -b:v 3M -fflags nobuffer",
  "OutputSettings": " -f rtsp -rtsp_transport tcp ",
  "FrameRate": 30
}
```

### Results

| Metric | CPU (libx264) | GPU (h264_nvenc) |
|--------|--------------|------------------|
| FFmpeg CPU (3 streams) | 147% | 46% |
| Total container CPU | 323% | 201% |
| GPU utilization | 19% | 40% |
| GPU memory | 1.5 GB | 1.9 GB |
| Render FPS | 23 | 19 |

The CPU savings are significant — 1.2 fewer cores consumed. The render FPS dropped slightly (23 to 19) because the GPU now handles both rendering and encoding. For most simulation scenarios, 19fps is adequate, and the freed CPU headroom is valuable for other workloads (autopilot simulation, networking, logging).

## Dead Ends and Lessons

### 1. Fog Doesn't Work on All Shaders

Unity's `RenderSettings.fog` only affects shaders that include `multi_compile_fog`. The terrain asset bundle's shaders (converted from HDRP to Standard at runtime) didn't include fog compilation variants. Enabling fog with a sky-matching color did nothing to the terrain — it only affected a few objects that happened to use Standard shader variants with fog support.

### 2. Camera Far Clip Creates Hard Edges

Setting `camera.farClipPlane = 300f` did hide the brown terrain void, but it also clipped buildings at the edges of the view and created a jarring hard edge where geometry suddenly disappeared. A gradual solution (fog + extended terrain) is always better than a hard cutoff.

### 3. Per-Frame Property Overrides Are Silent Killers

The `CameraClearFlags.SolidColor` override in `LateUpdate` was invisible — no errors, no warnings. The skybox shader compiled and loaded successfully, the material was assigned correctly, but every frame the camera reset to solid color right before rendering. This cost hours of debugging because every diagnostic showed the skybox was "working."

**Rule**: Never set camera properties in a render loop unless you're absolutely sure no other system needs to modify them.

### 4. Unity Strips Unused Shaders Aggressively

`Shader.Find("Skybox/Panoramic")` returns null in builds if no material references the shader. Creating a dummy `.mat` file in `Resources/` that references the shader by its built-in fileID (108) ensures it's included in the build — but only if Unity's shader stripping pass sees the reference. For custom shaders placed in `Resources/`, Unity always includes them.

### 5. HDRI Panoramas Need Tone Mapping for LDR Pipelines

HDR Radiance (`.hdr`) files contain floating-point pixel values with a huge dynamic range. Unity's Built-in Render Pipeline in headless Vulkan mode doesn't tone-map HDR skybox textures correctly. Pre-converting to JPEG with Reinhard tone mapping produces reliable results.

### 6. World-Space UVs Beat Tiling

Applying a satellite texture with `material.SetTextureScale("_MainTex", new Vector2(50, 50))` creates an obvious repeating grid pattern. A world-space shader maps each vertex to a unique texture coordinate based on its world position — zero repetition, seamless across mesh boundaries.

## Architecture Summary

```
┌─ Resources/ (baked into build, no network needed) ──────┐
│                                                          │
│  Sky/desert_sky_ldr.jpg    2048x1024 HDRI panorama       │
│  Terrain/satellite.jpg     3328x3328 satellite mosaic    │
│  Terrain/heightmap.png     1079x1080 SRTM elevations     │
│  Shaders/WorldSpaceTerrain.shader                        │
│  Shaders/SkyboxPanoramic.shader                          │
└──────────────────────────────────────────────────────────┘

Runtime loading sequence:
  t=0s   Unity starts, terrain bundle begins loading
  t=3s   Terrain bundle loaded, bundle scene active
  t=8s   TerrainMaterialFix: fix broken shaders, set procedural sky
  t=18s  EnvironmentSetup:
         1. Load panoramic HDRI → set as skybox
         2. Apply satellite texture to untextured ground meshes
         3. Create 33km Unity Terrain from SRTM heightmap
         4. Apply satellite texture to DTM terrain
```

## Air-Gapped Deployment

Everything in this solution works without network access at runtime:

- **Satellite tiles**: downloaded once, stitched, baked into the Unity build
- **SRTM elevation**: downloaded once, processed to heightmap PNG, baked in
- **HDRI sky**: downloaded once from Poly Haven (CC0 license), tone-mapped, baked in
- **Custom shaders**: compiled into the build, no runtime shader compilation

The Docker image contains everything needed. No API keys, no tile servers, no CDN dependencies.

```bash
docker run --gpus all \
  -v /path/to/Entities.yaml:/config/Entities.yaml \
  -p 8554:8554 -p 4900:4900 \
  simulation-headless
```

Total added asset size: ~10MB (satellite 3.6MB + heightmap 43KB + HDRI 674KB + shaders <10KB).
