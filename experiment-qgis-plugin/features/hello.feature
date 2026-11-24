@plugin @action-surface
Feature: Greeting the user from inside QGIS
  The plugin's actions are its public surface: QGIS menus and the session
  panel reach the plugin only through them, and a host that asks for an action
  the plugin never declared must fail loudly rather than silently succeed.

  Background:
    Given the Experiment Plugin is loaded

  Scenario: An action greets a person by name
    When I call the "hello" action with name "world"
    Then the action replies "Hello, world!"

  Scenario: A missing name still produces a greeting
    When I call the "hello" action with no name
    Then the action replies "Hello, !"

  Scenario: The plugin exposes exactly its documented actions
    Then the plugin offers the actions "abandon_session, end_session, hello, log_manual_action, log_note, review_session, show_timer, start_session"

  Scenario: Asking for an action the plugin never declared is an error
    When I call the undeclared action "missing"
    Then the call fails with a lookup error

  Scenario: The session panel is registered as a surface the host can open
    Then the plugin registers a "session_panel_dialog" surface

  Scenario: The plugin shuts down cleanly
    When the plugin unloads
    Then the plugin reports itself as stopped
