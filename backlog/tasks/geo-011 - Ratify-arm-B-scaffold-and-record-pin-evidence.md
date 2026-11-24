---
id: GEO-011
title: Ratify arm-B scaffold and record study-pin evidence
status: Done
assignee: []
created_date: '2026-11-22T00:00:00Z'
updated_date: '2026-11-24T23:12:00Z'
labels: []
milestone: m-0
dependencies:
  - GEO-009
ordinal: 11000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The arm-B system prompt was tightened pre-freeze (see preregistration addendum 2026-11-22): single ```python fenced block required. Record local 0.5B evidence and run the same arm-B cell against the study pin (qwen2.5:3b) on the CI runner or a workstation (1.9 GB sandbox RAM cannot host it). Fold the result into the preregistration addendum as the pre-freeze evidence; if the pin emits no python fence, record the finding — do not patch the prompt or harness post-hoc.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Local 0.5B smoke evidence is recorded in the preregistration addendum.
- [x] #2 The pin (qwen2.5:3b) arm-B cell completes on a runner/workstation; score.json and transcript recorded.
- [x] #3 The preregistration addendum carries the pin outcome verbatim; no prompt/harness change follows without a new addendum.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Ensure scaffold wording is frozen in the addendum; run the pin cell on hardware that fits it.
2. Record verdict, oracle result, and any deviation in the addendum.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
- Ratified frozen Arm B system prompt (`_ARM_B_SYSTEM`, 418 bytes, SHA-256 `5c44378126c5b889a159b7524ea83bf0d365f45854ee2559b38230851ac1c985`) verbatim in `docs/study/preregistration.md` with zero changes to the Arm B prompt or harness.
- Recorded verbatim 0.5B (`qwen2.5-coder:0.5b`, digest `4ff64a7f502a08b7616edb8ca0a79eb1853fc363d842b7df4b46915d11a3fb09`) pilot evidence from Run `#45505815319` (`experiment-run-45505815319-4a7efe5b2742dfa175e7c3581acc994cb41305a2`, artifact ID `14972624264`, 169,754 bytes): 1/6 Arm B cells emitted a Python fence; TSR 0/6, MPS 0.0000.
- Recorded verbatim study-pin (`qwen2.5:3b`, digest `357c53fb659c5076de1d65ccb0b397446227b71a42be9d1603d46168015c9e4b`) pilot evidence from Run `#45505826575` (`experiment-run-45505826575-4a7efe5b2742dfa175e7c3581acc994cb41305a2`, artifact ID `14974065703`, 172,083 bytes): 4/6 Arm B cells emitted a Python fence (4/4 on confirmatory A/P families; 0/2 on descriptive C-family `cartography-jenks-001`); `prep-axis-order-001` rep 1 exited 0 with MPS 0.50 (`single-output-feature` passed, `representative-point-axis-order` failed, `silent_invalid=true`).
- Both non-fence findings (`cartography-jenks-001`) and sandbox `PROJ` stderr errors are recorded verbatim without post-hoc prompt or harness modification.
<!-- SECTION:NOTES:END -->
