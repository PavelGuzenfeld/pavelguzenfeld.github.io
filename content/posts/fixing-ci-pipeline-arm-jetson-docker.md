---
title: "Fixing a CI Pipeline on a Jetson Xavier — 15 Failures to Green"
date: 2026-03-20
draft: false
tags: ["CI/CD", "Docker", "ARM", "GCC", "GitHub Actions", "debugging", "DevOps"]
keywords: ["Jetson Docker CI pipeline", "ARM Docker build GitHub Actions", "GCC assembler error Jetson"]
categories: ["deep-dive"]
summary: "A day-long battle fixing a CI pipeline that builds Docker images on a self-hosted Jetson Xavier runner. From stale git submodules to GCC-15 assembler errors, expired tokens, DNS failures inside Docker, and deleted upstream branches — every layer of the stack had something broken."
ShowToc: true
---

## The Problem

A QA tag push on our robotics monorepo triggered two CI workflows — "Build and Deploy on QA" and "Flight Controller Unit Tests." Both failed. The tag had been working days earlier, and the only code change was a one-line Python type hint fix in a submodule. Something else was wrong.

What followed was a 15-failure, day-long investigation that peeled back layer after layer of infrastructure rot. Each fix revealed the next hidden problem. This is the full story.

```
Tag Push (QA)
     │
     ▼
┌─ Build & Deploy ──────────────────────┐  ┌─ FC Unit Tests ──┐
│                                       │  │                  │
│  ① Ghost submodule (stale dirs)       │  │  ④ Tags bypass   │
│     ▼ fixed, exposed:                 │  │    path filters  │
│  ② GCC-15 vs assembler (-march=native)│  └──────────────────┘
│     ▼ fixed, exposed:                 │
│  ③ Token expired (LFS > 1 hour)       │
│     ▼ fixed, exposed:                 │
│  ⑤ DNS / GitHub rate-limit in Docker  │
│     ▼ fixed, exposed:                 │
│  ⑥ GStreamer -Werror (GCC-15 warnings)│
│     ▼ fixed, exposed:                 │
│  ⑦ Deleted upstream branch (XGBoost)  │
│     ▼ fixed, exposed:                 │
│  ⑧ Dead dependencies (5 unused libs)  │
│     ▼ removed                         │
│                                       │
│  ✓ GREEN after 19 attempts            │
└───────────────────────────────────────┘
```

## Failure 1: The Ghost Submodule

**Symptom:** `colcon build` inside Docker discovers a package called `legacy_sdk` and fails because its dependency `common_utils` is missing.

**Investigation:** Neither `legacy_sdk` nor `common_utils` exist in the repository. They're not submodules, not in any directory listing, and not referenced in `.gitmodules`. So where was colcon finding them?

The CI logs held the answer:

```
warning: unable to rmdir 'legacy_sdk': Directory not empty
```

These were **former submodules** that had been removed from `.gitmodules` months ago, but their directories persisted on the self-hosted runner. The `actions/checkout@v4` with `clean: true` runs `git clean -ffdx`, but the directories contained nested `.git` state that prevented removal.

On previous CI runs, *both* `legacy_sdk` and `common_utils` were stale-but-present, so colcon built them successfully. Between runs, `common_utils` got partially cleaned up while `legacy_sdk` survived — creating an inconsistent state.

**Fix:**

```yaml
- name: Remove stale directories from removed submodules
  run: |
    for dir in legacy_sdk deploy-platform; do
      if [ -d "$dir" ] && ! git ls-files --error-unmatch "$dir" >/dev/null 2>&1; then
        echo "Removing stale directory: $dir"
        rm -rf "$dir"
      fi
    done
```

**Lesson:** Self-hosted runners accumulate state. Former submodules are particularly insidious because `git clean` can't always remove them, and build tools discover them automatically.

---

## Failure 2: GCC-15 vs. the System Assembler

**Symptom:** Flight Controller unit tests fail with:

