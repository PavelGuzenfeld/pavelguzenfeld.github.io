---
title: "The Road to Boost.SML 1.2.0: New API and a Type-Name Heisenbug"
date: 2026-06-01
draft: false
tags:
- C++
- open-source
- compilers
- GCC
- Docker
- documentation
- contributing
- debugging
- testing
- CI-CD
keywords:
- boost sml 1.2.0
- boost ext sml state machine
- get_type_name pretty function offset
- compiler explorer include from url
- inline namespace abi versioning
cover:
  image: /images/posts/boost-sml-1-2-0.png
  alt: The Road to Boost.SML 1.2.0
categories:
- deep-dive
summary: A warts-and-all account of cutting the Boost.SML 1.2.0 release — four new
  public APIs, a behavior change rooted in undefined behavior, a type-name Heisenbug
  that only fired on GCC and MSVC, a dead "Run" button, and the surprisingly deep
  rabbit hole of making 30 Compiler Explorer links that actually work.
ShowToc: true
audio:
  pronunciation:
    SML: S M L
    sml: S M L
    boost-ext: boost ext
    Boost.SML: boost S M L
    get_type_name: get type name
    constexpr: con-stex-per
    make_action: make action
    flush_queue: flush queue
    clear_defer: clear defer
    deps: deps
    __PRETTY_FUNCTION__: pretty function
    __FUNCSIG__: func sig
    namespace: namespace
    UBSan: U B san
    MSVC: M S V C
    GCC: G C C
    IAR: I A R
    Godbolt: god-bolt
    Wandbox: wand-box
    dispatch_table: dispatch table
    CMake: C make
    ctest: C test
    ABI: A B I
    semver: sem-ver
---

[Boost.SML](https://github.com/boost-ext/sml) is Kris Jusiak's header-only state machine library: one file, no dependencies, C++14, and a transition-table DSL that reads almost like the UML diagram it replaces. It compiles to tight code and has near-zero runtime overhead. It is also, internally, one of the densest pieces of template metaprogramming you will find in a widely-used C++ library — which makes contributing to it equal parts rewarding and humbling.

This post is the field report from cutting the **1.2.0 release**: everything that shipped, and — more interestingly — everything that went sideways along the way. There are four new public APIs, a behavior change that traces back to undefined behavior at `-O2`, a type-name bug that passed on Clang while failing on GCC and MSVC, a "Run this code" button that had been quietly dead for years, and a deep rabbit hole into how you make a Godbolt link for a library Compiler Explorer doesn't know about.

If you only take one thing away: **the hard part of a release is rarely the feature. It's the second-order coupling you didn't know existed.**

## What shipped in 1.2.0

The release collects everything merged since `v1.1.13`. Four of those are new public surface area, so let's start there.

### `sm::flush_queue()` — draining events from async callbacks

SML's `process_queue` policy lets actions enqueue events (via `back::process<E>`) to be dispatched after the current event finishes. `process_event()` drains that queue before it returns. But what about an event pushed *after* `process_event()` has already returned — say, from an asynchronous callback that captured a `back::process<>` handle?

Before 1.2.0 there was no way to drain it without feeding the machine another event. `flush_queue()` fixes that:

```cpp
struct AsyncHandle { sml::back::process<e2> push{}; };

sml::sm<SM, sml::process_queue<std::queue>> sm{handle, fired};

sm.process_event(e1{});  // an action stores the back::process<e2> handle
handle.push(e2{});       // async callback pushes e2 *after* process_event returned
sm.flush_queue();        // drain it now — e2 is processed
```

It runs anonymous transitions to a fixpoint, then dispatches whatever is queued, taking the same `thread_safe` lock as `process_event`. It is a no-op on an empty queue. Small surface, but it closes a real gap for anyone integrating SML with an event loop or an async I/O layer.

### `sml::clear_defer` — discarding deferred events

The `defer` action postpones an event for later re-evaluation. The mirror operation was missing: *throwing away* what's deferred. `clear_defer` is the counterpart, and the motivating case is composite states:

```cpp
state<Sub> + event<leave> / clear_defer = "outer"_s
```

When you leave a sub-machine, events that were deferred inside it should not survive to haunt you on re-entry. `clear_defer` drops them. It's a no-op when nothing is deferred and requires a `defer_queue` policy. (A related fix, issue #253, makes the sub-machine's defer queue clear automatically on composite re-entry — the two together close the "stale deferred event" class of bug.)

