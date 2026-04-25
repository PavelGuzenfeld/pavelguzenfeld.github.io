---
title: 'Procedural Settlement: Generating 3D Buildings, Roads, and Entities from OpenStreetMap
  in Unity'
date: 2026-04-13
draft: false
tags:
- Unity
- Docker
- terrain
- SRTM
- satellite
- shader
- headless
- simulation
- GIS
- DTM
- open-source
- rendering
keywords:
- OpenStreetMap Unity buildings
- procedural city generation Unity
- OSM building extrusion runtime
- headless Unity terrain generation
- Overpass API Unity integration
- procedural window textures Unity
cover:
  image: /images/posts/osm-procedural-terrain.png
  alt: Procedural settlement with OSM buildings, roads, and entities in a headless
    Unity simulation
categories:
- deep-dive
summary: How I replaced a proprietary terrain bundle with a fully procedural environment
  generated from open-source data — hundreds of buildings with window textures from
  OpenStreetMap, terrain-hugging roads, satellite-driven vegetation, and multiple
  ground and air entities — all built at runtime in a headless Unity Docker simulation.
ShowToc: true
audio:
  pronunciation:
    OSM: O S M
    OpenStreetMap: open street map
    Overpass API: overpass A P I
    WGS84: W G S eighty four
    DTM: D T M
    SRTM: S R T M
    HDRP: H D R P
    Built-in RP: built in R P
    Cull Off: cull off
    OSMNode: O S M node
    OSMBuildingLoader: O S M building loader
    OSMRoadLoader: O S M road loader
    TreePlacer: tree placer
    Terrain.activeTerrain: terrain dot active terrain
    Terrain.SampleHeight: terrain dot sample height
    TerrainCollider: terrain collider
    Physics.Raycast: physics dot raycast
    RaycastHit: raycast hit
    GetPixels: get pixels
    isReadable: is readable
    RTSP: R T S P
    NVENC: N V enc
    GStreamer: G streamer
    PrimitiveFlightController: primitive flight controller
    GoTo: go to
    Vector2: vector two
    Vector3: vector three
    MeshRenderer: mesh renderer
---

## Context

This is the fourth post in a series about running a Unity simulation headless in Docker:

1. [Running Unity Headless in Docker with GPU Rendering and RTSP Streaming](/posts/headless-unity-docker-simulation/) — got the simulation running with camera streams
2. [From Magenta to Desert: Fixing Cross-Platform Unity Terrain Rendering](/posts/unity6-terrain-rendering-cross-platform-asset-bundles/) — fixed broken shaders and materials
3. [Natural Skies and Satellite Terrain in a Headless Unity Simulation](/posts/unity-headless-environment-satellite-terrain-sky/) — satellite imagery and skybox
4. [From 21 to 25 FPS: Profiling and Optimizing](/posts/unity-headless-fps-optimization-pipeline/) — performance tuning

The previous posts used a proprietary terrain bundle containing 3D terrain mesh and buildings. It worked, but had persistent issues: shader pipeline mismatches (HDRP materials on Built-in RP), height alignment bugs between terrain layers, a restrictive camera culling mask hiding Layer 8, and satellite texture UV mapping that never quite matched the geometry.

This post documents replacing all of that with a fully procedural environment built from open-source data at runtime.

```
Before (proprietary bundle):        After (OSM procedural):
┌─────────────────────────┐   ┌─────────────────────────┐
│ 844MB asset bundle      │   │ 258KB OSM JSON          │
│ 5340 mesh renderers     │   │ ~500 buildings generated │
│ HDRP→Standard shader fix│   │ Custom double-sided      │
│ Material pipeline hacks │   │ Procedural windows       │
│ Height alignment bugs   │   │ Terrain-snapped          │
│ No entity visibility    │   │ All entities visible     │
└─────────────────────────┘   └─────────────────────────┘
```

## The Data Pipeline

### Step 1: Download Building Footprints from OpenStreetMap

The Overpass API gives you every mapped building in any area, free, with no API key:

```bash
curl -s "https://overpass-api.de/api/interpreter" \
  --data-urlencode 'data=[out:json][timeout:30];
    (way["building"](LAT_MIN,LON_MIN,LAT_MAX,LON_MAX););
    out body;>;out skel qt;' \
  -o osm_buildings.json
```