```
Error: unknown architectural extension `flagm+dotprod+crc+crypto+fp16+rcpc2+profile+pauth'
Error: unrecognized option -march=armv8.2-a+flagm+dotprod+crc+crypto+fp16+rcpc2+profile+pauth
```

**Root cause:** Four packages used `-march=native` in their CMakeLists.txt. GCC-15 on this ARM platform detects CPU features like `flagm`, `rcpc2`, `profile`, and `pauth`, and generates `-march` flags with those extensions. But the system assembler (`as`) bundled with the base Docker image is too old to understand them.

The older CI had cached Docker layers built with GCC-9, so this code path was never exercised. Our fresh build exposed the incompatibility.

**Fix:** Remove `-march=native` (and `-funroll-loops`) from all four packages:

```cmake
# Before
add_compile_options(-O3 -march=native -funroll-loops)

# After
add_compile_options(-O3)
```

**Lesson:** `-march=native` is a footgun in CI. The compiler and assembler must agree on supported extensions. If you compile with a newer GCC against an older assembler, native arch detection will generate flags the assembler rejects.

---

## Failure 3: The 1-Hour Token

**Symptom:** Model weights installation fails after exactly 1 hour:

```
batch response: Authentication required: Bad credentials
Token expired, skipping token revocation
```

**Investigation:** The CI uses GitHub App tokens (1-hour lifetime) for authentication. The model-weights repository uses Git LFS to store ~2GB of model files across multiple platforms. On the Jetson's slow network, `git lfs pull` takes over an hour — and the token expires mid-download.

The previous successful build (days earlier) happened to complete faster, likely due to LFS objects being partially cached on the runner.

**Fix — attempt 1:** Generate a fresh token right before the LFS pull:

```yaml
- name: Clone model weights repo (no LFS)
  run: |
    GIT_LFS_SKIP_SMUDGE=1 git clone --depth=1 --branch master \
      https://x-access-token:${{ steps.app-token.outputs.token }}@github.com/org/model-weights.git \
      /tmp/model-weights

- name: Generate fresh token for LFS
  id: lfs-token
  uses: actions/create-github-app-token@v1
  # ...

- name: Install Model Weights
  run: |
    cd /tmp/model-weights
    git remote set-url origin \
      https://x-access-token:${{ steps.lfs-token.outputs.token }}@github.com/org/model-weights.git
    git lfs pull --include="target-platform/**,scripts/**"
```

This helped (fast clone, fresh token for LFS, selective download) but the Jetson's network was still too slow.

**Fix — attempt 2:** Persist the LFS repo across runs:

```yaml
- name: Install Model Weights
  run: |
    REPO_DIR="/home/runner/model-weights-repo"
    if [ -d "$REPO_DIR/.git" ]; then
      cd "$REPO_DIR"
      git remote set-url origin "https://x-access-token:${TOKEN}@github.com/org/model-weights.git"
      git fetch --depth=1 origin master
      git reset --hard origin/master
    else
      GIT_LFS_SKIP_SMUDGE=1 git clone --depth=1 --branch master \
        "https://x-access-token:${TOKEN}@github.com/org/model-weights.git" "$REPO_DIR"
    fi
    cd "$REPO_DIR"
    git lfs pull --include="target-platform/**,scripts/**" || true
    # Check if enough files downloaded
    if find target-platform/models -type f -size +1k | head -1 | grep -q .; then
      ./scripts/install_models.sh "target-platform" "$DEST"
    else
      echo "::error::LFS pull incomplete. Re-run to resume."
      exit 1
    fi
```

The `|| true` on `git lfs pull` means a partial download doesn't fail the step. LFS objects already downloaded are cached in `.git/lfs/objects/`. Each subsequent run downloads more until the cache is complete. After 2-3 runs, the pull completes instantly.

**Lesson:** GitHub App tokens expire after 1 hour. For large LFS repos on slow networks, you need either: (a) SSH keys (no expiry), (b) persistent LFS cache across runs, or (c) alternative download mechanisms. On self-hosted runners, persistent storage is your friend.

---

## Failure 4: Flight Controller Tests on Tags

**Symptom:** The FC unit tests workflow triggers on every tag push and fails because `flight_controller` and `mavlink_filter` packages don't exist in the repo.

**Root cause:** The workflow has path filters:

```yaml
on:
  push:
    paths:
      - 'flight_controller/**'
      - '.github/workflows/flight-controller-tests.yml'
