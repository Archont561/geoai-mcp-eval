@plugin @post-session-review
Feature: Non-destructive post-session review of human-baseline takes
  As a study reviewer auditing a completed human-baseline session
  I want to review an immutable session directory and emit separate reviewed artifacts
  So audited steps, tools, and trajectories are traceable without mutating raw evidence

  Background:
    Given the Experiment Plugin is loaded
    And the pilot task suite is available

  Scenario: Reviewing a recorded session emits separate reviewed artifacts without mutating raw evidence
    Given a recorded session with processing history, raw host observations, and a note
    When I review that session adding manual action "exported GeoJSON" with tool "qgis:save-features-as" and mark review complete
    Then the original raw record and event log are byte-for-byte unchanged
    And the reviewed record marks study metrics reviewed with 2 steps and tools "native:reprojectlayer, qgis:save-features-as"
    And the reviewed record pins SHA-256 hashes of the raw record and event log
    And human_trajectory.jsonl contains only the 2 audited study steps

  Scenario: Draft review retains audited manual action groups while keeping study metrics pending
    Given a recorded session with processing history, raw host observations, and a note
    When I review that session adding manual action "inspected layer CRS" without marking review complete
    Then the original raw record and event log are byte-for-byte unchanged
    And the reviewed record keeps study metrics pending review for reason "manual_review_pending"
    And the reviewed record retains 1 manual action group with null tool

  Scenario: Reviewing a session without processing history or a processing log keeps metrics pending
    Given a recorded session captured without processing history coverage
    When I review that session adding manual action "exported GeoJSON" with tool "qgis:save-features-as" and mark review complete
    Then the reviewed record keeps study metrics pending review for reason "processing_history_unavailable"
    And the reviewed record leaves study steps and tools null

  Scenario: Reviewing a session with an external QGIS processing log resolves missing processing history
    Given a recorded session captured without processing history coverage
    And an external QGIS processing log with one buffer execution
    When I review that session with the external processing log and mark review complete
    Then the reviewed record marks study metrics reviewed with 1 steps and tools "native:buffer"
    And the reviewed record records the processing log SHA-256
    And human_trajectory.jsonl contains the parsed processing log execution

  Scenario: Reviewing an abandoned session is refused without writing reviewed artifacts
    Given an abandoned session on disk
    When I attempt to review that abandoned session
    Then the review is refused as an abandoned take
    And no reviewed record or trajectory file is written

  Scenario: Reviewing via the standalone CLI writes reviewed artifacts to a chosen output directory
    Given a recorded session with processing history, raw host observations, and a note
    When I run the review CLI targeting a separate output directory and marking review complete
    Then the review CLI exits successfully
    And the separate output directory contains the reviewed record and human_trajectory.jsonl
    And the original session directory contains no new files
