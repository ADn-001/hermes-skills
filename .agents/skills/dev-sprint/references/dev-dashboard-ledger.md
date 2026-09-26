# The dev-dashboard ledger — how an autonomous skill reads and acts on it

The dashboard (`~/projects/dev-dashboard`) is a **control panel**, not a
participant. It records what the user decided; it never acts. This file is how
the autonomous skills consume it.

**The one rule everything else follows from:**

> **The dashboard never creates, deletes, pauses or resumes a cron.** It sets
> `enabled: true` in the ledger. The owning skill reads that and provisions or
> removes its *own* job.

Cron creation is the one irreversible operation in this system. It stays behind
the skills that already carry the guards, the rate limits and the
`admin_gate()`. A skill that "helpfully" also provisions from the dashboard has
defeated the entire design.

---

## Where the ledger is

```
~/projects/dev-dashboard/state.json     canonical
~/projects/dev-dashboard/state.md       generated view — never edit, never parse
```

Path resolution, in order: the server's `--state` flag, then `$DASHBOARD_STATE`,
then the project's own `state.json`. Read it with the library, not by hand:

```python
import sys; sys.path.insert(0, "/home/user/projects/dev-dashboard")
from lib import state
doc = state.load("/home/user/projects/dev-dashboard/state.json")
```

`load()` validates and returns a normalised document, or raises `StateError`
naming the specific problem. **Never `json.load` it directly** — a half-parsed
ledger is how a skill ends up acting on a corrupt file as if it were truth.

Validate without writing:

```bash
python3 ~/projects/dev-dashboard/tools/validate_state.py validate --state <path>
```

---

## What is in it

```jsonc
{
  "version": 1,
  "updated_at": "2026-09-26T00:00:00Z",
  "projects": {
    "<project>": {
      "path": "/home/user/projects/<project>",
      "path_absent": false,
      "audit":   { "enabled": true, "cron": "codebase-audit-<p>-auto-00000000",
                   "interval": "every 4 days" },
      "nightly": { "enabled": true, "cron": "nightly-support-<p>-auto-00000000",
                   "interval": "every 8 days" },
      "sprint":  { "cron": "dev-sprint-<p>-auto-00000000", "job_id": "...",
                   "state": "running|idle|finished", "generation": "a3f2c1e0",
                   "noop_runs": 0, "session_id": null,
                   "finished_at": null, "finished_generation": null,
                   "reason": null }
    }
  },
  "ideas": { "<date>-<slug>": { "title": "...", "status": "captured|approved|greenlit|started|done",
                               "greenlit_for": "idea-record", ... } },
  "markers": { "<cron-name>": { "generation": "...", "audit_job": "...",
                                "created_at": "...", "reason": "..." } }
}
```

**A placeholder `cron` name is not a job.** The dashboard writes
`...-auto-00000000` so the ledger validates its own naming rule. That name does
not correspond to any real cron. When you provision, write the **real** name
(with the `uuid4()` suffix) back into the ledger.

`interval` is **advisory**. It records the cadence the user chose. It does not
set a schedule — you own the actual `hermes cron create --schedule`.

---

## The ownership contract — non-negotiable

Every cron the autonomous system creates is named:

```
<skill>[-<project>]-auto-<uid>      uid = 8 lowercase hex, from uuid4()
```

The **`-auto-<uid>` infix is the authorisation token.** A job without it is
not ours, no matter which skill it runs or which project it points at.

And the shape alone is **necessary but not sufficient**. A job is ours only if
**both** hold:

1. the name matches the shape above, **and**
2. its `created_by` field is `autonomous`.

A user can name a job like ours by accident. That is why the check is two
facts, not one.

Use the library — it is already tested, and its edge cases are subtle:

```python
import sys; sys.path.insert(0, "/home/user/projects/dev-dashboard")
from lib import ownership

mine = ownership.owned_jobs(all_jobs)              # filter to ours
one  = ownership.select_owned(all_jobs, exact_name) # exact equality, no prefix
one  = ownership.assert_solvable(candidates, job_id)  # raises on ambiguity
```

**The five rules, and what each one prevents:**

| Rule | Prevents |
|---|---|
| act only on shape **and** `created_by` | acting on a user's job that happens to match |
| **never enumerate-then-act** — filter first, then act within the set | picking "the first dev-sprint job" when a user has one too |
| delete/pause need **exact name equality** | a prefix match taking out a sibling job |
| **two owned sprint jobs for a project is a bug, not a choice** | silently picking one and leaving the user to guess which |
| a self-destructing job deletes **only its own `id`** | deleting a job that was replaced under it |

On ambiguity: **pick neither, report it, let the user resolve it.**
`assert_solvable` raises `AmbiguousJobError` for exactly this. Catching it and
choosing anyway defeats the mechanism.

---

## Provisioning — the actual commands

This is the tool surface the skills need. `hermes cron` is the CLI; see
`hermes cron --help` and `hermes cron create --help` for the full grammar.

