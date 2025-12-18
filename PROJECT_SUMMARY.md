Project summary (current state)
- Core idea: small AI council (STAR voting) for concrete choices. Two tracks: (1) Democracy Bots for delivery-day mode; (2) Code Explainer tool.
- Democracy Bots status: STAR tally implemented; agents Money, EnergyMatch, ScheduleFit, Safety, plus RestPrior and urgency curve; finance snapshot computes gross/gas/maint/net/gap coverage; near-tie discipline nudge added; CLI demo prints ballots/totals/winner.
- Code Explainer status: AST fact extraction + runtime trace; optional local LLM rewrite (Ollama); timeout hang fixed by safe runner; needs cleanup for HTTP mode and smaller model fallback.

Gaps to shippable (cross-platform)
- Config/data: finance.json, modes.json, settings.json (urgency soft/scale, maint $/mi, tip multiplier, schedule).
- Engine: finalize agents with env caps; deterministic logs (CSV/SQLite); unit tests for STAR and agent scoring.
- UX/CLI: `democracy vote --finance finance.json --modes modes.json`; pretty table + `--json`; action steps for SHORT/FULL.
- Packaging: pyproject, entry_points, pipx guidance; Windows/Linux/macOS testing (Python 3.10–3.12).
- Nice-to-have: Textual/Typer UI for edits; weekly rollup; policy packs.

Secondary tool (Code Explainer) TODOs
- HTTP call to Ollama with retry/timeout; strict JSON validator; launch scripts and README; smaller model fallback (e.g., llama3.2:3b-instruct-q4_K_M).