For my test area — a small settlement in an arid region — this returned **~500 buildings and ~2000 nodes**. 258KB of JSON containing every building footprint as a polygon of lat/lon coordinates.

The same approach works for roads:

```bash
curl -s "https://overpass-api.de/api/interpreter" \
  --data-urlencode 'data=[out:json][timeout:30];
    (way["highway"](LAT_MIN,LON_MIN,LAT_MAX,LON_MAX););
    out body;>;out skel qt;' \
  -o osm_roads.json
```

Result: **14 roads** — a mix of unclassified roads, tracks, and residential streets.

### Step 2: The Coordinate System

The simulation's geo-to-local conversion maps lat/lon to Unity world coordinates using standard WGS84 scale factors:

```
X = (longitude - LON_ORIGIN) × metersPerDegreeLon
Z = (latitude  - LAT_ORIGIN) × metersPerDegreeLat
Y = altitude ASL (direct)
```

I derived the origin by logging `PrimitiveFlightController` GoTo commands with two known geodetic→local conversions and solving for the origin. The scale factors (~111km/degree latitude, ~95km/degree longitude) are standard for mid-latitudes.

## Building Generation

### Parsing OSM JSON

The Overpass API returns two element types: `node` (lat/lon points) and `way` (ordered lists of node IDs forming polygons). Each building `way` has a `nodes` array and optional tags like `building:levels` or `height`.

I wrote a simple state-machine JSON parser to avoid pulling in a JSON library dependency:

```csharp
if (elemType == "node")
{
    long id = ExtractLong(elemJson, "\"id\":");
    double lat = ExtractDouble(elemJson, "\"lat\":");
    double lon = ExtractDouble(elemJson, "\"lon\":");
    data.nodes[id] = new OSMNode { lat = lat, lon = lon };
}
else if (elemType == "way")
{
    long id = ExtractLong(elemJson, "\"id\":");
    var nodeIds = ExtractLongArray(elemJson, "\"nodes\":");
    // ... extract height, levels, building type
}
```

### Polygon Winding Order

OSM polygons can be clockwise or counter-clockwise. For Unity's default front-face culling to work (or for correct normals), you need consistent winding. I detect and fix it using the shoelace formula:

```csharp
float GetSignedArea(List<Vector2> poly)
{
    float area = 0;
    for (int i = 0; i < poly.Count; i++)
    {
        int j = (i + 1) % poly.Count;
        area += poly[i].x * poly[j].y;
        area -= poly[j].x * poly[i].y;
    }
    return area * 0.5f;
}

// Negative = CCW, Positive = CW
if (GetSignedArea(positions) > 0)
    positions.Reverse();
```

This was a hard-won lesson. Without winding normalization, buildings rendered as "cardboard with 3 sides" — two walls always invisible due to backface culling.

### The Double-Sided Shader Solution

Even with correct winding, some walls still disappeared at certain camera angles. The fix: a custom surface shader with `Cull Off`:

```hlsl
Shader "Custom/BuildingDoubleSided"
{
    Properties
    {
        _MainTex ("Wall Texture", 2D) = "white" {}
        _Color ("Tint", Color) = (1,1,1,1)
    }
    SubShader
    {
        Tags { "RenderType"="Opaque" }
        Cull Off

        CGPROGRAM
        #pragma surface surf Lambert fullforwardshadows

        sampler2D _MainTex;
        fixed4 _Color;

        struct Input { float2 uv_MainTex; };

        void surf(Input IN, inout SurfaceOutput o)
        {
            fixed4 c = tex2D(_MainTex, IN.uv_MainTex) * _Color;
            o.Albedo = c.rgb;
        }
        ENDCG
    }
    Fallback "Diffuse"
}
```

This was significantly better than setting `material.SetInt("_Cull", 0)` on the Standard shader, which doesn't actually expose a `_Cull` property and produced black faces.

### Procedural Window Textures

Flat-colored boxes look terrible. I generate a 128x128 tileable window texture at runtime:

```csharp
Texture2D GenerateWindowTexture()
{
    // One tile = one floor bay with a window
    // Wall base → frame → glass panes with mullion cross → sill

    for (int y = winBottom; y <= winTop; y++)
        for (int x = winLeft; x <= winRight; x++)
        {
            bool inMullion = (Mathf.Abs(x - midX) <= mullionW)
                          || (Mathf.Abs(y - midY) <= mullionW);
            tex.SetPixel(x, y, inMullion ? frameColor : glassColor);
        }

    tex.wrapMode = TextureWrapMode.Repeat;
    return tex;
}
```

