# Claude subscription application answers

Draft answers based on public repository activity checked 9 November 2026.
Update the reach figures before submitting if the form is completed later.

## Tell us about the project's reach and impact

RepoShield is a new open-source project, so its adoption is still early: GitHub
currently shows 1 star and 0 forks, and it is not yet published on a package
registry, so there are no monthly package download figures. I do not yet have
verified external dependent projects or production users to report. The gap it
addresses is important to the coding-agent ecosystem: teams need both independent,
deterministic evidence for proposed changes and enforceable limits on connected
agent actions. RepoShield explores both in one Python prototype. It keeps missing
required evidence from passing, binds action approvals to exact context, and keeps
the core independent of an LLM. The public repository includes tests, measured
results and explicit limitations so others can inspect and build on the approach.

## How will you use the subscription for your project?

I will use the Claude subscription as a development assistant to understand unfamiliar
parts of the code, review proposed implementation changes, improve documentation,
and help develop regression tests for policy, authorization, evidence integrity and
Linux isolation. I will verify suggestions through RepoShield's deterministic tests
and real execution checks. Claude will not make RepoShield security decisions or
replace tests, and I will document failures and unresolved limitations.

## Other info

RepoShield has two required modes: deterministic code-change verification and
authorization/restriction of connected agent actions. The local suite reported
406 passed, 1 skipped, and no failures; the skipped Windows symlink test could not
run on that machine. Real GitHub checks used a synthetic demonstration repository.
Docker execution results are development-host evidence; dedicated Linux isolation,
independent-user validation, and broader adoption remain future work. Repository:
https://github.com/PROGRAMMER-1008/RepoGuard
