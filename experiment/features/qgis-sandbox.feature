@cli @qgis
Feature: The PyQGIS sandbox gate
  Arm B generates PyQGIS code, so the study needs a way to run that code in a
  known interpreter. The sandbox gate reports whether PyQGIS is importable and
  runs a script in a scrubbed subprocess. Both commands refuse loudly rather
  than pretending: an unavailable PyQGIS is an exit code, not a warning, and a
  script's own exit code propagates unchanged.

  Scenario: A sandbox check reports the interpreter it found
    When I ask the sandbox whether PyQGIS is available
    Then the sandbox reports a definite verdict
    And the command exits with the verdict's code

  Scenario: A harness with no PyQGIS is told how to get one
    Given a harness that cannot import PyQGIS
    When I ask the sandbox whether PyQGIS is available
    Then the command fails
    And the output names the sandbox environment to install

  Scenario: A script is refused when the file is not there
    Given a sandbox script path that does not exist
    When I run that script in the sandbox
    Then the command fails
    And the output says the script is missing

  Scenario: A scrubbed run reports the script's own output
    Given a working PyQGIS harness
    And a sandbox script that prints "hello-sandbox"
    When I run that script in the sandbox
    Then the command exits successfully
    And the output contains "hello-sandbox"

  Scenario: A failing script keeps its own exit code
    Given a working PyQGIS harness
    And a sandbox script that exits with code 7
    When I run that script in the sandbox
    Then the sandbox exits with code 7
    And the output shows the script's error output

  Scenario: A script that never finishes is stopped
    Given a working PyQGIS harness
    And a sandbox script that never finishes
    When I run that script in the sandbox with a one second timeout
    Then the sandbox exits with code 4
    And the output says the script timed out
