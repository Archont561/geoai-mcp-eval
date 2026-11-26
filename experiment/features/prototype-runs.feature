@cli @runs @proto
Feature: Experiment runs, oracle rescoring, token budgets, and caching
  As a GIS researcher comparing typed GIS tools against generated code
  I want deterministic runs, transparent token accounting, and safe refusal of invalid settings
  So every benchmark comparison is reproducible and cost-controlled

  Rule: Tool catalogue and self-test confirm the typed GIS operations are ready

    @smoke
    Scenario: Researcher lists the typed GIS operation catalogue
      When I inspect the typed GIS operation catalogue
      Then the action succeeds
      And the catalogue includes the boundary relation operation
      And the catalogue reports the total number of operations

    @smoke
    Scenario: Self-test verifies the typed GIS service end to end
      When I run the typed GIS service self-test
      Then the action succeeds
      And the self-test reports the tool count and filtered Poland feature
      And the self-test reports the boundary relationship between Poland and Czechia

  Rule: Repeated trials retain separate evidence and identifiers

    Scenario: A researcher repeats a typed-tool run and inspects its archive
      Given a fresh experiment output folder
      When I run two repetitions of a typed-tool task and save an archive
      Then both repetitions have separate scores and appear in both reports

    @edge_case
    Scenario: A run cannot request zero repetitions
      Given a fresh experiment output folder
      When I request a run with zero repetitions
      Then the action is refused
      And the explanation says repetitions must be positive

    @edge_case
    Scenario: An unknown enforcement level is rejected
      When I request a typed-tool run with an unknown enforcement level
      Then the action is refused
      And the explanation identifies the invalid enforcement level

  Rule: Researchers can review scores from either a saved archive or run folder

    Scenario: A saved run can be scored and displayed in both forms
      Given a completed typed-tool run saved as an archive
      When I score and display the archived run and score its output folder
      Then both forms report that the task passed

  Rule: Scripted runs produce scored outputs that can be rescored and audited

    Scenario: Scripted single-task run produces a scored cell with a study disclaimer
      Given a fresh experiment output folder
      When I run a scripted benchmark for task "analysis-de9im-001" in code-generation mode
      Then the action succeeds
      And the run summary reports one of one cells passed the oracle
      And the output folder holds a run summary
      And the output warns that this is not a study result

    Scenario: Completed run can be rescored and detects corrupted results
      Given a fresh experiment output folder
      When I run a scripted benchmark for task "analysis-de9im-001" in code-generation mode
      And I rescore that completed run
      Then the rescore reports one of one cells passed the oracle
      And displaying the run shows its oracle verdicts
      When I corrupt the saved result and rescore again
      Then the rescore reports zero cells passed the oracle

    @edge_case
    Scenario: Scoring an empty output folder fails clearly
      Given an empty experiment output folder with a long path
      When I attempt to score that empty output folder
      Then the action exits with status 1
      And the explanation states that no cells were found

    @edge_case
    Scenario: Displaying scores for a folder without a summary fails clearly
      Given an empty experiment output folder with a long path
      When I attempt to display scores for that folder
      Then the action exits with status 1
      And the explanation states that the summary is missing

  Rule: Invalid run settings are rejected before creating output folders

    @edge_case
    Scenario: Unknown execution driver is refused
      Given a fresh experiment output folder
      When I request a run using unknown driver "bogus"
      Then the action exits with status 2
      And the explanation identifies the supported execution drivers
      And no output folder is created

    @edge_case
    Scenario: Unknown execution driver preserves colored terminal diagnostics
      Given a fresh experiment output folder
      And a terminal that requests colored output
      When I request a run using unknown driver "bogus"
      Then the action exits with status 2
      And the explanation identifies the supported execution drivers
      And the output includes terminal color styling
      And no output folder is created

    @edge_case
    Scenario: Code-generation runs refuse typed-tool enforcement levels
      Given a fresh experiment output folder
      When I request a code-generation run with a typed-tool enforcement level
      Then the action exits with status 2
      And no output folder is created

    @edge_case
    Scenario: Unknown model backend profile is refused
      Given a fresh experiment output folder
      When I request a run using unknown backend "bogus"
      Then the action exits with status 2
      And the explanation identifies the unknown backend
      And no output folder is created

    @edge_case
    Scenario: Hosted model backend without credentials is refused before starting
      Given a fresh experiment output folder
      And the hosted backend has no API key configured
      When I request a model run on the hosted backend
      Then the action exits with status 2
      And the explanation identifies the missing hosted-service credential
      And no output folder is created

    @edge_case
    Scenario: Non-positive per-cell token budget is refused before starting
      Given a fresh experiment output folder
      When I request a run with a zero token budget per cell
      Then the action exits with status 2
      And the explanation says the token budget must be positive
      And no output folder is created

  Rule: Model runs record token usage, enforce token budgets, and reuse cached responses

    Scenario: Model token counts are recorded in the transcript and run records
      Given a fresh experiment output folder
      And a simulated model endpoint reporting 120 input and 35 output tokens
      When I run a model-driven code-generation cell for task "analysis-de9im-001"
      Then the action succeeds
      And the transcript records 120 input and 35 output tokens without warnings
      And the run records report totals of 120 input, 35 output, and 155 total tokens

    Scenario: Missing token usage is recorded as unavailable with an explicit warning
      Given a fresh experiment output folder
      And a simulated model endpoint reporting no token usage
      When I run a model-driven code-generation cell for task "analysis-de9im-001"
      Then the action succeeds
      And the transcript records unavailable usage with an explicit warning
      And the run records report unavailable token totals with 1 missing-usage cell

    @edge_case
    Scenario: Exceeding the cell token budget aborts cleanly before executing code
      Given a fresh experiment output folder
      And a simulated model endpoint reporting 400 input and 100 output tokens
      When I run a model-driven code-generation cell for task "analysis-de9im-001" with a budget of 100 tokens
      Then the action exits with status 1
      And the cell stops for exceeding the token budget without running generated code
      And the run records show 1 aborted cell and 500 total tokens

    Scenario: Digest-pinned caching reuses valid replies unless caching is disabled
      Given a fresh experiment output folder
      And a simulated model endpoint pinned to digest "sha256:pin-1" counting requests
      When I run the same cached cell twice and a third time with caching bypassed
      Then the endpoint answered 2 requests with cache reuse false, true, false
