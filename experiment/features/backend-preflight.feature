@preflight
Feature: Model backend preflight
  Researchers need to know whether a model backend is ready before starting a run.

  Rule: Readiness requires a reachable backend, the requested model, and a test response

    @smoke
    Scenario: A reachable model responds successfully
      Given a working connection and the requested model
      When the researcher checks backend readiness
      Then the backend is ready with the model version pinned
      And one test response was requested

    @edge_case
    Scenario: The remote host cannot be reached
      Given the remote host cannot be reached
      When the researcher checks backend readiness
      Then the report identifies an unreachable remote host

    @edge_case
    Scenario: The existing tunnel is inactive
      Given the connection tunnel is inactive
      When the researcher checks backend readiness
      Then the report identifies an unavailable tunnel

    @edge_case
    Scenario: The existing tunnel connection is missing
      Given the configured tunnel connection is missing
      When the researcher checks backend readiness
      Then the report identifies an unavailable tunnel

    @edge_case
    Scenario: The requested model is absent
      Given the backend has only a different model
      When the researcher checks backend readiness
      Then the report identifies the missing model
      And no test response was requested

  Rule: A local model service is managed safely when needed

    Scenario: The local model service responds to preparation and readiness checks
      Given a local model service with a prepared model
      When the researcher checks and prepares the local service
      Then model readiness, identity, and a test response are available

    @edge_case
    Scenario: An unavailable local service can be started and stopped safely
      Given a local model service that cannot be reached
      When the researcher prepares and then stops the local service
      Then failures are reported and the owned service is stopped safely

  Rule: Hosted model responses retain tool calls and never disclose credentials

    @edge_case
    Scenario: A hosted model recovers from rate limiting and hides an invalid credential
      Given a hosted model that first limits requests and then responds
      When the researcher requests tool calls and later encounters an authentication failure
      Then tool use and response usage are preserved without exposing the credential

  Rule: Local model responses retain tool calls and classify failures

    Scenario: A local model retries temporary overload and returns a tool call
      Given a local model endpoint experiencing temporary overload
      When the researcher requests a tool call and a final answer
      Then the response retains the tool call and token usage

    @edge_case
    Scenario: Invalid requests and timeouts are reported by the local model
      Given a local model endpoint that rejects requests or times out
      When the researcher requests a local model response
      Then the failures are classified and invalid requests are not retried

  Rule: Provider-specific readiness checks distinguish outages and invalid responses

    Scenario: Local model readiness survives temporary overload
      Given a local model readiness probe with a temporary service failure
      When the researcher probes the local model through its provider
      Then the probe reports the model identity and classifies invalid requests

    @edge_case
    Scenario: Provider readiness reports connection and response failures
      Given local and hosted model providers with simulated failures
      When the researcher checks both providers
      Then their readiness failures are classified and owned resources are released

  Rule: Model service configuration resolves predictably

    Scenario: Explicit model settings override the local environment and saved profile
      Given local and hosted service profiles and a local service environment setting
      When the researcher selects a local service with explicit host and model settings
      Then the explicit settings take precedence over the environment and saved profile
      And the local environment does not change the hosted service

    Scenario: A local service has a safe default when configuration is absent
      Given no saved service configuration or local service environment setting
      When the researcher selects the default local service
      Then the default local address and model are used

    @edge_case
    Scenario Outline: Damaged or missing service configuration is reported
      Given <problem> service configuration
      When the researcher loads service configuration
      Then the configuration failure is reported

      Examples:
        | problem   |
        | missing   |
        | malformed |

    @edge_case
    Scenario: An unknown service profile names the available choice
      Given a saved model service profile
      When the researcher selects an unknown service profile
      Then the error identifies the available profile

  Rule: Hosted provider failures lead to useful readiness diagnoses

    @edge_case
    Scenario Outline: Hosted provider errors receive a matching diagnosis
      Given a hosted provider reports <failure>
      When the researcher checks the reported provider failure
      Then the readiness diagnosis identifies <diagnosis>

      Examples:
        | failure                     | diagnosis             |
        | unauthorized credentials    | a credential problem  |
        | an exceeded context window  | a token limit         |
        | an exhausted quota          | a token limit         |
        | a missing model             | a request problem     |
        | an unavailable service      | a connection problem  |

  Rule: The readiness result is communicated to the researcher

    Scenario: A ready backend is reported with its model identity
      Given the readiness check reports a pinned model is ready
      When I ask for a backend readiness report
      Then the action succeeds
      And the report shows the ready model identity

    @edge_case
    Scenario: A disconnected tunnel produces a failing readiness status
      Given the readiness check reports a disconnected tunnel
      When I ask for a backend readiness report
      Then the readiness action reports a disconnected tunnel status

  Rule: Model replies and model identities can be requested through a compatible service

    Scenario: A compatible service passes a complete readiness probe
      Given a compatible model service with a pinned model
      When the researcher probes the available model and requests a test response
      Then the probe identifies the model and its pinned version

    Scenario: A researcher gets a model reply and its version from the service
      Given a compatible model service with a pinned model
      When the researcher requests a response and model identity
      Then the service returns the response and the pinned identity

  Rule: An unavailable model identity must not be mistaken for a pinned version

    @edge_case
    Scenario Outline: A model identity cannot be retrieved
      Given a model service whose identity lookup encounters <problem>
      When the researcher requests the model identity
      Then no model version is reported

      Examples:
        | problem                      |
        | a service error              |
        | an unreadable reply          |
        | a disconnected service       |

  Rule: Temporary failures are retried, but invalid requests fail promptly

    @edge_case
    Scenario: The backend is temporarily overloaded and rate limited
      Given temporary overload followed by a rate-limited response
      When the researcher checks backend readiness
      Then the backend is ready with the model version pinned
      And the test response was requested twice

    @edge_case
    Scenario: The backend rejects the credentials
      Given the backend rejects the credentials
      When the researcher checks backend readiness
      Then the report identifies a credentials error
      And the model list was requested only once

    @edge_case
    Scenario: The requested response exceeds the model's limit
      Given the backend rejects the response as too long
      When the researcher checks backend readiness
      Then the report identifies the model's token limit
      And one test response was requested

    @edge_case
    Scenario: The backend returns no usable response
      Given the backend returns an empty test response
      When the researcher checks backend readiness
      Then the report identifies a rejected response

  Rule: Readiness checks report configuration and response failures accurately

    Scenario: A healthy connection and model can be checked independently
      Given a ready model and an available remote connection
      When the researcher checks readiness through those connections
      Then the model is ready and a test response was requested

    @edge_case
    Scenario: Configuration and response errors receive distinct readiness statuses
      Given readiness checks with missing configuration or failed responses
      When the researcher checks those failure cases
      Then each failure reports its proper status and retry count

    Scenario: A hosted provider can report readiness
      Given a hosted provider with the requested model
      When the researcher checks that provider's readiness
      Then the hosted provider is ready with the model identity

  Rule: Temporary remote connections are released after use

    Scenario: A configured remote connection is opened and closed
      Given a remote connection with a named user and custom port
      When the researcher opens and closes the connection
      Then the connection uses the requested remote host and user
      And its local port is released after use

    @edge_case
    Scenario: Port forwarding fails while opening a remote connection
      Given a remote connection whose forwarding cannot start
      When the researcher checks backend readiness
      Then the report identifies an unavailable tunnel

    @edge_case
    Scenario: Remote connection authentication fails
      Given a remote connection that rejects authentication
      When the researcher checks backend readiness
      Then the report identifies an unreachable remote host
