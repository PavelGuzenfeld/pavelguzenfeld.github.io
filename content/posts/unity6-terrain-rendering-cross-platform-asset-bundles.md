---
title: "From Magenta to Desert: Fixing Cross-Platform Unity Terrain Rendering in Docker"
date: 2026-03-27
draft: false
tags: ["Unity", "Docker", "asset-bundles", "shader", "terrain", "rendering", "Vulkan", "HDRP", "Built-in-RP", "headless"]
keywords: ["Unity terrain rendering Docker", "Unity asset bundle shader mismatch", "headless Unity terrain fix"]
cover:
  image: /images/posts/unity-terrain.png
  alt: "From Magenta to Desert: Fixing Unity Terrain in Docker"
categories: ["deep-dive"]
summary: "A detailed account of fixing terrain rendering in a headless Unity 6 Docker simulation — from magenta buildings and gray streaming cameras to textured villages with working RTSP feeds. Covers cross-platform asset bundle shader mismatches, runtime material conversion, texture recovery from broken materials, and every dead end along the way."
ShowToc: true
---

## Context

This is a follow-up to [Running Unity Headless in Docker with GPU Rendering, RTSP Camera Streaming, and MAVLink](/posts/headless-unity-docker-simulation/). That post got a drone simulation running in Docker with dual RTSP camera streams. But the terrain was a flat gray mesh with elevation contours — no textures, no buildings, no roads. The main camera showed something recognizable; the streaming cameras showed uniform gray.

The simulation project had pre-built terrain asset bundles with detailed village geometry — buildings with textured walls, roads, terrain surfaces, vegetation. The bundles were originally built on Windows with Unity 2022.3 and the HDRP render pipeline. Our headless Docker runs Unity 6 with the Built-in render pipeline on Linux/Vulkan.

This post documents the journey from "everything is magenta" to "that's a recognizable village."

```
Before:                              After:
┌──────────────────────┐    ┌──────────────────────────────┐
│                      │    │  ☀  ~~~  sky  ~~~            │
│   MAGENTA EVERYWHERE │    │                              │
│                      │    │  ┌─┐ ┌──┐    ┌─┐            │
│   (broken shaders)   │    │  │█│ │██│    │█│ buildings   │
│                      │    │  └─┘ └──┘    └─┘            │
│                      │    │  ═══════════ road ═════════  │
│   ■ gray drone       │    │  ░░░░░░░░░ terrain ░░░░░░░  │
└──────────────────────┘    └──────────────────────────────┘
```

---

## The Rendering Pipeline Problem

### What Is an Asset Bundle?

