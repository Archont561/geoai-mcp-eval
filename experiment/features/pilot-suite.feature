@cli @tasks @pilot
Feature: Pilot task suite verification and determinism gate
  As a GIS researcher preparing an experiment
  I want to inspect and validate the benchmark task suite before running models
  So the study instrument is complete, readable, and deterministic

  Rule: Researchers can browse and inspect the shipped pilot tasks

    @smoke
    Scenario: Shipped pilot suite lists all tasks
      When I list the tasks in the pilot suite
      Then the action succeeds
      And the researcher sees "analysis-de9im-001"

    Scenario: Shipped pilot suite displays details for a chosen task
      When I inspect task "analysis-de9im-001" in the pilot suite
      Then the action succeeds
      And the researcher sees "topology-de9im"

    Scenario: Automated analysis can read task details and suite validation
      Given the pilot task suite is available for automated analysis
      When I request machine-readable task details and validation
      Then both reports identify a valid pilot task suite

  Rule: A damaged task does not hide another task, but prevents listing the suite

    @edge_case
    Scenario: A researcher can inspect a valid task beside a damaged task
      Given a pilot task suite with a damaged task definition
      When I inspect task "analysis-de9im-001" in the pilot suite
      Then the action succeeds
      And the researcher sees "topology-de9im"

    @edge_case
    Scenario: Listing a suite with a damaged task explains the failure
      Given a pilot task suite with a damaged task definition
      When I list the tasks in the pilot suite
      Then the action is refused
      And the explanation identifies the damaged task definition

  Rule: The task suite must pass validation before any experiment starts

    @smoke
    Scenario: Complete pilot suite passes validation
      When I validate the pilot task suite
      Then the action succeeds
      And the report confirms 3 tasks are valid and all pilot traps are covered

    @edge_case
    Scenario: Task suite missing its validation schema is rejected
      Given a pilot task suite missing its validation schema
      When I validate that task suite
      Then the action is refused
      And the explanation states that the schema cannot be read

  Rule: Invalid task definitions and evidence are reported before the study starts

    @edge_case
    Scenario Outline: A damaged task suite reports its specific problems
      Given a pilot suite damaged by <problem>
      When the researcher checks the damaged suite
      Then the report explains the task suite problems

      Examples:
        | problem                                     |
        | duplicate tasks and an unsupported check    |
        | a missing title and an unsafe fixture       |
        | an unreadable validation schema              |
        | an invalid validation schema                |
        | no task definitions                         |
        | a task definition that is not a record      |
        | an invalid fixture and missing baseline      |
        | malformed feature properties                |
        | a fixture that is not a feature collection  |
        | an unsafe result path and incomplete check  |
        | an invalid grading section                  |
        | an unsupported spatial relation             |
        | an unreadable task definition               |
        | incorrectly shaped task details             |
        | a schema that is not a record               |

  Rule: Each pilot task identifies its expected result format

    Scenario: Pilot tasks distinguish geographic results from other results
      Given the published pilot tasks
      When the researcher prepares their expected result files
      Then the representative-point task expects geographic output
      And the other pilot tasks expect ordinary structured results

  Rule: Oracle grading must give the same verdict across repeated runs

    Scenario: Valid task outputs pass the determinism gate
      Given valid reference outputs for every pilot task
      When I run the determinism gate for task "cartography-jenks-001"
      Then the determinism report states the task passed
      And the determinism report covers three repeated checks

    @edge_case
    Scenario: Missing task outputs fail the determinism gate
      Given no outputs for task "prep-axis-order-001"
      When I run the determinism gate for task "prep-axis-order-001"
      Then the determinism report states the task failed

    @edge_case
    Scenario: Determinism gate refuses an unknown task identifier
      Given valid reference outputs for every pilot task
      When I run the determinism gate for task "unknown-task"
      Then the action is refused
      And the explanation states that the task identifier is unknown

  Rule: Task lookup can find intact tasks without hiding damaged suite entries

    Scenario: An unreadable neighbouring task does not hide a valid task
      Given a task collection with one valid and one unreadable task
      When the researcher looks up the valid task
      Then the valid task is found and its details are available
      And both task documents are discoverable

    @edge_case
    Scenario: Loading the entire task collection rejects damaged entries
      Given a task collection with one valid and one unreadable task
      When the researcher loads the entire task collection
      Then the unreadable task is identified as the loading failure

    @edge_case
    Scenario: An unknown task is not found in the collection
      Given a task collection with one valid and one unreadable task
      When the researcher looks up a task that is not present
      Then the missing-task report identifies the task and collection