The wall mesh UVs tile this texture based on actual building dimensions — one tile per 3.5m bay horizontally, one per floor vertically:

```csharp
float bays = Mathf.Max(1f, wallLen / 3.5f);  // window bays
int floors = Mathf.RoundToInt(height / 3.2f);  // floor count

uvs.Add(new Vector2(0, 0));
uvs.Add(new Vector2(bays, 0));
uvs.Add(new Vector2(bays, floors));
uvs.Add(new Vector2(0, floors));
```

A 10-meter wall gets ~3 window bays. A 2-story building gets 2 rows of windows. The texture handles the rest.

### Height Assignment

OSM has building height data for major cities, but small rural settlements often have zero `building:levels` tags. I use a deterministic pseudo-random based on the building's OSM ID:

```csharp
int hash = (int)(building.id % 7);
int floors = minFloors + (hash % (maxFloors - minFloors + 1));
float height = floors * 3.2f;  // 1-3 floors × 3.2m
```

Deterministic means the same building always gets the same height across restarts.

### Terrain Snapping

The critical lesson: never use a fixed base elevation. The DTM terrain varies by 50+ meters across the settlement area. Each building samples the terrain height at its center:

```csharp
float terrainY = fallbackElevation;
Terrain terrain = Terrain.activeTerrain;
if (terrain != null)
{
    Vector3 worldPos = new Vector3(center.x, 0, center.y);
    terrainY = terrain.SampleHeight(worldPos) + terrain.transform.position.y;
}
go.transform.position = new Vector3(0, terrainY, 0);
```

I spent hours debugging "missing buildings" that were actually 20 meters underground because the terrain at their location was higher than my hardcoded base elevation.

## Road Generation

### Terrain-Hugging Roads

The first road implementation sampled terrain height only at OSM node positions — the original waypoints from the mapper. This created roads that floated above valleys and cut through hills between nodes.

The fix: subdivide every road segment into 5-meter chunks and sample terrain at each point:

```csharp
float maxSegLen = 5f;
for (int j = 0; j < rawPoints.Count; j++)
{
    if (j == 0) { densified.Add(rawPoints[0]); continue; }
    float dist = Vector2.Distance(rawPoints[j-1], rawPoints[j]);
    int subdivs = Mathf.CeilToInt(dist / maxSegLen);
    for (int s = 1; s <= subdivs; s++)
    {
        float t = (float)s / subdivs;
        densified.Add(Vector2.Lerp(rawPoints[j-1], rawPoints[j], t));
    }
}

// Sample terrain at every densified point
foreach (var p in densified)
{
    float y = terrain.SampleHeight(new Vector3(p.x, 0, p.y))
            + terrainBase + 0.5f;  // 50cm above surface
    points.Add(new Vector3(p.x, y, p.y));
}
```

The road mesh itself is a ribbon — two vertices per point, offset perpendicular to the road direction:

```csharp
Vector3 forward = (points[i+1] - points[i]).normalized;
Vector3 right = Vector3.Cross(Vector3.up, forward).normalized * halfWidth;
verts.Add(points[i] - right);
verts.Add(points[i] + right);
```

Road width comes from the OSM `highway` tag: 7m for primary roads, 5m for residential, 3m for tracks.

## Satellite-Driven Vegetation

OSM has almost no tree data for arid regions. Instead, I analyze the satellite texture directly to find green pixels:

```csharp
Texture2D satellite = Resources.Load<Texture2D>("Terrain/satellite");
Color[] pixels = satellite.GetPixels();

for (int py = 0; py < h; py += step)
{
    for (int px = 0; px < w; px += step)
    {
        Color c = pixels[py * w + px];

        // Convert pixel to geographic coordinates using satellite bounds
        double pixLon = satLonMin + u * (satLonMax - satLonMin);
        double pixLat = satLatMin + v * (satLatMax - satLatMin);

        // Convert to local Unity coordinates
        float worldX = (float)((pixLon - originLon) * metersPerDegreeLon);
        float worldZ = (float)((pixLat - originLat) * metersPerDegreeLat);

        float greenness = c.g - Mathf.Max(c.r, c.b);
        if (greenness > 0.05f && c.g > 0.25f)
            greenSpots.Add(new Vector2(worldX, worldZ));  // Trees here
        else if (greenness > 0.02f)
            fieldSpots.Add(new Vector2(worldX, worldZ));   // Grass here
    }
}
```

