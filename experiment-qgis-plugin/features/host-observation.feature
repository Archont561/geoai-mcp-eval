@plugin @host-observation
Feature: Observing the QGIS host
  While a session records, the plugin watches the host — layers, the project,
  the map canvas — and appends what changed to the event log. A hook that
  cannot be wired must be reported without stopping the recording.

  Background:
    Given the Experiment Plugin is loaded

  Scenario: Layer and project changes are recorded
    Given a QGIS host with a project open
    And a session is active
    When two layers are added, one is removed, the project CRS changes and the project is read
    Then the event log records two layers added
    And the event log records one layer removed
    And the event log records the project CRS
    And the event log records the project file path

  Scenario: A project that only offers the QGIS 3 signal is still observed
    Given a QGIS host with a project that only offers the "projectRead" signal
    And a session is active
    Then the project read hook is wired

  Scenario: A project with no read signal is reported but otherwise observed
    Given a QGIS host with a project that offers no read signal
    And a session is active
    Then the start message reports the missing project read hook
    And the layer and CRS hooks are still wired

  Scenario: Map canvas movement is recorded
    Given a QGIS host with a map canvas and a running session
    When the canvas extent changes and the canvas scale changes
    Then the event log records the extent and the scale

  Scenario: A host with no QGIS running records without hooks
    Given no QGIS host on this machine
    When I start a session for task "prep-axis-order-001"
    Then the start message says no host hooks were connected

  Scenario: A host with no reason to fail reports every hook it wired
    Given a QGIS host with a project and a map canvas open
    When I start a session for task "prep-axis-order-001"
    Then the start message lists the wired host hooks
    And the start message offers no hook failures

  Scenario: A canvas that cannot be wired is reported without stopping the recording
    Given a QGIS host whose map canvas cannot be wired
    When I start a session for task "prep-axis-order-001"
    Then the start message reports the canvas hook failure
    And the session is still running
