# hermes-skills

Personal Hermes Agent skills, installable on **Hermes Agent** and **Claude Code** from
this one repo.

Four skills that form a pipeline: a **codebase audit** finds problems and writes them to a
findings ledger, **nightly-support** turns the findings a human approved into tickets and
scheduled work, **dev-sprint** implements them phase by phase behind an all-green test
gate, and **daily-weekly-report** keeps the user informed about what is moving and what is
blocked.

```
codebase-audit ──► ledger.md ──► nightly-support ──► ticket ──► dev-sprint ──► phases done
   (read-only)     (human           (scoped,           (one per     (one phase
                    approves)        staggered)         project)     per run)
                                                                        │
                                                    daily-weekly-report ◄┘
                                                  (logs the significant
                                                   part; pre-written reports)
```

The interesting property of this family is that **it is designed to run unattended across
many separate sessions, including cron jobs with no human present.** All state lives on
disk, every step is idempotent, and the failure modes that matter are the ones where a
run repeats itself forever, strands a project permanently, or quietly re-plans work that
was already finished.

## Install

**As a project dependency** (both harnesses see it; run once after cloning):

```bash
git clone https://github.com/ADn-001/hermes-skills.git
cd hermes-skills
hermes skills trust .          # Hermes: load .agents/skills/
```

`.claude/skills/<name>` already contains per-skill symlinks into `.agents/skills/`, so
Claude Code needs no extra step. The symlinks are committed on purpose — contributors
never have to generate them.

**As personal/user-level skills:**

```bash
# Hermes — user-level
mkdir -p ~/.hermes/skills
cp -r .agents/skills/* ~/.hermes/skills/

# Claude Code — user-level
mkdir -p ~/.claude/skills
for d in .agents/skills/*/; do n=$(basename "$d"); ln -sfn "$PWD/$d" ~/.claude/skills/$n; done
```

## The skills

| Skill | What it does |
|---|---|
| [`dev-sprint`](.agents/skills/dev-sprint/) | Phased, resumable build workflow. One phase per run, each ending at an all-green e2e gate. State in `plan.md` + `gatelog.md`. |
| [`codebase-audit`](.agents/skills/codebase-audit/) | Read-only whole-codebase audit. Findings go to a persistent, append-and-merge ledger with stable IDs and a human-set `approved` flag. |
| [`nightly-support`](.agents/skills/nightly-support/) | Turns approved findings into tickets and schedules the work. Scoped to 1–3 projects, one cron per project, staggered so two sprints never run at once. |
| [`daily-weekly-report`](.agents/skills/daily-weekly-report/) | Rolling daily log plus two pre-written report files, so a status question is a file read rather than a fresh model run. |

Each skill's `SKILL.md` is the entry point; its `references/` holds the exact file formats,
schemas and prompt templates. Read the reference before creating or editing that skill's
state files — a future session (possibly a cron job with no memory of this conversation)
parses them by convention.

## Tools

Stdlib-only Python, no dependencies, in [`tools/`](tools/):

- **`ledger.py`** — parse, validate, query and surgically update a findings ledger:
  `validate`, `list`, `find`, `next-id`, `stats`, `stale-assigned`, `set-status`,
  `retitle`. Every subcommand takes `--json`.
- **`gatelog_check.py`** — `locate` (find the state files **case-insensitively** and
  report the dialect), `validate` (the gatelog's phases must mirror the plan's),
  `next`, `status`.

```bash
python3 tools/ledger.py validate /home/user/codereview/<project>/ledger.md
python3 tools/ledger.py find     /home/user/codereview/<project>/ledger.md --approved --status new
python3 tools/gatelog_check.py status /path/to/project

python3 -m unittest discover -s tools/tests -v
```

Exit codes: `0` clean, `1` a real problem, `2` usage error. Read-only subcommands never
write, not even an mtime.

## Prompts

[`prompts/`](prompts/) holds ready-to-paste cron prompt bodies for the two report jobs
that keep `daily-weekly-report` current. Each has two placeholders to fill in — the log
directory and the command that writes the report file — so they are not tied to any one
deployment. They are the reference implementation of what those jobs should do; adapt the
wording, keep the rules at the bottom (status content only, no self-referential logging).

## Why the tools exist

Three of these skills' bugs were **loops that ran forever or deadlocked**, and every one
of them was invisible in prose:

- A recurring dev-sprint cron re-launched a full-codebase audit on *every* invocation once
  a project finished, because nothing recorded that the completion audit had already run.
- A project with an `assigned` ledger entry looked permanently busy forever, because
  nothing ever moved `assigned` back to `new` — a crashed run stranded it silently.
- A project using `PLAN.md` instead of `plan.md` was read as a *brand new project*,
  because the resume check was case-sensitive. It would have re-planned 16 completed
  phases.

Each is now a rule in a skill *and* a check in a tool, because a rule an agent can forget
is not a guarantee.

## Layout

```
hermes-skills/
├── .agents/skills/<name>/     ← canonical; edit here
├── .claude/skills/<name>      ← per-skill symlinks into .agents (committed)
├── tools/                     ← stdlib-only validators + tests
├── prompts/                   ← ready-to-paste cron prompt bodies
├── docs/                      ← harness compatibility, design notes
└── TRACKING.md                ← what changed in each revision, and why
```

Both harnesses read the same `SKILL.md` files unmodified: the frontmatter is a clean
intersection and both ignore unknown fields. The incompatibility is purely the directory,
which the symlink layer handles. Full reasoning, with citations, in
[`docs/harness-compatibility.md`](docs/harness-compatibility.md).

## A note on scope

These skills provision autonomous coding and cron scheduling. `nightly-support` will
create recurring jobs — so it is deliberately scoped to a short, explicitly-set list of
projects rather than sweeping every ledger it can find, and it staggers its jobs so two
agents never edit codebases at the same time. Read `nightly-support`'s SKILL.md before
widening that scope.

## If you add a skill: put the trigger words first

Hermes truncates a skill's `description` to **60 characters** when it builds the skill
index in the system prompt (`SKILL_PROMPT_DESC_LIMIT` in `agent/skill_utils.py`). That
truncated line is all an agent has to go on when deciding which skill to load — so the
name and the trigger phrases have to land inside the first 57 characters or they are
simply invisible. Everything after that is still read once the skill *is* loaded.

```
daily-weekly-report    -> Daily and weekly report — "what happened today" / "give m...
codebase-audit         -> Codebase audit / codereview — a read-only whole-codebase ...
dev-sprint             -> Dev sprints: phased, resumable builds behind all-green te...
nightly-support        -> Nightly support — turn approved audit findings into ticke...
```

Claude Code's cap is far larger (1,536 chars), so write to Hermes' rule: it is the binding
one. Two related traps, both hit while writing these:

- **An unquoted `": "` inside a description breaks the YAML.** A plain scalar ends at the
  first colon-space, and the skill then loads with *no fields set* — silently, with no
  error. `approved:true` is fine (no space); `report: today` is not. Quote the whole
  description.
- **`name` must match the directory name.** It overrides the directory in Hermes but is
  display-only in Claude Code, so a mismatch shows up in only one harness.

## License

MIT — see [LICENSE](LICENSE). Use them, change them, teach them to your own agents.
