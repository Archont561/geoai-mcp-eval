---
id: m-2
title: "Pre-freeze"
---

## Description

Pre-freeze audit before preregistration.

Exit criteria:

- Directory hash and fixture checksums are recorded.
- Task-suite validation and oracle determinism results are recorded.
- Human-reference and contamination audits are complete.
- Contamination audit records inherited vs constructed counts; either at least one inherited-stratum task is added or the 0-inherited state is explicitly accepted in writing.
- Instrument evidence is recorded: pinned checker versions (shapely/GEOS/Python), suite YAML checksums folded into the preregistration record.
