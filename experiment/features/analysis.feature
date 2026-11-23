@cli @analysis
Feature: Preparing analysis-ready data
  The flat predicate matrix is what the analysis depends on: one row per run,
  one 0/1 column per named predicate, with the run keys carrying through
  unchanged.

  Scenario: A results directory flattens into a binary predicate matrix
    Given a results directory with scored runs
    When I flatten the results
    Then the table has one row per run
    And every predicate column holds only 0 or 1

  Scenario: A missing check scores zero rather than dropping the row
    Given a run whose score file omits one predicate
    When I flatten the results
    Then that run's row stays in the table
    And the missing predicate scores 0

  Scenario: An unknown assertion is reported rather than guessed
    Given a run whose score file names an unknown assertion
    When I flatten the results
    Then the command fails
    And the output names the assertions that have no predicate mapping

  Scenario: An empty results directory is not silently reported as a success
    Given a results directory with no score files
    When I flatten the results
    Then the command fails
    And the output says no score files were found
