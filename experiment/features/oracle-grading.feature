@oracle
Feature: Repeated oracle grading
  Researchers rely on repeated checks to establish that grading is reliable.

  Rule: A determinism check passes only when all required verdicts agree

    @edge_case
    Scenario: Repeated checks disagree
      Given a pilot task with conflicting grading verdicts
      When the researcher checks grading determinism
      Then the determinism check fails because its verdicts are inconsistent

    @edge_case
    Scenario: A repeated check does not return a verdict
      Given a pilot task with a missing grading verdict
      When the researcher checks grading determinism
      Then the determinism check fails because its verdicts are inconsistent
      And the report identifies the missing verdict

    @edge_case
    Scenario: An unreadable task cannot be checked for determinism
      Given a task document that cannot be read
      When the researcher checks grading determinism
      Then the determinism report explains that the task could not be loaded

    @edge_case
    Scenario: A grading check fails unexpectedly
      Given a pilot task with an unavailable grading check
      When the researcher checks grading determinism
      Then the determinism check fails and explains the grading error

    @edge_case
    Scenario: A task requests fewer than the required three checks
      Given a pilot task configured for only two grading checks
      When the researcher checks grading determinism
      Then the determinism check fails and states that three checks are required

  Rule: Trial measurements distinguish missing outputs from silently incorrect results

    @edge_case
    Scenario: A reversed point is recorded as a silent invalid result
      Given a completed trial with a reversed representative point
      When the researcher measures that trial
      Then the measurement records a silent spatial failure and a partial score

    @edge_case
    Scenario: A missing result is not a silent invalid result
      Given a trial with no geographic result
      When the researcher measures that trial
      Then the measurement records failure without silent invalidity

    @edge_case
    Scenario: An incorrect boundary relation is silently invalid
      Given a completed trial with an incorrect boundary relation
      When the researcher measures that trial
      Then the measurement records a silent invalid boundary result

    Scenario: A valid boundary trial preserves grading, determinism, and usage
      Given a valid boundary trial with recorded usage and determinism checks
      When the researcher measures that trial
      Then the measurement records successful grading and the audit and usage

  Rule: Human reference measurements preserve participant effort

    Scenario: A verified human reference contributes to trial measurements
      Given a completed human reference with a valid boundary result
      When the researcher measures the human reference
      Then the measurement records the successful result and participant effort
      And the recorded result can also be measured without the output files

  Rule: Pilot grading detects geographic errors in task results

    Scenario Outline: Correct pilot results pass grading
      Given the reference output for the <task> pilot task
      When the researcher grades the output
      Then the output passes grading

      Examples:
        | task           |
        | representative point |
        | boundary relation |
        | natural breaks |

    @edge_case
    Scenario: Reversed coordinates are rejected
      Given a representative point with longitude and latitude reversed
      When the researcher grades the output
      Then the output fails grading with an axis-order explanation

    @edge_case
    Scenario: An incorrect boundary relation is rejected
      Given a boundary relation with an incorrect intersection pattern
      When the researcher grades the output
      Then the output fails grading

    @edge_case
    Scenario: An incorrect natural-breaks class is rejected
      Given a natural-breaks result with an incorrect class assignment
      When the researcher grades the output
      Then the output fails grading

    @edge_case
    Scenario Outline: A malformed representative point is rejected
      Given a representative-point output exhibiting <problem>
      When the researcher grades the output
      Then the grading report explains the <problem>

      Examples:
        | problem                |
        | the wrong country code |
        | a non-point geometry   |
        | incomplete coordinates |

    @edge_case
    Scenario Outline: Unrequested information in an output is rejected
      Given the <task> result contains an unrequested field
      When the researcher grades the output
      Then the output fails grading

      Examples:
        | task              |
        | boundary relation |
        | natural breaks    |

    @edge_case
    Scenario: Missing geographic output is reported for each check
      Given a representative-point task with no output
      When the researcher grades the output
      Then each grading check reports that the output could not be assessed
