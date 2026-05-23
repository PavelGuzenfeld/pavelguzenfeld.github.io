---
title: 'C++ State Machine, Three Ways: Switch/Case, GoF unique_ptr, and C++23 Variant
  — Benchmarked'
date: 2026-05-23
draft: false
tags:
- C++
- design-patterns
- state-machine
- performance
- benchmarking
- compilers
- C++23
keywords:
- C++ state design pattern benchmark
- GoF state pattern unique_ptr
- std::variant std::visit state machine
- switch case FSM C++
- state machine dispatch overhead
- compile time state machine C++23
- nanobench state machine godbolt
- virtual dispatch vs variant benchmark
- heap allocation state transition cost
- std::get_if conditional jump variant
- visit_linear conditional branch C++
- likely attribute branch prediction C++23
- std::visit table vs conditional jump assembly
cover:
  image: /images/posts/cpp-state-pattern-benchmarked.png
  alt: C++ State Machine benchmarked — switch/case vs GoF unique_ptr vs C++23 variant/visit
categories:
- deep-dive
summary: 'Three implementations of the same aircraft lifecycle FSM — a switch/case
  flat machine, the classic GoF State pattern with unique_ptr, and a C++23 compile-time
  variant/visit design — compiled with GCC 14 at -O2 -std=c++23, measured with nanobench,
  and linked to four live Godbolt sessions. The headline numbers: for a full
  seven-event mission cycle, the variant approach is 6× faster than OOP and switch/case
  is essentially free (the optimizer evaluates the constant-input trace at compile
  time). On the steady-state telemetry hot path, switch runs at 0.56 ns/event, variant
  at 1.07 ns/event, OOP at 1.20 ns/event. The culprit is not virtual dispatch — it
  is heap allocation. A follow-up section adds get_if chains and the [[likely]]
  attribute: on single-variant dispatch all four strategies land within 0.11 ns.'
ShowToc: true
audio:
  pronunciation:
    std::variant: S T D variant
    std::visit: S T D visit
    std::get_if: S T D get if
    std::unique_ptr: S T D unique pointer
    std::make_unique: S T D make unique
    std::holds_alternative: S T D holds alternative
    std::move: S T D move
    nanobench: nano bench
    doNotOptimizeAway: do not optimize away
    Godbolt: god bolt
    godbolt.org: god bolt dot org
    TransitionTable: transition table
    OnGround: on ground
    InFlight: in flight
    TakeOffCmd: take off command
    LandCmd: land command
    update_telemetry_then: update telemetry then
    IState: I state
    SwitchFSM: switch F S M
    g++: G plus plus
    -O2: minus O two
    C++23: C plus plus twenty three
    CRTP: C R T P
    DCE: D C E
    vtable: V table
    GoF: gang of four
    FSM: finite state machine
    visit_linear: visit linear
    BTB: B T B
    get_if: get if
---

