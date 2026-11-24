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
    And the project observations keep their source and order

  Scenario: A project that only offers the QGIS 3 signal is still observed
    Given a QGIS host with a project that only offers the "projectRead" signal
    And a session is active
    When the project is read using its legacy signal
    Then the event log records the project file path

  Scenario: A project with no read signal is reported but otherwise observed
    Given a QGIS host with a project that offers no read signal
    And a session is active
    When a layer is added and the project CRS changes
    Then the start message reports the missing project read hook
    And the event log records both project changes

  Scenario: Map canvas movement is recorded
    Given a QGIS host with a map canvas and a running session
    When the canvas extent changes and the canvas scale changes
    Then the event log records the extent and the scale

  Scenario: A project hook fails partway through wiring
    Given a QGIS host whose project hooks fail partway through wiring
    And a session is active
    When a layer is added and the canvas scale changes
    Then the start message reports the project hook failure
    And the event log records the connected project and canvas changes

  Scenario: Host observations remain in the completed session evidence
    Given a QGIS host with a project and a map canvas open
    And a session is active
    When two layers are added, one is removed, the project CRS changes and the project is read
    And the canvas extent changes and the canvas scale changes
    And I end the session
    Then the completed event log keeps the host observations in order
    And human-reference-record.json exists in the session directory

  Scenario: A flood of host observations is capped
    Given a QGIS host with a project open
    And a session is active
    When the project reports 2005 CRS changes
    Then the event log contains 2000 entries
    And the session is still running

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
