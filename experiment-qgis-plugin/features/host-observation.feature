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

  Scenario: The legacy project-read hook is disconnected at the end
    Given a QGIS host with a project that only offers the "projectRead" signal
    And a session is active
    When the project is read using its legacy signal
    And I end the session
    And I capture the terminal evidence
    And the project is read using its legacy signal
    Then the terminal evidence remains unchanged
    And the legacy project-read listener is disconnected

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

  Scenario: Partially wired project hooks are disconnected at the end
    Given a QGIS host whose project hooks fail partway through wiring
    And a session is active
    When a layer is added and the canvas scale changes
    And I end the session
    And I capture the terminal evidence
    And a layer is added and the canvas scale changes
    Then the start message reports the project hook failure
    And the completed event log keeps only the earlier project and canvas changes
    And the terminal evidence remains unchanged
    And all host hooks are disconnected

  Scenario: Partially wired canvas hooks are disconnected on abandonment
    Given a QGIS host whose canvas hooks fail after connecting
    And a session is active
    When a layer is added and the canvas scale changes
    And I abandon the session
    And I capture the terminal evidence
    And a layer is added and the canvas scale changes
    Then the start message reports the partial canvas hook failure
    And the abandoned event log keeps only the earlier project and canvas changes
    And the terminal evidence remains unchanged
    And all host hooks are disconnected

  Scenario: Host observations remain in the completed session evidence
    Given a QGIS host with a project and a map canvas open
    And a session is active
    When two layers are added, one is removed, the project CRS changes and the project is read
    And the canvas extent changes and the canvas scale changes
    And I end the session
    Then the completed event log keeps the host observations in order
    And human-reference-record.json exists in the session directory

  Scenario: A canvas destroyed during a take is safely released at the end
    Given a QGIS host with a removable map canvas
    And a session is active
    When the map canvas is destroyed
    And I end the session
    And the project CRS changes
    Then human-reference-record.json exists in the session directory
    And the finished event log contains only the session markers
    And the surviving project hooks are disconnected

  Scenario: A disconnection failure is reported without changing terminal evidence
    Given a QGIS host with a project and a map canvas open
    And a canvas signal refuses to disconnect
    And a session is active
    When I end the session despite the disconnection failure
    And I capture the terminal evidence
    And a layer is added and the canvas scale changes
    Then the disconnection failure is reported
    And the terminal evidence remains unchanged
    And the remaining host hooks were disconnected

  Scenario: A failed abandonment does not leave a terminal log open
    Given a QGIS host with a project and a map canvas open
    And a session is active
    And the abandonment marker cannot be written
    When I try to abandon the session
    And I capture the terminal evidence
    And a layer is added and the canvas scale changes
    Then the abandonment failure is reported
    And the terminal evidence remains unchanged
    And no human-reference-record.json is written
    And all host hooks are disconnected
    And the plugin reports no active session

  Scenario: A failed end attempt keeps the active session observing
    Given a QGIS host with a project and a map canvas open
    And a session is active
    And the task fixture is unavailable
    When I try to end the session
    And a layer is added and the canvas scale changes
    Then the end failure is reported
    And the event log records the connected project and canvas changes
    And no human-reference-record.json is written
    And the session is still running

  Scenario: Host activity cannot change a finished session
    Given a QGIS host with a project and a map canvas open
    And a session is active
    When I end the session
    And a layer is added and the canvas scale changes
    Then the finished event log contains only the session markers

  Scenario: Host activity cannot change an abandoned session
    Given a QGIS host with a project and a map canvas open
    And a session is active
    When I abandon the session
    And a layer is added and the canvas scale changes
    Then the abandoned event log contains only the session markers
    And no human-reference-record.json is written

  Scenario Outline: Queued host changes cannot alter a terminal take
    Given a QGIS host with a project and a map canvas open
    And a session is active
    When project and canvas changes are queued
    And I <action> the session
    And I capture the terminal evidence
    And the queued changes are delivered
    Then the terminal evidence remains unchanged
    And all host hooks are disconnected

    Examples:
      | action  |
      | end     |
      | abandon |

  Scenario: Ending a session leaves other host listeners connected
    Given a QGIS host with a project and a map canvas open
    And another component listens to project and canvas changes
    And a session is active
    When I end the session
    And a layer is added and the canvas scale changes
    Then the other component still receives both changes
    And no session callbacks remain connected

  Scenario Outline: A new session observes host activity without changing a previous take
    Given a QGIS host with a project and a map canvas open
    And a session is active
    When I <action> the session
    And I capture the terminal evidence
    And I start a new session
    And every project and canvas signal fires
    Then the terminal evidence remains unchanged
    And the new session alone records every host change

    Examples:
      | action  |
      | end     |
      | abandon |

  Scenario: The panel reports a host hook failure while recording continues
    Given a QGIS host with a failing project hook and the session panel
    When I start a session from the panel for task "demo-task-001"
    And a layer is added and the canvas scale changes
    Then the panel reports the project hook failure
    And the panel's session records the connected host changes
    And the session is still running

  Scenario: Stopping from the panel closes the host observations
    Given a QGIS host with a project, a map canvas and the session panel
    When I start a session from the panel for task "demo-task-001"
    And I stop the session from the panel
    And I capture the panel's terminal evidence
    And a layer is added and the canvas scale changes
    Then human-reference-record.json exists for the panel's session
    And the panel's terminal evidence remains unchanged
    And all host hooks are disconnected

  Scenario: The panel reports a failed disconnection while keeping the take closed
    Given a QGIS host with a project, a map canvas and the session panel
    And a canvas signal refuses to disconnect
    When I start a session from the panel for task "demo-task-001"
    And I stop the session from the panel
    And I capture the panel's terminal evidence
    And a layer is added and the canvas scale changes
    Then the panel reports the disconnection failure
    And the panel's terminal evidence remains unchanged
    And the remaining host hooks were disconnected

  Scenario: Restarting from the panel observes only the new take
    Given a QGIS host with a project, a map canvas and the session panel
    When I start a session from the panel for task "demo-task-001"
    And I restart the session from the panel and confirm
    And a layer is added and the canvas scale changes
    Then the previous take is marked abandoned and has no record
    And the previous take's evidence remains unchanged
    And the restarted session records the host changes

  Scenario: A restarted take reports its own host hook failure
    Given a QGIS host with a failing project hook and the session panel
    When I start a session from the panel for task "demo-task-001"
    And I restart the session from the panel and confirm
    And a layer is added and the canvas scale changes
    Then the panel reports the project hook failure
    And the previous take's evidence remains unchanged
    And the restarted session records the host changes

  Scenario: Cancelling a panel restart keeps host observations active
    Given a QGIS host with a project, a map canvas and the session panel
    When I start a session from the panel for task "demo-task-001"
    And I restart the session from the panel and cancel
    And a layer is added and the canvas scale changes
    Then the same session is still running
    And the original session records the host changes

  Scenario: A failed abandonment prevents a panel restart
    Given a QGIS host with a project, a map canvas and the session panel
    And the abandonment marker cannot be written
    When I start a session from the panel for task "demo-task-001"
    And I restart the session from the panel and confirm
    And a layer is added and the canvas scale changes
    Then the panel reports the abandonment failure
    And the previous take's evidence remains unchanged
    And the incomplete take has no record and no new session was started
    And all host hooks are disconnected

  Scenario Outline: Unloading leaves a terminal take's evidence unchanged
    Given a QGIS host with a project and a map canvas open
    And a session is active
    When I <action> the session
    And I capture the terminal evidence
    And the plugin unloads
    And a layer is added and the canvas scale changes
    Then the terminal evidence remains unchanged
    And all host hooks are disconnected

    Examples:
      | action  |
      | end     |
      | abandon |

  Scenario: Unloading also disconnects partially wired hooks
    Given a QGIS host whose project hooks fail partway through wiring
    And a session is active
    When the plugin unloads
    And I capture the terminal evidence
    And a layer is added and the canvas scale changes
    Then the start message reports the project hook failure
    And the unloaded take is marked abandoned without a record
    And the terminal evidence remains unchanged
    And all host hooks are disconnected

  Scenario: Unloading releases hooks even if the abandonment marker cannot be written
    Given a QGIS host with a project and a map canvas open
    And a session is active
    And the abandonment marker cannot be written
    When I try to unload the plugin
    And I capture the terminal evidence
    And a layer is added and the canvas scale changes
    Then the unload reports the abandonment failure
    And the terminal evidence remains unchanged
    And no human-reference-record.json is written
    And all host hooks are disconnected
    And the plugin reports no active session

  Scenario: Unloading reports both abandonment and disconnection failures
    Given a QGIS host with a project and a map canvas open
    And a canvas signal refuses to disconnect
    And a session is active
    And the abandonment marker cannot be written
    When I try to unload the plugin
    And I capture the terminal evidence
    And a layer is added and the canvas scale changes
    Then the unload reports both failures
    And the terminal evidence remains unchanged
    And no human-reference-record.json is written
    And the remaining host hooks were disconnected
    And the plugin reports no active session

  Scenario: Reloading the plugin abandons an unfinished take before recording another
    Given a QGIS host with a project and a map canvas open
    And a session is active
    When the plugin is unloaded and reloaded
    And I start another session and trigger project and canvas changes
    Then the unloaded take is marked abandoned without a record
    And the unloaded take's evidence remains unchanged
    And only the new session records those host changes

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

  Scenario: A processing history hook failure is reported without stopping the recording
    Given a QGIS host whose processing history cannot be wired
    When I start a session for task "prep-axis-order-001"
    Then the start message reports the processing hook failure
    And the session is still running

  Scenario: Processing executions survive a raw host observation flood
    Given a QGIS host with project, canvas, and processing history open
    And a session is active
    When the project reports 2005 CRS changes
    And the processing algorithm "native:buffer" executes
    And I end the session
    Then the record preserves one observed processing execution for "native:buffer"

  Scenario Outline: Processing executions after a terminal take cannot alter its evidence
    Given a QGIS host with project, canvas, and processing history open
    And a session is active
    When the processing algorithm "native:buffer" executes
    And I <action> the session
    And I capture the terminal evidence
    And the processing algorithm "native:clip" executes
    Then the terminal evidence remains unchanged
    And the processing history listener is disconnected

    Examples:
      | action  |
      | end     |
      | abandon |

  Scenario Outline: Queued processing executions cannot alter a terminal take
    Given a QGIS host with project, canvas, and processing history open
    And a session is active
    When a processing execution for "native:clip" is queued
    And I <action> the session
    And I capture the terminal evidence
    And the queued changes are delivered
    Then the terminal evidence remains unchanged
    And the processing history listener is disconnected

    Examples:
      | action  |
      | end     |
      | abandon |

  Scenario Outline: A new session isolates processing executions from a previous take
    Given a QGIS host with project, canvas, and processing history open
    And a session is active
    When the processing algorithm "native:buffer" executes
    And I <action> the session
    And I capture the terminal evidence
    And I start a new session
    And the processing algorithm "native:clip" executes
    Then the terminal evidence remains unchanged
    And the new session alone records processing execution "native:clip"

    Examples:
      | action  |
      | end     |
      | abandon |

  Scenario: Unloading and reloading isolates processing history across takes
    Given a QGIS host with project, canvas, and processing history open
    And a session is active
    When the plugin is unloaded and reloaded
    And I start another session and execute processing algorithm "native:clip"
    Then the unloaded take is marked abandoned without a record
    And the unloaded take's evidence remains unchanged
    And only the reloaded session records processing execution "native:clip"

  Scenario: Ending a session leaves other processing history listeners connected
    Given a QGIS host with project, canvas, and processing history open
    And another component listens to processing history changes
    And a session is active
    When I end the session
    And the processing algorithm "native:buffer" executes
    Then the other component still receives the processing history entry
    And no session processing listener remains connected
