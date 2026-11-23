@cli @pilot
Feature: Preparing and checking the pilot task suite
  The pilot tasks are the measuring instrument. Before any run, the suite has
  to validate, and after a run the oracle has to give the same verdict on the
  same artefacts every time.

  Scenario: The shipped suite validates
    When I run the command "pilot validate --root {suite}"
    Then the command exits successfully
    And the output reports that 3 tasks are valid and the pilot traps are covered

  Scenario: A suite missing its schema is rejected with a reason
    Given a task suite copied without its schema
    When I run the command "pilot validate --root {suite}"
    Then the command fails
    And the output explains that the schema cannot be read

  Scenario: A deterministic artefact passes the determinism gate
    Given artefacts that satisfy each pilot task
    When I check determinism for task "cartography-jenks-001"
    Then the report says the task passed
    And the report covers three runs

  Scenario: Missing artefacts fail the determinism gate
    Given no artefacts for task "prep-axis-order-001"
    When I check determinism for task "prep-axis-order-001"
    Then the report says the task failed

  Scenario: A task identifier outside the suite is refused
    Given artefacts that satisfy each pilot task
    When I check determinism for task "unknown-task"
    Then the command fails
    And the output says the task ID is unknown
