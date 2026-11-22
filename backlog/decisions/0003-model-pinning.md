# Decision: Model pinning for the experiment

## Status

Accepted

## Decision

- Primary model: `qwen2.5:3b` (~2 GB quantized, strong code/reasoning, fast CPU inference; recommended for N >= 80)
- Backup model: `llama3.2:3b` (~2 GB, fastest)
- Fallback: `llama3.1:8b` (~4.7 GB, better reasoning, slower CPU inference — pilot only)

All models run via Ollama in the pixi experiment environment (conda-forge).

## Rationale

From `docs/study/experiment.md`: model must be pinned (`model_id`, `run_date`,
driver hash, temperature logged on every record). Provider drift is unmeasured
variance bounded by r=4. 3B quantized models are feasible on CPU-only runners
(GitHub Actions).

## Alternatives considered

- `llama3.1:8b`: better reasoning but ~4.7 GB, slower CPU inference — pilot only
