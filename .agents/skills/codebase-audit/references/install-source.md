# Installing and updating this skill

## Where the canonical copy lives

This skill is maintained in the **`hermes-skills`** repo (public), at:

    .agents/skills/<skill-name>/

That is the single source of truth. The copy installed under
`~/.hermes/skills/<category>/<skill-name>/` is what Hermes actually loads, and the two
drift unless you mirror them.

## Updating an installed copy

`skill_manage` (patch / write_file) edits the **installed** copy only. So after changing
one, mirror it back to the repo:

```bash
cp ~/.hermes/skills/<category>/<skill-name>/SKILL.md \
   .agents/skills/<skill-name>/SKILL.md
cp -r ~/.hermes/skills/<category>/<skill-name>/references \
      .agents/skills/<skill-name>/
```

Or the other direction, to take an update from the repo into the installed copy:

```bash
cp .agents/skills/<skill-name>/SKILL.md \
   ~/.hermes/skills/<category>/<skill-name>/SKILL.md
cp -r .agents/skills/<skill-name>/references \
      ~/.hermes/skills/<category>/<skill-name>/
```

Verify with `diff -r .agents/skills/<skill-name> ~/.hermes/skills/<category>/<skill-name>`
(ignore `__pycache__`). Two copies of a skill are two copies of a bug fix; drift here is
silent, which is why the repo ships validators.

## Both harnesses

The frontmatter of every `SKILL.md` in this repo is a clean intersection of what Hermes
Agent and Claude Code accept (`name`, `description`, and optionally `allowed-tools`,
`license`, `metadata`). **Both harnesses ignore unknown frontmatter fields rather than
rejecting them**, so no field here breaks the other. The only real incompatibility is the
directory, and the repo handles both:

- **Hermes Agent** reads `.agents/skills/` in a project (behind `hermes skills trust`),
  and `~/.hermes/skills/**/SKILL.md` for user-level skills.
- **Claude Code** reads `.claude/skills/<name>/SKILL.md`.

So `.claude/skills/<name>` holds **per-skill symlinks** into `.agents/skills/`. Do not
replace them with a single directory symlink: Claude Code writes internal state into
`~/.claude/skills/.system/`, so symlinking the whole directory leaks those files into the
shared canonical tree for every other agent reading it. See
`docs/harness-compatibility.md` for the full reasoning and citations.

Regenerate the symlinks after adding or removing a skill:

```bash
for d in .agents/skills/*/; do
  n=$(basename "$d"); ln -sfn "../../.agents/skills/$n" ".claude/skills/$n"
done
```

## These skills are standalone

Nothing in them depends on the Alexa bridge. a voice bridge wires them in by name (the
relay loads one with `hermes chat -s <skill-name>`), so they work in any Hermes session on
the machine, not only the voice one.
