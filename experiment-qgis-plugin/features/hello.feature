@plugin
Feature: Plugin availability in QGIS
  The plugin offers a greeting and makes session controls available to the host.

  Background:
    Given the Experiment Plugin is loaded

  Rule: The greeting responds to the name supplied

    Scenario: A participant receives a personal greeting
      Given the plugin is ready to receive requests
      When I request a greeting for "world"
      Then the greeting says "Hello, world!"

    @edge_case
    Scenario: An empty name still produces a greeting
      Given the plugin is ready to receive requests
      When I request a greeting without a name
      Then the greeting says "Hello, !"

  Rule: The host can discover the plugin's supported capabilities

    Scenario: All documented actions are available
      Given the plugin is ready to receive requests
      When the host discovers the plugin's actions
      Then exactly the documented actions are available

    Scenario: The host can open the session panel
      Given the plugin is ready to receive requests
      When the host discovers the plugin's panels
      Then the session panel is available

    @edge_case
    Scenario: An unsupported action is rejected
      Given the plugin is ready to receive requests
      When the host requests an unsupported action
      Then the request is rejected

  Rule: Unloading stops the plugin

    Scenario: The plugin shuts down cleanly
      Given the plugin is ready to receive requests
      When the plugin unloads
      Then the plugin reports itself as stopped
