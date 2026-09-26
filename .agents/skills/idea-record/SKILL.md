---
name: idea-record
description: "Idea capture, brainstorming and promotion — \"record this idea\", \"let's talk about an idea\", \"list my ideas\", \"let's start <idea>\". Records what the user says into a properly formatted idea file under the ideas directory, optionally brainstorms it into a full spec the way dev-sprint's early phases would, lists saved ideas with a one-line summary each, and promotes a spec into a real dev-sprint — either live in this session or as a scheduled cron job. Use this whenever the user mentions recording, capturing, discussing, listing or starting one of their ideas."
---

# Idea Record

Ideas start as a sentence and end as a scheduled project. This skill owns the whole path
in between, so the user never has to decide which of several tools to reach for.

```
  "record this idea"  ──►  raw capture        date-name.md, status: captured
        │
        │  "let's talk about <idea>"        (the brainstorming path)
        ▼
  brainstorm ──────────►  spec               same file, status: spec
        │
        │  "list my ideas"                   → one line each
        ▼
  "let's start <name>" ──►  is it a spec?
        ├── yes ──► review it,  OR  kick off dev (ask interval, default 3h)
        └── no  ──► hand the raw sketch to dev-sprint live; it can structure it
```

## Before you start: two paths

This skill is used by a voice bridge as well as by a person at a terminal, and the two
have different homes. Resolve them once, at the top of a session:

- **`$CORE`** — the bridge's `relay_core.py`, the module that owns the idea board and
  every `idea` subcommand. In the author's deployment it lives next to `bridge.py` in
  the bridge repository; elsewhere, find it with `find ~ -name relay_core.py`.
- **`$BRIDGE_ROOT`** — the directory containing `$CORE` and `scripts/`.

If you cannot find `$CORE`, this skill has nothing to record into — say so rather than
writing markdown by hand, because a hand-written file is one the rest of the system
cannot read.

## The file format

One markdown file per idea in the ideas directory (`BRIDGE_IDEAS_DIR`, default
`~/ideas`). This is the format the bridge already writes and reads, so a file created
here is indistinguishable from one created by voice.

```markdown
---
date: 2026-09-25
time: 22:14
source: echo | chat | whatsapp | cli | idea-record
status: captured | spec | dev-started
tags: []
---

# <title>

## Raw capture
<the user's words, verbatim — never edited or summarised away>

## Problem / goal
<what it is trying to achieve, and what "done" looks like>

## Rough approach
<the design decided during brainstorming, including alternatives rejected and why>

## Open questions
<unresolved, or "None — decided during brainstorming">
```

**Filename: `YYYY-MM-DD-<slug>.md`** — date first, then a kebab-case slug of the name.
The date prefix is load-bearing: the board is listed newest-first by sorting filenames
descending, so putting the name first would break that ordering. On a name collision
within one day, append `-2`, `-3`, and so on; never overwrite an earlier idea.

**The `## Raw capture` section is permanent.** A later pass fills in the other three
sections but never rewrites the capture — the user's original words are the one part of
the document that cannot be reconstructed later, and they are often more honest than the
polished version.

**Write these files with `$CORE`, not by hand:**

```bash
python3 "$CORE" idea capture "<text>"          # raw capture
python3 "$CORE" idea structure <slug> "<spec>" # fill in the three sections
python3 "$CORE" idea list                      # the board, with summaries
```

Those helpers own the filename collision, the frontmatter, the section markers and the
`status` flip, and they are the same code path the voice route uses.

**`status` is the authority on whether an idea is ready to build** — not how full the
prose looks. `captured` is a sketch; `spec` is planned and agreed; `dev-started` has a
scheduled job behind it.

## Mode 1 — capture an idea

Triggered by "record this idea", "note this idea", "here's an idea", or an intent that
routes here. Record the words **as given**; do not improve them, and do not ask a
follow-up question first — an idea captured late is an idea lost.

1. `idea capture "<the user's words>"`. Done. Report the filename.

That is the whole job for a bare capture. Do **not** start a brainstorming conversation
unprompted, and do **not** log to the daily report — see "Logging" below.

If the user names the idea, use their name verbatim as the title; do not re-slug their
phrasing into something tidier. If they don't name it, take the first line of what they
said as the title.

## Mode 2 — brainstorm an idea into a spec

Triggered when the user wants to *talk about* an idea rather than just file it: "let's
discuss X", "help me think through X", "I want to plan X". This is the first phases of
`dev-sprint` — brainstorming, approach and decision-making — stopping short of
implementation.

**This mode requires a live human.** It is a conversation, not a transformation. If
there is no user present (a cron run, a scheduled job), do not enter it.

Work in this order, and do not skip to the file:

1. **Understand the goal.** What is being tried to achieve, and how would the user know
   it worked? Ask until you can state it back to them in one sentence and they agree.
2. **Propose approaches.** Offer two or three genuinely different ways to do it, each
   with its real cost. A single option presented as inevitable is not a proposal — the
   point of this stage is that the user picks, not that you decide.
3. **Surface the decisions.** Name the choices that shape the work (storage, interface,
   scope in/out, dependencies) and ask for a decision on each. Record the rejected
   alternatives and the reason — that is the part a future session cannot reconstruct,
   and it stops the same debate being had twice.
4. **Ask the questions that change the plan**, and only those. Scope boundaries, what is
   explicitly out of scope, anything that would make the work wrong rather than merely
   different.
