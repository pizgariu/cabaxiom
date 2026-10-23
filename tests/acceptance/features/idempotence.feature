Feature: A converge is idempotent
  The README puts it in one sentence - because the same unit of work may run any number of times,
  doing it twice has to land exactly where doing it once did. Every other guarantee in this kernel
  rests on that one, so it is the first thing an operator gets to watch hold.

  The world here is a real directory on disk. Nothing is mocked. The operator declares files and
  directories, hands them to a Reconciler and reads what came back.

  Background:
    Given an empty working directory
    And a declaration of a directory holding a configuration file

  Scenario: The first converge builds the world and proves it
    When the operator converges the declaration
    Then the residual is empty
    And the applied channel names both the directory and the file
    And the configuration file exists on disk with the declared content

  Scenario: A second converge over a settled world applies nothing
    Given the declaration has already been converged once
    When the operator converges the declaration again
    Then the residual is empty
    And the applied channel is empty

  Scenario: The idempotence proof certifies the same thing the operator observed
    When the operator asks for an idempotence proof of the declaration
    Then the proof is stable
    And the proof reports no churn

  Scenario: A world that drifted is repaired by the next converge, not by a reset
    Given the declaration has already been converged once
    And somebody overwrote the configuration file with the wrong content
    When the operator converges the declaration again
    Then the residual is empty
    And the applied channel names only the file
    And the configuration file exists on disk with the declared content
