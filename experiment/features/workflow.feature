@cli @workflow
Feature: End-to-end researcher study workflow
  As a GIS researcher executing a benchmark study pass
  I want suite validation, multi-arm runs, determinism verification, and archive packing to work together
  So every published result traces cleanly back to a verified instrument and run archive

  Rule: External preparation commands cannot hang the workflow

    @edge_case
    Scenario: Timed-out commands fail whether their output is captured or passed through
      Given a preparation command that does not finish promptly
      When the workflow runs the command with a time limit in both output modes
      Then both attempts report that the time limit expired

  Rule: External preparation reports command outcomes and tool versions

    Scenario Outline: Preparation commands retain their output and exit status
      Given a preparation command that reports a message and exits with status <status>
      When the workflow runs the command in both output modes
      Then the captured message and both exit statuses are accurate

      Examples:
        | status |
        | 0      |
        | 4      |
        | 9      |

    Scenario: An unavailable tool version is reported honestly
      Given one available and one unavailable preparation tool
      When the researcher checks both tool versions
      Then the available tool reports its version and the missing tool is unavailable

  Rule: Workflow preparation verifies the instrument and records its environment

    Scenario: Preflight validates the task suite and records environment details
      Given a workflow checkout with a pinned environment
      When the researcher performs workflow preflight
      Then the environment record identifies the checkout and dependency lock
      And the task suite was validated once

    @edge_case
    Scenario: Preflight rejects an invalid study instrument
      Given a workflow checkout with an invalid task suite
      When the researcher performs workflow preflight
      Then the preflight explains why the task suite is invalid

    Scenario: Model preparation records the model identity and test response
      Given a reachable model service for workflow preparation
      When the researcher prepares the model for the workflow
      Then the model identity and test response are saved

  Rule: Hosted workflows publish their progress and environment details

    Scenario: Workflow preparation, harvest, and readiness publish their results
      Given a hosted workflow collecting progress and summary reports
      When the workflow prepares, harvests, summarizes, and checks readiness
      Then the hosted workflow receives the run details and readiness results

  Rule: Workflow trials distinguish pilot measurements from smoke checks

    Scenario: Pilot and smoke trials record their different outcomes
      Given a prepared model service and an isolated workflow
      When the researcher runs a pilot trial and a smoke trial
      Then the pilot records the model identity and successful grading
      And the smoke trial records a simulated check

    Scenario: Current run settings take precedence over older settings
      Given current and older workflow settings are both present
      When the researcher starts a workflow trial with response reuse enabled
      Then the trial uses the current settings and enables reuse
      When only older workflow settings are present
      Then the trial uses the older settings and enables reuse

  Rule: Harvesting reports missing or invalid trial evidence

    @edge_case
    Scenario: Harvest records a failed determinism check for missing trial output
      Given a completed trial with no result to grade
      When the researcher harvests the trial and checks determinism
      Then the harvest reports a failed determinism check with its detailed report

  Rule: Complete and targeted scripted passes score every trial and pack cleanly

    @smoke
    Scenario: Full scripted pass covers all pilot tasks across both paradigms
      Given a fresh experiment output folder
      When I run a scripted pass over the full pilot suite in both paradigms
      Then the run reports all six trials passed the oracle
      And every pilot task appears in both paradigms
      And every trial saves a transcript and an oracle score

    Scenario: Targeted scripted pass runs only the requested tasks
      Given a fresh experiment output folder
      When I run a scripted pass for tasks "prep-axis-order-001,cartography-jenks-001" in both paradigms
      Then the run reports all four trials passed the oracle
      And the run omits task "analysis-de9im-001"

    Scenario: Outputs from a scripted run pass the three-pass determinism gate
      Given a fresh experiment output folder
      When I run a scripted benchmark for task "prep-axis-order-001" in code-generation mode
      And I verify determinism on that trial for task "prep-axis-order-001" in code-generation mode
      Then the determinism report states the task passed
      And the determinism report covers three repeated checks

    @smoke
    Scenario: Completed multi-arm run packs into a verified run archive
      Given a fresh experiment output folder
      When I run a scripted pass over the full pilot suite in both paradigms
      And I pack and inspect the resulting run archive
      Then the archive inspection reports six passed trials

  Rule: Incomplete or broken task suites are rejected before any run begins

    @edge_case
    Scenario: Task suite missing a required family is rejected
      Given a pilot task suite missing its cartography task
      When I validate that task suite
      Then the action is refused
      And the explanation names the missing task family
      And the explanation names the uncovered pilot trap "jenks-classification"

    @edge_case
    Scenario: Task suite missing a required study trap is rejected
      Given a pilot task suite that no longer declares the axis-order trap
      When I validate that task suite
      Then the action is refused
      And the explanation names the uncovered pilot trap "crs-axis-order"

    @edge_case
    Scenario: Task suite missing a referenced geographic fixture is rejected
      Given a pilot task suite missing its data-preparation fixture
      When I validate that task suite
      Then the action is refused
      And the explanation names the missing fixture
