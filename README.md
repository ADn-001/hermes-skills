# hermes-skills

Personal [Hermes Agent](https://github.com/NousResearch/hermes-agent) skills, installable on
**Hermes Agent** and **Claude Code** from this one repo.

Five skills that form a pipeline: a **codebase audit** finds problems and writes them to a
findings ledger, **nightly-support** turns the findings a human approved into tickets and
queued work, **dev-sprint** implements them phase by phase behind an all-green test gate,
**idea-record** turns a stray thought into a planned project, and **daily-weekly-report**
keeps you informed about what is moving and what is blocked.

```
codebase-audit ──► ledger.md ──► nightly-support ──► ticket ──► dev-sprint ──► phases done
   (read-only)     (human          (explicitly       (one per     (one phase
                    approves)       scoped list)      project)     per run)
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

**These skills provision no cron jobs.** Recurring work comes from two report jobs you
create yourself (see [Set up the two report jobs](#set-up-the-two-report-jobs)) and, if you
install the optional control panel, from *its* two jobs. A skill that created scheduled work
on your machine would be a second, invisible scheduler racing the one you can see — that
design was deliberately dismantled, and the `SKILL.md` files now say so out loud.

## Contents

- [Quick start](#quick-start)
- [Folders to create](#folders-to-create)
- [What to download, and from where](#what-to-download-and-from-where)
- [Set up the two report jobs](#set-up-the-two-report-jobs)
- [Remote access: the Cloudflare tunnel](#remote-access-the-cloudflare-tunnel)
- [The skills](#the-skills)
- [Tools](#tools)
- [Why the tools exist](#why-the-tools-exist)
- [Layout](#layout)
- [If you add a skill: put the trigger words first](#if-you-add-a-skill-put-the-trigger-words-first)

---

## Quick start

Python 3.8+ (stdlib only — no pip, no venv, no dependencies). The tunnel section
additionally needs a domain on Cloudflare.

```bash
git clone https://github.com/ADn-001/hermes-skills.git
cd hermes-skills

# Trust this repo as a source of skills, then check the tools run.
hermes skills trust .          # Hermes: load .agents/skills/
python3 tools/ledger.py --help
python3 -m unittest discover -s tools/tests
```

`hermes skills trust .` registers `.agents/skills/` with Hermes. Without it the skills are
on disk but not offered to the agent.

**As personal/user-level skills** (available in every session on this machine, not only in
this checkout):

```bash
mkdir -p ~/.hermes/skills
cp -r .agents/skills/* ~/.hermes/skills/

# Claude Code — user-level
mkdir -p ~/.claude/skills
for d in .agents/skills/*/; do n=$(basename "$d"); ln -sfn "$PWD/$d" ~/.claude/skills/"$n"; done
```

`.claude/skills/<name>` already contains per-skill symlinks into `.agents/skills/`, so
Claude Code needs no extra step for a project checkout. The symlinks are committed on
purpose — contributors never have to generate them.

> **If you edit a skill, edit the one that gets loaded.** With `cp` that means the copy in
> `~/.hermes/skills/`. Prefer symlinking instead, so there is one copy:
>
> ```bash
> for d in .agents/skills/*/; do n=$(basename "$d"); ln -sfn "$PWD/$d" ~/.hermes/skills/"$n"; done
> ```
>
> A skill and its installed copy drifting apart is invisible and can **delete work**: the
> natural sync direction is canonical → installed, so a file that exists only in the
> installed copy gets removed. That has happened here once, and
> [`tools/tests/test_skill_hygiene.py`](tools/tests/test_skill_hygiene.py) now fails on it.

---

## Folders to create

The skills use three roots, referred to throughout as `$PROJECTS`, `$CODE_REVIEW` and
`$REPORTS`. Create them once:

```bash
mkdir -p ~/projects          # $PROJECTS   — your project checkouts
mkdir -p ~/codereview        # $CODE_REVIEW — one findings ledger per project
mkdir -p ~/reports           # $REPORTS    — the daily activity log + two report files
mkdir -p ~/.hermes/skills    # installed skills, if not symlinking
```

| Variable | Path | Holds | Written by |
|---|---|---|---|
| `$PROJECTS` | `~/projects` | One directory per project, each holding its own `plan.md` / `gatelog.md` | you |
| `$CODE_REVIEW` | `~/codereview` | `<project>/ledger.md` (audit findings) and `<project>/tickets/` | `codebase-audit`, `nightly-support` |
| `$REPORTS` | `~/reports` | `daily/YYYY-MM-DD.md`, plus `daily-report.md` and `weekly-report.md` | `daily-weekly-report` and the report jobs |

`$CODE_REVIEW` is a **sibling** of `$PROJECTS`, not a subdirectory of it. That is
deliberate: a ledger is a record *about* a project, and it has to survive the project being
moved, renamed or deleted.

**These are variables in the skill text, not literals.** Each skill says how to find them,
and the two code samples that need the control panel's library read it from the
environment instead of a hardcoded path:

```bash
export DASHBOARD_ROOT=/path/to/dev-dashboard
```

Nothing here hardcodes a home directory, and a test enforces it. An absolute path in a
tracked skill is wrong on every other machine, and it fails **silently**: a command pointed
at a directory that does not exist does not raise, it just writes nothing, or finds nothing
and reports "no results".

---

## What to download, and from where

| What | Where | Needed? |
|---|---|---|
| **The five skills** | this repo — `git clone https://github.com/ADn-001/hermes-skills.git` | Yes |
| **`tools/`** | this repo — the two validator CLIs | Yes, for anything unattended |
| **`prompts/`** | this repo — ready-to-paste report-job bodies | Yes, for the two report jobs |
| **dev-dashboard** (control panel) | *not published yet* — see below | Optional |
| **hermes-alexa-bridge** (voice) | separate project, optional | Optional |

The skills split cleanly by whether they need the control panel:

- **Fully standalone** — `dev-sprint`, `daily-weekly-report`, `idea-record`. Their state is
  `plan.md` / `gatelog.md` in the project and the files under `$REPORTS`. Clone this repo
  and you are done.
- **Standalone interactively, dashboard-dependent unattended** — `codebase-audit` and
  `nightly-support`. You can run either by hand against any project today. What the
  dashboard adds is the *unattended* path: a queue, a due-check, and a manager that starts
  one short-lived session per task when work is ready, so an audit runs every few days
  without anyone asking.

### The optional control panel

`dev-dashboard` is the queue, the cron-ownership contract, and a small web UI for both. **It
is currently private**, so there is nothing to clone yet — and nothing in this repo
requires it.

If you are running the unattended path, what it does is worth knowing before you build or
request one. It keeps a single `state.json` ledger, reconciles a FIFO queue of due work from
your per-project toggles, and spawns one session per task, one at a time. It owns exactly
two recurring jobs. The two invariants that matter to a skill author are:

- **the claim** — one file records which session owns the machine, so two sessions can never
  edit one checkout;
- **the completion marker** — a finished audit writes the date the ledger records, so a
  completed project is not re-audited forever.

Both are why the skills' own scheduling text says the trigger is never theirs to arrange.

---

## Set up the two report jobs

These are the only recurring jobs these skills need, and they are yours to create.
[`prompts/report-daily.txt`](prompts/report-daily.txt) and
[`prompts/report-weekly.txt`](prompts/report-weekly.txt) are ready-to-paste bodies. Each has
two placeholders to fill in — the log directory and the command that writes the report file
— so they are not tied to any one deployment. They are the reference implementation of what
those jobs should do; adapt the wording and keep the rules at the bottom (status content
only, no self-referential logging).

If you have a voice bridge, prefer its writer, because it stamps the covered date, sets
`0600` (these files name your projects) and writes atomically:

```bash
"$CORE" report write today  -    # body on stdin
"$CORE" report write weekly -
```

Feed it the **body only**, starting at the first `## ` heading. The writer emits the
`# Daily report — <date>` title itself and strips a duplicate from the body, so a body that
includes one ends up with the heading twice. Only when that command is unavailable should
you write the report file directly, title included.

Roughly daily, and once a week. Keep them independent — a failing weekly job must not stop
the daily one — and attach the `daily-weekly-report` skill to both so they use its
conventions.

---

## Remote access: the Cloudflare tunnel

For reaching the control panel from anywhere, and for reaching anything else on a machine
that has no public IP.

**Why a tunnel rather than port forwarding:** the connector makes an *outbound* connection,
so the machine needs no public IP and no inbound firewall rule. That is the only thing that
works from behind CGNAT, a phone on WiFi, or a laptop on someone else's network. The
trade-off is that **you are publishing a service to the internet**, which is why the
authentication step is not optional.

### 1. Install cloudflared

```bash
curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg \
  | sudo tee /usr/share/keyrings/cloudflare-main.gpg >/dev/null
echo "deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared any main" \
  | sudo tee /etc/apt/sources.list.d/cloudflared.list
sudo apt-get update && sudo apt-get install cloudflared
cloudflared --version
```

Other distributions: see
[Cloudflare's download page](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/).

### 2. Create a tunnel

**Zero Trust → Networks → Tunnels → Create a tunnel.** Cloudflare offers two models. Pick
deliberately, because they differ in where the configuration lives afterwards:

| | **Remotely managed (token)** | **Locally managed (`config.yml`)** |
|---|---|---|
| Config lives | Cloudflare's control plane | a file on the machine |
| Change a hostname | dashboard only, no restart | edit the file, `systemctl restart` |
| Reviewable in git | no — not on disk | yes |
| Credentials | the systemd unit holds a token | a JSON file, `chmod 600` |

Remotely managed is the smoother day-to-day experience. Locally managed is the better
choice if you want the ingress rules in version control.

**Remotely managed** — copy the token Cloudflare shows you, then install the service:

```bash
sudo cloudflared service install <TOKEN>
systemctl status cloudflared
```

The unit runs `cloudflared --no-autoupdate tunnel run --token-file /etc/cloudflared/token`.
There is **no `config.yml` on disk**, so add hostnames from the Cloudflare dashboard — an
edit to a local file will look like it should work and be silently ignored.

**Locally managed** —

```bash
sudo cloudflared tunnel create dev-tunnel
sudo cloudflared tunnel route dns dev-tunnel dev.example.com
sudo cloudflared service install          # no token argument
```

`credentials-file` is created under `/root/.cloudflared/`. Keep it out of git.

### 3. Point it at your local service

For the **control panel**, the origin is `https://127.0.0.1:8765` — HTTPS on loopback:

```yaml
# ~/.cloudflared/config.yml — locally managed only
tunnel: <TUNNEL_ID>
credentials-file: /root/.cloudflared/<TUNNEL_ID>.json
ingress:
  - hostname: dev.example.com
    service: https://127.0.0.1:8765
    originRequest:
      noTLSVerify: true          # the panel's certificate is self-signed
  - service: http_status:404     # required catch-all, and it must be last
```

Three things there are load-bearing:

- **`noTLSVerify: true`** — the panel serves a self-signed certificate. This is needed, and
  it is fine: the connection never leaves loopback, and Cloudflare terminates valid TLS at
  the edge for the public side. Do not "fix" it by switching the origin to `http://`;
  plaintext is not an improvement.
- **`127.0.0.1`, not the LAN address** — the panel is rebound to loopback on purpose. A DHCP
  change cannot invalidate a loopback origin, and the connector shares the host network
  namespace, so loopback is reachable from it normally. (That is verifiable, not assumed.)
- **The `http_status:404` catch-all must be last.** Without it cloudflared will not start.

For **any other local service** — a voice bridge, a dev server — add another ingress rule
above the catch-all. One hostname per service; `subdomain = service name` is a convention
that keeps the config readable.

### 4. Put authentication in front of it — do not skip this

**The control panel can create cron jobs on your machine.** It is protected by a single
static token, which is a loopback credential and is not what you want facing the internet.

Add a **Cloudflare Access** policy in front of the hostname: Zero Trust → Access →
Applications → Add an application → Self-hosted. One-time PIN against your email address is
the simplest thing that works, and it stops anonymous traffic before it reaches you. Put
one in front of *every* hostname you publish, not just the panel.

Without it you have published an unauthenticated control panel to the internet. The
tunnel's TLS does not help here: it protects the connection, not the authorisation.

### 5. Verify it end to end

```bash
# 1. The connector is up and has registered connections
systemctl is-active cloudflared
journalctl -u cloudflared -n 40 --no-pager | grep -iE 'registered|connection|error'

# 2. The origin answers on loopback (not on the LAN address)
curl -sk https://127.0.0.1:8765/api/status -o /dev/null -w '%{http_code}\n'

# 3. The public hostname reaches it, from somewhere that is not this machine
curl -s https://dev.example.com/ -o /dev/null -w '%{http_code}\n'
```

Do step 3 from a phone on mobile data, not from your own LAN — a hairpin request that works
locally tells you nothing about whether the tunnel is really routing.

If step 3 fails while step 1 is healthy, the problem is the ingress rule or the DNS route,
not the connector.

### Running the panel as a service

A minimal user unit. Bind loopback and let the tunnel be the only way in:

```ini
# ~/.config/systemd/user/dev-dashboard.service
[Unit]
Description=dev-dashboard control panel
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=%h/projects/dev-dashboard
Environment=PYTHONUNBUFFERED=1
Environment=PATH=%h/.local/bin:/usr/local/bin:/usr/bin:/bin
ExecStart=/usr/bin/python3 %h/projects/dev-dashboard/server.py \
  --host 127.0.0.1 --port 8765
Restart=on-failure
RestartSec=3

[Install]
WantedBy=default.target
```

```bash
systemctl --user enable --now dev-dashboard.service
loginctl enable-linger "$USER"     # so it survives logout
```

Two things that only show up when you actually run it, neither visible in application code:

- **`PATH` must include `~/.local/bin`.** A systemd user unit inherits a bare `PATH`, so
  `shutil.which("hermes")` returns `None` and the apply route refuses rather than guessing
  a binary. The refusal is correct; the fix belongs in the unit.
- **A wildcard bind (`0.0.0.0`) is refused by design.** Exposing it on the LAN as well as
  the tunnel is a deliberate loosening, not a fix.

If you harden the unit — `ProtectSystem=strict`, `NoNewPrivileges`, `ReadWritePaths` —
expect to add a path each time the panel grows a capability. A sandbox missing the write a
feature needs fails somewhere unrelated-looking, and **only for processes the unit starts**,
which is what makes it so easy to misdiagnose from an interactive shell where the same
write succeeds.

---

## The skills

| Skill | What it does |
|---|---|
| [`dev-sprint`](.agents/skills/dev-sprint/) | Phased, resumable build workflow. One phase per run, each ending at an all-green e2e gate. State in `plan.md` + `gatelog.md`. |
| [`codebase-audit`](.agents/skills/codebase-audit/) | Read-only whole-codebase audit. Findings go to a persistent, append-and-merge ledger with stable IDs and a human-set `approved` flag. |
| [`nightly-support`](.agents/skills/nightly-support/) | Turns approved findings into tickets and queues the work. Scoped to an explicit list of projects, so an unattended run cannot sweep every ledger it can find. |
| [`daily-weekly-report`](.agents/skills/daily-weekly-report/) | Rolling daily log plus two pre-written report files, so a status question is a file read rather than a fresh model run. |
| [`idea-record`](.agents/skills/idea-record/) | The path from "record this idea" to a planned project: capture, brainstorm into a spec, list, and promote. Works alongside a voice bridge or standalone. |

Each skill's `SKILL.md` is the entry point; its `references/` holds the exact file formats,
schemas and prompt templates. Read the reference before creating or editing that skill's
state files — a future session, possibly a cron job with no memory of the conversation
that created them, parses them by convention.

The two directories are not interchangeable: a `references/` file is read *in addition to*
the skill, so a path that goes stale in one goes stale in both.

---

## Tools

Stdlib-only Python, no dependencies, in [`tools/`](tools/):

- **`ledger.py`** — parse, validate, query and surgically update a findings ledger:
  `validate`, `list`, `find`, `next-id`, `stats`, `stale-assigned`, `set-status`,
  `retitle`. All but `next-id` take `--json`.
- **`gatelog_check.py`** — `locate` (find the state files **case-insensitively** and
  report the dialect), `validate` (the gatelog's phases must mirror the plan's), `next`,
  `status`.

```bash
python3 tools/ledger.py validate "$CODE_REVIEW/myproject/ledger.md"
python3 tools/ledger.py find     "$CODE_REVIEW/myproject/ledger.md" --approved --status new
python3 tools/gatelog_check.py status ~/projects/myproject

python3 -m unittest discover -s tools/tests -v
```

Exit codes: `0` clean, `1` a real problem, `2` usage error. Read-only subcommands never
write, not even an mtime. More in [`tools/README.md`](tools/README.md).

---

## Why the tools exist

Three of these skills' bugs were **loops that ran forever or deadlocked**, and every one of
them was invisible in prose:

- A recurring dev-sprint cron re-launched a full-codebase audit on *every* invocation once a
  project finished, because nothing recorded that the completion audit had already run.
- A project with an `assigned` ledger entry looked permanently busy forever, because nothing
  ever moved `assigned` back to `new` — a crashed run stranded it silently.
- A project using `PLAN.md` instead of `plan.md` was read as a *brand new project*, because
  the resume check was case-sensitive. It would have re-planned 16 completed phases.

Each is now a rule in a skill *and* a check in a tool, because a rule an agent can forget is
not a guarantee.

The same reasoning produced `tools/tests/test_skill_hygiene.py`, after a skill and its
installed copy silently diverged — in the direction where syncing the obvious way would
have **deleted** a file that existed only in the installed copy. It asserts that a skill
carries no machine-specific path, that every file in a skill tree is identical to its
installed mirror, and that **canonical is not behind its mirror** in either content or
files. It is mutation-tested, and finding that out was itself instructive: a stale `.pyc`
once made a test run execute the *previous* run's compiled copy and report a false result,
which is the same class of failure wearing a different costume.

---

## Layout

```
hermes-skills/
├── .agents/skills/<name>/     ← canonical; edit here
├── .claude/skills/<name>      ← per-skill symlinks into .agents (committed)
├── tools/                     ← stdlib-only validators + tests
├── prompts/                   ← ready-to-paste report-job bodies
├── docs/                      ← harness compatibility, design notes
└── TRACKING.md                ← what changed in each revision, and why
```

Both harnesses read the same `SKILL.md` files unmodified: the frontmatter is a clean
intersection and both ignore unknown fields. The incompatibility is purely the directory,
which the symlink layer handles. Full reasoning, with citations, in
[`docs/harness-compatibility.md`](docs/harness-compatibility.md).

---

## If you add a skill: put the trigger words first

Hermes truncates a skill's `description` to **60 characters** when it builds the skill
index in the system prompt (`SKILL_PROMPT_DESC_LIMIT` in `agent/skill_utils.py`). That
truncated line is all an agent has to go on when deciding which skill to load — so the name
and the trigger phrases have to land inside the first 57 characters or they are simply
invisible. Everything after that is still read once the skill *is* loaded.

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

---

## License

MIT — see [LICENSE](LICENSE). Use them, change them, teach them to your own agents.
