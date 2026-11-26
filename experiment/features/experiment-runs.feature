@runs
Feature: Model-driven experiment cells
  Study runs compare typed GIS tools with generated code under controlled conditions.

  Rule: Model instructions remain consistent with the ratified study

    Scenario: The study uses the ratified instructions for each model approach
      Given the study's model instructions
      When the researcher checks the instruction versions
      Then the code-generation instructions match the ratified version
      And the typed-tool instructions require use of the provided tools

  Rule: Pilot runs identify the model used for reproducibility

    Scenario: A missing local model is downloaded before its identity is resolved
      Given a pilot model that is not available locally
      When the researcher prepares the model for a pilot run
      Then the model is downloaded and its identity is resolved

    @edge_case
    Scenario: A failed model download stops pilot preparation
      Given a pilot model whose download fails
      When the researcher prepares the model for a pilot run
      Then pilot preparation reports the download failure

  Rule: Typed-tool runs preserve their results and manage the tool session

    Scenario: A model uses a GIS tool before giving its result
      Given a model response requesting geographic feature information
      When the researcher runs a typed-tool experiment cell
      Then the requested GIS operation is performed in one tool session
      And the model's final geographic result is saved

    Scenario: A typed-tool cell records and grades a geographic result
      Given a model requests a geographic tool and then returns a result
      When the researcher runs a typed-tool cell end to end
      Then the result passes grading and the tool use is recorded

    @edge_case
    Scenario: An unavailable tool is recorded without losing the model's final answer
      Given a model requests an unavailable geographic tool before giving its result
      When the researcher runs a typed-tool experiment cell with that response
      Then the cell completes and its transcript records the unavailable tool

  Rule: Typed geographic tools stay available throughout a model session

    Scenario: Multiple geographic operations share one tool session
      Given a researcher opens a geographic tool session
      When the researcher repeats a natural-breaks calculation in that session
      Then both calculations return the same classification
      And the advertised geographic tools are available

    @edge_case
    Scenario: An unknown geographic operation is reported
      Given a geographic operation that is not advertised
      When the researcher requests that operation
      Then the tool service identifies the unknown operation

  Rule: Successful model replies can be reused for identical code-generation cells

    Scenario: A repeated code-generation cell reuses the model reply
      Given a model supplies code for a geographic result
      When the researcher runs the same code-generation cell twice
      Then the generated code runs against the task fixture
      And the result is saved
      And the second cell reuses the first model response

    Scenario: Changing or omitting model identity prevents unsafe reuse
      Given a model response and a shared response cache
      When the researcher repeats cells with changed, absent, and bypassed model identities
      Then reuse occurs only for the matching pinned identity

    @edge_case
    Scenario: A failed model response is not stored for reuse
      Given a model service that fails the response request
      When the researcher runs a cached model cell
      Then the cell fails and the response cache stays empty

  Rule: A failing driver is recorded as a failed cell

    @edge_case
    Scenario: A driver fails unexpectedly
      Given a cell whose driver fails unexpectedly
      When the researcher executes that cell
      Then the cell records a failed status and failed grading

  Rule: Scripted runs explicitly report unavailable model usage

    Scenario: A scripted run records its results without claiming token use
      Given a scripted boundary-relation run
      When the researcher completes that scripted run
      Then the run manifest and transcript report unavailable token usage

  Rule: Generated code must be identifiable and run in isolation

    Scenario: Generated code sees only its input and produces a graded result
      Given the model supplies executable code that inspects its input workspace
      When the researcher runs a code-generation cell end to end
      Then the result passes grading and the input is not left in the cell directory

    Scenario Outline: Supported code presentation styles produce a result
      Given the model supplies executable code in the <style> presentation style
      When the researcher runs a code-generation cell end to end
      Then the generated result passes grading

      Examples:
        | style      |
        | short name |
        | unlabelled |

    @edge_case
    Scenario Outline: Responses without executable code do not produce a result
      Given the model supplies <response> instead of executable code
      When the researcher runs a code-generation cell end to end
      Then the cell fails grading without saving a result
      And the transcript explains that executable code was missing

      Examples:
        | response          |
        | a plain apology   |
        | a formatted result |

    Scenario: A generated script receives its own temporary workspace
      Given a geographic input for a generated script
      When the researcher runs that script in isolation
      Then the script sees the input and its own scratch file
      And the temporary workspace is removed without changing the source

    Scenario: Geographic libraries run cleanly in the isolated workspace
      Given a geographic input for a generated script
      When the researcher runs a geographic-library script in isolation
      Then the geographic script completes without diagnostics

  Rule: Token budgets apply across all model responses in a cell

    Scenario: A cell within its budget records the total model usage
      Given a model requests a geographic tool and then returns a result
      And the cell has enough tokens for both responses
      When the researcher runs the cell with its budget
      Then the cell completes and records the combined token usage

    @edge_case
    Scenario: Exceeding the budget stops the cell before the requested tool runs
      Given a model requests a geographic tool and then returns a result
      And the first response exceeds the cell's token budget
      When the researcher runs the cell with its budget
      Then the cell is stopped for exceeding its budget
      And the requested geographic tool is not executed
