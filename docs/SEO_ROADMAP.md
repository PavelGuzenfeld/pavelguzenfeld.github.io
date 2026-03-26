# SEO Roadmap — pavelguzenfeld.com

Goals: recruiter visibility, consulting leads, open-source discovery.

---

## Phase 1 — Quick Wins (homepage + config)

### 1.1 Enrich homepage title tag
- **Current:** `Pavel Guzenfeld`
- **Target:** `Pavel Guzenfeld — UAV Avionics & C++23 Engineer | ROS 2, PX4`
- **File:** `hugo.yaml` → `title` field
- **Why:** Title tag is the single strongest on-page ranking signal. Current title wastes it on name alone.

### 1.2 Strengthen meta description
- **Current:** "Drone Avionics Software Engineer — C++23, ROS 2, real-time systems, open-source"
- **Target:** "Senior C++23 engineer building flight-critical avionics, navigation, and computer-vision pipelines for UAVs with ROS 2 and PX4. Open to full-time, contract, and consulting."
- **File:** `hugo.yaml` → `params.description`
- **Why:** Current description is decent but misses recruiter/consulting intent keywords.

### 1.3 Keyword-rich homeInfoParams
- **Current Content:** "Drone Avionics Software Engineer — C++23, ROS 2, PX4, open-source"
- **Target Title:** "UAV Avionics & C++23 Engineer — ROS 2 / PX4 / Real-Time Systems"
- **Target Content:** "I design and implement flight-critical software for drones and robotics: navigation pipelines, behavior trees, and real-time computer vision. Open to full-time roles, contracting, and consulting — remote or on-site."
- **File:** `hugo.yaml` → `params.homeInfoParams`

### 1.4 Fix About page meta description
- **Current:** "About Pavel Guzenfeld" (generic)
- **Target:** Add a `summary` field to `content/about.md` frontmatter with a keyword-rich description.

### 1.5 Add Google Search Console verification
- **File:** `hugo.yaml` → `params.analytics.google.SiteVerificationTag`
- **Action:** Register site in Google Search Console, get verification tag, add it.

---

## Phase 2 — Visual & Social Sharing

### 2.1 Create a default OG image
- Design a 1200x630px image with name + title + key tech logos.
- Place in `static/images/og-default.png`.
- Reference in `hugo.yaml`:
  ```yaml
  params:
    images:
      - /images/og-default.png
  ```
- **Why:** Every social share currently renders with no image — kills click-through rate.

### 2.2 Add cover images to top blog posts
- At minimum, add `cover.image` frontmatter to the 5 highest-value posts:
  - contributing-to-ros2-a-practical-guide
  - px4-autopilot-troubleshooting-debugging-testing-guide
  - gst-nvmm-cpp-zero-copy-video-jetson
  - anatomy-of-gstreamer-shm-bugs
  - gram-schmidt-vs-householder-qr-benchmark
- Simple diagrams or terminal screenshots are fine.

### 2.3 Add Twitter/X handle
- If you have one, add to `hugo.yaml`:
  ```yaml
  params:
    social:
      twitter: "your_handle"
  ```

---

## Phase 3 — Content: Recruiter & Consulting Sections

### 3.1 Add "For Recruiters" section to homepage
Add below "What I Do" in `content/_index.md`:
```markdown
## For Recruiters

- **Experience:** 10+ years shipping C++ in production (avionics, robotics, real-time).
- **Core stack:** C++23, ROS 2, PX4, GStreamer, Jetson, Docker, CMake.
- **Domains:** UAV/drone, robotics, computer vision, flight control.
- **Status:** Open to full-time and contract roles, remote or hybrid.
- [Download CV (PDF)](/cv/pavel-guzenfeld-cv.pdf)
```
- Create and add a PDF CV at `static/cv/pavel-guzenfeld-cv.pdf`.

### 3.2 Create a Consulting page
- **File:** `content/consulting.md`
- **H1:** "Consulting for UAV and Robotics Teams"
- **Sections:**
  - What I help with (3-4 bullets: C++23 systems, ROS 2 + PX4 integration, GStreamer/Jetson pipelines, CI/testing infrastructure)
  - Micro case studies (2-3 sentences each: problem → what you did → outcome)
  - Call to action: "Tell me about your project" → email link
- **Add to nav:** `hugo.yaml` menu, weight 15 (between Projects and Blog).
- **Why:** Catches "hire ROS 2 developer" / "drone software consultant" long-tail queries.

