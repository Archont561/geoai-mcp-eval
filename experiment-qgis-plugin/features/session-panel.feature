@plugin @session-panel
Feature: The session panel
  The panel is what a participant actually touches: it starts, restarts and
  stops the recording, shows the clock and the live event log, and exports the
  log for review. Closing it must never disturb a recording.

  Background:
    Given the Experiment Plugin is loaded

  Scenario: Asking for the panel with nothing running says to start a session first
    When I ask the plugin to show the session panel
    Then the plugin answers "no active session — start one first"

  Scenario: A host without a GUI cannot open the panel
    Given a session is active
    When I ask the plugin to show the session panel
    Then the plugin explains that the panel needs a GUI host

  Scenario: The panel opens idle and offers exactly the session controls
    When I open the session panel with no session
    Then the panel has a "Timer" tab and a "Logs" tab
    And the panel offers the buttons "Start, Stop, Restart"
    And only the Start button is available

  Scenario: The panel carries an already running session
    Given a session is active
    When I open the session panel
    Then the panel shows the session's task in its task field
    And the panel says the session is recording
    And the clock reads zero

  Scenario: Starting from the panel begins a real recording
    When I start a session from the panel for task "demo-task-001" as participant "P-7"
    Then the panel says the session started
    And the task field becomes read-only
    And the Stop button becomes available

  Scenario: Stopping from the panel ends the recording and writes the record
    When I start a session from the panel for task "demo-task-001"
    And I stop the session from the panel
    Then human-reference-record.json exists for the panel's session
    And the panel returns to its idle state

  Scenario: Restarting abandons the take and starts a fresh one
    When I start a session from the panel for task "demo-task-001" as participant "P-7"
    And I restart the session from the panel and confirm
    Then the previous take is marked abandoned and has no record
    And a new session is running for the same task and participant

  Scenario: A restart the participant cancels changes nothing
    When I start a session from the panel for task "demo-task-001"
    And I restart the session from the panel and cancel
    Then the same session is still running
    And the panel says the restart was cancelled

  Scenario: The clock runs while recording and freezes when stopped
    When I start a session from the panel for task "demo-task-001"
    And the panel's clock ticks
    And I stop the session from the panel
    Then the clock still shows a fixed elapsed time

  Scenario: The Logs tab renders the running session
    When I start a session from the panel for task "demo-task-001"
    Then the log view contains the session_start event
    And the log header names the task

  Scenario: Exporting writes a readable log where the participant chooses
    When I start a session from the panel for task "demo-task-001"
    And I export the log to a file
    Then the exported file is a human-readable session log containing session_start

  Scenario: Cancelling an export writes nothing
    When I start a session from the panel for task "demo-task-001"
    And I cancel the export
    Then no file is written and the panel says the export was cancelled

  Scenario: Exporting with no session says so instead of failing
    When I open the session panel with no session
    And I ask the panel to export
    Then the panel says there is no session to export

  Scenario: An unwritable export location is reported, not raised
    When I start a session from the panel for task "demo-task-001"
    And I export the log to a location that cannot be written
    Then the panel reports that the export failed

  Scenario: A host without action dispatch degrades gracefully
    When I start a session from a panel on a host without actions
    Then the panel says the host has no actions capability

  Scenario: A host whose capability check raises degrades gracefully
    When I start a session from a panel whose action dispatch is unavailable
    Then the panel reports that the actions are unavailable

  Scenario: A failing action is reported in the panel
    When I start a session from a panel whose start action raises
    Then the panel reports that the start failed

  Scenario: Asking the panel for an action it does not know says so
    When I ask the panel to dispatch the undeclared action "no_such_action"
    Then the panel answers "unknown action no_such_action"