Unity [Asset Bundles](https://docs.unity3d.com/Manual/AssetBundlesIntro.html) are compiled archives of game assets — meshes, textures, materials, and entire scenes — that can be loaded at runtime. They're used to ship large terrain datasets separately from the main application binary.

The critical detail: **shader variants are compiled into the bundle at build time**, targeting a specific graphics API and render pipeline. A bundle built for Windows/DirectX with HDRP contains HDRP shader bytecode that is meaningless to a Built-in RP player running Vulkan on Linux.

### The Mismatch

| Property | Terrain Bundle | Headless Player |
|----------|---------------|-----------------|
| Unity version | 2022.3 | 6000.0.71f1 (Unity 6) |
| Render pipeline | HDRP 14 | Built-in RP |
| Platform | StandaloneWindows | StandaloneLinux64 |
| Graphics API | DirectX 11 | Vulkan |

When Unity loads a material whose shader doesn't exist in the current player, it substitutes the **error shader** — a flat magenta color that screams "something is wrong." Every building, road, and terrain surface in the village: magenta.

---

## Attempt 1: Rebuild the Bundle (Three Failures)

The terrain rebuild guide (written in a previous session) documented a plan: copy the source project, open it in Unity 6, and rebuild the bundles for Linux.

### Failure 1: The Scene Doesn't Exist

The existing terrain bundle contained a scene called `VillageTerrain_Standard_v3.unity`. This scene was not in the source repository. Someone had built it on a Windows workstation, likely through the Unity Editor GUI, and never committed the scene file to git. The bundle was the only copy.

We searched the entire NFS-mounted project: `find` across 15 GB of assets, checking git history for deleted files, scanning `.meta` files for bundle tags. The scene simply didn't exist outside the compiled bundle.

**Lesson**: Asset bundles are a one-way compilation. If you lose the source scene, you can't decompile the bundle back.

### Failure 2: Editor Can't Load Runtime Scene Bundles

The fallback plan: load the existing bundle in the Unity Editor, extract the scene, convert materials, and rebuild for Linux.

```csharp
// This was the theory:
AssetBundle bundle = AssetBundle.LoadFromFile(sourceBundle);
string[] scenePaths = bundle.GetAllScenePaths();
// scenePaths[0] = "Assets/Scenes/VillageTerrain_Standard_v3.unity"

// This FAILS:
SceneManager.LoadScene(sceneName, LoadSceneMode.Additive);
```

Unity's scene loading from asset bundles only works in a **built player** at runtime. The Editor's `SceneManager` cannot load scenes from compiled bundles. `EditorSceneManager.OpenScene()` also fails because the scene isn't a project asset — it's a serialized blob inside the bundle binary.

Three attempts with different loading strategies — `LoadScene`, `LoadSceneAsync`, `EditorSceneManager.OpenScene` — all crashed or returned invalid scene handles.

**Lesson**: Scene-type asset bundles are opaque at Editor time. You cannot extract, inspect, or modify their contents in the Editor.

### Failure 3: Compilation Errors in Batchmode

Even getting to the loading code was a struggle. The project had two batchmode compilation blockers:

1. **DIS/HLA interop package** — A local Unity package (`Packages/com.example.hla-interop`) that references types from the main assembly. The build script already handled this by temporarily moving the package directory before building (`mv Packages/com.example.hla-interop /tmp/`).

2. **URP setup script** — A leftover `SetupURP.cs` editor script that imported `UnityEngine.Rendering.Universal`, which isn't installed in a Built-in RP project. Fixed by wrapping it in `#if UNITY_HAS_URP`:

```csharp
// Before: immediate compilation error
using UnityEngine.Rendering.Universal;

// After: safely excluded
#if UNITY_HAS_URP
using UnityEngine.Rendering.Universal;
// ...
#endif
```

---

## Attempt 2: Runtime Material Conversion (Success)

Since we couldn't rebuild the bundle, we fixed the materials at runtime — after the bundle loads, iterate every renderer and replace broken materials with Standard shader equivalents.

### The Existing TerrainMaterialFix

The project already had a `TerrainMaterialFix.cs` component that ran on `Start()` with a delayed invoke. Its original implementation:

```csharp
// Original approach:
Texture mainTex = oldMat.HasProperty("_BaseMap") ? oldMat.GetTexture("_BaseMap") : null;
if (mainTex == null)
    mainTex = oldMat.HasProperty("_MainTex") ? oldMat.GetTexture("_MainTex") : null;
```

This checked URP's `_BaseMap` and Standard's `_MainTex`, but missed HDRP's `_BaseColorMap`. More importantly, it relied on `HasProperty()` — which returns `false` when the material's shader is the error shader, because the error shader doesn't declare these properties.

### Discovery: The Bundle Already Uses Standard Shader

A critical finding from the runtime logs:

```
[TerrainMaterialFix] MAT: 'Background_Image_0' shader='Standard' mainTex=null
```

The bundle name included `_stdrp` ("Standard RP"). Someone had already converted the materials to Standard shader before building the bundle. The shaders **were** Standard — the problem wasn't the shader, it was that the **shader variants** were compiled for DirectX, not Vulkan.

Unity loads the Standard shader name correctly, but the compiled shader code doesn't execute on Vulkan. The material appears valid (shader name says "Standard") but renders as if broken.

### The Texture Lookup Approach

When a bundle loads, all assets — including textures — are loaded into memory, even if the material can't reference them through shader properties. The key insight: **enumerate all loaded textures and match them to materials by name**.

```csharp
static Dictionary<string, Texture2D> BuildTextureLookup()
{
    var lookup = new Dictionary<string, Texture2D>();
    foreach (var tex in Resources.FindObjectsOfTypeAll<Texture2D>())
    {
        if (string.IsNullOrEmpty(tex.name)) continue;
        // Skip Unity built-in textures
        if (tex.name.StartsWith("unity_")) continue;
        lookup[tex.name.ToLowerInvariant()] = tex;
    }
    return lookup;
}
```

### The Name Matching Problem

First run with the texture lookup: **581 textures found, 0 matched.**

The debug log revealed why. Material names from the bundle were Windows file paths:

```
MAT: 'I:/Textures/Building_Wizard/A_First_Floor/Mala/Background_Image_0.jpg'
MAT: '../FBX/Textures/cement smooth #2.jpg'
MAT: 'I:/Textures/Building_Wizard/Roofs/Roof0.jpg'
```

Texture names in memory were just filenames without paths or extensions:

```
TEX: 'background_image_0' (1024x1024)
TEX: 'cement_smooth__2' (512x512)
```

The matching logic needed to extract the filename from Windows-style paths:

```csharp
static Texture FindTextureByMaterialName(string matName, Dictionary<string, Texture2D> lookup)
{
    string key = matName.ToLowerInvariant();

    // Extract filename from path-like material names
    int lastSlash = Math.Max(key.LastIndexOf('/'), key.LastIndexOf('\\'));
    if (lastSlash >= 0)
        key = key.Substring(lastSlash + 1);

    // Remove file extension
    int dotPos = key.LastIndexOf('.');
    if (dotPos > 0)
        key = key.Substring(0, dotPos);

    // Clean up special characters
    key = key.Replace(' ', '_').Replace('#', '_');

    if (lookup.TryGetValue(key, out var tex)) return tex;

    // Try suffix variants: _d, _diffuse, _albedo...
    // Try fuzzy matching for partial names...
}
```

### Results

After fixing the name matching:

| Category | Count | Status |
|----------|-------|--------|
| Materials already working | 894 | Standard shader + textures loaded correctly |
| Materials fixed by lookup | ~10 | Texture matched by filename extraction |
| Materials without textures | 52 | Texture data not embedded in bundle (external `I:` drive) |
| Non-textured (intentional) | ~10 | Simple colored materials (drone parts, markers) |

**894 out of 956 materials** rendered correctly — the vast majority of buildings, roads, terrain surfaces, and vegetation.

The 52 unfixable materials had their textures on a Windows `I:` drive at bundle build time. The texture files were never included in the bundle — they were external references that only existed on the original build machine. These render as flat-colored surfaces using the material's base color. Not ideal, but recognizable.

---

## Fixing the Skybox

With materials sorted, the next issue was obvious: the entire sky was magenta.

The loaded bundle scene overrode `RenderSettings.skybox` with its own sky material — an HDRP Enviro sky shader that doesn't exist in our Built-in RP player.

### Attempt 1: Load a 6-Sided Skybox from Resources

```csharp
Material skybox = Resources.Load<Material>("SkyBox/SkySeriesFreebie/6SidedFluffball");
RenderSettings.skybox = skybox;
```

The material loaded, but the sky was still magenta. The `Skybox/6 Sided` shader was being **stripped from the build** — Unity's shader stripping removes unused shader variants to reduce build size. Since no scene material directly referenced the skybox shader, the build optimizer removed it.

### Attempt 2: Procedural Skybox

```csharp
Shader procSkyShader = Shader.Find("Skybox/Procedural");
```

Same problem — `Shader.Find()` returned null. The procedural skybox shader was also stripped.

### The Fix: Always Included Shaders

Unity's `GraphicsSettings.asset` has an `m_AlwaysIncludedShaders` array. Shaders listed here are never stripped, regardless of whether any material references them.

```yaml
# ProjectSettings/GraphicsSettings.asset
m_AlwaysIncludedShaders:
  # ... existing entries ...
  - {fileID: 106, guid: 0000000000000000f000000000000000, type: 0}  # Skybox/Procedural
  - {fileID: 104, guid: 0000000000000000f000000000000000, type: 0}  # Skybox/6 Sided
```

The magic numbers `106` and `104` are Unity's built-in shader file IDs. After adding these, the procedural skybox loaded correctly:

```csharp
Material procSky = new Material(Shader.Find("Skybox/Procedural"));
procSky.SetFloat("_SunSize", 0.04f);
procSky.SetFloat("_SunSizeConvergence", 5f);
procSky.SetFloat("_AtmosphereThickness", 1f);
procSky.SetFloat("_Exposure", 1.3f);
RenderSettings.skybox = procSky;
RenderSettings.ambientMode = AmbientMode.Skybox;
DynamicGI.UpdateEnvironment();
```

**Lesson**: If you create materials at runtime via `new Material(Shader.Find(...))`, the shader must be in `m_AlwaysIncludedShaders` or it gets stripped from the build.

---

## Fixing the Lighting

With the skybox fixed, the terrain was visible but washed out at distance. The bundle scene had HDRP fog settings that, when interpreted by Built-in RP, created a dense fog effect that reduced distant terrain to a uniform color.

```csharp
static void FixRenderSettings()
{
    // Disable HDRP fog that doesn't translate to Built-in RP
    RenderSettings.fog = false;

    // Set directional light for desert environment
    Light sun = FindDirectionalLight();
    if (sun != null)
    {
        sun.intensity = 1.5f;
        sun.color = new Color(1f, 0.95f, 0.85f); // warm desert sun
        sun.shadows = LightShadows.Soft;
    }

    // Trilight ambient — sky blue, horizon warm, ground dark
    RenderSettings.ambientMode = AmbientMode.Trilight;
    RenderSettings.ambientSkyColor = new Color(0.6f, 0.65f, 0.8f);
    RenderSettings.ambientEquatorColor = new Color(0.55f, 0.5f, 0.45f);
    RenderSettings.ambientGroundColor = new Color(0.3f, 0.25f, 0.2f);
}
```

---

## Streaming Camera Positioning

The final issue was non-rendering: the drone's body camera was showing nothing but blue sky.

### The Rotation Bug

The entity configuration had:

```yaml
BodyCamera:
  LocalPosition: {x: 0, y: -5, z: 0}      # 5m below drone
  LocalRotation: {x: -90, y: 0, z: 0}      # WRONG: points UP
```

In Unity's coordinate system, rotating -90 degrees around the X axis from a forward-facing camera points it **straight up**. The body camera was a belly camera that stared at the sky.

Fix: `x: 90` (positive) points the camera **straight down** — a proper nadir view.

### Altitude Tuning

The drone's initial altitude was 300m MSL. The terrain ranges from 125m to 212m MSL. At 300m, the drone was 100-175m above the village — too high for detailed building views.

Through several iterations:

| Altitude (MSL) | AGL at village center | Result |
|---|---|---|
| 300m | ~130m | Buildings are tiny dots |
| 190m | ~20m | Camera almost at ground level — too close |
| 220m | ~50m | Good overview, buildings and roads clearly visible |

---

## The Complete Runtime Fix Pipeline

The final `TerrainMaterialFix` runs as a `MonoBehaviour` with `[DefaultExecutionOrder(-300)]` to ensure it fires early. The fix sequence:

```
Bundle loads scene (8 second delay for terrain bundle loading)
    │
    ▼
1. BuildTextureLookup()
   └── Resources.FindObjectsOfTypeAll<Texture2D>()
   └── Index by lowercase name → Dictionary<string, Texture2D>
    │
    ▼
2. For each MeshRenderer in scene:
   ├── Already Standard + has texture? → skip
   ├── Create new Standard material (metallic=0, smoothness=0)
   ├── Try material properties: _BaseColorMap, _BaseMap, _MainTex
   ├── Try texture lookup by filename extraction
   └── Apply to renderer
    │
    ▼
3. FixSkybox()
   └── Replace RenderSettings.skybox with procedural sky
    │
    ▼
4. FixRenderSettings()
   ├── Disable fog
   ├── Configure directional light (desert profile)
   └── Set trilight ambient
```

---

## Performance

The entire runtime fix adds negligible overhead. It runs once, 8 seconds after scene load, and takes less than a frame to complete.

GPU memory usage on an NVIDIA RTX 3060 (6 GB):

| Component | VRAM |
|---|---|
| Unity player + scene | ~1.0 GB |
| Terrain bundle (894 materials, textures) | ~0.2 GB |
| 2x 1080p render targets | ~0.06 GB |
| **Total** | **~1.2 GB** |

Minimum VRAM requirement: **2 GB** at 1080p, **3 GB** comfortable at 4K.

---

## What Didn't Work (Summary)

| Approach | Why it failed |
|---|---|
| Rebuild bundle from source project | Scene file never committed to git — only exists inside the compiled bundle |
| Load scene bundle in Editor batchmode | Unity Editor cannot load scenes from runtime asset bundles (EditorSceneManager and SceneManager both fail) |
| `HasProperty()` on error shader materials | Returns `false` — error shader doesn't declare the original properties |
| Direct `GetTexture("_BaseColorMap")` on Standard shader | Returns null — Standard shader doesn't have HDRP property names |
| `Skybox/Procedural` via `Shader.Find()` | Returns null — shader stripped from build. Must add to `m_AlwaysIncludedShaders` |
| 6-Sided skybox from Resources | Material loads but shader is stripped — same root cause |
| Name-matching textures by material name | Material names are Windows file paths (`I:/Textures/...`), texture names are just filenames. Required path extraction |

## What Worked

| Approach | Key insight |
|---|---|
| `Resources.FindObjectsOfTypeAll<Texture2D>()` | Textures from bundles are in memory even when materials can't reference them |
| Filename extraction from Windows paths | `I:/Textures/Foo/Bar.jpg` → `bar` matches texture `bar` in the lookup |
| `m_AlwaysIncludedShaders` | Prevents shader stripping for runtime-created materials |
| Procedural skybox | No texture dependencies — pure math shader |
| `RenderSettings.fog = false` | Disables HDRP fog settings that wash out distant terrain |
| Trilight ambient lighting | Better visual quality than the broken HDRP ambient from the bundle |

---

## Viewing the Result

```bash
# Head camera (30° pitch, village overview)
gst-launch-1.0 rtspsrc location=rtsp://localhost:8554/HeadCamera \
  latency=100 protocols=tcp \
  ! rtph264depay ! avdec_h264 ! videoconvert ! autovideosink sync=false

# Body camera (nadir/belly view, straight down)
gst-launch-1.0 rtspsrc location=rtsp://localhost:8554/BodyCamera \
  latency=100 protocols=tcp \
  ! rtph264depay ! avdec_h264 ! videoconvert ! autovideosink sync=false
```

The `protocols=tcp` flag remains essential on Ubuntu 24.04 — GStreamer's UDP transport still fails with the IPv6 address family error documented in the previous post.

---

## Remaining Limitations

1. **52 materials without textures** — their texture files were on a Windows drive (`I:\Textures\...`) at bundle build time and never embedded. These render as flat-colored surfaces. Fix requires rebuilding the bundle on the original Windows machine with all textures accessible.

2. **Terrain boundary** — the terrain mesh covers a finite area. Beyond the edge, only the skybox ground color is visible. A larger terrain bundle or procedural terrain extension would fix this.

3. **No normal maps recovered** — the name-matching approach could recover albedo textures but normal map naming conventions in the bundle were inconsistent. Buildings appear "flat" without normal mapping.

---

## Key Takeaways

1. **Asset bundles are platform-locked _and_ pipeline-locked.** A bundle built for Windows/HDRP won't render on Linux/Built-in RP. Even the same shader name ("Standard") compiles to different bytecode per platform and graphics API.

2. **Scene bundles are opaque.** You cannot load, inspect, or modify a scene bundle in the Editor. The scene data is serialized into a format that only the runtime player can deserialize. If you lose the source scene, you're stuck with what's in the bundle.

3. **`Resources.FindObjectsOfTypeAll` is your escape hatch.** When shader mismatches break material-to-texture references, the textures are still in memory. Enumerate them and rebuild the references manually.

4. **Shader stripping is aggressive.** Any shader used only via `Shader.Find()` at runtime — not referenced by any scene material — will be stripped from the build. Add it to `m_AlwaysIncludedShaders` in `GraphicsSettings.asset`.

5. **Runtime material conversion is viable.** Processing 956 materials at startup takes negligible time. It's not as clean as rebuilding bundles from source, but when the source is unavailable, it's the pragmatic path.

6. **Windows paths in asset metadata persist.** Materials built on Windows carry their original texture paths as metadata (material name, texture references). Cross-platform tooling must handle backslashes, drive letters, and case-insensitive matching.

---

**Related:**
- [Running Unity 2019.4 Headless in Docker with GPU Rendering, RTSP Camera Streaming, and MAVLink](/posts/headless-unity-docker-simulation/)
- [Connecting PX4 SITL to a Headless Unity Simulation in Docker](/posts/unity-px4-sitl-docker-debugging-odyssey/)
