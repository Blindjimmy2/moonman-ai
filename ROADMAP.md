# Moon Man Engineering Roadmap

Written 2026-11-01. Checkpoints preserved: git `b646d89` + full snapshot at
`Documents\MoonMan\checkpoints\20261101_moonman`. No history rewritten.

## 0. Hackathon integrity

- The hackathon build uses Meta's Model API meaningfully: every conversation
  turn, every tool-calling round, and every grounded research query calls
  `muse-spark-1.3` at `https://api.meta.ai/v1`.
- Usage telemetry added 2026-11-01 is additive only (new module + guarded
  record calls). It cannot change answers, routing, or behavior.
- Local-AI work below is documented as a FUTURE phase. Nothing here replaces
  Meta for the submission.

## 1. Current capabilities (verified working)

- Two-eye robot: left Waveshare ESP32-S3 412x412 (MOKI art, PCA9685
  servo/body master), right KLAYERS AMOLED 466x466 (baked MOKI art, mic,
  speaker). IPs .20 / .21.
- Voice loop: eye mic -> laptop Whisper -> Meta agent -> British TTS
  (Pocket `stuart_bell`, Piper fallback) -> eye speaker. Proven live.
- Agent (`src/agent.py`): sarcastic astronaut personality, persistent memory,
  vision, Fusion 360 CAD bridge, knob tools, printer monitor/commands, MQTT
  hardware control, physical-action approvals. Tool loop: max 8 rounds,
  max 20 tool calls.
- Tracking: webcam face tracking -> eased pan/tilt servo commands
  (SIM_ONLY until servos wire up) + OpenCV preview overlay.
- Mission Control (`src/moonman_control.py`, localhost:8100): service
  lifecycle, logs, tracker/mic state, text chat, helmet cam, AI cost panel.
- Pi: MQTT broker + relay + experimental webcam-mic ear.
- AI cost telemetry: per-call token + cost logging with dashboard panel
  (see sections 2-3).

## 2. API pricing and usage visibility (verified)

