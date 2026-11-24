# Human reference (H) execution and evidence protocol

**Status: prepared; execution pending.** No human session, timing, tool count, screenshots, processing log, output, or oracle result is recorded by this document. H is a descriptive reference arm and does not need to be completed before task-spec preparation; it must be oracle-verified before any comparative agent-run analysis.

## Before the session

1. Review `README.md`, the task YAML, fixture checksum, and oracle assertions. Do not modify prompts, fixtures, assertion thresholds, or this protocol after the task suite is frozen. If a task defect is found, correct it before any H or model run, then re-run validation and document the version change.
2. Use a clean QGIS profile with network access disabled. Record QGIS, GDAL, GEOS, and PROJ versions. Use only the task prompt and the committed input fixture; do not use web search, external geocoders, or additional datasets.
3. Create a private, empty evidence directory. Do not place personal data, unredacted recordings, or workstation-specific files in Git.
4. Obtain informed consent before recording a screen or collecting identifying information. Recording is optional and is not required for a valid H result.

## Execute and capture

For each task, read the prompt once, start the timer at the first interaction with the GIS environment, and stop after the requested deliverable is saved. Work independently without coaching. Save the exact requested deliverable in the task's `human_baseline.artifact_dir` (these paths are gitignored). Do not rerun to improve a result after seeing oracle feedback.

Complete a copy of `human-reference-record.template.json` (`record_version: 2`) for each task. Record elapsed minutes, number of meaningful GIS operations/steps, tools and processing algorithms, software versions, fixture checksum, output filenames and SHA-256 hashes, deviations, and any interruptions. Raw QGIS host observations (layer, project, canvas events) and free-text notes are supporting evidence only, never study steps or tools. Leave `session.steps` and `session.tools` as `null` (`metrics_status: "pending_review"`) until Processing history executions and manual action groups have been reviewed; never treat an unverified empty list `[]` or a raw event count as a verified study metric. Preserve the original output, sanitized run record, and (if consented) recording together in approved private storage. Record unsuccessful or incomplete sessions honestly; never impute missing fields or convert failures to successes.

## Verify and preserve

1. Run task-suite validation after recording the baseline metadata. Do not change `human_baseline.status` to `complete` until the user has executed the task and the output exists.
2. Invoke the three-run gate, using the fixed output directory, for example:

   ```bash
   pixi run experiment pilot determinism prep-axis-order-001 \
     --artifacts-dir experiment/tasks/baselines/prep-axis-order-001
   ```

3. Preserve the JSON gate report with the evidence. The gate evaluates a fixed file three times; it does not repeat the human session and does not establish human reproducibility.
4. A failed oracle result remains a failed H record. Investigate only as a task-design issue before freeze; do not tune the oracle against a completed session.
5. After review, the user may update the task YAML's human-reference fields and archive only sanitized, non-identifying metadata in the repository. Recordings and raw workspaces remain outside Git.

## Evidence checklist

- [ ] Participant consent recorded if a recording is made.
- [ ] Task ID, task file version, and input fixture SHA-256 recorded.
- [ ] Software versions, environment/network restrictions, steps, tools, and elapsed time recorded.
- [ ] Requested output and SHA-256 recorded; raw output retained privately.
- [ ] Three-run oracle JSON report retained, including failures.
- [ ] `pending` remains the status until these facts are supplied by the user; no blank template is evidence of execution.
