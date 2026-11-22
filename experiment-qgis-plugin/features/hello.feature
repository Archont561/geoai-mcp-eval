Feature: Hello action
  As a QGIS user
  I want to greet someone through the plugin
  So I can verify the plugin responds correctly

  Scenario: Hello returns a greeting for a name
    Given the Experiment Plugin is loaded
    When I call the "hello" action with name "world"
    Then the result is "Hello, world!"

  Scenario: Hello returns a greeting for an empty name
    Given the Experiment Plugin is loaded
    When I call the "hello" action with name ""
    Then the result is "Hello, !"

  Scenario: Hello returns a greeting for a long name
    Given the Experiment Plugin is loaded
    When I call the "hello" action with name "QGIS"
    Then the result is "Hello, QGIS!"
