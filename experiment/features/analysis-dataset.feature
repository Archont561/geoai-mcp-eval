@analysis
Feature: Research datasets from archived runs
  Researchers need reliable tables and access to the evidence behind each trial.

  Rule: A complete archive supports analysis and inspection

    Scenario: A pilot archive supplies tables and trial evidence
      Given an archive of a completed pilot run
      When the researcher opens the archive for analysis
      Then the measurement table describes all six trials
      And the predicate table contains the expected pilot results
      And the cell summaries report successful trials
      And the assertion table describes the graded checks
      And the researcher can inspect a trial's transcript and deliverable

  Rule: Analysis rejects unknown evidence and handles incomplete runs honestly

    @edge_case
    Scenario: An unrecognised grading check cannot be classified
      Given a run with a grading check unknown to the task suite
      When the researcher requests the predicate and assertion tables
      Then both tables reject the unrecognised check

    @edge_case
    Scenario: Trial evidence cannot be opened from an in-memory run
      Given a run with a grading check unknown to the task suite
      When the researcher requests its trial evidence
      Then the request explains that an archive is required

    Scenario: An empty preparation run yields an empty summary
      Given an empty preparation run
      When the researcher requests its cell summary
      Then the summary is empty with the expected columns

  Rule: Researchers can retrieve runs safely and reuse local copies

    Scenario: The latest successful run is available for analysis
      Given a repository with a completed pilot run
      When the researcher lists and loads its latest run
      Then the run's identity and six trial measurements are available
      And the download does not expose credentials to the storage host

    Scenario: A previously downloaded run is reused
      Given a locally cached pilot run
      When the researcher loads that run again
      Then all six trial measurements are available without another download

    Scenario: A researcher requests a fresh copy
      Given a locally cached pilot run
      When the researcher refreshes that run
      Then the archive is downloaded again

    @edge_case
    Scenario: A damaged local copy is replaced
      Given a locally cached pilot run that has become damaged
      When the researcher retrieves that run
      Then a fresh archive replaces the damaged copy

    Scenario: A local archive can be analysed without a network
      Given an archive of a completed pilot run
      When the researcher opens it directly without connecting to the repository
      Then the pilot run and its six measurements are available

    Scenario: A redirected archive download keeps credentials private
      Given a repository that redirects archive downloads to a storage service
      When the researcher loads the run from the repository
      Then all six trial measurements are available
      And repository credentials are absent from the storage request

  Rule: Each pilot grading check has a distinct analysis predicate

    Scenario: The pilot suite defines a unique predicate for each grading check
      Given the published pilot task suite
      When the researcher prepares its grading predicates for analysis
      Then the four pilot grading checks map to distinct analysis predicates

  Rule: Repository problems are reported instead of producing misleading data

    @edge_case
    Scenario: Repository credentials are rejected
      Given a repository that rejects the researcher's credentials
      When the researcher lists its runs
      Then the repository access error is reported

    @edge_case
    Scenario: No successful run is available
      Given a repository without a completed successful run
      When the researcher requests the latest run
      Then the absence of a successful run is reported

    @edge_case
    Scenario: A run has no matching experiment archive
      Given a run without an experiment archive
      When the researcher retrieves its archive
      Then the missing experiment archive is reported

    @edge_case
    Scenario Outline: An archive cannot be downloaded safely
      Given a run whose archive download encounters <problem>
      When the researcher retrieves its archive
      Then the download reports <explanation>

      Examples:
        | problem                    | explanation                  |
        | a network failure          | an artifact download failure |
        | invalid archive contents   | an invalid archive           |
        | a missing download         | an unavailable download      |
        | an incomplete redirect     | an incomplete redirect       |

    @edge_case
    Scenario: Repository identity is unavailable
      Given no repository is configured for analysis
      When the researcher lists its runs
      Then the missing repository configuration is reported

    Scenario: A local checkout identifies its repository
      Given a checkout with a configured GitHub repository
      When the researcher lists its runs
      Then the configured repository is used without requiring a command-line client

    Scenario: A direct archive download uses the configured environment credentials
      Given a direct archive download with environment credentials
      When the researcher retrieves its archive
      Then the archive is saved and the credentials are sent to the repository

    Scenario: Downloaded runs have a default local cache
      Given the default analysis settings
      When the researcher prepares the run client
      Then the local cache is in the study checkout