```

But GitHub **ignores path filters on tag pushes** — there's no base commit to diff against, so all workflows run. Since we modified the workflow file, every tag push triggered it.

**Fix:**

```yaml
on:
  push:
    branches: ['**']
    tags-ignore: ['**']
    paths:
      - 'flight_controller/**'
      - '.github/workflows/flight-controller-tests.yml'
```

**Lesson:** GitHub Actions path filters don't work on tag pushes. Explicitly exclude tags with `tags-ignore` if the workflow shouldn't run for them.

---

## Failure 5: DNS Death Inside Docker

**Symptom:** The runtime Dockerfile clones several public GitHub repositories, but fails with:

```
fatal: could not read Username for 'https://github.com': No such device or address
```

**Investigation:** This error looks like a DNS issue, but it's actually a git credential prompt failure. The runner's IP was being rate-limited by GitHub, causing 401 responses. Git tries to prompt for credentials, but there's no terminal inside Docker.

Setting `GIT_TERMINAL_PROMPT=0` changed the error to `terminal prompts disabled` — confirming the rate-limit theory. Adding retries didn't help because every attempt hit the rate limit.

**Fix:** Pass a GitHub App token into the Docker build:

```dockerfile
ARG GITHUB_TOKEN=""
ENV GIT_TERMINAL_PROMPT=0
RUN if [ -n "$GITHUB_TOKEN" ]; then \
      git config --global url."https://x-access-token:${GITHUB_TOKEN}@github.com/".insteadOf "https://github.com/"; \
    fi && \
    for repo in ...; do \
      git clone --depth 1 "$repo" "/tmp/$name" && \
      cmake -G Ninja -B "/tmp/$name/build" ... && \
      cmake --build "/tmp/$name/build" --target install; \
    done
```

```bash
# In the build script:
docker build \
  --network=host \
  --build-arg GITHUB_TOKEN="${GITHUB_TOKEN:-}" \
  ...
```

Note: `DOCKER_BUILDKIT=0` was required because BuildKit handles `--network=host` differently and wasn't propagating host network access to build steps on this platform.

**Lesson:** GitHub rate-limits unauthenticated git operations (60/hour per IP). Self-hosted runners sharing an IP can exhaust this quickly. Pass tokens into Docker builds via `--build-arg`, and use `--network=host` with `DOCKER_BUILDKIT=0` if BuildKit's networking doesn't work on your platform.

---

## Failure 6: GCC-15 Warnings in GStreamer

**Symptom:** GStreamer 1.24.13 compilation fails with GCC-15:

```
/usr/include/glib-2.0/glib/gatomic.h:112:5: warning: argument 2 of '__atomic_load'
discards 'volatile' qualifier [-Wdiscarded-qualifiers]
```

GStreamer's meson build sets `-Werror` internally, so this warning becomes a fatal error.

**Fix:** Disable werror per-subproject in the meson setup:

```dockerfile
RUN meson setup builddir \
    -Dwerror=false \
    -Dgstreamer:werror=false \
    -Dgst-plugins-base:werror=false \
    -Dgst-plugins-good:werror=false \
    -Dgst-plugins-ugly:werror=false \
    ...
```

Note: Using both `--werror=false` and `-Dwerror=false` causes meson to error with `Got argument werror as both -Dwerror and --werror. Pick one.`

**Lesson:** When cross-compiling with a newer GCC against older system headers, `-Werror` will break. Disable it at the build-system level, not with compiler flags — meson subprojects have their own werror settings that override global flags.

---

## Failure 7: The Deleted Branch

**Symptom:** XGBoost clone fails:

```
fatal: Remote branch remove-fit.__doc__ not found in upstream origin
```

The Dockerfile referenced a branch on a fork that had been deleted. The branch originally existed to remove Python `fit.__doc__` references that fail on Python 3.8 and to remove the `nvidia-nccl-cu12` dependency unavailable on Jetson Xavier (ARM/CUDA 11.4, JetPack 5.1).

**Fix:** Create a new `arm-edge-fixes` branch based on XGBoost v2.1.4 (the latest version supporting Python 3.8), with both fixes applied:

1. Remove `nvidia-nccl-cu12` from `pyproject.toml` dependencies
2. Remove `fit.__doc__` references from `sklearn.py` and `dask/__init__.py`

Pin the Dockerfile to this branch:

```dockerfile
RUN git clone --branch arm-edge-fixes --recursive \
    https://github.com/org/xgboost /tmp/xgboost
