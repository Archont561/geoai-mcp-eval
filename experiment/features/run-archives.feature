@archive
Feature: Integrity of experiment run archives
  Researchers must be able to trust the evidence saved for each trial.

  Rule: A completed run can be archived and inspected later

    Scenario: A researcher archives and inspects a completed run
      Given a completed scripted experiment run
      When the researcher packs and inspects the run archive
      Then the archive identifies the run and its recorded trial

  Rule: Incomplete harvests remain available for inspection and reporting

    @edge_case
    Scenario: Incomplete evidence is reported while the archive and summary are preserved
      Given a harvest containing only one completed trial
      When the researcher packs the incomplete harvest with strict completeness
      Then packing reports incomplete evidence but saves the archive and summary
      When the researcher allows incomplete evidence
      Then the incomplete archive remains inspectable

    Scenario: A workflow summary can be produced through the task runner
      Given harvest environment details for a workflow run
      When the researcher produces the workflow summary through the task runner
      Then the summary identifies the workflow run

    Scenario: Cleanup retains the requested archive using the hosting run identifier
      Given a hosted run with a numeric identifier and a descriptive run name
      When the researcher cleans up intermediate artifacts
      Then cleanup uses the hosting run identifier and keeps the requested archive

  Rule: Hosted archives summarize generated-code evidence

    Scenario: Archive notices distinguish runnable code from an incomplete model response
      Given hosted code-generation trials with and without runnable code
      When the researcher archives the hosted trials
      Then the hosted notices summarize the model and code-generation evidence

  Rule: Hosted cleanup removes intermediates but retains the final archive

    Scenario: Intermediate evidence is removed after a run is archived
      Given hosted trial artifacts and a final run archive
      When the researcher removes intermediate artifacts
      Then only the intermediate artifacts are deleted

  Rule: Parallel trial fragments combine into a verified run

    Scenario: A researcher combines two trial fragments
      Given run preparation and two separate trial fragments
      When the researcher combines the fragments into an archive
      Then the combined run retains its preparation details and both trials
      And the archive verifies and both trial results remain available

  Rule: Trial evidence is loaded on demand and absent evidence is reported honestly

    Scenario: A researcher opens an archive and reads its trial evidence
      Given a complete archived trial with provenance and a summary
      When the researcher reads the archived trial evidence
      Then the archive preserves its records and verifies all evidence

    @edge_case
    Scenario: An archived trial has no optional evidence
      Given an archived trial without optional evidence
      When the researcher opens the trial without evidence
      Then the archive reports absent evidence and rejects unknown trial requests

  Rule: Altered trial evidence is detected when it is read or verified

    @edge_case
    Scenario: A saved trial result has been altered
      Given an archive with one recorded trial
      And the saved trial result has been altered
      When the researcher opens the altered archive
      Then the unchanged transcript remains readable
      And reading the altered result reports an integrity failure
      And verifying the whole archive reports an integrity failure

    @edge_case
    Scenario: Required trial evidence is missing during packing
      Given a trial with recorded evidence
      When the researcher packs the run without that evidence
      Then packing reports that required evidence is missing
