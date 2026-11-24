@cli @workflow
Feature: The experiment workflow from suite check to predicate matrix
  A researcher's pass through the instrument is a fixed sequence: check that
  the task suite still measures what it claims, run every task for every arm,
  confirm the oracle gives the same verdict on the artefacts that run left
  behind, and flatten the verdicts into the matrix the analysis reads. This
  feature walks that sequence in order, so a break anywhere in it shows up as
  a failed scenario rather than as a surprising column in the analysis.

  Scenario: A scripted pass covers every pilot task in both arms
    Given a prototype output directory
    When I run a scripted prototype over the whole suite in both arms
    Then the run reports that all six cells passed the oracle
    And every pilot task appears in both arms
    And every cell keeps a transcript and a score file

  Scenario: A run can be narrowed to the tasks under investigation
    Given a prototype output directory
    When I run a scripted prototype for the tasks "prep-axis-order-001,cartography-jenks-001" in both arms
    Then the run reports that all four cells passed the oracle
    And the run holds no cell for task "analysis-de9im-001"

  Scenario: The artefacts a run produced satisfy the determinism gate
    Given a prototype output directory
    When I run a scripted prototype for task "prep-axis-order-001" in arm "B"
    And I check determinism on the cell that run produced for task "prep-axis-order-001" in arm "B"
    Then the report says the task passed
    And the report covers three runs

  Scenario: A completed run flattens into one row per cell
    Given a prototype output directory
    When I run a scripted prototype over the whole suite in both arms
    And I flatten that run against the shipped suite
    Then the table has one row per cell of that run
    And every predicate column holds only 0 or 1

  Scenario: A suite missing a task family is refused before any run
    Given a task suite copied without its cartography task
    When I run the command "pilot validate --root {suite}"
    Then the command fails
    And the output names the task family that is missing
    And the output names the uncovered pilot trap "jenks-classification"

  Scenario: A suite that stops covering a pilot trap is refused
    Given a task suite whose axis-order trap is no longer declared
    When I run the command "pilot validate --root {suite}"
    Then the command fails
    And the output names the uncovered pilot trap "crs-axis-order"

  Scenario: A suite whose fixture has gone missing is refused
    Given a task suite copied without its prepare fixture
    When I run the command "pilot validate --root {suite}"
    Then the command fails
    And the output names the fixture that cannot be found