```

**Lesson:** Never reference branches that aren't protected from deletion. Pin to tags or use protected branches for CI dependencies. When a dependency drops support for your Python version, pin to the last compatible release and maintain a fork with your patches.

---

## Failure 8: Dead Dependencies

Along the way, I audited every git clone in the Dockerfile and found **5 libraries** that were cloned, compiled, and installed but never actually used by any source code:

- `cmake-library` (private repo — caused auth failures)
- `exception-rt` (test linking failed — pthread issues)
- `gcem`
- `strong-types`
- `linalg3d`

Each was verified with a codebase-wide grep:

```bash
grep -rn "library_name" --include="*.{cpp,hpp,h,cmake,txt,py,xml}" .
# No matches found
```

Removing them cut Docker build time and eliminated 5 potential failure points.

**Lesson:** Docker images accumulate dead dependencies over time. Periodically audit your build steps — `grep` the codebase for each installed library to confirm it's actually used.

---

## The Timeline

| Attempt | Duration | Failure | Root Cause |
|---------|----------|---------|------------|
| 1 | 6m | `legacy_sdk` build | Stale submodule directory |
| 2 | 1h1m | Token expired | LFS download too slow |
| 3 | 1h1m | Token expired | Fresh token still not enough |
| 4 | 18m | `-march=native` | GCC-15 assembler flags |
| 5 | 18m | `flight_controller` missing | FC tests on tags |
| 6 | 1h2m | Token expired | Selective LFS still slow |
| 7 | 1h2m | Token expired | LFS cache not persisting |
| 8 | 2h43m | `git clone` in Docker | DNS/rate-limit failure |
| 9 | 27m | `git clone` in Docker | Same — network host not working |
| 10 | 54s | SSH auth failure | SSH key doesn't have org access |
| 11 | 1h4m | `git clone` in Docker | BuildKit ignores --network=host |
| 12 | 29m | `cmake-library` auth | Private repo, wrong token format |
| 13 | 1h4m | GStreamer werror | GCC-15 warnings in glib headers |
| 14 | 30s | meson config | Duplicate --werror flag |
| 15 | 9m | DNS timeout | Transient network failure |
| 16 | 20m | XGBoost nccl | nvidia-nccl-cu12 unavailable |
| 17 | 15m | XGBoost Python | Requires Python >=3.10 |
| 18 | 9m | DNS timeout | Transient (rerun succeeded) |
| **19** | **30m** | **None** | **SUCCESS** |

---

## Key Takeaways

1. **Self-hosted runners accumulate state.** Git submodules, Docker layers, LFS caches, pip caches — all persist across runs. Add explicit cleanup steps for known stale artifacts.

2. **GitHub App tokens expire after 1 hour.** For any operation that might exceed this (large LFS repos, slow networks), use persistent caches, SSH keys, or split operations across multiple token-generation steps.

3. **`-march=native` breaks cross-version builds.** If your compiler is newer than your assembler (common when installing GCC-15 on an Ubuntu 20.04 base), native arch detection generates flags the assembler doesn't understand.

4. **Docker BuildKit handles networking differently.** `--network=host` may not work as expected with `DOCKER_BUILDKIT=1`. Test explicitly, and fall back to `DOCKER_BUILDKIT=0` if needed.

5. **GitHub rate-limits unauthenticated git operations.** Self-hosted runners on shared IPs hit this quickly. Always pass tokens into Docker builds.

6. **Tag pushes bypass path filters.** Use `tags-ignore: ['**']` if your workflow shouldn't run on tags.

7. **Audit Docker dependencies periodically.** Dead libraries add build time, increase attack surface, and create failure points. A simple `grep` across the codebase catches them.

8. **Each fix reveals the next bug.** CI pipelines are layered systems. Fixing one layer exposes issues in the next. Budget time for cascading failures — the first error is rarely the last.

---

**Related:**
- [Zero-Copy Video on Jetson: Building gst-nvmm-cpp and Contributing to GStreamer](/posts/gst-nvmm-cpp-zero-copy-video-jetson/)
- [PX4 Autopilot: A Practitioner's Guide to Troubleshooting, Debugging, Building, and Testing](/posts/px4-autopilot-troubleshooting-debugging-testing-guide/)
