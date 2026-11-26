@cli @qgis @qgis_sandbox
Feature: Isolated GIS script execution gate
  As a GIS researcher executing generated geospatial scripts
  I want an availability gate and an isolated script runner
  So unavailable GIS runtimes, missing scripts, script failures, and hangs are reported cleanly

  Rule: The availability check reports clearly whether the GIS runtime can be loaded

    @smoke
    Scenario: Availability check returns a definite verdict on the current machine
      When I check whether the GIS script runtime is available
      Then the gate reports a definite availability verdict
      And the exit status matches the availability verdict

    Scenario: Available GIS runtime reports its desktop and geospatial library versions
      Given an environment with a working GIS runtime
      When I check whether the GIS script runtime is available
      Then the action succeeds
      And the report lists the QGIS and geospatial library versions

    @edge_case
    Scenario: Unavailable GIS runtime explains how to install the sandbox environment
      Given an environment without the GIS runtime
      When I check whether the GIS script runtime is available
      Then the action exits with status 3
      And the explanation names the sandbox environment to install

  Rule: Version reports describe the available GIS environment

    @edge_case
    Scenario: A missing GIS host has no version report
      Given a machine without the GIS host libraries
      When the researcher requests the GIS environment versions
      Then no GIS version report is available

    Scenario: A current GIS host reports its geospatial library versions
      Given a GIS host reporting versions for its desktop and geospatial libraries
      When the researcher requests the GIS environment versions
      Then the report includes the desktop and all available library versions

    Scenario: A legacy GIS host reports available versions and marks missing libraries
      Given a legacy GIS host without some geospatial libraries
      When the researcher requests the GIS environment versions
      Then the report includes the legacy desktop and projection versions
      And unavailable library versions are marked unknown

  Rule: Running a GIS script isolates outputs and propagates failures accurately

    @edge_case
    Scenario: Missing script file is refused without creating an output folder
      Given an environment without the GIS runtime
      And a non-existent script path with a long directory name
      When I execute that script in the isolated GIS runner
      Then the action exits with status 2
      And the explanation states that the script is missing
      And no isolated artifacts folder is created

    @edge_case
    Scenario: Running a script without the GIS runtime fails with setup guidance
      Given an environment without the GIS runtime
      And a GIS script that prints "hello-sandbox"
      When I execute that script in the isolated GIS runner
      Then the action exits with status 3
      And the explanation names the sandbox environment to install
      And the isolated artifacts folder exists

    Scenario: Valid script runs inside the isolated artifacts folder and prints its output
      Given an environment with a working GIS runtime
      And a GIS script that prints "hello-sandbox"
      When I execute that script in the isolated GIS runner
      Then the action succeeds
      And the researcher sees "hello-sandbox"
      And the script executes inside the isolated artifacts folder

    @edge_case
    Scenario: Failing script preserves its own non-zero exit status and error message
      Given an environment with a working GIS runtime
      And a GIS script that exits with status 7
      When I execute that script in the isolated GIS runner
      Then the action exits with status 7
      And the output shows the script error message

    @edge_case
    Scenario: Runaway script is stopped when its time limit expires
      Given an environment with a working GIS runtime
      And a GIS script that never finishes
      When I execute that script in the isolated GIS runner with a one-second limit
      Then the action exits with status 4
      And the explanation states that the script timed out
