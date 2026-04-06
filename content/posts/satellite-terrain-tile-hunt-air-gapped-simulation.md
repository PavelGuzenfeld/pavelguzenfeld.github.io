---
title: "The Satellite Tile Hunt: From 15m Blobs to 13cm Resolution in an Air-Gapped Simulation"
date: 2026-04-05
draft: false
tags: ["Unity", "Docker", "terrain", "satellite", "DTM", "GIS", "ESRI", "Google", "Mapzen", "simulation", "headless", "air-gapped", "Python"]
keywords: ["satellite imagery Unity terrain", "download satellite tiles Python", "Google satellite tiles offline", "Mapzen terrain tiles DTM", "Unity heightmap resolution", "digital terrain model Unity", "SRTM vs Copernicus DTM", "tile stitching Python", "air-gapped terrain simulation", "ESRI World Imagery download"]
cover:
  image: /images/posts/satellite-tile-hunt.png
  alt: "Satellite imagery comparison: 15m vs 0.13m resolution in headless Unity simulation"
categories: ["deep-dive"]
summary: "A practical guide to finding, downloading, and fusing satellite imagery and elevation data for an air-gapped Unity simulation. Covers every free tile provider (ESRI, Bing, Google), every free DTM source (SRTM, Copernicus, Mapzen), how to stitch thousands of tiles into Unity-ready textures, and the dead ends along the way."
ShowToc: true
---

## Context

This is the fourth post in a series about running a Unity simulation headless in Docker:

1. [Running Unity Headless in Docker with GPU Rendering and RTSP Streaming](/posts/headless-unity-docker-simulation/) — got the simulation running with camera streams
2. [From Magenta to Desert: Fixing Cross-Platform Unity Terrain Rendering](/posts/unity6-terrain-rendering-cross-platform-asset-bundles/) — fixed broken shaders and materials from cross-platform asset bundles
3. [Natural Skies and Satellite Terrain in a Headless Unity Simulation](/posts/unity-headless-environment-satellite-terrain-sky/) — added satellite imagery, SRTM topography, and panoramic skybox

The previous post got satellite imagery working — ESRI tiles at zoom 13, stitched into a JPEG, projected onto terrain via a world-space shader. It worked. But at 15 meters per pixel, buildings were indistinguishable blobs and roads were barely visible smears.

When I started flying a drone through the simulation with real camera feeds, I needed to actually *see* things on the ground. This post documents the hunt for maximum-resolution terrain data that works in an air-gapped (no runtime internet) simulation.

```
Zoom 13 (before):           Zoom 20 (after):
┌──────────────────┐        ┌──────────────────┐
│ ░░░░░░░░░░░░░░░░ │        │ ┌──┐  ╔══╗  ┌─┐ │
│ ░░░ blobs ░░░░░░ │        │ │  │  ║  ║  │ │ │
│ ░░░░░░░░░░░░░░░░ │        │ └──┘  ╚══╝  └─┘ │
│ ░░ 15m/pixel ░░░ │        │  road ═══════    │
│ ░░░░░░░░░░░░░░░░ │        │ 0.13m/pixel      │
└──────────────────┘        └──────────────────┘
```

## Part 1: Satellite Imagery

### Understanding Tile Zoom Levels

Web map providers (Google Maps, Bing, ESRI, OpenStreetMap) serve imagery as 256×256 pixel tiles at different zoom levels. Each zoom level doubles the resolution:

| Zoom | Meters/pixel | One tile covers | What you can see |
|------|-------------|----------------|-----------------|
| 13 | 15m | ~4 km | Cities as colored patches |
| 16 | 2.4m | ~500m | Building footprints |
| 18 | 0.6m | ~130m | Cars, individual trees |
| 20 | 0.13m | ~33m | Road markings, shadows of poles |

The tradeoff is coverage vs. detail. A 50 km area at zoom 20 would require hundreds of thousands of tiles and produce a ~400,000 pixel image. You need to pick an operational area and zoom in on that.

### How to Find the Max Zoom for Your Area

Not every provider has high-resolution imagery everywhere. The trick: **check the response body size**, not just the HTTP status code. Every provider returns `200 OK` at every zoom level. But real imagery produces 8–25 KB per tile, while upscaled placeholders are 1–3 KB.

