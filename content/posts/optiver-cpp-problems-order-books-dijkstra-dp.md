---
title: "Five Optiver-Style C++ Problems: Order Books, Dijkstra, and DP"
date: 2026-04-12
draft: false
tags: [C++, debugging, optimization, performance, compilers]
keywords: ["Optiver C++ assessment preparation", "order book matching engine C++", "Dijkstra shortest path C++ implementation"]
cover:
  image: /images/og-default.png
  alt: "Five Optiver-Style C++ Problems: Order Books, Dijkstra, and DP"
categories: ["deep-dive"]
summary: "Working through five C++ problems modeled on Optiver's Senior SWE assessment: supermarket checkout simulation, order book matching, dividend pricing, lattice path DP, and Dijkstra with K free edges. Every bug, wrong turn, and data structure tradeoff included."
ShowToc: true
---

Optiver's Senior Software Engineer EU assessment is one coding problem in two hours. The problem is long, the spec is dense, and the code quality bar is high. They want clean OOP, correct complexity analysis, and evidence that you think about cache lines and allocator behavior — not just algorithmic correctness.

I spent a week working through five problems modeled on what shows up in public Optiver OA reports: supermarket checkout simulation, order book matching, stock dividend pricing, a lattice-path DP problem, and a modified Dijkstra. Each problem produced bugs worth documenting. The recurring pattern: architectural instincts were right, but operator typos (`<` vs `=`), container initialization (braces vs parentheses), and iterator invalidation burned real time.

This post is the full record. Every wrong output, every segfault, every fix.

---

## Problem 1: Supermarket Checkout Simulation

This problem appears most frequently in Optiver OA reports. A supermarket has L checkout lines. Customers enter, join the shortest line, and exit when their item count reaches zero. Three event types drive the simulation: `CustomerEnter`, `BasketChange`, and `LineService`.

The rules that matter:

- Customers join the shortest line. Ties break by lowest index.
- `LineService` processes one item from the front customer of a line.
- `BasketChange` with a positive delta moves the customer to the back of their line — but only if they are at the front.
- Item count reaching zero means immediate exit. Print the customer ID.

### The Data Structure Choice

The obvious structure for customer lookup is `std::unordered_map<size_t, Customer>`. O(1) lookup, O(1) insert. But I deliberately chose a `std::vector<Customer>` with linear scan and slot reuse for a reason: contiguous memory is cache-friendly, and for the expected customer counts in this problem (hundreds, not millions), the linear scan with good cache locality beats a hashmap with pointer chasing and hashing overhead.

The key is articulating the tradeoff. A comment like this makes the intent clear:

```cpp
// Using contiguous storage for cache locality.
// Linear scan is acceptable for expected customer counts < ~1000.
// For larger N, consider unordered_map with pooled allocator.
```

If an interviewer asks "what if N is 100k?", the answer is: switch to `unordered_map` with a custom allocator using a pre-allocated pool to keep allocation patterns predictable.

### The Bugs

Four bugs showed up during implementation.

**Off-by-one in the line bounds check.** The guard `if(lines_.size() >= line_number) return;` rejects valid indices. With 2 lines (indices 0, 1), `lines_.size()` is 2, so `line_number=0` triggers the early return. The fix: `<=`.

**`try_back_of_line` checked the wrong position.** The spec says move to back if the customer is at the front. The code checked if the customer was at the end:

| Bug | Fix |
|-----|-----|
| `if(line_customer_itr == line.end() - 1)` | `if(line_customer_itr == line.begin())` |

**`BasketChange` delta read as `size_t`.** A negative delta read into `size_t` becomes a huge positive value, causing `std::bad_alloc`. The fix: read it as `int`.

**Missing output on customer exit.** Both `line_service` and `basket_change` had paths where customers exited without printing their ID.

### The Final Structure