### 3.3 Add location signals
- Add "Based in Israel — available worldwide (remote)" to About page and/or homepage.
- **Why:** Surfaces in geo-flavored recruiter searches like "C++ engineer Israel remote".

---

## Phase 4 — Content: Dedicated Project Pages

Create individual pages for each featured project so they can rank independently.

### 4.1 behavior-tree-lite
- **File:** `content/projects/behavior-tree-lite.md`
- **H1:** "behavior-tree-lite — C++23 Header-Only Behavior Tree Library"
- **Target queries:** "C++ behavior tree library", "header-only behavior tree", "compile-time behavior tree DSL"
- **Content:** What it does, why it's different (zero heap, 10x smaller binary), code examples, benchmarks, link to GitHub.

### 4.2 strong-types
- **File:** `content/projects/strong-types.md`
- **H1:** "strong-types — Compile-Time Type Safety for C++ Primitives"
- **Target queries:** "C++ strong typedef", "type-safe units C++", "strong type aliases"

### 4.3 l2-hybrid-protocol
- **File:** `content/projects/l2-hybrid-protocol.md`
- **H1:** "l2-hybrid-protocol — Low-Latency Layer 2 Protocol for Drone Telemetry"
- **Target queries:** "low latency drone telemetry", "Layer 2 protocol UAV"

### 4.4 fiber-nav-sim
- **File:** `content/projects/fiber-nav-sim.md`
- **H1:** "fiber-nav-sim — PX4 + Gazebo VTOL Navigation Simulator"
- **Target queries:** "PX4 Gazebo VTOL simulator", "drone navigation simulation ROS 2"

### 4.5 Update projects.md
- Change project entries to link to dedicated pages instead of (or in addition to) GitHub.
- **Why:** Keeps traffic on your site, gives Google more pages to index.

---

## Phase 5 — Authority & Backlinks

### 5.1 GitHub README backlinks
- In each featured project's GitHub README, add a link back to the dedicated project page on pavelguzenfeld.com.
- Use descriptive anchor text: "Documentation and design notes for this C++ behavior tree library".

### 5.2 LinkedIn / profile consistency
- Ensure LinkedIn, GitHub bio, and other profiles all link to pavelguzenfeld.com with consistent anchor text: "Pavel Guzenfeld — UAV Avionics & C++23 Engineer".

### 5.3 Add "Selected Contributions" section
- On About or homepage, link to 3-5 notable merged PRs with brief context.
- **Why:** Increases time on site, gives Google expertise signals.

---

## Phase 6 — Blog Post SEO Polish

### 6.1 Audit post frontmatter
- Ensure every post has:
  - `description:` or `summary:` (unique, 120-160 chars, includes target keyword)
  - `tags:` (relevant, consistent naming)
  - `keywords:` (if different from tags — target specific search phrases)

### 6.2 Internal cross-linking
- Link between related posts (e.g., PX4 posts link to each other, Eigen posts link to each other).
- Link from posts to relevant project pages (Phase 4) and consulting page (Phase 3).

### 6.3 Enrich post titles for search
- Review post titles — some are good for readers but could include a target keyword more explicitly.
- Example: "Anatomy of Four GStreamer Shared Memory Bugs" is strong as-is.
- Example: "Hello World" → could be retitled or noindexed if it has no SEO value.

---

## Priority Order

| Priority | Item | Effort | Impact |
|----------|------|--------|--------|
| 1 | 1.1–1.3 Homepage title + meta + homeInfo | 15 min | High |
| 2 | 2.1 Default OG image | 30 min | High |
| 3 | 3.1 "For Recruiters" section | 30 min | High |
| 4 | 1.4 About page description | 5 min | Medium |
| 5 | 3.2 Consulting page | 1 hr | High |
| 6 | 4.1–4.4 Dedicated project pages | 2 hr | Medium |
| 7 | 1.5 Search Console verification | 15 min | Medium |
| 8 | 5.1–5.2 Backlinks from GitHub/LinkedIn | 30 min | Medium |
| 9 | 6.1–6.3 Blog post SEO polish | 1 hr | Low-Med |
| 10 | 2.2 Post cover images | 1 hr | Low-Med |
| 11 | 3.3 Location signals | 5 min | Low |
| 12 | 2.3 Twitter handle | 5 min | Low |
