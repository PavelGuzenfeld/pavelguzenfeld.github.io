---
title: "Contributing to ROS 2 — A Practical Guide from Four Accepted PRs"
date: 2026-03-22
draft: false
tags: ["ROS 2", "open-source", "Docker", "C++", "Python", "testing", "git", "contributing"]
keywords: ["how to contribute to ROS 2", "ROS 2 pull request guide", "ROS 2 DCO check"]
categories: ["deep-dive"]
summary: "Everything I learned submitting four pull requests to ROS 2 core repositories — from finding issues and building in Docker to passing DCO checks, handling OSRF's AI disclosure policy, rebasing across distro branches, and running the full test suites. A warts-and-all field guide."
ShowToc: true
---

## Why This Post Exists

Contributing to a large open-source robotics framework like ROS 2 is not the same as contributing to a typical GitHub project. The codebase spans hundreds of repositories, each with its own release cadence. The CI is opinionated. The maintainers follow processes that are documented in scattered places — or not documented at all. And if you're coming from a product engineering background where you ship features on your own terms, the cultural shift can be jarring.

I recently submitted four pull requests across three ROS 2 core repositories:

| PR | Repository | Summary |
|---|---|---|
| [#3109](https://github.com/ros2/rclcpp/pull/3109) | `ros2/rclcpp` | [Fix O(N²) entity addition in `CallbackGroup`](/posts/fixing-quadratic-callback-group-rclcpp/) |
| [#3110](https://github.com/ros2/rclcpp/pull/3110) | `ros2/rclcpp` | Fix deadlock in `TimeSource::destroy_clock_sub` |
| [#1213](https://github.com/ros2/ros2cli/pull/1213) | `ros2/ros2cli` | Add `--content-filter` to `ros2 topic echo\|hz\|bw` |
| [#908](https://github.com/ros2/geometry2/pull/908) | `ros2/geometry2` | Fix `StaticCache::getData()` on empty cache |

Every single one of them hit at least one non-obvious obstacle during the submission process. This post is the guide I wish I'd had before I started.

---

## Step 0: Finding Issues Worth Fixing

The best place to start is the issue tracker on each ROS 2 repository. Look for issues tagged `help wanted` or `good first issue`, but don't limit yourself to those — many legitimate bugs sit untagged for months.

The four issues I picked:

- **[rclcpp#2942](https://github.com/ros2/rclcpp/issues/2942)** — A user reported that creating 10,000 timers took 429ms due to O(N²) cleanup in `CallbackGroup::add_timer()`. The reproducer was included. Clear bug, clear impact.
- **[rclcpp#2962](https://github.com/ros2/rclcpp/issues/2962)** — A deadlock in `TimeSource::destroy_clock_sub()` where the main thread held a lock while joining a thread that needed the same lock. Race conditions are hard to reproduce but easy to reason about once identified.
- **[ros2cli#1126](https://github.com/ros2/ros2cli/issues/1126)** — A feature request to support DDS content filter expressions in `ros2 topic echo`. The middleware already supports it via `rclpy`; the CLI just didn't expose it.
- **[geometry2#769](https://github.com/ros2/geometry2/issues/769)** — `StaticCache::getData()` returned `true` even when no data had been inserted, causing callers to read uninitialized `TransformStorage`.

**Tip:** Before writing code, read the entire issue thread. Often, maintainers have already commented on the desired approach, or other contributors have attempted fixes that reveal constraints you wouldn't otherwise know about.

---

## Step 1: Fork, Clone, and Branch

ROS 2 repositories live under the [ros2](https://github.com/ros2) organization. You can't push branches directly — you need to fork.

```bash
# Fork via GitHub UI, then clone your fork
git clone https://github.com/YourUsername/rclcpp.git
cd rclcpp
git remote add upstream https://github.com/ros2/rclcpp.git
git fetch upstream rolling
```

### Target the `rolling` Branch

This is the first thing most new contributors get wrong — I did too. ROS 2 has multiple active distro branches: `humble`, `jazzy`, `rolling`, etc. **Always target `rolling`** unless the bug is confirmed to only affect an older distro.

The maintainers will backport to older distros after merging into `rolling`. If you submit against `humble` or `jazzy`, you'll be asked to retarget:

> *"Although some bug reports or feature requests mention a specific distro, we prefer making changes to the Rolling distro (rolling branch) and then we can backport it to older distros if appropriate."*
> — christophebedard, ROS 2 maintainer

I initially submitted my PRs against `humble` and `jazzy` because the bug reports referenced those distros. All four had to be retargeted and rebased onto `rolling`.

```bash
# Create your feature branch from rolling
git checkout -b fix/my-awesome-fix upstream/rolling
```

**Naming convention:** Use descriptive branch names with a prefix: `fix/`, `feature/`, `docs/`.

---

## Step 2: Build and Test in Docker

Never install ROS 2 natively for contribution work. Use Docker. The official images match what CI runs, and you avoid polluting your development machine.

```bash
# Pull the rolling image
docker pull ros:rolling

# Start a persistent container
docker run -d --name ros2-dev ros:rolling sleep infinity

# Install build tools
docker exec ros2-dev bash -c '
  apt-get update -qq
  apt-get install -y -qq git build-essential python3-colcon-common-extensions
'
```

### Setting Up the Workspace

```bash
docker exec ros2-dev bash -c '
  mkdir -p /ws/src
  cd /ws/src
  git clone --branch fix/my-awesome-fix --depth 1 \
    https://github.com/YourUsername/rclcpp.git
'
```

### The Version Mismatch Trap

Here's a problem that will bite you: **the Docker image's installed packages may lag behind the git `HEAD` of `rolling`**.

When I cloned rclcpp from the latest `rolling` commit and tried to build it inside the `ros:rolling` Docker image, I got:

```
error: 'rcl_subscription_is_cft_supported' was not declared in this scope;
did you mean 'rcl_subscription_is_cft_enabled'?
```

The rclcpp source code on git `HEAD` referenced a function that had been renamed in `rcl`, but the Docker image still had the old `rcl` package.

**The fix:** Don't build from git `HEAD`. Build from the tag that matches the installed binary package:

```bash
# Check the installed version
dpkg -s ros-rolling-rclcpp | grep Version
# Version: 30.1.5-1noble.20260210.205440

# Clone at the matching tag
git clone --branch 30.1.5 --depth 1 https://github.com/ros2/rclcpp.git
```

Then apply your changes on top of that tag. This guarantees your code compiles against the same dependencies that exist in the Docker image.

For small, contained changes (like modifying a single `.cpp` file), you can even apply the patch directly:

```bash
# Apply just your changes to the matching source
cd /ws/src/rclcpp
# ... edit the specific files ...
```

### Building

```bash
docker exec ros2-dev bash -c '
  source /opt/ros/rolling/setup.bash
  cd /ws
  colcon build --packages-select rclcpp \
    --cmake-args -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=ON
'
```

If you get missing test dependency errors:

```bash
apt-get install -y ros-rolling-test-msgs \
  ros-rolling-mimick-vendor \
  ros-rolling-performance-test-fixture \
  ros-rolling-ament-cmake-google-benchmark
```

### Running Tests

ROS 2 uses `ctest` under the hood. You can run specific tests or the full suite:

```bash
docker exec ros2-dev bash -c '
  source /opt/ros/rolling/setup.bash
  source /ws/install/setup.bash
  cd /ws/build/rclcpp

  # Run a specific test
  ctest -R test_time_source --output-on-failure --timeout 120

  # Run the full suite
  ctest --output-on-failure --timeout 120
'
```

For my callback group fix, the relevant tests were:

```bash
ctest -R test_allocator_memory_strategy   # Passed
ctest -R test_add_callback_groups_to_executor  # Passed
ctest -R test_memory_strategy             # Passed
ctest -R test_executors_callback_group_behavior  # Passed
```

For the deadlock fix, I ran `test_time_source` multiple times to confirm no freezes:

```bash
for i in 1 2 3; do
  echo "=== Run $i ==="
  ctest -R test_time_source --output-on-failure --timeout 120
done
```

All three runs passed cleanly — 16 tests each, no hangs.

### Python Package Testing

For `ros2cli` (Python), the workflow is different. You build with colcon and then test the CLI directly:

```bash
# Build the modified package
colcon build --packages-select ros2cli ros2topic

# Source the overlay
source /ws/install/setup.bash

# Verify the new arguments appear
ros2 topic echo --help | grep content-filter
ros2 topic hz --help | grep content-filter
ros2 topic bw --help | grep content-filter
```

### End-to-End Testing

For the content filter feature, I ran actual E2E tests with a publisher:

```bash
# Start a talker in the background
ros2 run demo_nodes_cpp talker &

# Test: matching filter should receive messages
timeout 5 ros2 topic echo /chatter \
  --content-filter "data LIKE '%Hello%'" --once
# Output: data: 'Hello World: 3'

# Test: non-matching filter should receive nothing
timeout 5 ros2 topic echo /chatter \
  --content-filter "data LIKE '%NOMATCH%'" --once
# (times out — correct, no matching messages)

# Test: no filter works unchanged
timeout 5 ros2 topic echo /chatter --once
# Output: data: 'Hello World: 9'
```

---

## Step 3: The Commit

### Signed-off-by (DCO)

ROS 2 repositories require the [Developer Certificate of Origin](https://developercertificate.org/). Every commit must have a `Signed-off-by` trailer matching the commit author. Without it, the DCO CI check fails with `action_required`.

```bash
# Always commit with --signoff
git commit --signoff -m "Fix O(N²) entity addition in CallbackGroup

The add_* methods performed a full linear scan to remove expired
weak_ptrs on every call. When adding N entities, this resulted in
O(N²) total operations.

Move expired-entry cleanup into collect_all_ptrs, which already
iterates all entries and is called regularly by the executor.

Fixes https://github.com/ros2/rclcpp/issues/2942

Signed-off-by: Your Name <your@email.com>"
```

**If you forgot `--signoff`**, amend the commit:

```bash
git commit --amend --signoff --no-edit
git push --force
```

This was the very first CI failure I hit on all four PRs. The fix is trivial but the failure message (`DCO: action_required`) isn't obvious if you've never seen it before.

### Commit Message Style

ROS 2 doesn't enforce a rigid format, but good practice is:

- **First line:** Imperative mood summary (under 72 chars)
- **Body:** Explain *what* changed and *why*, not *how* (the diff shows how)
- **Footer:** Reference the issue with `Fixes #NNN` or `Closes #NNN`
- **Trailer:** `Signed-off-by: Name <email>`

---

## Step 4: The Pull Request

### PR Description

Include:

1. **Summary** — What the PR does and why
2. **What changed** — Bullet points of the specific modifications
3. **Why it's safe** — For behavioral changes, explain why existing code won't break
4. **Test plan** — Checklist of tests you ran, with results

Example from my callback group PR:

```markdown
## Summary

Fixes #2942

The `add_*` methods performed a full linear scan to remove expired
`weak_ptr`s on every call. When adding N entities, this resulted in
O(N²) total operations.

**Changes:**
- Remove the `erase(remove_if(...expired...))` cleanup from all five
  `add_*` methods, making them O(1)
- Move expired-entry cleanup into `collect_all_ptrs` via a new
  `collect_and_compact` helper

## Test plan

- [x] `test_allocator_memory_strategy` — passed
- [x] `test_add_callback_groups_to_executor` — passed
- [x] `test_memory_strategy` — passed
- [x] Full rclcpp test suite: 122/122 passed
```

### OSRF AI Disclosure Policy

If you used any generative AI tool while writing your contribution, **you must disclose it**. This is an [OSRF policy](https://github.com/openrobotics/osrf-policies-and-procedures/blob/main/OSRF%20Policy%20on%20the%20Use%20of%20Generative%20Tools%20(%E2%80%9CGenerative%20AI%E2%80%9D)%20in%20Contributions.md), not a suggestion.

The disclosure must include:
- That AI was used
- Which tool/model (e.g., "Claude Opus by Anthropic")
- That you have reviewed and validated the changes

I added mine as a PR comment:

> **AI disclosure:** This PR was authored with the assistance of Claude Opus (Anthropic) as a generative AI coding tool. I have reviewed and validated the changes.

The maintainer specifically flagged this when it was missing:

> *"I believe that this PR was written and/or opened by an AI agent. Please note that the OSRF has a policy on the use of tools like generative AI tools."*

Don't skip this. It's a policy requirement and maintainers will call it out.

---

## Step 5: Rebasing Across Distro Branches

If you initially targeted the wrong branch (as I did), you need to rebase your changes onto `rolling`. This is where things get interesting.

### The Easy Case: Clean Cherry-Pick

For my `geometry2` fix (2 files changed), the cherry-pick applied cleanly:

```bash
git checkout -b fix/static-cache-rolling upstream/rolling
git cherry-pick --signoff <commit-sha>
# Auto-merging tf2/include/tf2/time_cache.hpp
# [fix/static-cache-rolling 2371ec45] Fix StaticCache::getData()...
```

### The Hard Case: Merge Conflicts

For `rclcpp` and `ros2cli`, the `rolling` branch had diverged significantly from `humble`/`jazzy`. The `rolling` branch had new features (multi-topic support, interactive selection, `--all` flag) that didn't exist in the older branches.

Cherry-picking produced conflicts in every file:

```
CONFLICT (content): Merge conflict in ros2topic/ros2topic/verb/echo.py
CONFLICT (content): Merge conflict in ros2topic/ros2topic/verb/hz.py
CONFLICT (content): Merge conflict in ros2topic/ros2topic/verb/bw.py
```

The resolution strategy:

1. **Keep all of `rolling`'s code** — the new features, imports, function signatures, everything
2. **Adapt your feature to work with `rolling`'s API** — don't just pick one side of the conflict
3. **Test thoroughly** — the adapted code is effectively a new implementation

For `ros2cli`, I had to adapt the content-filter feature from a single-topic API (jazzy) to a multi-topic API (rolling). The `_rostopic_hz` function signature changed from:

```python
# jazzy (single topic)
def _rostopic_hz(node, topic, window_size=..., filter_expr=None,
                 use_wtime=False, content_filter_options=None):
```

to:

```python
# rolling (multi-topic with --all support)
def _rostopic_hz(node, topics, qos_args, window_size=..., filter_expr=None,
                 use_wtime=False, all_topics=False, content_filter_options=None):
```

The content filter parameter passes through to `create_subscription()` in the per-topic loop — the core idea is the same, but the plumbing is different.

### Force-Pushing the Rebased Branch

After resolving conflicts:

```bash
# Force-push your rebased branch to update the PR
git push origin fix/my-branch-rolling:fix/my-branch-original --force
```

This updates the PR in place. The diff stats should now show only your actual changes:

```
Before rebase: 97 commits, 126 files changed  (included all humble→rolling diffs)
After rebase:  1 commit, 2 files changed       (just the fix)
```

---

## Step 6: Handling Reviewer Feedback

ROS 2 maintainers are thorough but fair. Common feedback patterns:

### "Please target rolling"

Already covered above. This is the most common first response.

### "Please disclose AI usage"

Already covered. Include the tool name and model.

### Backport Requests

After retargeting to `rolling`, explicitly ask for backports in a comment:

```
The bug also affects `humble` and `jazzy`. Would appreciate a backport
to those distros once this is merged into `rolling`.
```

Maintainers handle backports themselves — you don't need to submit separate PRs for each distro.

---

## Step 7: CI Checks

ROS 2 PRs typically run two CI checks:

### 1. DCO (Developer Certificate of Origin)

Checks that every commit has a `Signed-off-by` line. Fails with `action_required` if missing.

**Fix:** `git commit --amend --signoff --no-edit && git push --force`

### 2. Summary (Build + Test)

The full CI build runs on the maintainers' infrastructure. It builds your changes against the full ROS 2 dependency graph and runs the test suite.

You can't trigger this yourself, but you can pre-validate locally in Docker (as described in Step 2). If your local tests pass with 100% on `ros:rolling`, the CI will almost certainly pass too.

---

## Common Pitfalls and How to Avoid Them

### 1. Building from git HEAD in Docker

**Problem:** The rolling Docker image packages lag behind git HEAD. API mismatches cause build failures in files you didn't touch.

**Solution:** Check the installed package version with `dpkg -s ros-rolling-<package>`, clone at the matching git tag, and apply your changes on top.

### 2. Forgetting --signoff

**Problem:** DCO check fails immediately.

**Solution:** Always use `git commit --signoff`. Add it to your git alias:

```bash
git config --global alias.cs "commit --signoff"
```

### 3. Targeting the Wrong Branch

**Problem:** Maintainer asks you to retarget, and now you need to rebase across potentially divergent branches.

**Solution:** Always start from `rolling`. If the issue mentions `humble`, verify the bug exists on `rolling` first. If it does, fix it there.

### 4. Not Testing in Docker

**Problem:** "Works on my machine" doesn't cut it when CI runs on a different Ubuntu version with different compiler flags.

**Solution:** Always validate in `ros:rolling` Docker. The 5 minutes of container setup saves hours of CI debugging.

### 5. Massive PR Diffs After Retargeting

**Problem:** After changing the base branch from `humble` to `rolling`, your PR shows hundreds of commits and files because it includes all the divergent history.

**Solution:** Don't just change the base branch — rebase your commits onto `rolling` and force-push. The PR should show only your actual changes.

### 6. Test Dependencies Not Installed

**Problem:** Build fails with `find_package(test_msgs)` or similar.

**Solution:** Install test dependencies explicitly:

```bash
apt-get install -y ros-rolling-test-msgs \
  ros-rolling-mimick-vendor \
  ros-rolling-performance-test-fixture \
  ros-rolling-ament-cmake-google-benchmark \
  ros-rolling-ament-cmake-gtest
```

---

## The Concrete Changes: What I Actually Fixed

### Fix 1: O(N²) Entity Addition (rclcpp)

The `CallbackGroup::add_timer()` (and four siblings) ran `erase(remove_if(...expired...))` on every call — a full linear scan of the vector to remove expired `weak_ptr`s. Adding N entities was O(N²).

The fix: remove the cleanup from `add_*` methods (making them O(1)), and instead compact expired entries during `collect_all_ptrs()`, which the executor already calls on every spin iteration:

```cpp
namespace {
template<typename T, typename Func>
void collect_and_compact(
  std::vector<typename T::WeakPtr> & ptrs,
  const Func & func)
{
  size_t write_idx = 0;
  for (size_t read_idx = 0; read_idx < ptrs.size(); ++read_idx) {
    auto ref_ptr = ptrs[read_idx].lock();
    if (ref_ptr) {
      func(ref_ptr);
      if (write_idx != read_idx) {
        ptrs[write_idx] = std::move(ptrs[read_idx]);
      }
      ++write_idx;
    }
  }
  ptrs.resize(write_idx);
}
}  // namespace
```

Result: 10,000 timers went from 429ms to 6ms — a 71.5x speedup.

### Fix 2: Deadlock in TimeSource (rclcpp)

`destroy_clock_sub()` held `clock_sub_lock_` while calling `clock_executor_thread_.join()`. If the executor thread's callback needed `clock_sub_lock_`, deadlock:

```
Main thread:     lock → cancel → join [BLOCKED]
Executor thread: callback needs lock [BLOCKED]
→ DEADLOCK
```

The fix: move the thread, executor, and callback group into local variables under the lock, release the lock, then join outside the critical section:

```cpp
void destroy_clock_sub()
{
  std::thread thread_to_join;
  std::shared_ptr<SingleThreadedExecutor> executor_to_clean;
  CallbackGroup::SharedPtr callback_group_to_remove;

  {
    std::lock_guard<std::mutex> guard(clock_sub_lock_);
    if (clock_executor_thread_.joinable()) {
      clock_executor_->cancel();
      thread_to_join = std::move(clock_executor_thread_);
      executor_to_clean = clock_executor_;
      callback_group_to_remove = clock_callback_group_;
    }
    clock_subscription_.reset();
  }

  // Join outside the lock
  if (thread_to_join.joinable()) {
    thread_to_join.join();
    executor_to_clean->remove_callback_group(callback_group_to_remove);
  }
}
```

### Fix 3: Content Filter CLI (ros2cli)

Added `--content-filter` and `--content-filter-params` to `ros2 topic echo`, `hz`, and `bw`. The middleware already supports content filtering via `rclpy.subscription_content_filter_options.ContentFilterOptions` — the CLI just didn't expose it:

```python
content_filter_options = None
if args.content_filter_expr:
    content_filter_options = ContentFilterOptions(
        filter_expression=args.content_filter_expr,
        expression_parameters=args.content_filter_params)

node.create_subscription(
    msg_class, topic, callback, qos_profile,
    content_filter_options=content_filter_options)
```

Usage:

```bash
ros2 topic echo /chatter --content-filter "data LIKE '%Hello%'"
ros2 topic hz /sensor --content-filter "temperature > %0" \
  --content-filter-params 30.0
```

### Fix 4: StaticCache Empty Check (geometry2)

`StaticCache::getData()` unconditionally returned `true` and copied `storage_` to the output — even when `insertData()` had never been called. The output was uninitialized memory.

The fix: a `populated_` flag:

```cpp
bool StaticCache::getData(TimePoint time, TransformStorage & data_out,
                          std::string * error_str, TF2Error * error_code)
{
  if (!populated_) {
    if (error_str) *error_str = "Static cache is empty";
    if (error_code) *error_code = TF2Error::TF2_LOOKUP_ERROR;
    return false;
  }
  data_out = storage_;
  data_out.stamp_ = time;
  return true;
}
```

---

## Test Results Summary

All testing was done in `ros:rolling` Docker containers:

| PR | Test Suite | Result |
|---|---|---|
| rclcpp #3109 | Full rclcpp (122 tests) | 122/122 passed |
| rclcpp #3110 | Full rclcpp (122 tests) + 3x `test_time_source` | All passed, no freezes |
| ros2cli #1213 | Help output + E2E filter tests | All passed |
| geometry2 #908 | Full tf2 (12 tests) | 12/12 passed |

---

## The Workflow Cheat Sheet

```
1. Find an issue on github.com/ros2/*
2. Fork the repo
3. git checkout -b fix/your-fix upstream/rolling
4. Make your changes
5. Build + test in Docker (ros:rolling)
6. git commit --signoff
7. git push origin fix/your-fix
8. Open PR against rolling
9. Add AI disclosure if applicable
10. Wait for review
11. Address feedback
12. Ask for backport to older distros
```

---

## Key Takeaways

1. **Always target `rolling`.** The maintainers backport from there. Submitting against an older distro creates unnecessary work for everyone.

2. **Always use `--signoff`.** The DCO check is a hard gate. Make it muscle memory.

3. **Always test in Docker.** `ros:rolling` is your ground truth. Match the installed package version when building from source.

4. **Disclose AI usage.** It's OSRF policy. Include the tool name and model. Don't make the maintainer ask.

5. **Expect rebasing pain.** If `rolling` has diverged from the distro where you found the bug, the rebase may require adapting your code to a different API. Budget time for this.

6. **Small, focused PRs.** Each of my PRs changed 1–3 files. Small PRs get reviewed faster and are easier to backport.

7. **Pre-validate everything.** The faster your PR goes green on the first CI run, the faster it gets reviewed. Maintainers have hundreds of PRs to look at — don't waste their time with avoidable failures.

---

**Related:**
- [Fixing O(N^2) Entity Addition in ROS 2's CallbackGroup](/posts/fixing-quadratic-callback-group-rclcpp/)
- [PX4 Autopilot: A Practitioner's Guide to Troubleshooting, Debugging, Building, and Testing](/posts/px4-autopilot-troubleshooting-debugging-testing-guide/)
