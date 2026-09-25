# One skill repo, two harnesses: Hermes Agent + Claude Code

**Scope:** how to lay out a public GitHub repo so the same skill installs and works on
**Hermes Agent** (`hermes`, v0.21.3) and **Anthropic's Claude Code** (docs current to v2.1.282,
Sept 2026).

**Bottom line up front (the high-risk item):** a single `SKILL.md` loads unmodified on both
harnesses. The intersection of "fields both accept" is
`name`, `description`, `allowed-tools`, `license`, `compatibility`, `metadata`.
Claude Code **ignores unknown frontmatter fields silently** (documented, quoted below), and
Hermes reads only the keys it knows and ignores the rest (verified empirically). So no field
you add can break the other harness at load time. The real incompatibility is **not
frontmatter — it is the directory.** The two harnesses look in different project folders, and
that is what the layout has to solve.

**Author's note on evidence:** every Hermes claim marked ✅ was executed on this machine
(Hermes Agent v0.21.3, git `8a8bd93e`). Every Claude Code claim is from Anthropic's official
docs or the official changelog, **except** the two explicitly marked *unverified* — the
Claude Code CLI is not installed on this machine, so no Claude Code behavior was executed here.

---

## 1. Hermes skill discovery

### 1.1 The directory layout Hermes scans

Confirmed three ways — `--help` output, source, and the docs — and they agree.

**CLI (`/home/user/.local/bin/hermes skills --help`) ✅:**

```
    trust               Trust a project so its repo-local skills
                        (./.hermes/skills, ./.agents/skills) load
```

**Source of truth** — `/home/user/.hermes/hermes-agent/agent/skill_utils.py:415` ✅:

```python
PROJECT_SKILLS_SUBDIRS = (os.path.join(".hermes", "skills"), os.path.join(".agents", "skills"))
```

Hermes resolves the project root as the **nearest ancestor containing `.git`**
(`find_project_root()`, `skill_utils.py:420` ✅; it walks up to 64 levels and explicitly
returns `None` if that root is `$HOME`). So the complete scan list is:

| Location | Scope | Notes |
|---|---|---|
| `<root>/.hermes/skills/` | project, Hermes-native | ✅ verified |
| `<root>/.agents/skills/` | project, cross-tool convention | ✅ verified |
| `~/.hermes/skills/<profile>/skills/` | profile-local, primary | `get_all_skills_dirs()`, `skill_utils.py:398` |
| `skills.create_dir` (config) | profile-local | optional redirect |
| `skills.external_dirs` (config) | extra dirs, e.g. `~/.agents/skills`, `/shared/team-skills` | `config_defaults.py:1350` |

**Category subdirectories: yes, at any depth.** Discovery is `os.walk(..., followlinks=True)`
looking for the literal filename `SKILL.md` (`iter_skill_index_files()`,
`skill_utils.py:761` ✅). Verified ✅: a skill at `.agents/skills/cat/alpha-skill/SKILL.md`
and one at `.agents/skills/l1/l2/l3/deep-skill/SKILL.md` both loaded. The category dir is
cosmetic for loading but *is* surfaced as the `Category` column in `hermes skills list`
(`skills_hub.py:262` — "children without their own SKILL.md").

**Not scanned:** `.claude/skills/`. I tested this directly ✅ — a skill that existed **only**
under `.claude/skills/` was invisible to `hermes skills list`; the same skill under
`.agents/skills/` was listed. This is the single most important discovery fact in this
document. (Ironically, Hermes' *Skills Hub installer* does know `.claude/skills/` as a
source path when fetching from a remote repo: `_STANDARD_BASE_PATHS = ("skills/",
".agents/skills/", ".claude/skills/")`, `tools/skills_hub_skillssh.py:55` ✅ — but that is the
remote-fetch path, not local project discovery.)

### 1.2 Project skills require explicit trust (the `hermes skills trust` gate)

Project-local skills do **not** auto-load. This is a deliberate prompt-injection defense —
`skill_utils.py:409-413` ✅:

> Project-local skills (`<root>/.hermes/skills`, `<root>/.agents/skills`; root = nearest
> `.git` ancestor) are a prompt-injection vector if auto-sourced from any clone, so they load
> only when the root is in `skills.trusted_project_dirs`; then they override same-named
> profile/bundled skills.

```bash
hermes skills trust             # trust the enclosing git checkout
hermes skills trust /path/repo  # or name it explicitly
hermes skills untrust           # revoke
```

Trust is persisted in `skills.trusted_project_dirs` in `~/.hermes/config.yaml`; the whole
mechanism can be disabled with `skills.project_discovery: false`. Verified ✅ — the exact
output after trusting my test repo:

```
Trusted: /tmp/hc-test/repo
1 project skill(s) will load in sessions started inside this repo (they take precedence over
same-named profile skills).
```

⚠️ **The trust gotcha that will bite you in automation:** `hermes skills trust` with no
argument resolves the project root through `TERMINAL_CWD`, not the process cwd. In a
non-interactive surface (cron, gateway, subagent) `TERMINAL_CWD` is whatever the surface set,
so the command can fail with `Not inside a git checkout. Run from a project directory or pass
the project root path explicitly.` even though you *are* in the repo. I hit this ✅. **Always
pass the path explicitly** in scripts and cron.

