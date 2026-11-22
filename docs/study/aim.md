---
title: Aim — frozen thesis specification
short_title: Aim
description: >-
  Primary aim, concrete framing, secondary aim, contribution claim (three legs),
  and title refinement for the MCP vs CodeGen interface experiment.
---

(fresh-aim)=

# Aim — Frozen Thesis Specification

**Status:** pre-implementation design specification (post-professor-consultation).
Frozen material: AIM, LITERATURE REVIEW, DEFINITIONS, GAP, PROPOSED EXPERIMENT.
**Not covered here, by design:** IMPLEMENTATION, RESULTS, DISCUSSION, SUMMARY — they
derive from data generated under this specification and are written only after runs
exist.

**Standing rule:** this document stands alone. Nothing from other files in the
workspace is assumed. Bibliographic keys `[key]` refer to `bibliography.bib`
(81 entries, canonical corpus). No citation appears here that is not in that file.

**Revision discipline:** tolerances, arms, hypotheses and stop-rules are
append-only from the moment of freeze (§7). Changes after freeze invalidate the
run log.

---

## Primary aim

Empirically determine whether *the way an LLM agent reaches geospatial processing
operations* changes the correctness of the artefact it produces — not what it
plans, not what it says, not how cheap it is first — i.e. whether the integration
interface is a **causal factor** on outcome quality of executed GIS work.

## Concrete framing

Same model, same engine, same data, same prompt scaffold; only the interface block
differs:

- **(A)** typed Model Context Protocol (MCP) tools
- **(B)** unrestricted code generation (Python)
- **(C)** typed MCP with an `execute_code` escape hatch inside the server
- **(D)** agent code orchestrating the same typed MCP tools

Output correctness is decided by an ISO-19157-derived **predicate oracle** applied
to the *executed* artefact, never by LLM judgement, text similarity, or human
impression.

## Secondary aim

Decompose *why*: contract-enforcement depth at the tool boundary (N1→N4) as the
mechanism axis; failure taxonomy; repeatability (pass^k); the human analyst as a
descriptive reference — not as a baseline to beat.

## Contribution claim (defensive, three legs)

- **C1 — instrument**: a reusable, versioned, frozen evaluation harness
  (tasks-as-YAML, predicate oracle, results contract) for executional assessment
  of LLM agents on geoprocessing tasks.
- **C2 — estimate, not declaration**: an effect-size estimate of the interface
  factor with intervals (bootstrap/McNemar-style paired analysis), instead of
  opinions, at a clearly stated power limit.
- **C3 — mechanism**: empirical separation of *contract enforcement depth* (N1–N4)
  from *protocol identity* — the transferable science of boundary design, not a
  “MCP wins/loses” headline.

## Title refinement (post-consultation reframe)

The consultation killed the “MCP vs CodeGen” horse-race framing as the *title*:
the interface comparison is the gate question, the mechanism is the contribution.
The thesis subject (GIS + executed artefacts + MCP-vs-typed tooling) is
unchanged; only the claim positioning is refactored:

- **Recommended (PL):** „Kontrakt zamiast protokołu? Głębokość egzekwowania
  kontraktu typowanego narzędzia a poprawność artefaktów agentów LLM w zadaniach
  geoprzetwarzania“
- **Recommended (EN):** *“Contract, not Protocol? Tool-Contract Enforcement Depth
  and Artefact Correctness of LLM Agents on Geoprocessing Tasks”*
- **Alternative (minimal change, interrogative form):** „Czy interfejs ma
  znaczenie? Wpływ głębokości egzekwowania kontraktu narzędzia (N1–N4) na
  artefakty agentów LLM w zadaniach GIS”
- **Keywords (PL):** LLM, GIS, agenty, głębokość kontraktu, predykaty ISO 19157,
  QGIS, benchmark, generowanie kodu, wyrocznia
- **Keywords (EN):** LLM, GIS, agents, contract enforcement depth, ISO 19157
  predicates, QGIS, benchmark, code generation, test oracle

**Honest caveat to carry everywhere:** at pilot scale (§6.8), results are
**effect-size estimates for the scaled study**, never confirmatory statements.
