# cost-router — decision log

## 2026-09-24 — First brick (world window P1; user: "选一个最有价值的, 做")
- What: pure-Python CLI that turns an agent task trace (codex `turn.completed` usage, or CSV/JSONL) into an itemised bill under GPT-6 Sol / Luna / Opus 5.5 standard / Opus 5.5 Fast, plus an explainable routing suggestion vs an SLO. Price snapshot `prices/2026-09-24.json`, every field with source URL + fetch time; 44/48 fields known (unknown: Sol/Luna 1h cache-write price, Sonnet 5.5 official price).
- Why this: price war week (GPT-6 half price, Opus 5.5 -40% but Fast = 2x token price, AA: cost halved, intelligence flat). Helicone proves people pay to attribute LLM cost per workflow. Our wedge: cross-vendor billing edges (cache read/write tiers, long-context multipliers, failed attempts still billed, reasoning inside output) + real fleet traces.
- Evidence: 5 hand-worked examples match the program item by item; 33 tests; independent receipt check 790 assertions; synthetic trace totals Sol $0.0606 / Luna $0.00303 / Opus $0.1176 / Opus Fast $0.2352.
- Honest limits: fleet sample (23 turns) lacks original model + per-request boundaries, so its Sol/Luna totals stay unknown; no quality/latency evidence, so `route` only offers cost scenarios, never claims a downgrade is safe.
- Not done: no web tool page yet (next brick), not published, not on GitHub. Built on mini (commit c8e39ad), cloned to main Mac.