```python
import requests, math

def tile_coords(lat, lon, zoom):
    """Convert lat/lon to tile x,y at given zoom."""
    n = 2 ** zoom
    x = int((lon + 180) / 360 * n)
    y = int((1 - math.log(math.tan(math.radians(lat)) +
            1/math.cos(math.radians(lat))) / math.pi) / 2 * n)
    return x, y

def check_provider(lat, lon, zoom, provider):
    """Check if a provider has real imagery at this zoom."""
    x, y = tile_coords(lat, lon, zoom)

    urls = {
        "esri": f"https://server.arcgisonline.com/ArcGIS/rest/services/"
                f"World_Imagery/MapServer/tile/{zoom}/{y}/{x}",
        "google": f"https://mt{x%4}.google.com/vt/lyrs=s&x={x}&y={y}&z={zoom}",
        "bing": f"https://ecn.t0.tiles.virtualearth.net/tiles/"
                f"a{quadkey(lat, lon, zoom)}.jpeg?g=14226",
    }

    r = requests.head(urls[provider], timeout=5, allow_redirects=True)
    size = int(r.headers.get("Content-Length", 0))
    return size > 3000  # True = real imagery

# Test your area
lat, lon = 40.7128, -74.0060  # example: NYC
for z in range(17, 22):
    for p in ["esri", "google", "bing"]:
        real = check_provider(lat, lon, z, p)
        print(f"  {p} z{z}: {'REAL' if real else 'upscaled'}")
```

When I tested my area of interest, the results were:

| Provider | Max real zoom | Resolution |
|----------|--------------|-----------|
| ESRI | 18 | 0.6m/pixel |
| Bing | 19 | 0.3m/pixel |
| **Google** | **20–21** | **0.06–0.13m/pixel** |

Google had the best coverage by far. Your results will vary by location — urban areas in developed countries tend to have the highest zoom available.

### Downloading and Stitching Tiles

Here's the complete pipeline to download, stitch, and produce a Unity-ready texture:

```python
#!/usr/bin/env python3
"""Download satellite tiles and stitch into a single texture."""
import requests
import math
from concurrent.futures import ThreadPoolExecutor, as_completed
from io import BytesIO
from PIL import Image

# === CONFIGURATION ===
CENTER_LAT = 40.7128      # your area center latitude
CENTER_LON = -74.0060     # your area center longitude
AREA_SIZE_M = 5000        # area size in meters (5km)
ZOOM = 20                 # max zoom with real imagery
TILE_SIZE = 256
MAX_UNITY_TEXTURE = 16384  # Unity's max texture dimension


def tile_coords(lat, lon, zoom):
    n = 2 ** zoom
    x = int((lon + 180) / 360 * n)
    y = int((1 - math.log(math.tan(math.radians(lat)) +
            1 / math.cos(math.radians(lat))) / math.pi) / 2 * n)
    return x, y


def meters_per_pixel(lat, zoom):
    return 156543.03392 * math.cos(math.radians(lat)) / (2 ** zoom)


# Calculate tile range
mpp = meters_per_pixel(CENTER_LAT, ZOOM)
dlat = AREA_SIZE_M / 2 / 111320
dlon = AREA_SIZE_M / 2 / (111320 * math.cos(math.radians(CENTER_LAT)))

tx_min, ty_max = tile_coords(CENTER_LAT - dlat, CENTER_LON - dlon, ZOOM)
tx_max, ty_min = tile_coords(CENTER_LAT + dlat, CENTER_LON + dlon, ZOOM)
nx = tx_max - tx_min + 1
ny = ty_max - ty_min + 1
total = nx * ny

print(f"Zoom {ZOOM}: {mpp:.3f} m/pixel")
print(f"Tiles: {nx} x {ny} = {total}")
print(f"Raw image: {nx * TILE_SIZE} x {ny * TILE_SIZE} pixels")

# Download tiles in parallel
session = requests.Session()

def download_tile(z, x, y):
    # Google load-balances across mt0-mt3
    url = f"https://mt{x%4}.google.com/vt/lyrs=s&x={x}&y={y}&z={z}"
    for attempt in range(3):
        try:
            r = session.get(url, timeout=10)
            if r.status_code == 200 and len(r.content) > 1000:
                return x, y, Image.open(BytesIO(r.content))
        except Exception:
            pass
    return x, y, None

stitched = Image.new("RGB", (nx * TILE_SIZE, ny * TILE_SIZE))
downloaded, failed = 0, 0

with ThreadPoolExecutor(max_workers=16) as pool:
    futures = {
        pool.submit(download_tile, ZOOM, tx, ty): (tx, ty)
        for ty in range(ty_min, ty_max + 1)
        for tx in range(tx_min, tx_max + 1)
    }
    for f in as_completed(futures):
        x, y, tile = f.result()
        if tile:
            stitched.paste(tile, ((x - tx_min) * TILE_SIZE,
                                   (y - ty_min) * TILE_SIZE))
            downloaded += 1
        else:
            failed += 1

print(f"Downloaded {downloaded}/{total} ({failed} failed)")

# Downscale if needed (Unity max texture = 16384x16384)
w, h = stitched.size
if w > MAX_UNITY_TEXTURE or h > MAX_UNITY_TEXTURE:
    scale = MAX_UNITY_TEXTURE / max(w, h)
    nw, nh = int(w * scale), int(h * scale)
    print(f"Downscaling {w}x{h} → {nw}x{nh}")
    stitched = stitched.resize((nw, nh), Image.LANCZOS)

stitched.save("satellite.jpg", quality=95)
print(f"Saved: satellite.jpg ({stitched.size[0]}x{stitched.size[1]})")
```

