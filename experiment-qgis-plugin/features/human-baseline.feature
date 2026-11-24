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
    Given a session is active with raw host observations and a note
    When I end the session
    Then human-reference-record.json exists in the session directory
    And the record leaves study steps and tools pending review
    And the record retains raw observations separately from study metrics
    And the record hashes every output file the participant left behind

  Scenario: Ending a session with no evidence leaves study metrics unknown
    Given a session is active
    When I end the session
    Then human-reference-record.json exists in the session directory
    And the record leaves study steps and tools pending review
    And the record reports missing processing history and pending manual review

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
    Given a session is active with raw host observations and a note
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

  Scenario: Processing executions are captured as partial evidence pending manual review
    Given a QGIS host with project, canvas, and processing history open
    And a session is active
    When a layer is added, three processing algorithms run, and a note is logged
    And I end the session
    Then human-reference-record.json exists in the session directory
    And the record leaves study steps and tools pending review
    And the record preserves the observed processing executions and their algorithm ids
    And the record excludes raw host observations and notes from processing metrics

  Scenario: Zero processing executions without manual review still leaves study metrics unknown
    Given a QGIS host with project, canvas, and processing history open
    And a session is active
    When a layer is added and the canvas scale changes
    And I end the session
    Then the record leaves study steps and tools pending review
    And the record notes zero observed processing executions while manual review is pending

  Scenario: Non-processing entries are ignored and malformed processing entries block verification
    Given a QGIS host with project, canvas, and processing history open
    And a session is active
    When a non-processing history entry and a malformed processing entry arrive
    And I end the session with manual review completed
    Then the record leaves study steps and tools pending review
    And the record flags incomplete processing history without inventing an algorithm id

  Scenario: Logging a manual action group with no session running is harmless
    When I log the manual action group "styled Jenks classes"
    Then the plugin answers "no active session"

  Scenario: Logging a blank manual action group is refused
    Given a session is active
    When I log the manual action group "   "
    Then the plugin explains that a manual action group description is required

  Scenario: Manual action groups without completed review remain partial evidence
    Given a QGIS host with project, canvas, and processing history open
    And a session is active
    When I log the manual action group "styled Jenks classes"
    And I end the session
    Then the record leaves study steps and tools pending review
    And the record retains the manual action group without attributing a tool

  Scenario: Reviewed processing executions and manual action groups populate study steps and tools
    Given a QGIS host with project, canvas, and processing history open
    And a session is active
    When a layer is added, three processing algorithms run, and a note is logged
    And I log the manual action group "styled Jenks classes"
    And I end the session with manual review completed
    Then the record verifies 4 study steps and the observed processing tools
    And the end summary reports reviewed steps and tools without raw sources

  Scenario: A reviewed pure-manual workflow verifies an empty tools list honestly
    Given a QGIS host with project, canvas, and processing history open
    And a session is active
    When I log the manual action group "selected POL polygon"
    And I log the manual action group "exported GeoJSON"
    And I end the session with manual review completed
    Then the record verifies 2 study steps and an explicitly empty tools list

  Scenario: Manual review cannot verify study metrics when processing history was unavailable
    Given a session is active
    When I log the manual action group "exported GeoJSON" using tool "qgis:save-features-as"
    And I end the session with manual review completed
    Then the record leaves study steps and tools pending review
    And the record reports missing processing history while retaining the manual action group

  Scenario: Ending a session records QGIS 4 host software versions
    Given a QGIS 4 host reporting versions for QGIS, GDAL, GEOS, and PROJ
    And a session is active
    When I end the session
    Then the record captures the QGIS, GDAL, GEOS, and PROJ versions

  Scenario: Ending a session without QGIS leaves unconfigured software versions unknown
    Given no QGIS host on this machine
    And a session is active
    When I end the session
    Then the record leaves host software versions as null

  Scenario: Starting a session from a nested working directory finds the task suite
    Given no EXPERIMENT_TASK_DIR is configured and cwd is nested inside a task checkout
    When I start a session using the default task directory for task "demo-task-001"
    Then the started session belongs to that checkout's baselines folder

  Scenario: Starting a session when the configured task directory is missing explains how to fix it
    When I start a session for task "demo-task-001" with a missing task directory
    Then the plugin explains that the task directory does not exist and mentions EXPERIMENT_TASK_DIR

  Scenario: Ending a session hashes nested multi-file outputs recursively
    Given a session is active
    When the participant saves top-level and nested output files into the session directory
    And I end the session
    Then the record hashes both top-level and nested output files with relative POSIX paths
