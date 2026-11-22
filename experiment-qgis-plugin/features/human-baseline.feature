Feature: Human-baseline session recording
  As a human performing a GIS task for the benchmark
  I want the plugin to time my session and capture my actions
  So the baseline is recorded without manual bookkeeping

  Background:
    Given the Experiment Plugin is loaded
    And the task suite is available under experiment/tasks

  Scenario: Metadata is fetched automatically at session start
    When I invoke "start_session" for "prep-axis-order-001"
    Then the session output directory is experiment/tasks/baselines/prep-axis-order-001
    And the record points at the task file and fixture SHA-256 values
    And the UTC start time is recorded

  Scenario: Behavior events are appended to the event log
    Given a session is active
    When I invoke "log_note" with message "re-read the prompt"
    Then events.jsonl contains a "note" event with my message

  Scenario: End writes the human-reference record
    Given a session is active with two logged events
    When I invoke "end_session"
    Then human-reference-record.json exists in the baseline directory
    And its steps count excludes the start and end markers
    And the record hashes every output file in the directory
    And task YAML human_baseline.status is unchanged (still pending)