The [Gang of Four State pattern](https://en.wikipedia.org/wiki/State_pattern) is one of those designs that looks clean in a UML diagram and costs you dearly at runtime if you reach for it without thinking. A concrete state object behind a `unique_ptr`. A virtual dispatch for every event. A fresh heap allocation every time the machine changes state. The books rarely show the profile.

This post benchmarks three concrete implementations of the same finite state machine — an aircraft lifecycle modelled after [this C++23 reference machine](https://godbolt.org/z/x4j8MMEzo) — against each other using [nanobench](https://github.com/martinus/nanobench) on GCC 14 with `-O2 -std=c++23`. Every implementation compiles, runs, and produces timing output directly in the browser. Every Godbolt link at the bottom of each section is live.

## The use case: aircraft lifecycle FSM

All three implementations model the same four-state machine:

```
OnGround ──TakeOffCmd──▶ Takeoff ──Telemetry(gv>0)──▶ InFlight ──LandCmd──▶ Landing
   ▲                                                                              │
   └──────────────────── Telemetry(alt<1 && gv<1) ──────────────────────────────┘
```

**States:** `OnGround`, `Takeoff`, `InFlight`, `Landing`

**Events:**
- `TakeOffCmd` — explicit command to start takeoff roll
- `LandCmd` — explicit command to begin descent
- `Telemetry{altitude, ground_velocity}` — periodic sensor packet that drives automatic transitions

**Mission cycle used in the benchmark:**

```
TakeOffCmd           →  OnGround → Takeoff     (explicit command)
Telemetry{50, 0}     →  Takeoff  (no change, gv == 0)
Telemetry{200, 80}   →  Takeoff → InFlight     (gv > 0 → mission start)
Telemetry{500, 120}  →  InFlight (cruise, no change)
LandCmd              →  InFlight → Landing     (explicit command)
Telemetry{30, 20}    →  Landing  (no change, still airborne)
Telemetry{0, 0}      →  Landing → OnGround     (alt < 1 && gv < 1 → touchdown)
```

Seven events, four state transitions with side effects. The `64× cruise telemetry` hot-path benchmark fires 64 consecutive `Telemetry{500, 120}` events while the machine is in `InFlight` — no transition, just repeated dispatch.

---

## Approach 1 — Switch / Case

The oldest tool in the C FSM toolbox. One enum for state, one `switch` per event handler, pure value semantics.

```cpp
enum class St : uint8_t { OnGround, Takeoff, InFlight, Landing };

struct SwitchFSM {
    St  state           = St::OnGround;
    int altitude        = 0;
    int ground_velocity = 0;
    int side_effects    = 0;

    void on_telemetry(int alt, int gv) noexcept {
        altitude        = alt;
        ground_velocity = gv;
        switch (state) {
        case St::OnGround:
            if (alt > 0) state = St::Takeoff;
            break;
        case St::Takeoff:
            if (gv > 0) { ++side_effects; state = St::InFlight; }
            break;
        case St::InFlight:
            /* cruise — stay */
            break;
        case St::Landing:
            if (alt < 1 && gv < 1) { ++side_effects; state = St::OnGround; }
            break;
        }
    }
    void on_takeoff_cmd() noexcept {
        if (state == St::OnGround) { ++side_effects; state = St::Takeoff; }
    }
    void on_land_cmd() noexcept {
        switch (state) {
        case St::OnGround: break;
        default: ++side_effects; state = St::Landing; break;
        }
    }
};
```

**What the compiler does with this:** everything lives in registers. No heap, no function pointers, no indirection. With fixed-value inputs GCC -O2 can evaluate the entire mission trace as a compile-time constant — `side_effects` becomes the literal `4` in the generated binary and the `run_mission` body shrinks to a handful of stores. The benchmark measures this ceiling; it is not a measurement artifact.

**Weaknesses:** adding a state means touching every switch in every handler. The state is a flat integer — there is nowhere to hang per-state data. Multi-file or plugin-loaded states are impossible.

**Godbolt:** [godbolt.org/z/eqsW3vfPs](https://godbolt.org/z/eqsW3vfPs)

---

## Approach 2 — Classic GoF State Pattern (virtual dispatch + `unique_ptr`)

The textbook design. Each state is a heap-allocated object that knows how to handle each event. The context (`Aircraft`) owns the current state via `std::unique_ptr<IState>` and delegates every event call to it.

One important subtlety: state transition methods must **not** call `set_state` while still executing a virtual method on the object being replaced — that deletes `this` mid-call, which is UB. The safe pattern is to return the next state as a `unique_ptr` and let the context apply it after the virtual call returns.

```cpp
struct IState {
    virtual ~IState() = default;
    // Return non-null to transition; null = stay in current state.
    virtual std::unique_ptr<IState> on_telemetry (Aircraft&, int alt, int gv) = 0;
    virtual std::unique_ptr<IState> on_takeoff_cmd(Aircraft&)                 = 0;
    virtual std::unique_ptr<IState> on_land_cmd  (Aircraft&)                  = 0;
    virtual int id() const noexcept = 0;
};

struct Aircraft {
    std::unique_ptr<IState> state;
    int altitude = 0, ground_velocity = 0, side_effects = 0;

    explicit Aircraft(std::unique_ptr<IState> s) : state(std::move(s)) {}

    void on_telemetry(int alt, int gv) {
        altitude = alt; ground_velocity = gv;
        if (auto n = state->on_telemetry(*this, alt, gv)) state = std::move(n);
    }
    void on_takeoff_cmd() {
        if (auto n = state->on_takeoff_cmd(*this)) state = std::move(n);
    }
    void on_land_cmd() {
        if (auto n = state->on_land_cmd(*this)) state = std::move(n);
    }
};
```

Each concrete state (e.g. `TakeoffState`) implements the interface and returns `make_unique<NextState>()` when a transition fires:

```cpp
std::unique_ptr<IState> TakeoffState::on_telemetry(Aircraft& a, int, int gv) {
    if (gv > 0) { ++a.side_effects; return std::make_unique<InFlightState>(); }
    return nullptr;
}
```

**What the compiler does with this:** every event dispatch goes through a vtable pointer load + indirect call — two memory accesses before any application logic runs. On a transition, `make_unique` calls `operator new`, which touches the allocator, potentially takes a lock (in older libstdc++), and returns a pointer from a free-list that may be cold in L1d. Four such allocations happen per mission cycle.

**Strengths:** trivially extensible. New states are new classes. States can carry their own data. Works across translation units and dynamic libraries.

**Godbolt:** [godbolt.org/z/cnfvzjPra](https://godbolt.org/z/cnfvzjPra)

---

## Approach 3 — Compile-time dispatch (`std::variant` + `std::visit`, C++23)

This is the design from the [reference machine](https://godbolt.org/z/x4j8MMEzo). States are empty structs in a `std::variant`. Dispatch goes through `std::visit` with a `TransitionTable` — an overload set built from lambdas. The current state type is the variant's active alternative; the compiler can resolve all possible (state, event) pairs at compile time and emit a 2D jump table.

```cpp
namespace sm {
    template<class... Ts> struct TransitionTable : Ts... { using Ts::operator()...; };
    template<class... Ts> TransitionTable(Ts...) -> TransitionTable<Ts...>;

    template <class STATES, class EVENTS, class CONTEXT, class TRANSITIONS>
    struct Machine {
        void operator()(EVENTS const& e) {
            current_ = std::visit(
                [&](auto const& s, auto const& ev) -> STATES {
                    return transitions_(s, ev, ctx_);
                },
                current_, e);
        }
        template<class S>
        bool in() const noexcept { return std::holds_alternative<S>(current_); }
        // ...
    };
}
```

The C++23 `requires`-clause in the `update_telemetry_then` decorator pins each lambda to a specific state type at compile time — the compiler rejects ill-formed pairings before a single byte of object code is written:

```cpp
auto update_telemetry_then = [](auto h) {
    return [h](auto const& s, Telemetry const& t, Context& ctx) -> state::Any
        requires requires { h(s, t); }   // compile-time gate
    {
        ctx.altitude = t.altitude;
        ctx.ground_velocity = t.ground_velocity;
        return h(s, t);
    };
};
```

**What the compiler does with this:** `std::visit` internally uses an array of function pointers indexed by the variant's type index — similar to a vtable but owned by the call site, not the type. With `-O2` GCC can inline through it in many cases, but the variant type-index load and indirect branch prevent the same constant-folding that collapses the switch/case mission to zero. Zero heap allocation.

**Godbolt:** [godbolt.org/z/Me1bKxe9h](https://godbolt.org/z/Me1bKxe9h)

---

## Benchmark results

All measurements: GCC 14.2, `-O2 -std=c++23`, nanobench v4.3.11, `gcc:14` Docker container on an Intel i7 desktop (4.6 GHz boost, powersave governor, turbo on). The CPU frequency-scaling warning applies — numbers would be ~20% lower at locked performance frequency — but the **relative ordering is stable** across runs.

### Full mission cycle (7 events, 4 transitions)

| Implementation | ns / mission | relative |
|---|---:|---:|
| Switch / case | **0.74 ns** | 1× |
| Variant / visit | **8.25 ns** | 11× |
| GoF `unique_ptr` | **50.57 ns** | 68× |

The switch/case number requires explanation. GCC -O2 sees that `reset()` establishes a fully-known machine state and that every event argument is a compile-time constant. It evaluates the entire seven-step trace at compile time, reduces `side_effects` to the literal value `4`, and the benchmark body becomes two stores and a register load for `doNotOptimizeAway`. This is not a measurement artifact — it is the optimizer working correctly. When inputs are statically known, a state machine with no virtual dispatch and no heap allocation has zero marginal cost.

The variant number (8.25 ns) is the cost when the compiler cannot fold through `std::visit`'s indirect dispatch. Seven events, ~1.2 ns each — register operations plus one indirect branch per event.

The OOP number (50.57 ns) is dominated by the four `make_unique` calls on the four transitions. At roughly 10–12 ns per heap allocation on this machine (fresh allocator path, no free-list hit), four allocations contribute ~44 ns. The virtual dispatch overhead is only the remaining ~6 ns.

**The headline takeaway: the GoF State pattern's performance problem is the allocator, not the vtable.**

### Steady-state telemetry hot path (64× `InFlight` cruise events, no transitions)

| Implementation | ns / 64 events | ns / event | relative |
|---|---:|---:|---:|
| Switch / case | **35.93 ns** | 0.56 ns | 1× |
| Variant / visit | **68.51 ns** | 1.07 ns | 1.9× |
| GoF `unique_ptr` | **77.02 ns** | 1.20 ns | 2.1× |

Here no transitions fire, so `make_unique` is never called. The OOP implementation pays only for the vtable pointer load and indirect call. The gap between OOP and variant collapses to 13% — both are doing a level of indirection per event. Switch/case is 2× faster because the branch predictor learns `state == InFlight` after one iteration and the body reduces to two conditional stores that are never taken.

This is the operational regime for high-frequency state machines. A flight controller or a robotics pipeline spends most of its time in one state processing sensor data, not transitioning between states. In that regime, OOP and variant are within noise of each other; switch wins by a factor of two.

---

## Reading the numbers: what actually costs what

```
Switch/case — full mission:   0.74 ns   ← compiler constant-folds the whole trace
Variant    — full mission:    8.25 ns   ← ~1.2 ns/event, zero allocation
OOP        — full mission:   50.57 ns   ← ~44 ns in make_unique, ~6 ns in vtables

Switch/case — 64× hot path:  35.93 ns  = 0.56 ns/event
Variant    — 64× hot path:   68.51 ns  = 1.07 ns/event
OOP        — 64× hot path:   77.02 ns  = 1.20 ns/event  (no allocations here)
```

A few things worth calling out:

**Virtual dispatch alone costs ~0.6 ns** when the target is warm in cache. The OOP hot-path overhead over switch/case is 77 - 36 = 41 ns for 64 events = 0.64 ns/event extra. That is one vtable load plus one branch misprediction at most. Not nothing, but not catastrophic.

**Heap allocation costs ~10–12 ns each.** Four transitions × 11 ns = ~44 ns. This is the 42-ns gap between OOP full-mission (50.57) and variant full-mission (8.25). Every time the machine transitions in OOP, you pay the allocator. The variant machine transitions for free.

**`std::visit` adds ~0.5 ns per event over switch** in the hot path (1.07 vs 0.56 ns). The cost is not an indirect function-pointer table — GCC -O2 generates conditional jumps even for `std::visit` on small variants. The overhead here comes from the aircraft FSM's **two-variant visit** (`std::visit(visitor, current_state, current_event)`), which dispatches over 4 states × 3 event types = 12 combinations. The multi-variant machinery is heavier than single-variant. For single-variant dispatch, `std::visit` and `get_if + [[likely]]` land within noise of each other; see the section below.

---

## Design trade-offs

| | Switch / case | GoF `unique_ptr` | `std::variant` |
|---|---|---|---|
| **Dispatch cost (hot path)** | 0.56 ns/event | 1.20 ns/event | 1.07 ns/event |
| **Transition cost** | ~0 | ~10–12 ns (malloc) | ~0 |
| **Compiler optimization ceiling** | very high (full trace fold) | low (heap prevents) | medium (visit blocks fold) |
| **Type safety** | none (enum int) | `virtual` interface | `std::variant` (exhaustive at compile time) |
| **Extensibility** | rewrite all switches | add a new class | add variant alternative + overloads |
| **Per-state data** | requires union / map | natural (member fields) | via data in variant alternative |
| **Dynamic/plugin states** | impossible | natural (`IState*` from DLL) | impossible |
| **C++ standard** | any | any | C++17+ (`std::visit` multi-arg is C++17; `requires` decorator uses C++20/23) |

**Use switch/case when:** the state set is small, fixed, known at compile time, and you want the optimizer to have maximum visibility. Embedded systems, inner-loop controllers, parsing hot paths.

**Use GoF `unique_ptr` when:** states need to be extended at runtime (plugin architecture), states carry significant per-state data, or you are targeting an architecture where state transitions are rare and the object-oriented model makes the logic clearer to maintain.

**Use `std::variant` when:** you want the GoF model's expressiveness and type safety without the heap cost. The C++23 `requires`-clause guard gives you compile-time exhaustiveness checking — the compiler will refuse to compile a (state, event) pair that has no matching handler, something you only discover at runtime with switch/case.

---

## Getting conditional jumps from `std::visit`

The previous section noted that the two-variant visit carries more overhead than a plain switch. A natural follow-up question: can we make `std::visit` emit conditional jumps instead of heavier dispatch machinery, and does it help?

The answer is yes — and there is a surprise along the way.

### Why std::visit does NOT always use a table

For a **single-variant visit** over a small variant (≤ 4–8 alternatives), GCC -O2 already generates conditional jumps, not a function-pointer table. The assembly for `std::visit(TelemetryVisitor{}, state)` on our four-state variant looks like this:

```asm
; std::visit — GCC 14 -O2, single-variant, non-trivial visitor
movzx   eax, BYTE PTR [rdi+4]   ; load variant's index byte
cmp     al, 2                    ; InFlight (index 2)?
je      .inflight                ; ← one comparison for the hot state
ja      .landing                 ; > 2 → Landing
test    al, al
jne     .takeoff                 ; ≠ 0 → Takeoff; fall-through = OnGround
```

GCC built a **balanced binary tree** pivoting on the middle index. InFlight is reached in one comparison. There is no indirect call.

### Three techniques to control the branch order

The table dispatch is a myth for small variants. What matters is *which state gets tested first* — and `std::visit` doesn't let you say. Three alternatives do:

**1. `visit_linear<>` — recursive template, if/else in index order**

```cpp
template<size_t I = 0, class Ret, class Vis, class Var>
[[nodiscard]] Ret visit_linear(Vis vis, Var& var) {
    if constexpr (I + 1 == std::variant_size_v<std::remove_cvref_t<Var>>)
        return vis(std::get<I>(var));          // last case: no guard
    else {
        if (var.index() == I) return vis(std::get<I>(var));
        return visit_linear<I+1, Ret>(vis, var);
    }
}
```

Generates `cmp index, 0; je; cmp index, 1; je; ...`. Tests `OnGround` first. Fine when states are equally likely; **slower for InFlight-dominant** because InFlight (index 2) requires three comparisons.

**2. `std::get_if<>` chain — same codegen, explicit, pointer access**

```cpp
int by_getif(AState& s, ...) {
    if (auto* st = std::get_if<OnGround>(&s)) { ...; return 0; }
    if (auto* st = std::get_if<Takeoff>(&s))  { ...; return 1; }
    if (auto* st = std::get_if<InFlight>(&s)) { ...; return 2; }
    auto* st = std::get_if<Landing>(&s); ...; return 3;
}
```

Identical codegen to `visit_linear`. The advantage: `get_if` returns a pointer to the active state value, useful when you need to call a state-specific method.

**3. `get_if + [[likely]]` — hot state first, cold tail pushed away**

```cpp
int by_getif_likely(AState& s, ...) {
    if (auto* st = std::get_if<InFlight>(&s)) [[likely]]  // tested first
        { st->altitude_m = alt; ctx.result = alt * vel; return 2; }
    if (auto* st = std::get_if<OnGround>(&s)) { ...; return 0; }
    if (auto* st = std::get_if<Takeoff>(&s))  { ...; return 1; }
    auto* st = std::get_if<Landing>(&s); ...; return 3;
}
```

`[[likely]]` does two things: moves InFlight to the front of the comparison chain, and makes the hot branch a **fall-through** (`jne .cold_tail`) rather than a taken jump. A not-taken branch fetches the next sequential instruction — the CPU never leaves the current I-cache line. The cold states go into a separate tail block.

Generated assembly for the hot path:

```asm
; by_getif_likely — InFlight dominant
movzx   eax, BYTE PTR [rdi+4]
cmp     al, 2                ; InFlight?
jne     .cold                ; rarely taken → cold tail
; ── hot path: straight-line code, no jump ────────────────────────────
mov     DWORD PTR [rdi], esi ; st->altitude_m = alt
imul    esi, edx             ; alt * vel
mov     eax, 2
mov     DWORD PTR [rcx+8], esi
ret
; ── cold tail ────────────────────────────────────────────────────────
.cold:
test    al, al               ; OnGround?
...
```

### Benchmark: single-variant dispatch, GCC 14 -O2

| | InFlight-dominant | Uniform (4 states) |
|---|---:|---:|
| `std::visit` | **0.67 ns** | 0.91 ns |
| `visit_linear<>` | 0.77 ns | **0.87 ns** |
| `get_if` chain | 0.78 ns | 0.94 ns |
| `get_if + [[likely]]` | **0.67 ns** | **0.86 ns** |

For InFlight-dominant: `get_if + [[likely]]` ties `std::visit` — both put InFlight in one comparison. `visit_linear` is *slower* because it starts from index 0, reaching InFlight only after testing OnGround and Takeoff first.

For uniform distribution: `visit_linear` and `[[likely]]` both beat `std::visit` slightly. GCC's balanced-tree layout has mixed jump directions that the linear structure avoids.

The practical rule: **if one state dominates, use `get_if + [[likely]]` with that state first. Otherwise `std::visit` is fine — it already generates conditional jumps and its balanced-tree order is nearly optimal.**

**Godbolt (assembly + benchmark, GCC 14.2 `-O2 -std=c++23`):** [godbolt.org/z/1a9M6MvxY](https://godbolt.org/z/1a9M6MvxY)

---

## The reference machine

The variant implementation in this post is a direct benchmark adaptation of [godbolt.org/z/x4j8MMEzo](https://godbolt.org/z/x4j8MMEzo), which shows the design in its most complete form: the `update_telemetry_then` decorator, the full test driver with assertions, and `cout` output at each step. If you want to understand the template machinery before reading the benchmark version, start there.

---

## Running the benchmarks yourself

All three programs compile from a single `.cpp` file with no dependencies beyond `nanobench.h` (single header, MIT):

```bash
curl -sL https://raw.githubusercontent.com/martinus/nanobench/v4.3.11/src/include/nanobench.h \
  -o nanobench.h

g++ -O2 -std=c++23 -I. switch_case_fsm.cpp   -o switch_fsm   && ./switch_fsm
g++ -O2 -std=c++23 -I. oop_unique_ptr_fsm.cpp -o oop_fsm     && ./oop_fsm
g++ -O2 -std=c++23 -I. variant_visit_fsm.cpp  -o variant_fsm && ./variant_fsm
```

Or click "Execute the code" in the output pane of any of the three Godbolt links — the executor pane has the nanobench library pre-wired.

Godbolt links (GCC 14.2, `-O2 -std=c++23`, nanobench v4.3.11, execution enabled):

- **Switch / case:** [godbolt.org/z/eqsW3vfPs](https://godbolt.org/z/eqsW3vfPs)
- **GoF `unique_ptr`:** [godbolt.org/z/cnfvzjPra](https://godbolt.org/z/cnfvzjPra)
- **`std::variant` / `std::visit`:** [godbolt.org/z/Me1bKxe9h](https://godbolt.org/z/Me1bKxe9h)
- **Conditional jumps: `visit_linear`, `get_if`, `[[likely]]`:** [godbolt.org/z/1a9M6MvxY](https://godbolt.org/z/1a9M6MvxY)
- **Reference (full-featured, with test driver):** [godbolt.org/z/x4j8MMEzo](https://godbolt.org/z/x4j8MMEzo)