```bash
# 1. Generate the name FIRST, so the ledger and the job agree.
#    (or let the ledger's placeholder stand and rewrite it after)

# 2. Create the job.
hermes cron create "every 3 hours" "<the prompt>" \
    --name "dev-sprint-<project>-auto-<uid>" \
    --workdir "/home/user/projects/<project>" \
    --skill dev-sprint \
    --skill test-driven-development \
    --skill systematic-debugging \
    --skill codebase-inspection \
    --skill requesting-code-review

# 3. List, and get the job's stable id — the id, not the name, is what you
#    delete. The name can be reused; the id cannot.
hermes cron list
hermes cron status

# 4. Remove. By id, and only after assert_solvable() has told you it is
#    unambiguous and it is yours.
hermes cron remove <job-id>
hermes cron pause  <job-id>
hermes cron resume <job-id>
```

**Write the real name and `job_id` back into the ledger** after provisioning.
The ledger is where the next run looks; a job that exists but is not in the
ledger is invisible to the loop, and a ledger entry pointing at a job that does
not exist is worse.

Provisioning is never the dashboard's job, and it is never done by a *different*
skill than the one that owns the scope. `codebase-audit` provisions audits,
`nightly-support` provisions nothing except tickets, `idea-record` provisions
only for ideas it has been greenlit.

---

## Reading your own scope

```python
p = doc["projects"].get(project_name)
if not p: return                      # not in the dashboard's world at all
if p.get("path_absent"): return       # recorded as deleted — do not touch
if not (p.get("audit") or {}).get("enabled"): return   # user switched us off
```

A disabled scope is the user saying no. Respect it without asking why, and do
not re-enable it yourself.

---

## The finished state — read this before provisioning a sprint

`sprint.state` is one of `running`, `idle`, `finished`.

`finished` is **not** a broken state, and it **suppresses re-provisioning
entirely**. It exists because deleting a cron is only half the job: with the
project still sprint-enabled, the next `nightly-support` or `idea-record` run
would see "this project is scoped for sprints" and provision a fresh job for a
plan that is already complete. That job would find no work twice, provision a
redundant audit, and delete itself — an infinite provision/delete loop charging
a full audit every cycle.

The flag is keyed to `finished_generation`, so **new phases appearing clears it
automatically**:

| `finished_generation` vs current generation | Meaning | Action |
|---|---|---|
| equal | the finish still describes the current plan | **stand down** — do not provision |
| different | the plan changed since; new work is waiting | provision normally |

```python
d = state.sprint_disposition(p.get("sprint"), current_generation)
if d == "suppressed":  return   # do not provision; the work is already done
if d == "reopenable": provision # new phases — go
if d == "active":      provision # mid-sprint or idle
```

**Get this backwards and new work is silently blocked forever.** An unkeyed
finish (no `finished_generation`) counts as `reopenable`, never `suppressed`:
we cannot prove it is current, and a rule that blocks on unproven state is how
new work gets stopped.

**Nothing reopens itself.** Only the user, via the dashboard's "Reopen for more
work" button, or a genuine generation change.

---

## Markers and staleness

A `markers` entry is keyed to the **cron name**, not to the project, and carries
the `generation` fingerprint of the plan state that produced it.

```python
if state.marker_is_stale(marker, current_generation): ignore it, and clean it up
```

A stale marker (generation ≠ current) **can never suppress anything**. That is
the entire point of keying on a fingerprint instead of on the project. Keyed on
the project, a marker left by a sprint that ended weeks ago would silently kill
a future sprint on the same codebase — newly provisioned work would never kick
off. If you find yourself wanting to key on the project, re-read this.

---

## Sessions — the same discipline

The system uses session ids. **A session is only ever touched if it is provably
one of ours.**

- Record `session_id` on the job at dispatch time, **in the ledger**, not in
  prose.
- **Never kill, resume, or `--continue` a session the ledger does not name.** A
  session the user started by hand on the same project with the same skill is
  invisible to us and must stay that way — it is frequently the interactive
  session the user is typing into right now.
- `session_search` results are **evidence to look at**, never a handle to act
  on. Filter to ledger-known ids before reading or acting on anything.
- `--continue` / `--resume` on a session that is not ours is **prohibited**:
  those mutate state, and the user's own long-running session is the most
  likely thing to be in range.

Autonomous runs are single-shot by design.

---

## Writing back

When a skill acts, it updates the ledger through the same validated write path:

```python
state.save(path, doc)   # normalise → validate → temp file → os.replace
```

**Never hand-edit `state.json` with a text editor from a skill**, and never
write it with a bare `json.dump`. `save()` validates before touching the
filesystem, so a bad document cannot overwrite a good one, and the write is
atomic so a crash cannot truncate it. A skill that bypasses those two
guarantees puts every other skill's assumptions at risk.

Keep `updated_at` current — the dashboard shows "updated Xs ago" from it.

---

## Failure modes worth knowing

| Symptom | Cause |
|---|---|
| `StateError` on load | the ledger is corrupt; report it, do not "fix" it by guessing |
| a job in the ledger with no matching cron | the dashboard wrote a **placeholder** name; check `created_by` and the `-auto-` infix before assuming |
| two owned sprint jobs for one project | a provisioning race — report it, pick neither |
| `sprint.state` is `finished` but work is waiting | compare `finished_generation` against the current generation; if it differs, it is reopenable |
| nothing to provision despite `enabled: true` | check `path_absent` first, and whether the project is even in the ledger |