Additional project-skill behaviors worth knowing (docs + `skill_utils.py:495-560` ✅):
- **Precedence:** `project → local (~/.hermes/skills/) → external_dirs`. Project wins; first
  match by name. Verified ✅: with `collide` present in both `.agents/skills/` and
  `.claude/skills/`, Hermes served the `.agents` one. (Only because `.claude` isn't scanned
  at all — see §5.6.)
- **Quarantine:** every project `SKILL.md` is scanned by the same security scanner the Hub
  uses; a `dangerous` verdict removes the skill from the index entirely (fail-closed — a
  scanner crash also quarantines). Content-hash cached under `~/.hermes/cache/`, never in
  your repo.
- **Non-interactive surfaces inherit trust** by project identity via the job's `workdir`
  (`hermes cron` jobs do this), but never auto-trust and never prompt.

### 1.3 Frontmatter fields Hermes reads

There is **no fixed allowlist** — Hermes is a permissive reader. From the docs' documented
SKILL.md format and the source:

| Field | Hermes behavior | Source |
|---|---|---|
| `name` | Skill identity. Overrides the directory name. | docs |
| `description` | Routing text; see truncation in §5.4 | `skill_utils.py:750` |
| `version` | Documented in Hermes' own SKILL.md format; inert | docs |
| `author` | Documented; inert | docs |
| `license` | Documented; inert | docs |
| `platforms` | **Functional** — `[macos\|linux\|windows]`; hides the skill on non-matching hosts | `skill_utils.py:128`, docs |
| `allowed-tools` | Treated as standard/informational. Validator requires it be a **string** if present. | `tools/skills_guard.py:311`, `hermes_cli/agent_plugins.py:137` |
| `metadata.hermes.tags` | Functional — hub/category tagging | `skill_utils.py:626` |
| `metadata.hermes.category` | Functional | docs |
| `metadata.hermes.fallback_for_toolsets` / `requires_toolsets` / `fallback_for_tools` / `requires_tools` / `session_platforms` | **Functional** — conditional show/hide | `skill_utils.py:635-641` |
| `metadata.hermes.config` | **Functional** — declares non-secret `config.yaml` settings | `skill_utils.py:644` |
| `required_environment_variables` | **Functional** — secure setup on load | docs |
| `disable-model-invocation`, `user-invocable`, `argument-hint`, `when_to_use`, `model`, `context`, `agent`, `hooks`, `paths`, `shell`, `effort`, `background`, `disallowed-tools` | **No Hermes handler found — parsed and ignored.** | source search |
| anything else | Ignored | — |

**Validation when Hermes writes a skill** (`tools/skill_manager_tool.py::_validate_frontmatter`,
`_validate_name` ✅) — this is stricter than the *reader*, and only applies to
`skill_manage`/hub installs, not to files merely discovered on disk:

- `MAX_NAME_LENGTH = 64`, `MAX_DESCRIPTION_LENGTH = 1024`, `MAX_SKILL_CONTENT_CHARS = 100_000`
- `VALID_NAME_RE = ^[a-z0-9][a-z0-9._-]*$` — lowercase, digits, `.`, `_`, `-`; must start alphanumeric
- Must start with `---` as the first bytes, close with `\n---\n`, parse as a YAML **mapping**,
  contain **both** `name` and `description`**, and have a non-empty body
- New skills must also fit `SKILL_PROMPT_DESC_LIMIT` (60) chars or creation is refused

So: **`name` + `description` are required by Hermes' writer; not required by Hermes' reader**
(see §5.2) and not required by Claude Code. Ship them anyway.

---

## 2. Claude Code skill discovery

Source: <https://code.claude.com/docs/en/skills> (canonical; `docs.claude.com/en/docs/claude-code/skills` redirects there).

### 2.1 Where Claude Code loads skills from

The docs' "Choose where skills load" table, verbatim in structure:

| Location | Path | Loads in |
|---|---|---|
| Enterprise | `.claude/skills/<skill-name>/SKILL.md` in the managed settings dir | all users on managed machines |
| Personal | `~/.claude/skills/<skill-name>/SKILL.md` | all your projects on this machine |
| **Project** | **`.claude/skills/<skill-name>/SKILL.md`** | **sessions in this repository — commit it** |
| Nested | `<subdir>/.claude/skills/<skill-name>/SKILL.md` | sessions started in or below `<subdir>` |
| Additional dir | `.claude/skills/...` in a `--add-dir` target | that session |
| Plugin | `<plugin>/skills/<skill-name>/SKILL.md` | where the plugin is enabled, as `/plugin:skill` |

Additional documented rules:
- Project skills load from `.claude/skills/` **in the start directory and every parent up to
  the repo root** (so `packages/frontend/` still picks up root skills). In a linked worktree,
  the search stops at the worktree root; since v2.1.277 a worktree with no `.claude/skills`
  falls back to the main checkout.
- Skills in a `.claude/skills/` dir *below* the start dir don't load at startup — only once
  Claude reads/edits a file there. Use `/add-dir` to load sooner (v2.1.257+).
