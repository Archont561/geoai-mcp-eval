@plugin @review
Feature: Review of human-baseline sessions
  A reviewer can add audited evidence without changing the original session.

  Background:
    Given the Experiment Plugin is loaded
    And the pilot task suite is available

  Rule: Completed review preserves its sources and records audited work

    Scenario: A reviewer adds an export to a recorded session
      Given a recorded session with processing history, raw host observations, and a note
      When I complete a review adding a manually performed export
      Then the original raw record and event log are byte-for-byte unchanged
      And the reviewed record reports two steps and both observed tools
      And the reviewed record identifies the original evidence by its fingerprints
      And the reviewed trajectory contains only the two audited study steps

    Scenario: A reviewer supplies an external processing history
      Given a recorded session captured without processing history coverage
      And an external QGIS processing log with one buffer execution
      When I review that session with the external processing log and mark review complete
      Then the reviewed record reports one buffer step and its tool
      And the reviewed record identifies the external processing log
      And the reviewed trajectory contains the external processing execution

    Scenario: An empty processing history supports a fully manual workflow
      Given a recorded session captured without processing history coverage
      And an empty external processing history
      When the reviewer completes a manual-only review
      Then the reviewed record reports one manual step and no tools

    Scenario: Repeating a review does not duplicate matching processing evidence
      Given a recorded session with processing history, raw host observations, and a note
      And an external history matching its recorded processing execution
      When the reviewer repeats the same completed review
      Then the reviewed trajectory retains only one copy of the execution and one manual action

    Scenario: Review keeps manual actions recorded during the session
      Given a recorded session with a manual styling action and processing history
      When I complete a review adding a manually performed export
      Then the review counts both manual actions and attributes only the export tool

    Scenario: A reviewer writes the results to a separate location
      Given a recorded session with processing history, raw host observations, and a note
      When I complete a review in a separate output directory
      Then the review succeeds
      And the separate output directory contains the reviewed record and trajectory
      And the original session directory contains no new files

  Rule: Incomplete evidence must not be presented as a completed review

    @edge_case
    Scenario: A draft retains the reviewer's action but leaves metrics pending
      Given a recorded session with processing history, raw host observations, and a note
      When I add a manual inspection without completing the review
      Then the original raw record and event log are byte-for-byte unchanged
      And the reviewed record says manual review is pending
      And the reviewed record retains one manual action without a named tool

    @edge_case
    Scenario: Missing processing history leaves metrics pending
      Given a recorded session captured without processing history coverage
      When I complete a review adding a manually performed export
      Then the reviewed record says processing history is unavailable
      And the reviewed record leaves study steps and tools unknown

    @edge_case
    Scenario: A damaged external processing history prevents verified metrics
      Given a recorded session captured without processing history coverage
      And an external processing history with an unreadable execution
      When the reviewer completes the review using that history
      Then the reviewed record says processing history is incomplete
      And the reviewed record leaves study steps and tools unknown

    @edge_case
    Scenario: A review that cannot be saved leaves no partial reviewed record
      Given a recorded session with processing history, raw host observations, and a note
      And the review destination cannot publish the record
      When the reviewer tries to complete the review
      Then the save failure is reported and no partial reviewed record remains

    @edge_case
    Scenario: An abandoned session cannot be reviewed
      Given an abandoned session on disk
      When I attempt to review that abandoned session
      Then the review is refused as an abandoned take
      And no reviewed record or trajectory file is written

    @edge_case
    Scenario Outline: Review rejects incomplete or incompatible session evidence
      Given a recorded session with processing history, raw host observations, and a note
      And the review evidence has <problem>
      When the reviewer attempts to review the affected session
      Then the review reports <explanation>

      Examples:
        | problem                  | explanation                         |
        | a missing session        | the session does not exist          |
        | a missing record         | the record is missing               |
        | missing event history    | the event history is missing        |
        | an unsupported record    | the record version is unsupported   |
        | an unreadable record     | the record cannot be read           |
        | an unrecorded take       | the take has not been recorded      |
        | a missing processing log | the processing log does not exist   |
        | a blank manual action    | the manual action needs a description |

    @edge_case
    Scenario: A tool cannot be supplied without a corresponding manual action
      Given a session location that does not exist
      When the reviewer supplies a tool without a manual action in the terminal
      Then the terminal rejects the invalid review request

    @edge_case
    Scenario: A missing session cannot be reviewed from the terminal
      Given a session location that does not exist
      When the reviewer requests a terminal review of that location
      Then the terminal review reports failure
      And no session evidence is created at that location
