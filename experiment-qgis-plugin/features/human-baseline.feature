@plugin @human-baseline
Feature: Human-baseline session recording
  As a person performing a GIS task for the benchmark
  I want the plugin to time my session and capture what I do
  So the baseline is recorded without manual bookkeeping

  Background:
    Given the Experiment Plugin is loaded
    And the pilot task suite is available

  Scenario: Starting a session records the task's provenance
    Given the Experiment Plugin is loaded with the pilot suite
    When I start a session for task "prep-axis-order-001"
    Then the session directory sits under the task's baselines folder
    And the event log opens with a session_start event
    And the start event pins the task file and fixture SHA-256 values
    And the UTC start time is recorded

  Scenario: Notes are appended to the event log
    Given a session is active
    When I log the note "re-read the prompt"
    Then the event log contains a "note" event carrying that message
    And the reply reports that the session holds two events

  Scenario: Ending a session writes the human-reference record
    Given a session is active with two logged events
    When I end the session
    Then human-reference-record.json exists in the session directory
    And the record's step count excludes the start and end markers
    And the record hashes every output file the participant left behind

  Scenario: A finished session is closed for good
    Given a session is active
    When I end the session
    Then the plugin reports no active session

  Scenario: Only one session may run at a time
    Given a session is active
    When I start a session for task "prep-axis-order-001"
    Then the start is refused because a session is already running

  Scenario: Starting a session for a task that does not exist fails readably
    When I start a session for task "no-such-task"
    Then the plugin explains that the session cannot be started

  Scenario: Abandoning a session keeps the evidence but promotes nothing
    Given a session is active with two logged events
    When I abandon the session
    Then the event log records that the session was abandoned
    And a session-abandoned marker exists in the session directory
    And no human-reference-record.json is written
    And the task manifest's human_baseline status stays "pending"

  Scenario: Asking for a note with no session running is harmless
    When I log the note "anything"
    Then the plugin answers "no active session"

  Scenario: Ending a session that was never started is harmless
    When I end the session
    Then the plugin answers "no active session"

  Scenario: Abandoning a session that was never started is harmless
    When I abandon the session
    Then the plugin answers "no active session"

  Scenario: Two sessions started in the same second keep separate evidence
    When I start two sessions for task "prep-axis-order-001" in the same second
    Then each session has its own directory and its own event log
