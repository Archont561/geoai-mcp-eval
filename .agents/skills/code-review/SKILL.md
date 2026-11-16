---
name: code-review
description: Review proposed code changes for correctness, regressions, security, and conformance to the request and repository conventions. Use when asked to review a diff, branch, pull request, or implementation; do not use for ordinary implementation work unless the user asks for a review.
---

# Code Review

Review changes as an independent reviewer. Do not modify the code unless the user separately asks you to fix findings.

## Review process

1. **Establish the review scope.** Identify the requested base or fixed point and inspect the complete diff against it. If the comparison point is ambiguous and materially affects the review, ask before proceeding. Include relevant uncommitted changes when the user asks to review the working tree.
2. **Understand the intent.** Read the originating request, issue, or specification when available. Compare the implementation with that intent; do not invent requirements. If no spec is available, review the change on its own merits and mention the limitation only if it affects a finding.
3. **Read applicable repository guidance.** Check `AGENTS.md`, relevant skill instructions, and the standards or tests that apply to the changed files. Follow this repository's project constraints, including its Pixi-based Python environment, `experiment/` source-root convention, and generated-template/source consistency where relevant.
4. **Trace changed behavior.** Inspect surrounding code and call sites for correctness, error handling, edge cases, compatibility, security, and unintended side effects. Check whether tests cover meaningful behavior; run focused checks when practical and report what was or was not run.
5. **Report only actionable findings.** Prioritize concrete defects introduced by the change. Do not report pre-existing issues, speculative concerns, formatting already enforced by tooling, or subjective preferences as defects. Suggest a minimal correction when helpful.

## Findings

List findings first, ordered by severity. Each finding should include:

- **Severity:** critical, high, medium, or low, based on impact and likelihood.
- **Location:** the changed file and the smallest useful line range.
- **Problem:** the specific behavior that is wrong or risky, with the affected scenario.
- **Impact:** why it matters to users or maintainers.
- **Correction:** a concise suggested fix, when clear.

A finding must be supported by the diff and enough surrounding context to explain why it is a real issue. If no actionable findings remain, say so plainly, and note any meaningful test or scope limitations. Do not imply that the absence of findings guarantees the change is defect-free.
