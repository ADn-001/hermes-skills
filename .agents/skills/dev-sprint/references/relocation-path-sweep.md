# Relocating a project: the path sweep that is easy to under-do

> **Recovered from an installed mirror, 2026-09-30.** This file existed only
> under `~/.hermes/skills/`, never in this repository, and a sync of the
> obvious direction (canonical -> installed) would have deleted it. Nothing
> compared the two trees, so nothing noticed. It is here now, and
> `tools/tests/test_skill_hygiene.py` checks mirrors in **both** directions —
> a file present only in a mirror fails there rather than at the next
> project move.

Moving a project out of `$HOME` into `~/projects/` breaks references in more
places than the project's own files. The dangerous cases are the ones that
**look correct while being wrong**.

## The trap: the config is right and the job still fails

A cron job can have a correct `workdir` and still fail, because the thing it
actually executes lives one level down:

```
cron job workdir:  ~/projects/alexa-hermes            <- already repointed
job script:        alexa_cron_bridge_sync.sh          <- a bare NAME
that script:       exec python3 ~/alexa-hermes/sync_hermes_cron.py
                                                    ^^^^^^^^^^^^^^^^^^^^^^^^
                                                    still the pre-move path
```

This cost **47 consecutive failures** before anyone noticed, because the
dashboard showed a healthy-looking job with a correct workdir. Repointing
the job's own fields fixed nothing.

**Lesson: when a `script:` value is a bare filename, resolve it.** The script
lives in `~/.hermes/scripts/`, not in the job's workdir, and the path that
matters is inside it. Follow the indirection:

```bash
python3 -c "import json,os;[print(j.get('script')) for j in json.load(open(os.path.expanduser('~/.hermes/cron/jobs.json')))['jobs']]"
find ~ -name '<that script>' -not -path '*/.git/*'
grep -n '~/<old-path>' <that script>
```

## Sweep order

1. **jobs.json** — `workdir`, `prompt`, `command`, and also `last_error`
   (which embeds a stale path as *text*; harmless but confusing later)
2. **The script each job runs**, if `script:` is a bare name
3. **systemd units** — `WorkingDirectory=`, `ExecStart=`, `ReadWritePaths=`
4. **Skills** — hardcoded paths in `SKILL.md` and `references/`
5. **Then verify by running**, not by reading

## Rewrite rules

- **Longest prefix first.** `~/alexa-hermes/expansion_skills` must be
  replaced *before* `~/alexa-hermes`, or you get
  `~/projects/alexa-hermes/projects/alexa-hermes/...`. Always grep the
  result for `/projects/projects`.
- **Rewrite in place, never delete-and-recreate.** Recreating a job resets its
  schedule history, `failure_streak`, and `completed` counts.
- **Back up first**, and diff old vs new to confirm *only* path-bearing fields
  changed — names, schedules, `enabled` and `repeat.completed` must be
  untouched.
- **A path that does not exist may be an output, not a break.**
  `reports/weekly-report.md` is written by a job that has not run yet. Check
  whether the job is supposed to create it before "fixing" it.

## What to leave alone

- **Session logs and request dumps** under `~/.hermes/sessions/` — historical
  records, not live config. Rewriting history is worse than a stale string.
- **`.curator_backups/`** — snapshots of prior state, same reasoning.
- Anything under a `.git/` directory.

Restrict the sweep to live surfaces: `~/.hermes/scripts`, `~/.config/systemd`,
`~/.hermes/skills`, `~/.hermes/plugins`, crontabs, `/etc/cron.d`.

## Verify by running

Reading config proves what you *wrote*. Running proves it *works*:

```bash
bash ~/.hermes/scripts/<the script>          # does it exit 0?
hermes cron run <job-id>                     # does the scheduler agree?
hermes cron list                             # failure_streak back to 0?
```

A job showing `last_status: ok` and `failure_streak: 0` is the only real
proof the relocation is finished. Reading a corrected workdir is not.