- **Symlinked `<skill-name>` entries are explicitly supported** at enterprise/personal/project
  locations: "Claude Code reads `SKILL.md` from the target and loads the skill once even if
  several locations point at the same target." (Plugin skills handle symlinks differently.)
- Reserved name: never name a skill folder `synced` in any capitalization.
- Legacy `.claude/commands/*.md` still works and accepts the same frontmatter **except `name`
  and `paths`**.

⚠️ **`.agents/skills/` is NOT a Claude Code discovery path.** This is the crux of the layout
problem, and the evidence is strong:
- The string `.agents/skills` appears **zero times** in the entire skills doc page (checked
  programmatically over the full extracted text).
- The skills doc's only mention of cross-tool portability is *format*: "Claude Code skills
  follow the Agent Skills open standard."
- The feature request is long-standing and **closed as a duplicate, not implemented**:
  [anthropics/claude-code#31005](https://github.com/anthropics/claude-code/issues/31005)
  ("Support for AGENTS.md and .agents/skills/"). A user comment in that thread reports:
  *"tested on `v2.1.100`: `.agents/skills/` still returns 'Unknown skill.' per-skill symlinks
  from `.claude/skills/` to `.agents/skills/` work though, so the discovery path is the only
  thing missing."*
- A different commenter notes `.agents/skills` worked in v1.0.117 and was later dropped — so
  this has flip-flopped historically and should not be relied on at any version.
- The Claude Code changelog through **2.1.282 (Sept 22, 2026)** contains **no entry** for
  `.agents/skills` discovery. It *does* record AGENTS.md support landing in **2.1.277**
  ("in a project with no CLAUDE.md, Claude Code reads AGENTS.md instead") — but that is the
  instructions file, not the skills directory. Do not conflate the two.

### 2.2 Claude Code frontmatter

From the docs' **Frontmatter reference**. Key framing sentence: *"All fields are optional.
Only `description` is recommended so Claude knows when to use the skill."*

| Field | Required | Notes |
|---|---|---|
| `name` | No | Display name; defaults to the directory name. For a **personal or project** skill, `name` sets only the display label — **the command still comes from the directory name**. In a plugin skill it sets the command's last segment. |
| `description` | **Recommended** | If omitted, Claude uses the first non-empty line of the markdown body. Combined `description` + `when_to_use` is **truncated at 1,536 characters** in the skill listing (configurable via `skillListingMaxDescChars`). |
| `when_to_use` | No | Appended to `description`; counts toward the 1,536 cap. |
| `argument-hint` | No | Autocomplete hint. |
| `arguments` | No | Named positional args for `$name`. |
| `disable-model-invocation` | No | `true` = manual `/name` only. |
| `user-invocable` | No | `false` = hidden from the `/` menu. |
| `allowed-tools` | No | Pre-approved for the invoking turn. Accepts space-separated string, comma-separated string, or YAML list. |
| `disallowed-tools` | No | Removes tools while the skill is active. |
| `model` | No | Per-turn model override, or `inherit`. |
| `effort` | No | `low\|medium\|high\|xhigh\|max`. |
| `context` | No | `fork` to run in a forked subagent. |
| `agent` | No | Subagent type when `context: fork`. |
| `background` | No | With `context: fork`. Requires v2.1.218+. |
| `hooks` | No | Hooks registered on invocation. |
| `paths` | No | Glob patterns gating auto-activation. |
| `shell` | No | `bash` (default) or `powershell` for `!` blocks. |
| `metadata` | No | Free-form YAML map. Claude Code doesn't act on it and drops a non-map value. |
| `license` | No | Accepted, not acted on. |
| `compatibility` | No | Accepted, not acted on. Max 500 chars. |

### 2.3 Constraints Claude Code imposes

- **Field names are lowercase-hyphenated, except `when_to_use`.**
- **Unknown fields are ignored, not rejected** (the decisive quote, §3).
- Frontmatter is read **only when the opening `---` is the file's first line**. Otherwise the
  whole file, `---` markers included, is treated as skill content.
- If the YAML between the markers doesn't parse, **the skill still loads with no fields set** —
  silent degradation, not an error.
- Booleans accept `yes/no/on/off/1/0` in any case as well as `true/false` (v2.1.218+).
- **No character-level restriction on skill names is documented for Claude Code** — the
  lowercase/hyphen/64-char rules come from the Agent Skills spec (§2.4), and Claude Code
  itself documents only the `synced` reserved name. *Unverified whether Claude Code rejects a
  name violating the spec (e.g. uppercase) — the docs do not say, and I could not run it.*

### 2.4 The Agent Skills open standard (the shared floor)

<https://agentskills.io/specification> — both harnesses claim it; Hermes' docs say skills "are
compatible with the agentskills.io open standard."

| Field | Required | Constraints |
|---|---|---|
| `name` | **Yes** | 1–64 chars; lowercase alphanumerics + hyphens only; no leading/trailing hyphen; no `--`; **must match the parent directory name** |
| `description` | **Yes** | 1–1024 chars, non-empty |
| `license` | No | Name or bundled-license reference |
| `compatibility` | No | Max 500 chars |
| `metadata` | No | String→string map |
| `allowed-tools` | No | Space-separated string. **Experimental**; "support may vary between agent implementations." |

Plus recommended structure: `scripts/`, `references/`, `assets/`; keep `SKILL.md` under
500 lines; reference files one level deep. A `skills-ref validate ./my-skill` reference
validator exists.

---

## 3. The overlap: field-by-field compatibility table

**The verdict that matters, quoted from Anthropic's docs (§ "Frontmatter reference"):**

> "A field name must match the table exactly, hyphens included: **Claude Code ignores a field
> it doesn't recognize without reporting an error.**"
> — <https://code.claude.com/docs/en/skills#frontmatter-reference>

And the corresponding Hermes behavior, verified rather than assumed ✅: `parse_frontmatter()`
(`skill_utils.py:105`) returns a plain dict; consumers read specific keys via
`fm.get(...)`/`frontmatter.get("metadata")`. There is no allowlist check, no unknown-key
rejection, and no warning. **A skill carrying every field in Claude Code's table loaded
cleanly in Hermes** — I built exactly that test case:

```yaml
name: demo-skill
description: Use when testing cross-harness frontmatter compatibility for a shared skills repo.
allowed-tools: Read Grep
version: 1.0.0
license: MIT
compatibility: Requires git
platforms: [linux, macos]
disable-model-invocation: true
user-invocable: false
argument-hint: "[thing]"
totally-unknown-field: hello          # deliberately bogus
metadata:
  hermes:
    tags: [demo]
  author: someone
```

Result ✅: `hermes skills list` showed `demo-skill … enabled`, and a live
`hermes chat --toolsets skills` run returned its full description. The Claude-only fields
(`disable-model-invocation`, `user-invocable`, `argument-hint`) and the outright bogus
`totally-unknown-field` were all inert, with no error, no warning, and no quarantine.

### 3.1 Compatibility matrix

"Load" = does the field prevent the skill from loading.

| Field | Spec | Claude Code | Hermes | Same file, both harnesses? |
|---|---|---|---|---|
| `name` | required | optional; display label only (command = dir name) | **required by the writer**; overrides dir name | ✅ Yes — but see §5.1, keep it == dir name |
| `description` | required | recommended; falls back to first body line | required by the writer; drives routing | ✅ Yes — the one field to get right |
| `allowed-tools` | optional, experimental | optional; string / CSV / YAML list | optional; **must be a string** if present | ⚠️ Use a **space-separated string** — the only form both accept unambiguously |
| `license` | optional | accepted, inert | accepted, inert | ✅ Yes |
| `compatibility` | optional (≤500) | accepted, inert | accepted, inert | ✅ Yes |
| `metadata` | optional (str→str map) | free-form map; non-map dropped | `metadata.hermes.*` **is functional** | ✅ Yes — see §3.2 |
| `version` | — | unknown → ignored | documented, inert | ✅ Yes |
| `author` | — | unknown → ignored | documented, inert | ✅ Yes |
| `platforms` | — | unknown → ignored | **functional** (host-OS gate) | ✅ Yes — but it *silently hides the skill in Hermes* on a mismatched OS |
| `when_to_use` | — | optional | unknown → ignored | ✅ Yes (Claude-only feature) |
| `argument-hint` | — | optional | unknown → ignored | ✅ Yes (Claude-only) |
| `disable-model-invocation` | — | optional | unknown → ignored | ✅ Yes (Claude-only) |
| `user-invocable` | — | optional | unknown → ignored | ✅ Yes (Claude-only) |
| `disallowed-tools` | — | optional | unknown → ignored | ✅ Yes (Claude-only) |
| `model` / `effort` / `context` / `agent` / `background` / `hooks` / `paths` / `shell` | — | optional | unknown → ignored | ✅ Yes (Claude-only) |
| `required_environment_variables` | — | unknown → ignored | **functional** | ✅ Yes (Hermes-only feature) |
| `metadata.hermes.*` | — | unknown key in a map → ignored | **functional** | ✅ Yes (Hermes-only) |
| Any unknown field | — | **ignored, no error** (documented) | **ignored, no error** (verified) | ✅ Yes — confirmed on both sides |

**Conclusion: there is no field that breaks the other harness.** Unknown fields are
tolerated by both, so the frontmatter is genuinely a clean intersection. The residual risks
are behavioral, not structural: a field one harness *acts on* changes how the skill behaves
there and is silently inert in the other (§3.3).

### 3.2 `metadata` is the right home for harness-specific keys

Both harnesses accept a free-form `metadata` map and neither acts on the other's contents.
Nest under a namespaced key:

```yaml
metadata:
  author: your-handle            # spec-friendly, string values
  version: "1.0.0"
  hermes:                        # Hermes reads this subtree
    tags: [pdf, extraction]
```

Claude Code ignores the `hermes` key entirely; Hermes ignores `author`/`version` inside the
map. The agentskills.io spec says `metadata` is "a map from string keys to string values," so
keep leaf values as strings (quote numbers) if you also want claude.ai upload / `package_skill.py`
compatibility (§3.4).

### 3.3 Fields that are silently *asymmetric* (the real trap)

Not load-breaking, but they will make you think a skill is doing something on one harness when
it isn't:

- `platforms:` — active in Hermes (hides the skill on non-matching hosts), invisible in Claude Code.
  Never set it to a single OS in a shared repo unless the skill is genuinely OS-bound.
- `disable-model-invocation: true` — Claude Code won't auto-load; **Hermes will.** In a shared
  repo, "manual invocation only" is not portable.
- `user-invocable: false` — hidden from Claude's `/` menu; Hermes has no equivalent and still
  registers a slash command.
- `allowed-tools` means different things: Claude Code pre-approves tools for the turn (a
  permission grant); Hermes treats it as informational metadata (its own security scanner rates
  it `low`/informational). Don't rely on it to constrain Hermes.
- `required_environment_variables` / `metadata.hermes.config` — Hermes features, inert in Claude Code.

Rule of thumb: **if a field changes behavior, it is a Hermes-only or Claude-Code-only feature
in practice, even though both parse it.**

### 3.4 One hard-failure path to know about (not the local-load path)

Claude Code's *local* loader ignores unknown fields. But when the same skill is uploaded to
**claude.ai / the Skills API / packaged with `package_skill.py`**, only six fields are allowed
and extras are a **hard error**:

> "If you include any field the spec doesn't allow, packaging or upload fails with a hard error
> instead of ignoring the field:
> `Unexpected key(s) in SKILL.md frontmatter: argument-hint. Allowed properties are:
> allowed-tools, compatibility, description, license, metadata, name`"
> — <https://code.claude.com/docs/en/skills#using-skill-frontmatter-outside-claude-code>

So: **the six spec fields are the portable core.** Claude-Code-only fields are safe for a
git-installed repo, and fatal for a claude.ai upload. If your repo advertises claude.ai sync
or API distribution, keep frontmatter to the six and document the CC-only extras in the body.

---

## 4. Recommended layout

### 4.1 The decision

The two harnesses want different project directories and there is no shared path:

- Hermes wants `<root>/.hermes/skills/` or `<root>/.agents/skills/`
- Claude Code wants `<root>/.claude/skills/`

Canonical skills go in **`.agents/skills/`** — the Agent Skills open-standard location.
Rationale: it is the cross-tool convention Hermes explicitly documents as "shared with other
agent CLIs", it's what `vercel-labs/skills` writes for the ~75 agents that support the
standard, and it keeps the tree meaningful for anyone not using Claude Code. Then expose it
to Claude Code with **per-skill symlinks** in `.claude/skills/`.

### 4.2 The layout (no build step)

```
my-skills/                              # the public repo
├── README.md
├── LICENSE
├── .agents/
│   └── skills/                         # ✅ CANONICAL — edit here
│       ├── pdf-extraction/
│       │   ├── SKILL.md
│       │   ├── references/
│       │   └── scripts/
│       └── changelog-writer/
│           └── SKILL.md
└── .claude/
    └── skills/                         # symlink farm, generated once, committed
        ├── pdf-extraction -> ../../.agents/skills/pdf-extraction
        └── changelog-writer -> ../../.agents/skills/changelog-writer
```

**Why per-skill symlinks rather than one directory symlink** (`.claude/skills ->
../.agents/skills`): both work for Hermes — I verified ✅ that Hermes follows a
directory-level symlink in either direction. But a whole-directory symlink is the exact shape
that broke for Claude Code users: [anthropics/claude-code#20820](https://github.com/anthropics/claude-code/issues/20820)
("Not planned") documents that Claude Code writes internal state into
`~/.claude/skills/.system/`, so symlinking the whole `skills/` dir **pollutes the shared
target with Claude's internal files** and leaks them to every other agent reading that
directory. Per-skill symlinks are the shape Anthropic's docs explicitly bless: "a
`<skill-name>` entry in the enterprise, personal, or project location can be a symlink to a
directory elsewhere on disk. Claude Code reads `SKILL.md` from the target and loads the skill
once even if several locations point at the same target." Per-skill links also keep
`.claude/skills/` a real directory, so a future Claude-internal file written there cannot leak
into your canonical tree.

⚠️ *Unverified:* I could not run Claude Code to confirm it resolves these relative symlinks.
The doc sentence above is the basis, and a user report in #31005 corroborates it ("per-skill
symlinks from `.claude/skills/` to `.agents/skills/` work though"). If you want zero
uncertainty, use `--copy` style duplication instead (see §4.4).

**One-line regeneration** (run when you add/remove a skill; the symlinks are committed so
contributors never need to run it):

```bash
mkdir -p .claude/skills
for d in .agents/skills/*/; do
  n=$(basename "$d")
  ln -sfn "../../.agents/skills/$n" ".claude/skills/$n"
done
```

### 4.3 Install commands

**As a project dependency** (each contributor clones and runs once):

```bash
# Hermes — trust the repo so its project skills load
hermes skills trust

# Claude Code — nothing to do; it reads .claude/skills/ on session start
```

**As a user-global install** of your published repo:

```bash
# Hermes
hermes skills install owner/repo/skill-name     # one skill (owner/repo/path form)
hermes skills install https://raw.githubusercontent.com/owner/repo/main/.agents/skills/skill-name/SKILL.md
hermes skills tap add owner/repo                # add the repo as a browsable source
hermes skills search <query> --source skills-sh
```

**Both harnesses at once** — `vercel-labs/skills` (the `npx skills` CLI) installs to many
agents including Claude Code and anything using `.agents/skills/`:

```bash
npx skills add owner/repo --all          # all skills, all supported agents
npx skills add owner/repo -a claude-code --skill '*'
npx skills add owner/repo --list         # what would install
```

Its agent→path table maps **Claude Code → `.claude/skills/`** and **Codex/Cursor/Gemini CLI
and others → `.agents/skills/`**, and it defaults to symlinking from a canonical copy
(`--copy` to force copies). *Unverified here:* I did not run `npx skills add`, and its table
does not list Hermes — check whether it recognizes Hermes before relying on it for
Hermes-side installs.

**Claude Code as a plugin** (alternative to committing `.claude/skills/`): add
`.claude-plugin/plugin.json` to a skill folder and it loads as a plugin
`<name>@skills-dir`. For distribution, a marketplace is
`.claude-plugin/marketplace.json` + `claude plugin marketplace add <repo>` +
`claude plugin install <plugin>@<marketplace>`. Note this is a *third* layout convention and
a plugin skill takes its **command name from frontmatter `name`**, not the directory — a
different name-resolution rule from the project-skill case in §2.2.

### 4.4 Duplication vs symlink

| Option | Pros | Cons |
|---|---|---|
| **Per-skill symlinks (recommended)** | Single source of truth, no build step, committed, updates are `git pull` | Breaks on Windows checkouts with `core.symlinks=false` (they degrade into 10-byte text files — a real failure mode documented in [kingpanther13/Hubitat-local-MCP-server#149](https://github.com/kingpanther13/Hubitat-local-MCP-server/pull/149)) |
| **Copy both trees** | Works everywhere incl. Windows-without-symlinks; trivially inspectable | Two files to keep in sync; drift is silent. If you do this, add a CI check that diffs the trees (that repo's `pr_guard.py check_agents_claude_sync()` is a good model) |
| **Directory symlink** | One link, no per-skill upkeep | Claude Code's `.system/` writes land in your canonical tree (#20820). Avoid. |
| **`.claude/skills` only, plus `skills.external_dirs`** | No symlinks in the repo | Canonical tree is Claude-specific; other standard-convention tools see nothing |

If your audience includes Windows contributors without symlink support, copy the trees and
enforce sync in CI. Say so in the README.

---

## 5. Pitfalls

### 5.1 `name` vs directory name — the harnesses resolve it differently

The spec requires `name` to match the parent directory. In practice they diverge:

- **Hermes:** frontmatter `name` **overrides** the directory name. Verified ✅ — a skill in
  `mismatch-skill/` declaring `name: totally-different` was listed as `totally-different`, and
  `mismatch-skill` did not exist as far as Hermes was concerned.
- **Claude Code:** for a personal/project skill, `name` is **display only**; the command you
  type is the **directory name**. (For *plugin* skills it's the reverse — frontmatter `name`
  wins.)

Consequence: with `name != dirname`, `/totally-different` in Claude Code vs `totally-different`
in Hermes → one of them is unreachable. **Always keep `name` identical to the directory name.**
This also satisfies the agentskills.io validator.

### 5.2 Missing frontmatter: both harnesses degrade differently, and Hermes' writer is stricter

- **Hermes' reader:** a `SKILL.md` with *no* frontmatter still loads ✅ — it appeared in
  `hermes skills list`, and its description fell back to the first body line (`no-fm-skill:
  just body`). `skill_view` returns it. Note that `hermes skills inspect no-fm-skill` then
  fails with `Error: No skill named 'no-fm-skill' found in any source.` — inspect and the
  index disagree, which is confusing when debugging.
- **Claude Code:** if the YAML doesn't parse, "the skill still loads with no fields set," and
  with no `description` it uses the first non-empty markdown line.
- **Hermes' writer** (`skill_manage`, hub install) **rejects** a skill with no `name` or no
  `description`. So a skill that a human drops into the tree by hand can work, yet fail to
  install via the Hub.

Never rely on the fallback. Ship `name` + `description`.

### 5.3 Malformed YAML fails differently

- **Hermes:** falls back to naive `key: value` line splitting, so a broken skill can load with
  garbage values instead of erroring. Verified ✅ in isolation: `name: [unclosed` +
  `description: "x` parsed to `{'name': '[unclosed', 'description': '"x'}` — no exception, wrong
  data. (Hermes' *writer* validator catches this with `YAML frontmatter parse error:`.)
- **Claude Code:** loads with no fields set, silently.

**Unquoted `:` in a description breaks YAML.** `description: Use when: doing X` fails to parse
(`mapping values are not allowed here`). Hermes' line-split fallback rescued it in my test ✅,
which is exactly the kind of accident you don't want to depend on. **Quote any description
containing a colon** — Hermes' own authoring guide calls this out. (Quotes don't count toward
length limits.)

Also: a UTF-8 BOM before the first `---` is tolerated by both (Hermes strips it explicitly;
Claude Code's changelog records a fix for "agents, skills, and commands whose `.md` file
starts with a UTF-8 BOM"). But the opening `---` must be the **first line** for Claude Code —
no leading blank line.

### 5.4 Description truncation — the two harnesses truncate very differently

- **Hermes:** `SKILL_PROMPT_DESC_LIMIT = 60`. In the system-prompt skill index a longer
  description is cut to `desc[:57] + "..."` (`skill_utils.py:741-758`) ✅. Longer than that and
  the routing signal is destroyed. `skill_manage(create)` **refuses** to create a skill whose
  description exceeds 60 chars, telling you to move detail into the body. Hermes' repo
  authoring standard is even stricter: ≤60 chars, one sentence, ending in a period, no
  marketing words, and the trigger must be self-contained in the first 57 characters.
- **Claude Code:** the budget is a **fraction of the model's context window (default 1%)**,
  scaled across *all* skills; combined `description`+`when_to_use` is hard-capped at **1,536
  characters** per entry (configurable), and when the listing overflows Claude Code drops
  descriptions starting with the skills you invoke *least*. `/doctor` estimates the cost.

**These caps are 25× apart, and they truncate opposite ends of the spectrum** — Hermes
punishes long descriptions, Claude Code punishes a catalog with many long ones. The
description that satisfies Hermes' 60-char rule is comfortably inside Claude Code's 1,536 cap,
so **writing to Hermes' 60-char rule is safe for both.** If you need a longer description for
Claude Code routing, put the trigger in the first 57 characters and move the rest into the
body; do not rely on `when_to_use` (Hermes ignores it, and it eats the 1,536 budget).

### 5.5 Name collisions resolve differently, and Hermes can hide your skill

- **Claude Code:** enterprise > personal > project. Nested same-name skills both stay
  available (`/apps/web:deploy` for the nested one). Command-file and skill collisions resolve
  by location. Reserved: a folder named `synced` (any capitalization) is skipped.
- **Hermes:** `project → local (~/.hermes/skills/) → external_dirs`, first-wins by name. A
  project skill silently **shadows** your bundled or profile skill of the same name. Project
  skills are also **quarantined** (invisible to index, `skills_list`, `skill_view`, and slash
  commands) if the security scanner returns `dangerous` — fail-closed, so a scanner crash also
  hides it. Don't name a shared skill the same as a Hermes bundled skill; the local one will
  win inside the repo and nowhere else.

### 5.6 `.claude/skills/` is invisible to Hermes — the trap this whole document exists for

Verified ✅ in both directions: a skill **only** in `.claude/skills/` was not listed by
`hermes skills list`; the same skill under `.agents/skills/` was. Conversely `.claude/skills`
is the *only* project location Claude Code reads. **A repo with skills in only one of the two
directories works on exactly one harness.** Hence §4.

### 5.7 Trust, enablement, and freshness differ

| | Hermes | Claude Code |
|---|---|---|
| Extra step to load a project skill | **Yes** — `hermes skills trust` (per repo) | No — but a workspace-trust dialog is needed for a skill folder that is also a plugin |
| Scan gate | Hub install scan + per-project scan; `dangerous` ⇒ quarantined | Workspace trust dialog; `disableBundledSkills` / `skillOverrides` can hide built-ins |
| Pick up an edit mid-session | `/reload-skills` re-scans `~/.hermes/skills/` | live change detection for `.claude/skills/`; `--add-dir` dirs are watched; restart for added dirs |
| Disable one skill | `hermes skills config` (enable/disable) | `skillOverrides` entry `"name": "off"`, or `user-invocable: false` |

Practical consequence: a contributor who clones your repo and runs Hermes gets a banner —
`◆ N project skill(s) found in … but not loaded — run 'hermes skills trust' to enable them.` —
and **no skills at all** until they do. Put that in the README install steps; it is the single
most likely "it doesn't work" report you'll get.

### 5.8 Filesystem and naming details

- `SKILL.md` is matched **case-sensitively** (Hermes: `if filename in files` with
  `filename="SKILL.md"`) ✅. `skill.md` will be ignored. Claude Code documents the name as
  `SKILL.md` with no case note — *unverified for Claude Code, but matching Hermes' exact
  spelling is free insurance.*
- Hermes prunes `EXCLUDED_SKILL_DIRS` while walking: `.git .github .hub .archive
  .curator_backups .locks .venv venv node_modules site-packages __pycache__ .tox .nox
  .pytest_cache .mypy_cache .ruff_cache` ✅. Don't park skills in any of those.
- Hermes does **not** descend into `references/ templates/ assets/ scripts/` when looking for
  nested skills ✅ (verified: a `references/SKILL.md` did not register as its own skill), so
  you can put reference material there safely. These four are also the only subdirs
  `skill_manage(write_file)` allows ✅ — the same set the spec recommends.
- A category dir (a dir with children but no `SKILL.md` of its own) is treated as a category
  bucket, not a skill ✅.
- Hermes walks with `followlinks=True` ✅, so symlinked skill dirs are followed.

### 5.9 The 100k-char ceiling

`MAX_SKILL_CONTENT_CHARS = 100_000` for Hermes-written skills; 1 MiB per supporting file
(`MAX_SKILL_FILE_BYTES`). Not a cross-harness problem (Claude Code documents no equivalent
limit), but a skill near 100k is bad practice on both — the spec's guidance is <500 lines in
`SKILL.md` with detail in `references/`, loaded on demand.

---

## 6. Where sources disagree, and what I trust

| Disagreement | Resolution |
|---|---|
| Hermes docs say project skills live in `.hermes/skills` + `.agents/skills`; Claude Code docs list only `.claude/skills*` | **Not a contradiction — a real gap.** Both are correct about their own harness. Trust both; this is why the layout needs a symlink farm. |
| `.agents/skills` "worked in Claude Code v1.0.117" (user report) vs "still returns Unknown skill" on v2.1.100 (user report) vs absent from the v2.1.282 changelog | **Trust the changelog's silence + the two later reports.** Do not target `.agents/skills` for Claude Code. |
| Hermes CLI `--help` vs Hermes website docs | **They agreed** on every point I checked (project dirs, trust gate, precedence, SKILL.md format). Where the CLI and source were both available I preferred those, per the task's instruction — the source is what actually runs. |
| Agent Skills spec says `name`/`description` are **required**; Claude Code says **all fields are optional** | Both true at different layers. The spec is normative for *packaging/upload*; Claude Code's loader is lenient. Target the spec — it satisfies every layer. |
| Third-party blogs claim "Claude Code reads `.agents/skills/`" | **Contradicted** by Anthropic's docs and changelog. I found no primary source for it. Do not rely on these blogs. |
| `metadata` as "string→string map" (spec) vs "free-form YAML map" (Claude Code) | Use string leaves. Works for both, and keeps `package_skill.py` / claude.ai upload viable. |

---

## 7. Explicitly unverified

Marked rather than guessed, because each would change a recommendation if wrong:

1. **No Claude Code execution.** The CLI is not installed on this machine. Every Claude Code
   behavioral claim is from Anthropic's docs/changelog, not from a run.
2. **Per-skill symlink resolution in Claude Code** — based on the documented symlink support
   sentence plus one corroborating user report, not tested.
3. **Whether Claude Code enforces spec name rules** (lowercase, ≤64, must match parent dir).
   Claude Code documents only the `synced` reserved name. If it *does* enforce them, a
   non-conforming name would be rejected there while Hermes happily accepts uppercase,
   underscores, and dots (verified ✅ — `Upper-Case-Skill` and `under_score` both loaded in
   Hermes). Conforming to the spec is free insurance either way.
4. **Whether `SKILL.md` must be exactly that case in Claude Code.**
5. **Whether `npx skills` (vercel-labs) recognizes Hermes.** Its published agent table does
   not list Hermes; I did not run it.
6. **Hermes' hub install of a `skills/`-rooted repo.** `_STANDARD_BASE_PATHS` includes
   `"skills/"` ✅, so `hermes skills install owner/repo/<skill>` should work for a repo with a
   top-level `skills/`, but I did not run a live hub install against a public repo.
7. **Description-length behavior at the Claude Code boundary** (1,536 cap, 1% budget) is
   documented but not measured here.
8. **Current Claude Code version at time of writing.** Docs were current to v2.1.282
   (Sept 22, 2026). Claude Code ships fast; re-check the changelog for `.agents/skills` before
   publishing, since that single change would delete the need for the symlink farm.

---

## 8. Checklist for a new skill in a shared repo

- [ ] Directory `skills/<name>/` with `SKILL.md`; `name:` == directory name, lowercase,
      hyphens only, ≤64 chars
- [ ] `description:` starts with `Use when <trigger>.` and fits in **60 characters** (Hermes'
      hard ceiling; safely under Claude Code's 1,536); **quote it** if it contains a colon
- [ ] Frontmatter limited to the **six spec fields** (`name`, `description`, `allowed-tools`,
      `license`, `compatibility`, `metadata`) — anything else is dead weight on one harness and
      a hard error on claude.ai upload
- [ ] `allowed-tools` as a **space-separated string** (the only form both accept unambiguously)
- [ ] Harness-specific keys namespaced under `metadata.hermes.*`; Claude-only features
      (`when_to_use`, `argument-hint`, `disable-model-invocation`, `user-invocable`) only if the
      repo is git-install-only — and never `platforms:` unless genuinely OS-bound
- [ ] Detail lives in `references/`, `scripts/`, `templates/`, `assets/` — one level deep, and
      `SKILL.md` under ~200 lines
- [ ] A `.claude/skills/<name>` symlink committed
- [ ] README tells Hermes users to run `hermes skills trust`, and gives the `hermes skills
      trust <path>` form for non-interactive setups
- [ ] CI (optional but recommended): assert every `.agents/skills/*/SKILL.md` has a matching
      `.claude/skills/*` symlink, and that `name` == dirname