5. **Write the spec** into the same file via `idea structure <slug> "<spec>"`, with the
   three sections filled in properly. The `status` flips `captured` → `spec`; the raw
   capture stays exactly as it was.

When a section genuinely has no answer yet, write what is known and list the remainder
under `## Open questions`. A spec with honest open questions is useful; a spec that
invents certainty is not.

## Mode 3 — list the ideas

Triggered by "list my ideas", "what ideas do I have", "show my ideas".

Read the board and present **one line per idea**: name, what it is trying to achieve, and
its status. Group by status if that reads more naturally, and never make the user scroll
past a wall of filenames.

```
You have 3 ideas.
  music-playlist-sort — reorder playlists by mood instead of date. Captured.
  offline-queue — queue playback when the uplink drops. Has a spec.
  gpio-panel — no idea yet, just a name. Captured.
```

`idea list --json` returns each idea with `title`, `status`, `summary` and `is_spec`, so
you do not have to re-read the files. For a voice route, `idea list-spoken` gives a
bounded, markdown-free rendering (at most the five most recent, then a count of the
rest). If the board is empty, say so in one line — that is not an error.

## Mode 4 — start an idea ("let's start X")

Resolve which idea the user means (`idea list`, then match on the name they used; ask
only if more than one is plausible). Then read what they are starting from:

```bash
python3 "$CORE" idea start <slug> --json     # is_spec: true|false
```

### If it is a spec (`status: spec`)

Tell the user it is already a spec, then offer the two ways forward and let them pick:

- **Review it** — walk them through what it says, section by section.
- **Kick off dev** — this schedules real autonomous work, so before creating anything:
  - Confirm the idea by name, so a mis-resolved match can't start the wrong project.
  - Ask for the interval, offering the **3h default** explicitly. Interval grammar is
    closed: `3h`, `90m`, `1h`. An unrecognised answer becomes the default — say so
    rather than silently guessing.
  - Provision it (below), then **log to the daily report** — this is the one mode that
    does, because it creates scheduled autonomous work the user needs to know about.

### If it is a raw sketch (`status: captured`)

It is not a spec, so it cannot be scheduled as one — a dev-sprint cron needs a plan to
plan from, and would otherwise invent the design unattended with nobody to object. Do
not try to force it, and do not create a cron for a sketch.

**Load `dev-sprint` into this live session and hand it off**, because dev-sprint's own
"Starting fresh" step handles exactly this case: it runs the brainstorming conversation,
then writes `report.md`/`plan.md`/`gatelog.md` and starts implementing. That is the same
work Mode 2 does, continued rather than repeated.

So: say the idea is a rough capture, and offer to plan it properly now.

## Provisioning the dev-sprint job

**Two rules apply to every job this skill provisions**, both from
`dev-sprint/references/dev-dashboard-ledger.md`:

1. **The name is `dev-sprint-<project>-auto-<uid>`** with a real
   `uuid4().hex[:8]` suffix. The `-auto-` infix is the authorisation token that
   marks a job as the loop's; a job without it is not ours, and the ownership
   rules will correctly refuse to touch it.
2. **Write the real name and `job_id` back into the dev-dashboard ledger** after
   provisioning, replacing the `-auto-00000000` placeholder. Use `state.save()`
   (validated, atomic) — never a text edit or a bare `json.dump`.

**Check the ledger's finished state first.** Before provisioning, confirm the
project is not `sprint.state: finished` with a `finished_generation` matching
the current one — that combination **suppresses** provisioning entirely.
Re-provisioning a finished project starts an infinite provision/delete loop that
charges a full audit every cycle. A *differing* generation means new phases are
waiting, and provisioning is correct.

Also skip if the project is absent from the ledger or `path_absent` is true.

Only in the spec + "kick off dev" path. Use the project's deterministic handoff script —
it is what keeps a spoken sentence from ever being composed into a scheduled command:

```bash
"$BRIDGE_ROOT"/scripts/dev-sprint-handoff.sh <project-dir> <interval>
```

The idea command does this for you, including the project directory, the copy of the
spec, the status flip and the rollback if provisioning fails:

```bash
python3 "$CORE" idea start <slug> <interval> --json
```

It exits **3** and changes nothing if the idea is still a sketch — that refusal is the
safety property, not an error to work around. It creates one project directory per idea
(ideas are new work, so they get their own sprint dir) and copies the spec in as
`SPEC.md`. Report the job name and schedule back to the user.

## Logging

Log to the daily report (`daily-weekly-report` format) in **exactly one** case: when a
dev-sprint job is provisioned from an idea. That is a project milestone and the user
needs to know autonomous work now exists.

Do not log a bare idea capture, a brainstorming session, or a list request. An idea
someone had while making coffee is not a status update, and a board that logs every one
of them stops being a status channel — the same dilution `daily-weekly-report` exists to
prevent.

## Rules

- **Never lose the raw words.** Capture before anything else, always. A slow
  conversation, a dead provider or a user who changes their mind must not cost the idea.
- **Never overwrite an idea file.** Collisions get `-2`, `-3`.
- **Never invent certainty in a spec.** Unknowns go under `## Open questions`.
- **Never create a cron job without an explicit "yes, start it" and a stated interval.**
  Scheduling autonomous coding is the one irreversible thing this skill does.
- **One phase per session, one idea per file.** Don't merge two ideas into one document.
- **This skill never implements anything.** Planning ends where `dev-sprint` begins.