### `sml::deps<Ts...>` — when a dependency vanishes from the pool

This one is subtle and bit real users. SML builds its dependency pool from the parameter types that appear in your actions' and guards' signatures. It reads those types off each callable's `operator()`. So this works — `Dep&` is in the signature:

```cpp
auto action = [](Dep& d) { d.value = 99; };
```

But a *generic* lambda that fishes the dependency out of the deps tuple by hand does **not** advertise `Dep` anywhere:

```cpp
auto action = [](auto, auto&, auto& deps, auto&) {
  sml::aux::get<Dep&>(deps).value = 99;   // Dep appears in no signature
};
```

`Dep` never makes it into the auto-deduced dependency list, so it's absent from the pool, and the `static_cast` from the pool to `pool_type<Dep&>` fails to compile. The fix is a new SM policy that widens the pool explicitly:

```cpp
sml::sm<table, sml::deps<MyDep>> sm{dep};  // force MyDep into the pool
```

Purely additive — existing machines are unaffected.

### `sml::make_action<Deps...>` — teaching the deducer about generic lambdas

The same root cause — SML reading parameter types off `operator()` — produces a *second* failure mode. A generic or concept-constrained callable exposes only a template, so the type-trait probe has nothing concrete to read and guesses wrong (it tends to conclude the callable wants the *event* rather than the dependency).

`make_action<Deps...>(f)` pins an explicit signature in front of the callable so the deducer has something real to inspect, while still forwarding to the original lambda:

```cpp
// generic lambda — name the dependency explicitly
*"s1"_s + event<trigger> / make_action<Counter&>([](auto& c) { c.n++; }) = X

// works for guards too, and for event + deps in call order
*"s1"_s + event<trigger> / make_action<const trigger&, Counter&>(
                              [](const auto& e, auto& c) { /* ... */ }) = X
```

The implementation is delightfully small — a wrapper struct with a fixed `operator(TDeps...)` — but it removes a genuine papercut for anyone who likes `[](auto&)` lambdas or C++20 constrained `auto`.

### The behavior change worth shouting about: the min-size UB (#249)

Not every change is an addition. SML historically shrank empty state-machine objects with a zero-length-array trick. It works — until you turn on the UndefinedBehaviorSanitizer at `-O2`, where it trips "insufficient object size" violations. That's genuine UB, not a false positive.

So 1.2.0 flips the default: the trick is **off** by default on GCC/Clang. You can opt back in with `BOOST_SML_CFG_ENABLE_MIN_SIZE`. The practical consequence is that `sizeof(sm<...>)` for an empty machine **may differ** from older releases. That observable change — combined with the new public API — is exactly why this is a **minor** version bump and not a patch.

