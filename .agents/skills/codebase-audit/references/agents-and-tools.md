# Agent delegation, skills, and tools — canonical, expanded

This is the canonical version of this reference for the whole skill family: `dev-sprint`, `codebase-audit`, `nightly-support`, `daily-weekly-report`. If a local copy in another skill's `references/` disagrees with this one, treat this one as correct and update the other to match.

This file exists so an agent running any of these skills — including a bare cron session with zero conversational context — knows what help is available and reaches for it proactively.

## Default posture: delegate, don't hoard

A single agent grinding through recon, implementation, review, testing, debugging, and docs in one undifferentiated pass is worse than splitting that work across scoped agents — it has no independent check on its own blind spots, and it burns context doing things a narrower agent would do faster and more carefully. Use `delegation` (and `a2a` for agent-to-agent handoffs) to spawn a subagent whenever a piece of work:

- has a clear, self-contained goal that can be described in a few sentences,
- doesn't need the full running context of the parent session, and
- benefits from a fresh, unbiased pass (review, testing, debugging, auditing especially).

This is not optional flourish — it's the expected way to run any of these skills. Cron/unattended sessions in particular should default to spawning rather than doing everything solo, since there's no human present to catch a single overloaded agent quietly missing something.

## Subtask → agent role → skills/tools

| Subtask | Spawn an agent for it when... | Skills to reach for | Tools to reach for |
|---|---|---|---|
| **Code writing** | A task (or cluster of related tasks) is big enough to scope independently | test-driven-development, simplify-code (if the task is a refactor/cleanup) | code_execution, terminal, file, todo |
| **Code review** | Any nontrivial diff before it's considered "done," or a full-codebase audit | codebase-inspection, requesting-code-review (for a scoped diff/PR review, as distinct from a whole-codebase audit) | file, code_execution, terminal, github |
| **Investigation / recon** | Before writing report.md, before a codebase-audit scan, or when something unanticipated needs understanding *why* | codebase-inspection, context_engine (large/unfamiliar codebases), session_search (prior session history), spike (quick exploratory prototype when the unknown needs a proof-of-concept) | context_engine, session_search, file, web, browser |
| **Test writing** | Writing a phase's e2e/regression suite | test-driven-development | code_execution, terminal, file |
| **Debugging** | A test fails in a Test/Debug loop | systematic-debugging, python-debugpy (Python, step-through/breakpoint), node-inspect-debugger (Node), docker-service-triage (containerized services) | code_execution, terminal, file |
| **Documentation** | Something a future phase or human needs explained (beyond gatelog findings notes) | document-to-action-items (notes/specs → concrete tasks), dogfood (validate docs by using the feature as a user would), architecture-diagram (structural changes worth diagramming) | file, terminal |
| **Task tracking within a session** | Any multi-step sprint or audit, so nothing gets silently dropped | — | todo |
| **External research** | Needs current, outside-the-codebase information | grounded-citations (when claims need sourcing) | web, browser |
| **Talking to other connected systems/services** | Task needs data or actions in a connected external tool | — | connections |
| **Scheduling follow-up work** | Setting up or adjusting cron cadence (dev-sprint cron, recurring codebase-audit, nightly-support's own schedule) | — | cronjob |
| **Clarifying scope/requirements** | A live human-driven session needs the important details pinned down before planning (dev-sprint's brainstorming step, or any other ambiguous request) | — | clarify |
| **Discovering what other skills exist** | Unsure whether a specialized skill already covers a subtask | — | skills |
| **Landing work as a reviewable change** | Project is git-based and conventions call for a PR rather than a direct commit | github, github-push-pr | terminal, github |
| **UI/browser-driven validation** | Dogfooding or auditing a feature that's a UI, not just backend code | computer-use, popular-web-designs (if evaluating design conventions), p5js (if the project involves generative/creative visual work) | computer_use, browser |

## Notes on specific skills

- **systematic-debugging**: use instead of ad hoc fix-and-rerun cycling in any Test/Debug loop. It's the difference between guessing and isolating root cause — especially when a failure isn't obviously explained by the last change made.
- **python-debugpy** / **node-inspect-debugger**: use for the matching language whenever a bug needs actual step-through/breakpoint inspection rather than log-reading.
- **docker-service-triage**: reach for this when the debugging target is a containerized service and the issue might be at the container/orchestration layer, not just the code.
- **test-driven-development**: bias any implementation step toward writing the test (or at least its skeleton) before or alongside the code, not purely after.
- **codebase-inspection**: use for both initial recon and as the review pass on any nontrivial diff, and as the backbone of a codebase-audit scan.
- **requesting-code-review**: for a scoped diff/PR review request — distinct from codebase-audit's full-codebase, ledger-based review. Don't conflate the two triggers.
- **dogfood**: use when the honest way to check work is to actually use the built feature as an end user would, not just run automated tests.
- **document-to-action-items**: use when the input to a fresh-start planning pass, or a nightly-support ticket, is loose notes/spec text that needs to become a concrete task list.
- **simplify-code**: good fit for a code-writing or review pass that's turned up unnecessary complexity — including as the suggested_fix direction for a codebase-audit "smell" finding.
- **spike**: quick exploratory prototype role — for a Test/Debug Sprint or an audit finding that needs a proof-of-concept before committing to a fix direction.
- **architecture-diagram**: documentation role, when a phase or fix changes structure enough that a diagram helps more than prose.
- **grounded-citations**: use when a report, ticket, or doc makes a factual claim from external research that should be sourced rather than asserted.
- **github / github-push-pr**: code-writing/review role, when the project is git-based and work should land as a reviewable PR rather than a direct commit.
- **computer-use / popular-web-designs / p5js**: situational, UI/visual-work-specific — reach for these only when the project itself involves a UI, design evaluation, or generative visual work.

## Hermes-infrastructure-specific (situational, not standard roles)

`hermes-agent`, `hermes-agent-skill-authoring`, `hermes-gateway-troubleshooting`, `hermes-provider-plugins`, `inspecting-hermes-desktop-dom`, `alexa-echo-channel`, `alexa-hermes-bridge` — these exist for when the project *being worked on* is Hermes/Alexa infrastructure itself (e.g. a dev-sprint building a new Hermes intent, or an audit of the Hermes codebase). They are not part of the standard role table above because they're infra-specific, not generic dev-sprint/audit roles. Reach for them only in that specific context; otherwise ignore them.

## Applies in every context, not just main-chat

None of the above is main-chat-only. A cron-triggered session (dev-sprint resuming a phase, a scheduled codebase-audit, nightly-support's daily run) should delegate and pull in these skills/tools exactly as an interactive session would — arguably more readily, since there's no human available to notice if a single overloaded agent missed something.