Source: [Meta Model API pricing](https://dev.meta.ai/docs/pricing-rate-limits),
checked 2026-11-01. Model in use: `muse-spark-1.3`.

| Meter | Standard (our tier) | Contributor |
|---|---|---|
| Input | $1.25 / 1M | $0.10 / 1M |
| Cached input (auto prefix) | $0.15 / 1M | $0.002 / 1M |
| Output (incl. hidden reasoning) | $4.25 / 1M | $0.20 / 1M |
| Web search grounding | $2.50 / 1k queries | same (assumed) |

Verified live 2026-11-01 (real API calls, not docs alone):

- Tier is **Standard**: rate-limit headers return 3000 RPM / 4M TPM, which
  matches Standard (`muse-spark-1.3`), not Contributor (150 / 3M).
- Every Chat Completions response returns exact usage: `prompt_tokens`,
  `completion_tokens`, `cached_tokens`, `reasoning_tokens`.
- Measured trivial ask: 6,926 in + 710 out (697 reasoning!) = **$0.0117**.
  Two cost drivers to know: the injected system+memory context (~7k input
  before you say a word) and hidden reasoning tokens billed as output.
- What costs what: voice STT/TTS = $0 (local Whisper/Piper/Pocket);
  vision = image input tokens at $1.25/M; tools = extra rounds, each
  re-sending full history (prefix likely gets the $0.15 cached rate);
  `web_research` = Responses API tokens + $0.0025/search minimum.
- $25/mo feasibility: ~30 asks/day of light chat fits (~$10/mo). 100+
  asks/day with tools can exceed $25. The panel tracks actuals; see
  optimization levers in section 7. Contributor tier is ~12x cheaper but
  grants Meta training rights on content -- a decision, not a default.

## 3. Cost monitoring (implemented 2026-11-01)

- `src/moonman_usage.py` (new): append-only JSONL log, cost math from the
  table above, daily/monthly/per-task rollups. Never raises, never blocks.
- Log: `Documents\MoonMan\usage.jsonl` (survives restarts, outside the repo;
  override with `MOONMAN_USAGE_FILE`).
- Hooks: 3 guarded record calls in `agent.py` (every main-loop round +
  summarize fallback, sharing one task id per ask) and 1 in
  `web_research.py` (Responses API + search count). Zero behavior change.
- Dashboard: `GET /api/costs` + AI COST panel (last request, today, month,
  run-rate month estimate, per-task top 10, tier + pricing source).
- Measured vs estimated is explicit: live API usage = measured; only the
  no-usage fallback path is estimated (~4 chars/token) and flagged `EST`.
- Budgets: `MOONMAN_BUDGET_MONTHLY_USD` (default 25) /
  `MOONMAN_BUDGET_DAILY_USD`. Panel warns at 80%. **Tracking + warnings
  only -- stops nothing automatically** (see section 4).

## 4. Cost controls: what is real, what is proposed

Implemented (no approval needed, done): budget display, 80% warnings,
per-task costs, run-rate projection, persistent history.

Proposed, needs approval (behavior-adjacent, not yet built):

- Soft spend-stop: check month-to-date before each agent round; abort with
  a spoken "budget pause" message instead of calling the API. Per-task $
  caps and Engineer Mode iteration/timeout limits ride the same mechanism.
- Kill switch for long tasks: dashboard Stop button sets a flag the
  Engineer loop checks each iteration (see section 5).

Honest limits (no hard cap is claimed):

- Meta bills server-side; in-flight tokens are spent before we see usage.
- Rate limits and spend apply **per team**, across all keys and processes.
- Anything calling the API directly (scripts, probes) bypasses our checks.
- So: we can refuse NEW calls past a budget (effective in practice), but
  cannot guarantee a hard ceiling. The panel says exactly this.

## 5. Engineer Mode (PLAN -- approval required before build)

Keep two modes. Astronaut Mode = today's `ask_moonman` path, untouched:
fast chat, voice, vision, memory, gaze, CAD commands, shop talk.

Engineer Mode = new supervised capability for longer engineering tasks.
Proposed design (not built):

- New module (`moonman_engineer.py`), separate entry point; Agent never
  self-escalates. Mode select via dashboard toggle, MQTT command, or an
  explicit voice phrase ("engineer mode").
- Plan -> approve -> execute loop: Moon Man inspects, writes a short plan
  with file diffs + commands + cost estimate, and WAITS. Human approves
  in the dashboard (or typed confirm) before any write, command run,
  equipment operation, or destructive action.
- Isolated execution: workspace-scoped file tools (read/search/diff),
  sandboxed shell (allowlisted commands, timeouts, no network except
  package mirrors if approved), bounded iterations + wall-clock timeout
  + per-task $ cap with soft-stop (section 4).
- Kill switch: dashboard Stop halts between iterations; partial work is
  kept as a diff + transcript, never half-applied silently.
- Every task gets a `task_id` reused by the usage logger, so the cost
  panel shows per-engineering-task spend automatically.
- Approvals required from you before build: the tool allowlist, the
  file roots Engineer may touch, default iteration/$/time bounds, and
  the approval UX (dashboard buttons vs typed confirm vs voice).

## 6. Post-hackathon local AI migration (PLAN -- document only)

Goal: Moon Man runs without Meta or any cloud AI. Not for the hackathon.

- Provider abstraction (investigated, not built): agent code already talks
  to an OpenAI-compatible client (`base_url` + key + model). The swap is
  `get_client(provider)` returning a client plus capability flags
  `{tools, vision, context_window}`. Local servers (Ollama / vLLM /
  LM Studio) all serve OpenAI-compatible endpoints, so standard calls
  port directly; Responses API + server-side web search do NOT (see
  blockers). Voice stays untouched -- STT/TTS are already local.
- Blockers in current code to fix at migration time: (a) 1M-context
  assumption -- trivial asks inject ~7k tokens of system+memory, and
  history + images grow unbounded; local models need summarization and
  image downsampling/dropping; (b) tool-calling reliability varies
  widely by local model -- needs an eval harness running our real tool
  loop before trusting it; (c) `web_research` uses Meta server-side
  grounding -- replace with a local search tool or drop it;
  (d) reasoning-effort and verbosity need per-model tuning.
- Local candidates (directions, not verified): Meta's own open models
  (`muse-spark-open`, `muse-glimmer` -- see Meta docs "Run inference /
  Hardware platforms"), or current open tool-calling models. Eval first.
- Hardware/cost projections (UNVERIFIED -- verify post-hackathon):
  70B-class Q4 needs ~40GB+ VRAM; 8-32B models fit a single 24GB card
  with capability loss; CPU-only is too slow for the voice loop. Power
  + hardware amortization replaces per-token bills; break-even depends
  on actual daily usage, which the new telemetry will quantify.
- Hybrid option: local model for chat + Meta API for hard engineering
  tasks, switched per mode (Astronaut local, Engineer cloud) with the
  cost panel proving the split. Decide after measuring.

## 7. Recommended order after submission

1. Fix the spoken-input path + TTS reliability (section 8) -- demo first.
2. Run on telemetry for 1-2 weeks; read real $/day before optimizing.
3. Cheap wins if over budget: trim injected memory context, cap history
   length, consider Contributor tier (with eyes open on data use).
4. Approve + build Engineer Mode (section 5) with soft-stop + kill switch.
5. Build the provider abstraction + tool-loop eval harness (no model swap).
6. Eval local models against the harness; measure quality + latency.
7. Migrate Astronaut Mode local-first, keep Meta for Engineer Mode.
8. Full independence when the evals -- not the calendar -- say so.

## 8. Known open issues (pre-existing)

- Spoken input path unconfirmed end-to-end (server chain healthy; eye mic
  leg needs a physical test + MIC panel read).
- Pocket TTS jobs occasionally time out (25s) with Piper covering; root
  cause unknown.
- Eye HTTP responses cap at 60s; long answers flirt with the timeout.
- Pi camera ~1fps; tracker still SIM_ONLY (servos unwired; needs
  MIRROR_X/Y + FX/FY_DEG tuning on the rig).
- Disk pressure seen during builds (~9.7GB freed from Arduino caches).
- LVGL/core upgrade still needs a left-eye re-verify.