A handful of other fixes round out the release: the `any`/`_` wildcard no longer fires when a composable sub-machine has terminated (#622); `process(E{})` events are now storable in the process queue (#580); a guard taking `const State&` now sees live pool state instead of a stale copy (#530). Useful, surgical, and individually undramatic.

## Semver, and why a "patch" became a minor

The reflex was 1.1.14. The right answer was 1.2.0.

New backward-compatible public API (`flush_queue`, `clear_defer`, `deps`, `make_action`) is, by the book, a **minor** bump. The `sizeof` behavior change under #249 reinforces it — code that (unwisely) asserted on empty-SM size could observe a difference. The project's own history was looser — 1.1.11 shipped a feature as a patch — but "what we did before" is not an argument for getting semver wrong now.

That decision had a cost I did not see coming. Bumping the version means bumping the **inline namespace**: `v1_1_13` → `v1_2_0`. And that one rename is where the release nearly went off the rails.

## The Heisenbug: a version bump that broke type names

Here is the entire diff that broke continuous integration:

```diff
-#define BOOST_SML_VERSION 1'1'13
-  inline namespace v1_1_13 {
+#define BOOST_SML_VERSION 1'2'0
+  inline namespace v1_2_0 {
```

Three characters shorter. CI went red on two jobs:

```
test_type_traits ...........................***Failed
type_traits.cpp:73: std::string("int") == get_type_name<int>()
test_policies_logging ......................***Failed
```

`get_type_name<int>()` was no longer returning `"int"`. And the failure had a bizarre signature: **GCC failed, MSVC failed, but macOS Clang passed.** Same source, same standard. How does a namespace rename break type-name extraction on two compilers but not the third?

### Why a name shrank a string

SML has no real reflection, so `get_type_name<T>()` does the classic trick: it reads `__PRETTY_FUNCTION__` (or `__FUNCSIG__` on MSVC) and slices out the type with **hardcoded character offsets**:

```cpp
#if defined(_MSC_VER) && !defined(__clang__)
  return detail::get_type_name<T, 65>(__FUNCSIG__, /* ... - 65 - 8 */);
#elif defined(__clang__) && (__clang_major__ >= 12)
  return detail::get_type_name<T, 50>(__PRETTY_FUNCTION__, /* ... - 50 - 2 */);
#elif defined(__GNUC__)
  return detail::get_type_name<T, 69>(__PRETTY_FUNCTION__, /* ... - 69 - 2 */);
#elif defined(__ICCARM__)
  return detail::get_type_name<T, 72>(__PRETTY_FUNCTION__, /* ... - 72 - 2 */);
#endif
```

That offset is the length of the prefix the compiler prints *before* the template argument — and that prefix contains the function's fully-qualified name, which contains the inline namespace:

```
const char* boost::ext::sml::v1_1_13::aux::get_type_name() [with T = int]
                              ^^^^^^^ shrink this by one char and every offset is off by one
```

`v1_1_13` is seven characters; `v1_2_0` is six. Every GCC/MSVC/IAR offset was now one too large, and the slice came back wrong.

### Why Clang got away with it

This is the part that turns a bug into a lesson. **Clang elides inline namespaces in `__PRETTY_FUNCTION__`.** Its printed name is `boost::ext::sml::aux::get_type_name()` — no `v1_2_0` at all. So Clang's offsets are independent of the namespace length and the rename couldn't touch them. GCC, MSVC, and IAR all print the inline namespace; Clang doesn't. That single divergence is why CI split cleanly down compiler lines and pointed straight at the cause.

The git history confirmed the pattern: an old commit had bumped the GCC offset `68 → 69` — exactly when a previous release lengthened the namespace from six to seven characters. The offsets had *always* been coupled to the namespace string length. Nobody had changed the length in a while, so the trap had gone dormant.

### The fix, and verifying it where I couldn't run it

The fix is a one-character-per-compiler adjustment for the compilers that print the namespace, and *nothing* for Clang:

```diff
-  return detail::get_type_name<T, 65>(__FUNCSIG__, ...);          // MSVC
+  return detail::get_type_name<T, 64>(__FUNCSIG__, ...);
-  return detail::get_type_name<T, 69>(__PRETTY_FUNCTION__, ...);  // GCC
+  return detail::get_type_name<T, 68>(__PRETTY_FUNCTION__, ...);
-  return detail::get_type_name<T, 72>(__PRETTY_FUNCTION__, ...);  // IAR
+  return detail::get_type_name<T, 71>(__PRETTY_FUNCTION__, ...);
```

GCC `68` wasn't a guess — it's the exact value the project used the last time the namespace was six characters long. I verified the GCC fix with the full test suite in Docker (69/69), but I couldn't run the live CI's MSVC locally. So I reached for an MSVC-via-Wine image and ran a **sensitivity check**: offset 64 passed, offset 65 produced the exact `type_traits.cpp:73` failure. That two-sided test — *this value works and the old value reproduces the bug* — is far stronger evidence than a single green run, and it's the kind of confirmation worth insisting on when you can't see the production environment.

I also left a comment in the header so the next person who renames the namespace doesn't rediscover this from scratch. The deeper lesson is uncomfortable: **an ABI-versioning decision (the inline namespace) was silently coupled to a reflection hack (the offsets).** Two features with no obvious relationship, joined by a string length. Those are the couplings that turn a trivial change into a CI fire.

## The documentation no one had written

With the code settled, the docs needed to actually describe 1.2.0. None of the new API appeared anywhere under `doc/`. So: a real CHANGELOG entry, a configuration-macro table (it had previously documented exactly one macro), reference entries for `flush_queue`, `deps`, and `make_action`, tutorial coverage for `defer`/`clear_defer`, and — because the FAQ was a zero-byte file — a seeded FAQ documenting two genuine limitations (`on_entry<_>` across translation units, and the `operator,` two-member-function-pointer gotcha) that had only ever lived in source comments.

I also fixed two pre-existing broken doc links while I was in there: a typo (`action_guards.cpp` → `actions_guards.cpp`) and a path that pointed at a directory that doesn't exist (`example/errors/` → `test/ft/errors/`). Small, but broken links erode trust in everything around them.

### The "Run this code" button that had been dead for years

SML's docs embed a "Compile & Run" button on examples. It POSTed to `http://melpon.org/wandbox/api/compile.json`. Two problems, each fatal:

1. **Plain HTTP on an HTTPS site** → browsers block it as mixed content.
2. **The host moved years ago.** Wandbox lives at `wandbox.org` now; the old endpoint is gone.

Repointing to `https://wandbox.org/api/compile.json` got it talking again — but the request still failed, because the payload carried a `boost-1.60` compiler option that current Wandbox rejects outright (SML has no Boost dependency; the option was vestigial). Dropping it, supplying the `dispatch_table.hpp` utility header alongside `sml.hpp`, and fixing the footer link brought the in-page runner back to life, verified end-to-end against the live API across half a dozen examples.

### The Godbolt rabbit hole

I wanted real, clickable "Run on Compiler Explorer" links next to every example. This turned out to be the deepest hole of the entire release.

**Problem one: SML isn't a Compiler Explorer library.** You can't just `#include <boost/sml.hpp>` and pick "sml" from a dropdown — there is no such dropdown. The first working approach was brute force: **inline the entire 3,600-line `sml.hpp` into every link's source.** Ugly, but it compiles, and I validated all 30 links (25 examples + 4 deliberately-failing error demos + a `make_action` snippet) by actually compiling and executing each through Godbolt's API.

That validation immediately earned its keep. The `data.cpp` example defines a config macro *before* including the header:

```cpp
#define BOOST_SML_CREATE_DEFAULT_CONSTRUCTIBLE_DEPS
#include <boost/sml.hpp>
```

My first assembler pasted the header at the top and the example after it — putting the `#define` *after* the header, where it does nothing. The example silently failed to compile on Godbolt while passing locally (where the include order was correct). The fix was to **hoist** any `BOOST_SML_*` config macro above the inlined header. A reminder that include *order* is part of a single-header library's API.

**Problem two — discovered thanks to a reader tip:** Jason Turner (lefticus) had Godbolt examples that pulled headers straight from GitHub. The mechanism is Compiler Explorer's **client-side `#include`-from-URL**:

```cpp
#include <https://raw.githubusercontent.com/boost-ext/sml/master/include/boost/sml.hpp>
```

The catch that cost me an hour: this is resolved by **JavaScript in the browser**, not by the compile API. My API test of that exact line returned `fatal error: ... No such file or directory`, which looked like a dead end — until the realization that the doc links are *clicked by humans in browsers*, where the JS runs. The link's stored source stays tiny (the example, ~100 lines, instead of 3,700); CE fetches the header on open.

**Problem three:** `dispatch_table.hpp` does a *relative* `#include "boost/sml.hpp"`, and CE's fetcher only resolves URL-includes in the top-level source, not nested ones inside fetched files. So `dispatch_table` and `sdl2` get a hybrid: URL-include for the big header, with the small utility header inlined and *its* `sml.hpp` include rewritten to the URL form too — preserving the order so the header arrives before the macros that need it.

**Problem four**, and the most embarrassing: regenerating the links surfaced a bug in *my own generator*. The macro-hoisting fix from `data.cpp` used a strip pattern of `#define BOOST_SML*`. Applied indiscriminately, it also deleted `dispatch_table.hpp`'s **deliberate re-definition** of `BOOST_SML_DETAIL_REQUIRES` — a macro `sml.hpp` `#undef`s at its end specifically so downstream headers re-declare it. The result: `dispatch_table`/`sdl2` broke with `'BOOST_SML_DETAIL_REQUIRES' has not been declared`. The fix was to scope the strip — hoist config macros only from the *example*, never touch the utility header's own directives.

The thread running through problems one to four: **you cannot validate what you cannot run.** The URL-include links can't be checked by the API. The trick I settled on was to validate the *fully-inlined equivalent* through the API (which the API *can* compile and execute), then ship the *thin URL-include* link — same content, delivered two ways, one of which is machine-verifiable. It's not a substitute for a browser click, but it catches every compilation and logic error before a human ever sees the link.

## What we learned

A few things crystallized over this release that generalize well beyond SML:

- **Second-order coupling is where releases die.** A version bump broke type-name extraction because an inline namespace was secretly load-bearing for a `__PRETTY_FUNCTION__` offset. Nothing in either feature hinted at the dependency. When you change something "trivial and mechanical," ask what *reads the string representation* of the thing you changed.
- **A split CI result is a gift.** "GCC and MSVC fail, Clang passes" wasn't noise — it was the diagnosis. The compilers that print the inline namespace broke; the one that elides it didn't. Let the *pattern* of failures point at the cause before you start changing code.
- **Two-sided verification beats a green checkmark.** "Offset 64 passes" is weak. "Offset 64 passes *and* offset 65 reproduces the exact failure" is proof. When you can't see production (here, the CI's MSVC), reconstruct a local oracle and test both directions.
- **Validate the thing you can run; ship the thing you want.** The thin Godbolt links aren't API-checkable, so I validated their inlined twins and shipped the thin ones. Find the verifiable equivalent of the unverifiable artifact.
- **Defaults are an API.** Turning the min-size trick off by default changes observable `sizeof` — a behavior contract, even though no signature changed. That's a minor bump, full stop.
- **Dead links and dead buttons cost trust.** A "Run this code" button that silently fails for years, a doc link to a directory that doesn't exist — none of it breaks the build, all of it quietly tells readers the docs aren't maintained. Fixing them was some of the highest-leverage, lowest-glamour work in the whole release.
- **Include order is part of a single-header library's contract.** `#define BOOST_SML_CREATE_DEFAULT_CONSTRUCTIBLE_DEPS` before the include is load-bearing. Tools that reorganize source — like a Godbolt assembler — have to respect it.

Boost.SML 1.2.0 is, on the surface, four small features and some docs. Underneath, it was a tour of all the ways a "simple" change reaches further than you expect: into the compiler's name mangling, into a sanitizer's object-size model, into a JavaScript header fetcher, into the exact order your macros expand. The features were the easy part. The couplings were the education.