**Key details:**

- **`mt{x%4}`**: Google distributes tiles across 4 servers. Spreading requests prevents throttling.
- **3 retries per tile**: Occasional timeouts are normal at 16 concurrent workers.
- **`Image.LANCZOS` downscale**: Preserves sharpness much better than bilinear when reducing 39K pixels to 16K.
- **Quality 95**: Below 90, JPEG compression artifacts become visible on satellite imagery at this resolution.

For a 5 km area at zoom 20, this downloads ~24,000 tiles in about 3 minutes.

### Using Other Providers

Replace the URL pattern for different providers:

```python
# ESRI World Imagery
url = (f"https://server.arcgisonline.com/ArcGIS/rest/services/"
       f"World_Imagery/MapServer/tile/{z}/{y}/{x}")

# Bing Maps Aerial (requires quadkey encoding)
def quadkey(lat, lon, zoom):
    x, y = tile_coords(lat, lon, zoom)
    qk = ""
    for i in range(zoom, 0, -1):
        d = 0
        mask = 1 << (i - 1)
        if (x & mask) != 0: d += 1
        if (y & mask) != 0: d += 2
        qk += str(d)
    return qk

url = f"https://ecn.t0.tiles.virtualearth.net/tiles/a{qk}.jpeg?g=14226"

# OpenStreetMap (no satellite, but useful for vector overlay)
url = f"https://tile.openstreetmap.org/{z}/{x}/{y}.png"
```

## Part 2: Elevation Data (DTM)

### The Free DTM Landscape

Finding free, high-resolution elevation data is harder than satellite imagery. Here's every source I tested:

| Source | Resolution | Free? | What happened |
|--------|-----------|-------|--------------|
| **SRTM** (NASA) | 30m | Yes | Already had it — too coarse |
| **Copernicus GLO-30** | 30m | Yes | Downloaded — same as SRTM |
| **Copernicus GLO-10** | 10m | "Yes" | S3 returns **403 Forbidden** |
| **OpenTopography API** | varies | Was free | Now returns **401 Unauthorized** |
| **ALOS World 3D** | 5m | Registration | Requires JAXA account |
| **AWS Terrain Tiles** | **4.1m** | **Yes** | **Works. No auth. No limits.** |

### The Copernicus Gotcha

The Copernicus DEM has a file naming convention that's misleading:

```
Copernicus_DSM_COG_10_N31_00_E034_00_DEM.tif
                  ^^
                  This "10" is the tile GRID, not the resolution
```

I downloaded a 29 MB GeoTIFF and checked with GDAL:

```bash
$ gdalinfo Copernicus_DSM_COG_10_N31_00_E034_00_DEM.tif
Size is 3600, 3600
Pixel Size = (0.000277777777778, -0.000277777777778)
```

