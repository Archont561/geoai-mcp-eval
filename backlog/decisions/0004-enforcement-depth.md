# Decision: Enforcement depth flag (N1-N4)

## Status

Proposed (to freeze at v1.0-prereg)

## Decision

A single `--enforce=N1..N4` flag gates middleware enforcement depth within arm A.
The catalogue-constant rule requires one server, one tool surface, one catalogue
hash; depth is the only variable.

- N1: minimal enforcement
- N2: eliminates executable-but-invalid artefacts (RQ8 silent corruption)
- N3: primary execution depth for arm A
- N4: full enforcement curve (RQ2 enforcement-depth curve)

## Rationale

From `docs/study/experiment.md`: catalogue-constant rule is non-negotiable. Depth
is a single flag. RQ2 tests whether WSZ rises with enforcement depth at the
boundary (N1→N4). RQ8 tests whether enforcement ≥ N2 eliminates silent
corruption.