**Important**: the satellite texture must have `isReadable: 1` in its `.meta` file, or `GetPixels()` throws `ArgumentException: texture data is not readable`. This is off by default in Unity for memory optimization.

The satellite image's geographic bounds come from its metadata file — not from the terrain size parameter. Getting this wrong (I used `terrainSize = 54000` initially) maps green pixels to completely wrong world positions.

Trees are procedural primitives — palms (cylinder trunk + cube fronds) and round-canopy trees (cylinder trunk + sphere canopy). Grass is flat green quads laid on the terrain. The result: ~100 trees and ~80 grass patches placed exactly where the satellite shows green.

## Entity System

### Procedural Models

Multiple entities run simultaneously, each with a procedural 3D model built from Unity primitives:

| Entity | Model | Key Feature |
|--------|-------|-------------|
| Drone | Loaded prefab | 3 RTSP camera streams |
| 3× Quadcopter | Loaded prefab | Airborne objects |
| 2× Truck | Box body + flatbed + wheels | Heavy vehicle |
| 2× Sedan | Body + glass cabin + wheels | Passenger car |
| 2× Pedestrian | Body + head + limbs | Walking figure |
| 2× Pickup | White body + open bed | Utility vehicle |

### Terrain Snapping via Raycast

Ground entities must sit on the terrain surface. `Terrain.SampleHeight()` works but requires the TerrainCollider to be present (I had removed it in an earlier optimization). The more reliable approach: raycast from above:

```csharp
void SnapToTerrain(Transform t)
{
    Vector3 origin = new Vector3(t.position.x, 500f, t.position.z);
    if (Physics.Raycast(origin, Vector3.down, out RaycastHit hit, 600f))
        t.position = new Vector3(t.position.x, hit.point.y + 1f, t.position.z);
}
```

This also works with non-terrain colliders (buildings, roads) if they have colliders. Setting the origin at Y=500 ensures it's above any terrain peak.

### The Culling Mask Bug

The streaming cameras couldn't see any terrain objects — they were all on Layer 8 (set by the terrain loader) but the camera capture script hardcoded a culling mask of `262199`:

```
262199 = bits 0,1,2,4,5,18
Layer 8 = bit 8 → NOT INCLUDED
```

Every terrain renderer was invisible to every streaming camera. The fix:

```csharp
_camera.cullingMask = -1;  // all layers visible
```

This single line made buildings appear after hours of debugging material shaders, render pipelines, and LOD settings.

## What I'd Do Differently

**Start with OSM, not proprietary bundles.** The proprietary terrain bundle was 844MB, required HDRP→Standard shader conversion, had height alignment issues between layers, and needed constant material fixups. The OSM approach is 258KB of JSON, generates exactly what you need, and every parameter is tunable.

**Sample terrain at every vertex.** Fixed base elevations are never right in hilly terrain. Always use `Terrain.SampleHeight()` or raycasts.

**Use a custom Cull Off shader from the start.** Don't fight winding order across thousands of auto-generated polygons. `Cull Off` with a surface shader gives correct lighting on both sides.

**Mark textures as readable in the import settings.** If you need `GetPixels()` at runtime, set `isReadable: 1` in the `.meta` file before building. The error message doesn't make this obvious.

## The Full Stack

```
OpenStreetMap (Overpass API)
    ↓ curl
osm_buildings.json (~500 buildings, 258KB)
osm_roads.json (14 roads)
    ↓ Unity C# at runtime
OSMBuildingLoader → extruded meshes + window textures
OSMRoadLoader → terrain-hugging ribbon meshes
    +
satellite.jpg → TreePlacer → palms, trees, grass
heightmap.png → DTM terrain with collider
    +
Entity configs (YAML) → vehicle models, pedestrian figures, etc.
    ↓
3 × RTSP camera streams (1920×1080 @ 30fps, H.264 NVENC 8Mbps)
    ↓ GStreamer
Live drone camera view
```

Total runtime data: ~15MB (satellite image + heightmap + OSM JSON). No proprietary terrain bundles. No network dependency. Everything generates in ~10 seconds at startup.