The pixel size is 0.000278° × 111,320 m/° = **30.9 meters per pixel**. Not 10m. The truly free Copernicus data is all 30m — the 10m product requires ESA Panda registration, and even then the S3 bucket returns 403.

**Lesson**: Always verify with `gdalinfo`. Don't trust filenames.

### AWS Terrain Tiles: The Best Free DTM

[AWS Terrain Tiles](https://registry.opendata.aws/terrain-tiles/) hosts Mapzen's elevation data as an open dataset. It's:

- **Free** — no API key, no registration, no rate limits
- **Tiled** — same slippy-map tile scheme as satellite imagery
- **4.1m resolution** at zoom 15 (7× better than SRTM/Copernicus)
- **Global coverage**

The tiles use **Terrarium encoding** — elevation is packed into the R, G, B channels:

```
elevation_meters = (R × 256 + G + B / 256) − 32768
```

This gives sub-meter precision in a standard PNG image.

### Downloading and Decoding DTM Tiles

```python
#!/usr/bin/env python3
"""Download AWS Terrain Tiles and convert to Unity heightmap."""
import requests
import math
import numpy as np
from concurrent.futures import ThreadPoolExecutor, as_completed
from io import BytesIO
from PIL import Image

# === CONFIGURATION ===
CENTER_LAT = 40.7128
CENTER_LON = -74.0060
AREA_SIZE_M = 5000
ZOOM = 15              # 4.1m/pixel — max useful resolution
TILE_SIZE = 256


def tile_coords(lat, lon, zoom):
    n = 2 ** zoom
    x = int((lon + 180) / 360 * n)
    y = int((1 - math.log(math.tan(math.radians(lat)) +
            1 / math.cos(math.radians(lat))) / math.pi) / 2 * n)
    return x, y


# Calculate tile range (same math as satellite)
dlat = AREA_SIZE_M / 2 / 111320
dlon = AREA_SIZE_M / 2 / (111320 * math.cos(math.radians(CENTER_LAT)))
tx_min, ty_max = tile_coords(CENTER_LAT - dlat, CENTER_LON - dlon, ZOOM)
tx_max, ty_min = tile_coords(CENTER_LAT + dlat, CENTER_LON + dlon, ZOOM)
nx = tx_max - tx_min + 1
ny = ty_max - ty_min + 1

print(f"DTM zoom {ZOOM}: ~{156543*math.cos(math.radians(CENTER_LAT))/(2**ZOOM):.1f} m/pixel")
print(f"Tiles: {nx} x {ny} = {nx*ny}")

# Download
session = requests.Session()

def download(z, x, y):
    url = f"https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"
    for _ in range(3):
        try:
            r = session.get(url, timeout=10)
            if r.status_code == 200:
                return x, y, Image.open(BytesIO(r.content))
        except:
            pass
    return x, y, None

raw = Image.new("RGB", (nx * TILE_SIZE, ny * TILE_SIZE))
with ThreadPoolExecutor(max_workers=8) as pool:
    futures = {pool.submit(download, ZOOM, tx, ty): (tx, ty)
               for ty in range(ty_min, ty_max + 1)
               for tx in range(tx_min, tx_max + 1)}
    for f in as_completed(futures):
        x, y, tile = f.result()
        if tile:
            raw.paste(tile, ((x - tx_min) * TILE_SIZE,
                              (y - ty_min) * TILE_SIZE))

# Decode Terrarium encoding → elevation in meters
arr = np.array(raw, dtype=np.float64)
elevation = (arr[:, :, 0] * 256.0 + arr[:, :, 1] + arr[:, :, 2] / 256.0) - 32768.0

elev_min = float(elevation.min())
elev_max = float(elevation.max())
print(f"Elevation: {elev_min:.1f}m to {elev_max:.1f}m")

# Normalize to 16-bit PNG (Unity reads this as a heightmap)
normalized = ((elevation - elev_min) / (elev_max - elev_min) * 65535).astype(np.uint16)
Image.fromarray(normalized, mode="I;16").save("heightmap.png")

# Save metadata (needed by the terrain loader)
with open("heightmap_meta.txt", "w") as f:
    f.write(f"min_elevation={elev_min:.2f}\n")
    f.write(f"max_elevation={elev_max:.2f}\n")
    f.write(f"width={elevation.shape[1]}\n")
    f.write(f"height={elevation.shape[0]}\n")

print(f"Saved: heightmap.png ({elevation.shape[1]}x{elevation.shape[0]})")
```

For a 5 km area at zoom 15, this downloads **36 tiles in 2 seconds**.

## Part 3: Fusing Satellite + DTM in Unity

Now you have two files:
- `satellite.jpg` — 16384×16384 RGB texture
- `heightmap.png` — 1536×1536 16-bit grayscale elevation

Both cover the same geographic bounds. Here's how to combine them into a Unity terrain.

### Creating the Terrain at Runtime

```csharp
void CreateTerrainFromHeightmap(Texture2D heightmap, Texture2D satellite)
{
    int res = heightmap.width;
    TerrainData terrainData = new TerrainData();
    terrainData.heightmapResolution = Mathf.ClosestPowerOfTwo(res) + 1;

    float elevationRange = maxElevation - minElevation;
    terrainData.size = new Vector3(terrainSize, elevationRange, terrainSize);

    // Read heightmap pixels → Unity heights (0..1 range)
    Color[] pixels = heightmap.GetPixels();
    int hmRes = terrainData.heightmapResolution;
    float[,] heights = new float[hmRes, hmRes];

    for (int y = 0; y < hmRes; y++)
        for (int x = 0; x < hmRes; x++)
        {
            // Sample from the heightmap texture
            float u = (float)x / (hmRes - 1);
            float v = (float)y / (hmRes - 1);
            int px = Mathf.Clamp((int)(u * (res - 1)), 0, res - 1);
            int py = Mathf.Clamp((int)(v * (res - 1)), 0, res - 1);
            heights[y, x] = pixels[py * res + px].r;  // 16-bit normalized to 0..1
        }

    terrainData.SetHeights(0, 0, heights);

    // Apply satellite as terrain layer
    TerrainLayer layer = new TerrainLayer();
    layer.diffuseTexture = satellite;
    layer.tileSize = new Vector2(terrainSize, terrainSize);  // one tile = full area
    terrainData.terrainLayers = new TerrainLayer[] { layer };

    // Position terrain centered on origin
    float halfSize = terrainSize / 2f;
    Vector3 pos = new Vector3(-halfSize, minElevation, -halfSize);
    GameObject terrainGO = Terrain.CreateTerrainGameObject(terrainData);
    terrainGO.transform.position = pos;
}
```

### World-Space Shader (for Overlaying on Existing Geometry)

If you have pre-built 3D terrain (from photogrammetry, asset bundles, etc.), you can overlay the satellite texture using world-space UV mapping instead of creating a separate Unity Terrain:

```glsl
Shader "Custom/WorldSpaceTerrain"
{
    Properties
    {
        _MainTex ("Satellite Texture", 2D) = "white" {}
        _TerrainSize ("Terrain Size (meters)", Float) = 5000
        _TerrainOffset ("Terrain Center Offset XZ", Vector) = (0,0,0,0)
    }
    SubShader
    {
        Tags { "RenderType"="Opaque" }
        Pass
        {
            CGPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #include "UnityCG.cginc"

            sampler2D _MainTex;
            float _TerrainSize;
            float4 _TerrainOffset;

            struct v2f {
                float4 pos : SV_POSITION;
                float2 uv : TEXCOORD0;
                float3 worldNormal : TEXCOORD1;
            };

            v2f vert(float4 vertex : POSITION, float3 normal : NORMAL)
            {
                v2f o;
                o.pos = UnityObjectToClipPos(vertex);

                // World-space UV: each world position maps to a unique texel
                float3 worldPos = mul(unity_ObjectToWorld, vertex).xyz;
                float half = _TerrainSize * 0.5;
                o.uv.x = (worldPos.x - _TerrainOffset.x + half) / _TerrainSize;
                o.uv.y = (worldPos.z - _TerrainOffset.y + half) / _TerrainSize;

                o.worldNormal = UnityObjectToWorldNormal(normal);
                return o;
            }

            fixed4 frag(v2f i) : SV_Target
            {
                // Clamp: outside satellite coverage, use fallback color
                float2 uv = i.uv;
                bool inBounds = uv.x >= 0 && uv.x <= 1
                             && uv.y >= 0 && uv.y <= 1;

                fixed4 col;
                if (inBounds)
                    col = tex2D(_MainTex, uv);
                else
                    col = fixed4(0.76, 0.70, 0.58, 1.0);  // neutral ground

                // Basic directional lighting
                float3 lightDir = normalize(_WorldSpaceLightPos0.xyz);
                float ndl = max(0.6, dot(i.worldNormal, lightDir));
                col.rgb *= ndl * 1.3;

                return col;
            }
            ENDCG
        }
    }
    Fallback "Diffuse"
}
```

The UV clamping is critical: without it, the satellite texture tiles/repeats across any geometry outside the coverage area, producing bizarre visual artifacts where buildings 10 km away render with imagery from the center of your operational zone.

### Alignment Checklist

For the satellite and DTM to line up correctly:

1. **Same geographic bounds**: Both download scripts must use identical `CENTER_LAT`, `CENTER_LON`, and `AREA_SIZE_M`
2. **Same projection**: Both use Web Mercator tiles — no reprojection needed
3. **UV origin**: The shader assumes the terrain is centered on Unity's world origin. If your scene center doesn't match the satellite center, adjust `_TerrainOffset`
4. **Elevation baseline**: The heightmap metadata stores `min_elevation` and `max_elevation`. The Unity terrain uses these to map the 0–1 height values back to real meters

## Part 4: Running the Download in Docker

Both scripts run cleanly in a containerized Python environment — no need to install GIS tools on your host:

```bash
# Download satellite imagery
docker run --rm --network host \
  -v $(pwd)/scripts:/scripts \
  -v $(pwd)/terrain_output:/out \
  python:3.11-slim bash -c '
    pip install -q requests pillow &&
    python3 /scripts/download_satellite.py'

# Download DTM
docker run --rm --network host \
  -v $(pwd)/scripts:/scripts \
  -v $(pwd)/terrain_output:/out \
  python:3.11-slim bash -c '
    pip install -q requests pillow numpy &&
    python3 /scripts/download_dtm.py'
```

After running both, you'll have:
- `terrain_output/satellite.jpg` — stitched satellite texture
- `terrain_output/satellite_meta.txt` — geographic bounds and resolution
- `terrain_output/heightmap.png` — 16-bit elevation heightmap
- `terrain_output/heightmap_meta.txt` — elevation range and dimensions

Copy these into your Unity project's `Resources/Terrain/` folder and rebuild.

## Results

| Layer | Before | After |
|-------|--------|-------|
| **Satellite** | ESRI z13, 15m/pixel | Google z20, 0.13m/pixel (**115× better**) |
| **DTM** | SRTM, 30m | Mapzen z15, 4.1m (**7× better**) |
| **Coverage** | 54 km | 5 km (operational zone) |
| **Total size** | 5 MB | 115 MB |
| **API keys needed** | 0 | 0 |
| **Runtime network** | None | None |

Everything is baked into static files. No runtime downloads, no API keys, no rate limit concerns. Fully air-gapped.

## What I Learned

1. **Test tile sizes, not HTTP status codes.** Every provider returns 200 OK at every zoom. Real imagery is 8–25 KB per tile; upscaled placeholders are 1–3 KB.

2. **"10m" in a filename doesn't mean 10m resolution.** The Copernicus `COG_10` naming refers to the tile grid, not pixel spacing. Always verify with `gdalinfo` or compute `pixel_size_degrees × 111320`.

3. **AWS open data is underrated.** The Mapzen terrain tiles have no auth, no rate limits, and 4m resolution — better than anything from Copernicus or SRTM without registration.

4. **Unity's 16384 texture limit is the real constraint.** At 0.13m/pixel, 16384 pixels covers 2.1 km. For wider coverage, you trade resolution for area. The math: `coverage_m = 16384 × meters_per_pixel`.

5. **UV clamping prevents tiling artifacts.** When your satellite covers 5 km but your scene spans 50 km, geometry outside the coverage area will sample wrapped UVs. Clamp to [0,1] and provide a fallback color.

6. **Satellite + DTM alignment is automatic** when you use the same tile coordinate system and geographic bounds for both downloads. No manual georeferencing needed.

---

*Next up: connecting real autopilot hardware to the simulation and flying autonomous missions through the terrain.*