```cpp
struct Customer
{
    size_t id;
    size_t items;
    ssize_t line_id = -1;
};

class CustomerLines
{
public:
    CustomerLines(size_t lines)
    : lines_(lines), storage_{}
    {
        storage_.reserve(PAGE_SIZE);
    }

    void enter(Customer && new_customer);
    void line_service(size_t line_number);
    void basket_change(size_t customer_id, int delta);

private:
    std::vector<Customer>::iterator get_customer_itr(size_t id);
    void leave(size_t customer_id, size_t line_id);
    void try_back_of_line(size_t customer_id, size_t line_id);

    std::vector<std::deque<size_t>> lines_{};
    std::vector<Customer> storage_{};
    size_t last_id_ = 0;
};
```

Try it on Compiler Explorer: [godbolt.org/z/3Wxb5TbvG](https://godbolt.org/z/3Wxb5TbvG)

---

## Problem 2: Order Book Matching Engine

A simplified order book for a single stock. BUY orders match against the lowest-priced SELL. SELL orders match against the highest-priced BUY. Price-time priority: at the same price, the earliest order wins.

### The Design

Two `std::set` containers with custom comparators — one for asks (ascending price, ascending time), one for bids (descending price, ascending time):

```cpp
bool sell_order(Order const& me, Order const& other)
{
    return std::tie(me.price, me.id) < std::tie(other.price, other.id);
}

bool buy_order(Order const& me, Order const& other)
{
    if(me.price != other.price)
        return me.price > other.price;
    return me.id < other.id;
}

using Asks = std::set<Order, decltype(&sell_order)>;
using Bids = std::set<Order, decltype(&buy_order)>;
```

This gives O(log N) best-price lookup and correct time priority. The `mutable` qualifier on `quantity` allows updating a resting order's quantity through a const iterator — necessary because `std::set` iterators are const.

### The Bugs

**Missing empty-book check.** The matching loop dereferenced `bids_.begin()` and `asks_.begin()` without checking if either side was empty. Immediate crash on any order that doesn't match.

**`if/if/else` instead of `if/else if/else`.** The remainder logic for partial fills had two consecutive `if` statements. When `remainder < 0`, the code fell through to the `else` branch and double-processed:

| Bug | Fix |
|-----|-----|
| `if(remainder < 0) { ... } if(remainder == 0) { ... } else { ... }` | `if(remainder < 0) { ... } else if(remainder == 0) { ... } else { ... }` |

**MATCH output placed after iterator erase.** The print statement was after the erase calls, dereferencing invalidated iterators. Undefined behavior. The fix: compute match quantity and price before any modification, print, then erase.

**Match price logic.** The match price is the resting order's price, not the aggressor's. If the new order is a BUY, the match price is the ask price. If SELL, the bid price.

Try it on Compiler Explorer: [godbolt.org/z/ePh9fPbE1](https://godbolt.org/z/ePh9fPbE1)

---

## Problem 3: Stock Dividend Price Calculator

Given a stock price S and N dividends with amounts and days, answer Q queries: what is the stock price on day X?

### The Approach

Rather than the straightforward sort-and-prefix-sum approach, I went with an online insertion model using `std::set<PriceChange>` ordered by day offset. Each insertion updates the cumulative stock prices for all subsequent entries. This supports interleaved insertions and queries — more general than the offline approach, at the cost of O(N) per insertion.

```cpp
struct PriceChange
{
    size_t offset_days;
    size_t divident;
    mutable ssize_t stock_price = UNSET;
};
```

### The Bug

The query function used `lower_bound` instead of `upper_bound`, returning the first dividend day >= query day instead of the last dividend day <= query day:

| Bug | Fix |
|-----|-----|
| `price_set.lower_bound({offset_days,0,0})->stock_price` | Decrement from `upper_bound` result |

```cpp
ssize_t get_price(PriceSet & price_set, size_t offset_days)
{
    auto it = price_set.upper_bound({offset_days, SIZE_MAX, 0});
    if(it == price_set.begin()) return price_set.begin()->stock_price;
    --it;
    return it->stock_price;
}
```

The symptom: day 3 returned 900 (next dividend's price) instead of 1000 (no dividend yet). Day 60 returned 825 instead of 875. Both off by one lookup step.

Try it on Compiler Explorer: [godbolt.org/z/4dvW51nbM](https://godbolt.org/z/4dvW51nbM)

---

## Problem 4: Trading Sequences (Lattice Path DP)

Given k initial shares, target n shares, and at most m buy/sell transactions (+1 or -1 each), count the distinct valid sequences. Constraint: shares cannot go negative at any point.

### Why This Problem is Interesting

This is the Cox-Ross-Rubinstein binomial tree model. Stock price goes up or down by 1 unit each step, count paths to a target price. The non-negativity constraint maps to barrier options. Optiver trades options heavily — this tests whether you intuitively understand the pricing model structure.

### The Recursive Version

```cpp
int count_sub_paths(int pos, int target, int steps)
{
    if(pos < 0) return 0;
    if(!steps) return (pos == target) ? 1 : 0;
    return count_sub_paths(pos - 1, target, steps - 1)
         + count_sub_paths(pos + 1, target, steps - 1);
}
```

Clean recursion. The bug was in the wrapper:

```cpp
int count_pathes(int start_p, int target_p, int steps_left)
{
    return count_sub_paths(start_p, target_p, steps_left)
         + count_sub_paths(start_p, target_p, steps_left - 1);
}
```

This only sums paths of exactly m and m-1 steps. The problem says "at most m." For k=1, n=2, m=3: paths of length 1 (just BUY) are valid but missed. The code returned 3 instead of 4.

### The Enumeration That Found It

All 3-step paths from position 1:

| Sequence | Path | Reaches 2? |
|----------|------|-----------|
| BBB | 1→2→3→4 | No |
| BBS | 1→2→3→2 | Yes |
| BSB | 1→2→1→2 | Yes |
| BSS | 1→2→1→0 | No |
| SBB | 1→0→1→2 | Yes |
| SBS | 1→0→1→0 | No |
| SSB | 1→0→-1 | Invalid |
| SSS | 1→0→-1 | Invalid |

Three valid 3-step paths, plus one valid 1-step path (BUY). Total: 4.

### The Bottom-Up DP

The recursive version is O(2^m). The bottom-up DP runs in O(m * max_pos):

```cpp
long count_paths(int k, int n, int m)
{
    int max_pos = k + m;
    std::vector<long> dp(max_pos + 2, 0);
    dp[k] = 1;
    long total = 0;

    for(int step = 0; step <= m; ++step)
    {
        total += dp[n];
        std::vector<long> ndp(max_pos + 2, 0);
        for(int j = 0; j <= max_pos; ++j)
        {
            if(j > 0) ndp[j] += dp[j - 1];
            ndp[j] += dp[j + 1];
        }
        dp = ndp;
    }
    return total;
}
```

No parity logic needed. Unreachable states are naturally 0. Accumulate `dp[n]` at every step count.

Try it on Compiler Explorer: [godbolt.org/z/aKo5zf3rG](https://godbolt.org/z/aKo5zf3rG)

---

## Problem 5: Dijkstra with K Free Edges

Find the minimum cost path from S to T in a directed weighted graph, where at most K edges can be used for free (cost becomes 0).

### Learning Dijkstra From Scratch

I had not implemented Dijkstra before this exercise. The mental model that clicked: BFS but ordered by cumulative cost instead of hop count. A priority queue ensures the cheapest frontier node is always processed next. Once a node is popped, its distance is final — no cheaper path can exist because all edge weights are non-negative.

The core algorithm:

1. `dist[source] = 0`, everything else INF.
2. Priority structure contains `(cost, node)`, sorted by cost.
3. Pop the cheapest. For each neighbor, check if `current_cost + edge_weight` improves their best known cost. If yes, update and insert.
4. Stop when target is popped or structure is empty.

### `std::set` vs `std::priority_queue`

I chose `std::set<std::pair<NodeCost, NodeIndex>>` over `std::priority_queue`. With a priority queue, you cannot remove stale entries — when a better path is found, the old entry stays in the heap. You push the new entry and skip the old one when popped (`if(cost > dist[u]) continue`). With `std::set`, you erase the old entry and insert the updated one. No stale entries, no skip logic.

The tradeoff: `std::set` uses tree nodes (cache-unfriendly), `priority_queue` uses a contiguous vector. For an assessment, clarity wins.

### The Bugs on the Way to Working Dijkstra

**`operator<=>` returning `bool`.** Writing `return cost < other.cost;` inside `operator<=>` returns a `bool`, not `std::strong_ordering`. The map sorted incorrectly, producing wrong accumulated costs. The fix: `= default` or use `<=>` properly.

**Braces vs parentheses in vector initialization.** `std::vector<NodeIndex>{graph.size(), MAX}` creates a 2-element vector with values `{6, MAX}`. `std::vector<NodeIndex>(graph.size(), MAX)` creates a 6-element vector filled with MAX. This caused out-of-bounds access in path reconstruction.

**`<` instead of `=` for assignment.** `peretns[next_id] < node_index;` compiles silently as a comparison expression. The parent array was never populated. Path reconstruction walked to node `-1UL` and segfaulted. This bug appeared twice.

**`std::map` sorts by key, not value.** Using `map<NodeIndex, NodeCost>` processes nodes in index order, not cost order. Dijkstra requires cost ordering. The fix: `std::set<std::pair<NodeCost, NodeIndex>>` sorts by cost first via lexicographic pair comparison.

**Updating the wrong accumulator.** `cost_accumilators[node_index] = next_acc_cost;` updates the current node's cost instead of the neighbor's. Should be `cost_accumilators[next_id]`.

### The K Free Edges Extension

The state becomes `(cost, node, frees_used)`. The dist array becomes 2D: `dist[node][f]`. At each edge, two choices:

```cpp
// Option A: pay for the edge
if(node_cost + next_cost < cost_acc[next_id][f])
{
    frontier.erase({cost_acc[next_id][f], next_id, f});
    cost_acc[next_id][f] = node_cost + next_cost;
    frontier.insert({cost_acc[next_id][f], next_id, f});
    peretns[next_id][f] = {node_index, f};
}

// Option B: use a free edge (only if f < K)
if(f < free_nodes && node_cost < cost_acc[next_id][f + 1])
{
    frontier.erase({cost_acc[next_id][f + 1], next_id, f + 1});
    cost_acc[next_id][f + 1] = node_cost;
    frontier.insert({cost_acc[next_id][f + 1], next_id, f + 1});
    peretns[next_id][f + 1] = {node_index, f};
}
```

The `f < free_nodes` check is the entire constraint. Think of `f` as a fuel gauge — every free edge ticks it up by 1. When it hits K, only paid edges remain.

An alternative approach: run Dijkstra C(M, K) times, each time zeroing a different combination of K edges. For M=100 and K=3, that is 160,000 runs. For K=10, 17 trillion. The layered approach does it in one pass with O(N*K * log(N*K)) complexity.

Try it on Compiler Explorer: [godbolt.org/z/GK4djdGW8](https://godbolt.org/z/GK4djdGW8)

---

## Recurring Bug Patterns

Five problems, and the same categories of bug appeared repeatedly.

| Bug Pattern | Occurrences | Example |
|-------------|-------------|---------|
| `<` instead of `=` (comparison as assignment) | 2 | `peretns[next_id] < node_index;` |
| Braces `{}` vs parentheses `()` in initialization | 2 | `vector{n, val}` vs `vector(n, val)` |
| Off-by-one in bounds checks | 2 | `>=` instead of `<=` |
| Missing output on state transitions | 2 | No `cout` on customer exit |
| Iterator invalidation after erase | 1 | Print after `set::erase` |

The `<` vs `=` bug is the most dangerous. It compiles silently, produces no warnings, and the symptom (segfault in path reconstruction, infinite loop) is far from the cause (parent array never populated).

---

## Takeaways

**1. Articulate your data structure tradeoffs.** Choosing `vector` over `unordered_map` is defensible when you can explain why. "Contiguous storage for cache locality at expected N < 1000" scores better than reaching for the textbook-optimal structure without comment. The senior-level answer bridges both: "I would switch to `unordered_map` with a pooled allocator at higher N."

**2. The `=` vs `<` typo is a class of bug worth a mental lint rule for.** In C++, `x < y;` is a valid expression statement that discards the result. No compiler warning by default. Consider `-Wunused-value` or wrapping assignments in a helper that cannot be confused with comparison.

**3. `std::set` over `std::priority_queue` for Dijkstra in assessment contexts.** The priority queue approach requires stale-entry handling. The set approach is more code per update but eliminates an entire category of bugs. Under time pressure, fewer failure modes wins.

**4. Bottom-up DP is safer than memoized recursion for assessments.** The recursive lattice path solution invited a broken memo scheme (hash collisions, `val != 0` as sentinel when 0 is valid). The bottom-up version is 15 lines, no memo, no collisions, no sentinel issues. When both approaches have the same complexity, prefer the one with fewer moving parts.

---

<!--
GODBOLT SNIPPETS — paste each block into https://godbolt.org/, click "Share -> Short link", then replace the matching placeholder above with the real short URL.

## GODBOLT_1 — Supermarket checkout simulation
Compiler: x86-64 gcc 14.2
Flags: -std=c++23 -O2 -Wall -Wextra

```cpp
#include <vector>
#include <deque>
#include <algorithm>
#include <string>
#include <iostream>
#include <sstream>

struct Customer
{
    size_t id;
    size_t items;
    size_t line_id = 0;
};

class CustomerLines
{
public:
    CustomerLines(size_t lines) : lines_(lines), storage_{} { storage_.reserve(4096); }

    void enter(Customer && c)
    {
        auto const cmp = [](std::deque<size_t> const& a, std::deque<size_t> const& b){ return a.size() < b.size(); };
        auto it = std::min_element(lines_.begin(), lines_.end(), cmp);
        c.line_id = std::distance(lines_.begin(), it);
        it->push_back(c.id);

        auto slot = std::find_if(storage_.begin(), storage_.end(), [](Customer const& x){ return x.items == 0; });
        if(slot == storage_.end()) storage_.emplace_back(c);
        else *slot = c;
    }

    void line_service(size_t ln)
    {
        if(ln >= lines_.size() || lines_[ln].empty()) return;
        auto cid = lines_[ln].front();
        auto it = get(cid);
        if(it == storage_.end()) return;
        if(it->items > 1) { --it->items; }
        else { it->items = 0; lines_[ln].pop_front(); std::cout << cid << "\n"; }
    }

    void basket_change(size_t cid, int delta)
    {
        auto it = get(cid);
        auto res = static_cast<long>(it->items) + delta;
        if(res <= 0) { it->items = 0; leave(cid, it->line_id); std::cout << cid << "\n"; }
        else if(delta > 0) { it->items = res; try_back(cid, it->line_id); }
        else { it->items = res; }
    }

private:
    std::vector<Customer>::iterator get(size_t id)
    { return std::find_if(storage_.begin(), storage_.end(), [id](Customer const& c){ return c.id == id && c.items > 0; }); }

    void leave(size_t cid, size_t lid)
    { auto& l = lines_[lid]; l.erase(std::find(l.begin(), l.end(), cid)); }

    void try_back(size_t cid, size_t lid)
    { auto& l = lines_[lid]; auto it = std::find(l.begin(), l.end(), cid); if(it == l.begin()){ l.push_back(cid); l.pop_front(); } }

    std::vector<std::deque<size_t>> lines_;
    std::vector<Customer> storage_;
};

int main()
{
    std::istringstream in("2\n9\nCustomerEnter 1 3\nCustomerEnter 2 2\nCustomerEnter 3 1\nLineService 0\nBasketChange 3 -1\nLineService 1\nLineService 1\nLineService 0\nLineService 0\n");
    std::cin.rdbuf(in.rdbuf());

    size_t L, N; std::cin >> L >> N;
    CustomerLines cl(L);
    while(N--)
    {
        std::string ev; std::cin >> ev;
        if(ev == "CustomerEnter"){ size_t id, it; std::cin >> id >> it; cl.enter({id, it}); }
        else if(ev == "LineService"){ size_t l; std::cin >> l; cl.line_service(l); }
        else if(ev == "BasketChange"){ size_t id; int d; std::cin >> id >> d; cl.basket_change(id, d); }
    }
    // Expected output: 3 2 1
    return 0;
}
```

## GODBOLT_2 — Order book matching engine
Compiler: x86-64 gcc 14.2
Flags: -std=c++23 -O2 -Wall -Wextra

```cpp
#include <set>
#include <tuple>
#include <string>
#include <iostream>
#include <sstream>
#include <algorithm>

struct Order
{
    size_t id = 0;
    int side = 0; // 1=BUY, -1=SELL
    mutable long quantity = 0;
    long price = 0;
};

bool sell_cmp(Order const& a, Order const& b){ return std::tie(a.price, a.id) < std::tie(b.price, b.id); }
bool buy_cmp(Order const& a, Order const& b){ if(a.price != b.price) return a.price > b.price; return a.id < b.id; }

using Asks = std::set<Order, decltype(&sell_cmp)>;
using Bids = std::set<Order, decltype(&buy_cmp)>;

int main()
{
    std::istringstream in("5\nORDER 1 SELL 100 10\nORDER 2 SELL 99 5\nORDER 3 BUY 101 12\nORDER 4 BUY 98 5\nORDER 5 SELL 97 3\n");
    std::cin.rdbuf(in.rdbuf());

    Asks asks(&sell_cmp);
    Bids bids(&buy_cmp);
    size_t N; std::cin >> N;
    while(N--)
    {
        std::string tok; std::cin >> tok;
        if(tok == "ORDER")
        {
            size_t id; std::string side; long price, qty;
            std::cin >> id >> side >> price >> qty;
            int s = (side == "BUY") ? 1 : -1;
            if(s == 1) bids.insert({id, s, qty, price});
            else asks.insert({id, s, qty, price});

            while(!bids.empty() && !asks.empty())
            {
                auto bi = bids.begin(); auto ai = asks.begin();
                if(bi->price < ai->price) break;
                auto mq = std::min(bi->quantity, ai->quantity);
                auto mp = (s == 1) ? ai->price : bi->price;
                std::cout << "MATCH " << bi->id << " " << ai->id << " " << mp << " " << mq << "\n";
                if(bi->quantity == ai->quantity){ bids.erase(bi); asks.erase(ai); }
                else if(bi->quantity > ai->quantity){ bi->quantity -= mq; asks.erase(ai); }
                else { ai->quantity -= mq; bids.erase(bi); }
            }
        }
    }
    // Expected:
    //   MATCH 3 2 99 5
    //   MATCH 3 1 100 7
    //   MATCH 4 5 98 3
    return 0;
}
```

## GODBOLT_3 — Dividend price calculator with online insertion
Compiler: x86-64 gcc 14.2
Flags: -std=c++23 -O2 -Wall -Wextra

```cpp
#include <set>
#include <iostream>
#include <cstdint>

struct PriceChange
{
    size_t offset_days;
    size_t dividend;
    mutable long stock_price = -1;
};

bool order_by_offset(PriceChange const& a, PriceChange const& b){ return a.offset_days < b.offset_days; }
using PriceSet = std::set<PriceChange, decltype(&order_by_offset)>;

void insert(PriceSet& ps, PriceChange&& pc)
{
    if(ps.empty()){ ps.insert(std::move(pc)); return; }
    auto prev = *(--ps.lower_bound(pc));
    auto last = prev.stock_price;
    ps.insert(std::move(pc));
    for(auto it = ps.lower_bound(pc); it != ps.end(); ++it)
    { auto np = last - static_cast<long>(it->dividend); it->stock_price = np; last = np; }
}

long get_price(PriceSet& ps, size_t day)
{
    auto it = ps.upper_bound({day, SIZE_MAX, 0});
    if(it == ps.begin()) return ps.begin()->stock_price;
    --it;
    return it->stock_price;
}

int main()
{
    auto ps = PriceSet(&order_by_offset);
    insert(ps, {1, 0, 1000});
    insert(ps, {100, 50});
    insert(ps, {50, 25});
    insert(ps, {10, 100});

    for(auto day : {1, 10, 50, 100, 3, 60, 110})
        std::cout << "Day " << day << ": " << get_price(ps, day) << "\n";
    // Expected: 1000, 900, 875, 825, 1000, 875, 825
    return 0;
}
```

## GODBOLT_4 — Lattice path DP (trading sequences)
Compiler: x86-64 gcc 14.2
Flags: -std=c++23 -O2 -Wall -Wextra

```cpp
#include <vector>
#include <iostream>

long count_paths(int k, int n, int m)
{
    int max_pos = k + m;
    std::vector<long> dp(max_pos + 2, 0);
    dp[k] = 1;
    long total = 0;

    for(int step = 0; step <= m; ++step)
    {
        total += dp[n];
        std::vector<long> ndp(max_pos + 2, 0);
        for(int j = 0; j <= max_pos; ++j)
        {
            if(j > 0) ndp[j] += dp[j - 1];
            ndp[j] += dp[j + 1];
        }
        dp = ndp;
    }
    return total;
}

int main()
{
    std::cout << "k=1 n=2 m=3: " << count_paths(1, 2, 3) << "\n"; // Expected: 4
    std::cout << "k=0 n=0 m=4: " << count_paths(0, 0, 4) << "\n"; // Expected: 4 (return-to-zero paths)
    std::cout << "k=2 n=2 m=0: " << count_paths(2, 2, 0) << "\n"; // Expected: 1 (no moves needed)
    return 0;
}
```

## GODBOLT_5 — Dijkstra with K free edges
Compiler: x86-64 gcc 14.2
Flags: -std=c++23 -O2 -Wall -Wextra

```cpp
#include <vector>
#include <set>
#include <tuple>
#include <limits>
#include <iostream>

using NodeIndex = unsigned long;
using NodeCost = long;
using Edge = std::pair<NodeIndex, NodeCost>;
using Graph = std::vector<std::vector<Edge>>;

NodeCost min_cost_k_free(NodeIndex start, NodeIndex end, unsigned int K, Graph const& g)
{
    constexpr auto INF = std::numeric_limits<NodeCost>::max();
    auto n = g.size();
    std::vector<std::vector<NodeCost>> dist(n, std::vector<NodeCost>(K + 1, INF));

    using State = std::tuple<NodeCost, NodeIndex, unsigned int>;
    std::set<State> frontier;
    dist[start][0] = 0;
    frontier.insert({0, start, 0});

    while(!frontier.empty())
    {
        auto [cost, u, f] = *frontier.begin();
        frontier.erase(frontier.begin());
        if(u == end) return cost;
        if(cost > dist[u][f]) continue;

        for(auto [v, w] : g[u])
        {
            if(cost + w < dist[v][f])
            {
                frontier.erase({dist[v][f], v, f});
                dist[v][f] = cost + w;
                frontier.insert({dist[v][f], v, f});
            }
            if(f < K && cost < dist[v][f + 1])
            {
                frontier.erase({dist[v][f + 1], v, f + 1});
                dist[v][f + 1] = cost;
                frontier.insert({dist[v][f + 1], v, f + 1});
            }
        }
    }
    return -1;
}

int main()
{
    // 1-indexed nodes, so pad index 0
    Graph g(6);
    g[1] = {{2, 10}, {4, 5}};
    g[2] = {{3, 20}};
    g[3] = {{5, 100}};
    g[4] = {{3, 50}, {5, 60}};

    std::cout << "K=0: " << min_cost_k_free(1, 5, 0, g) << "\n"; // 65 (1->4->5)
    std::cout << "K=1: " << min_cost_k_free(1, 5, 1, g) << "\n"; // 5  (1->4->5, free 4->5)
    std::cout << "K=2: " << min_cost_k_free(1, 5, 2, g) << "\n"; // 0  (1->4, free both)
    return 0;
}
```
-->
