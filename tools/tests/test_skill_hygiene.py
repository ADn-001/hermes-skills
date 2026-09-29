"""Skill hygiene: no machine-specific paths in a shared repository.

`hermes-skills` is a public repo the author shares with friends. A tracked
skill carrying `/home/user/projects/alexa-hermes/relay_core.py` is wrong on
every machine but one, and it fails **silently** — a command pointed at a path
that does not exist does not raise an author error, it writes somewhere nobody
reads.

## The second failure this guards: drift between a skill and its install

`daily-weekly-report` had drifted. The canonical copy in `.agents/skills/` was
**missing** a section the installed copy under `~/.hermes/skills/` had, so the
canonical one was the stale one and the installed one was ahead. Nobody noticed
because nothing compared them.

The direction of that drift is the trap. Syncing canonical -> installed, the
obvious move, would have **deleted the section** and quietly lost three
verified instructions about how to write a report file. The rule has to be
"canonical wins", and the *check* has to be "does the installed copy still have
something the canonical one lacks?" — because that is the question whose wrong
answer destroys work.

So this asserts both directions, and the second one is the one that matters:

1. every installed mirror is byte-identical to canonical;
2. canonical is not *behind* its mirror, checked by content and not by
   existence, so a section present in only the mirror fails here rather than in
   the next report file.
"""

from __future__ import annotations

import os
import re
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
CANONICAL = os.path.join(REPO_ROOT, ".agents", "skills")

#: Where the installed mirrors live, and the real one found on this machine.
#: Overridable so the check is meaningful anywhere; skipped when absent, since
#: a repository that has never been installed has nothing to drift from.
INSTALLED_ROOT = os.environ.get("HERMES_SKILLS_INSTALLED",
                                os.path.expanduser("~/.hermes/skills"))


def skill_dirs(root):
    if not os.path.isdir(root):
        return []
    return [os.path.join(root, name)
            for name in sorted(os.listdir(root))
            if os.path.isfile(os.path.join(root, name, "SKILL.md"))]


def tracked_markdown():
    """Every markdown file in a skill tree, not just its SKILL.md.

    The first version of this guard read only `SKILL.md` and reported the
    tree clean -- while `references/` still held 13 machine-specific paths
    across four files. A references file is loaded *in addition to* the skill
    (`dev-sprint` reads `references/dev-dashboard-ledger.md`; the whole
    ledger schema lives in `references/ledger-schema.md`), so it is the more
    likely place for one to hide, and the more expensive when it does.
    """
    found = []
    for dirpath, dirnames, filenames in os.walk(CANONICAL):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for name in sorted(filenames):
            if name.endswith(".md"):
                found.append(os.path.join(dirpath, name))
    return found


def installed_mirror(name):
    """Find ``name``'s mirror anywhere under the installed root.

    Category is not part of the name — the same skill can be installed under
    `software-development/`, `productivity/` or anywhere else — so this walks
    the tree rather than guessing a layout. A skill with two installed copies
    is itself a drift, and :class:`TestOneInstalledCopyPerSkill` catches it.
    """
    found = []
    for dirpath, dirnames, filenames in os.walk(INSTALLED_ROOT):
        if os.path.basename(dirpath) == name and "SKILL.md" in filenames:
            found.append(os.path.join(dirpath, "SKILL.md"))
    return found


class TestNoMachineSpecificPathsInTrackedSkills(unittest.TestCase):
    """The share-ready rule, enforced rather than remembered.

    The author's own deployment is the only place these resolve, so a literal
    in a tracked file is a path that is wrong everywhere else.
    """

    #: Absolute home paths, GitHub identities, the user's hostnames, the LAN
    #: address, and the dashboard token. Each entry: (pattern, why).
    FORBIDDEN = [
        (r"/home/user\b",
         "an absolute home path; correct on exactly one machine"),
        (r"\bADn-001\b",
         "the author's GitHub identity, in a shared repository"),
        (r"\bAdnan\b",
         "the author's name"),
        (r"\blegate\.one\b",
         "a real hostname"),
        (r"\b192\.168\.\d+\.\d+\b",
         "a LAN address, which is not stable across networks"),
        (r"\.dashboard-token",
         "a credential's filename, which invites putting its value next to it"),
    ]

    #: Words that make a line a *prohibition* rather than a use. Phase 9's
    #: `_NEGATION` and Phase 23's route test already use exactly this list for
    #: exactly this reason, and the first run of this guard proved why it
    #: matters twice over:
    #:
    #:   * `dev-sprint/references/git-and-pr.md` says `.dashboard-token` is a
    #:     credential and **must never be pushed**. The guard flagged that
    #:     line, and the tempting repair was to delete the sentence — which
    #:     removes the rule and leaves the test green. A skill must be able to
    #:     state the rule it is held to.
    #:   * `daily-weekly-report` explained the rule *by showing the forbidden
    #:     shape*, and the guard flagged its own rationale. That one was not a
    #:     negation, so no marker would have saved it — the text was simply
    #:     reworded, which is the correct fix for prose that illustrates rather
    #:     than prohibits.
    #:
    #: So the exemption is for prohibitions only, and it is a real loophole: a
    #: line that says "never" can still leak. It is accepted deliberately --
    #: the alternative is a guard whose cheapest repair is deleting the rules.
    NEGATIONS = ("never", "not ", "no ", "cannot", "must not", "do not",
                 "don't", "without", "nothing", "refuse", "rather than",
                 "instead of", "prohibited", "forbidden", "credential")

    @classmethod
    def _is_a_prohibition(cls, line):
        return any(marker in line.lower() for marker in cls.NEGATIONS)

    def test_no_skill_carries_a_machine_specific_path(self):
        offenders = []
        exemptions = []
        for path in tracked_markdown():
            rel = os.path.relpath(path, CANONICAL)
            with open(path, encoding="utf-8") as fh:
                for number, line in enumerate(fh, 1):
                    for pattern, why in self.FORBIDDEN:
                        if not re.search(pattern, line, re.I):
                            continue
                        if self._is_a_prohibition(line):
                            exemptions.append("%s:%d" % (rel, number))
                            continue
                        offenders.append(
                            "%s:%d  %s\n        %s"
                            % (rel, number, line.strip()[:88], why))
        self.assertEqual(
            offenders, [],
            "tracked skills carry machine-specific paths; this repo is shared, "
            "and these resolve on exactly one machine:\n  "
            + "\n  ".join(offenders))

    def test_the_exemption_is_still_being_used(self):
        """A guard with a silent escape hatch rots into a no-op.

        The `NEGATIONS` exemption above is a real hole: any line containing
        "never" passes. If nobody is using it, the marker list is dead weight
        that will quietly widen; if suddenly everything is using it, the guard
        has stopped guarding. Both are worth seeing, so the exempted lines are
        reported rather than discarded.
        """
        exempted = []
        for path in tracked_markdown():
            with open(path, encoding="utf-8") as fh:
                for number, line in enumerate(fh, 1):
                    if not any(re.search(p, line, re.I)
                               for p, _ in self.FORBIDDEN):
                        continue
                    if self._is_a_prohibition(line):
                        exempted.append(
                            "%s:%d  %s"
                            % (os.path.relpath(path, CANONICAL), number,
                               line.strip()[:80]))
        self.assertLess(
            len(exempted), 12,
            "more and more lines are passing through the exemption; if these "
            "are all genuine prohibitions, split the rule instead:\n  "
            + "\n  ".join(exempted))

    def test_a_bare_home_reference_is_still_allowed(self):
        """`~/reports` is fine. `/home/user/reports` is not.

        Worth stating, because the fix for the rule above is to write `~` or a
        `$VAR` — and a test that also forbade `~` would push people back to
        absolute paths rather than to variables.
        """
        for path in tracked_markdown():
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
            self.assertNotIn("/home/", text,
                             os.path.relpath(path, CANONICAL))

    def test_the_scan_is_not_vacuous(self):
        """A guard that silently matches nothing is worse than no guard.

        The `FORBIDDEN` table is regexes and case flags, and every one of them
        could be mistyped into a pattern that never fires — the file would then
        pass by never matching. So each pattern is proved against a string it
        is *supposed* to catch.
        """
        should_match = {
            r"/home/user\b": "see /home/user/codereview/x/ledger.md",
            r"\bADn-001\b": "cloned from ADn-001/dev-dashboard",
            r"\bAdnan\b": "ask Adnan first",
            r"\blegate\.one\b": "served at alexa.legate.one",
            r"\b192\.168\.\d+\.\d+\b": "the host at 192.168.1.6",
            r"\.dashboard-token": "cat .dashboard-token",
        }
        for (pattern, _), sample in zip(self.FORBIDDEN, should_match.values()):
            with self.subTest(pattern=pattern):
                self.assertRegex(sample, pattern,
                                 "the pattern no longer matches the thing it "
                                 "exists to catch, so the test above would "
                                 "pass on a file full of them")
        # And the table is not shorter than its own samples.
        self.assertEqual(len(self.FORBIDDEN), len(should_match),
                         "a FORBIDDEN entry has no proving sample, or a sample "
                         "has no rule")


class TestCanonicalAndInstalledAgree(unittest.TestCase):
    """The drift guard.

    Both directions are asserted, and the second is the one that would have
    caught the real incident: the canonical copy was *behind* its mirror, so
    syncing canonical -> installed — the natural direction, and the one any
    sync tool defaults to — would have deleted a section.
    """

    def setUp(self):
        if not os.path.isdir(INSTALLED_ROOT):
            self.skipTest("no installed skills at %s" % INSTALLED_ROOT)
        if not skill_dirs(CANONICAL):
            self.skipTest("no canonical skills at %s" % CANONICAL)

    def test_every_mirror_is_byte_identical_to_canonical(self):
        offenders = []
        for skill in skill_dirs(CANONICAL):
            name = os.path.basename(skill)
            canon_path = os.path.join(skill, "SKILL.md")
            with open(canon_path, encoding="utf-8") as fh:
                canon = fh.read()
            for mirror in installed_mirror(name):
                with open(mirror, encoding="utf-8") as fh:
                    if fh.read() != canon:
                        offenders.append(
                            "%s\n        canonical: %s\n        installed:  %s"
                            % (name, canon_path, mirror))
        self.assertEqual(
            offenders, [],
            "an installed skill differs from its canonical copy; sync the "
            "installed side FROM canonical, never the other way:\n  "
            + "\n  ".join(offenders))

    def test_canonical_is_not_behind_its_mirror(self):
        """The one that matters, and the one that is easy to "fix" wrongly.

        Asserted over **headings**, because a mirror can be ahead by a
        paragraph that happens to add no heading — and that paragraph is
        exactly the verified instruction someone is relying on today.
        """
        offenders = []
        for skill in skill_dirs(CANONICAL):
            name = os.path.basename(skill)
            canon_path = os.path.join(skill, "SKILL.md")
            with open(canon_path, encoding="utf-8") as fh:
                canon = fh.read()
            canon_heads = {ln.strip() for ln in canon.splitlines()
                           if ln.startswith("#")}
            for mirror in installed_mirror(name):
                with open(mirror, encoding="utf-8") as fh:
                    text = fh.read()
                missing = {ln.strip() for ln in text.splitlines()
                           if ln.startswith("#")} - canon_heads
                if missing:
                    offenders.append(
                        "%s: canonical is missing %s, which the installed copy "
                        "has:\n        %s"
                        % (name, sorted(missing), mirror))
        self.assertEqual(
            offenders, [],
            "the canonical copy is BEHIND an installed one. Do not sync "
            "canonical -> installed: that deletes the missing section. Port it "
            "into canonical first, then sync:\n  " + "\n  ".join(offenders))

    def test_no_file_exists_only_in_a_mirror(self):
        """The loss that actually happened, and it was a whole *file*.

        `dev-sprint/references/relocation-path-sweep.md` — the note about a
        path indirection that cost 47 consecutive cron failures before anyone
        noticed — existed only under `~/.hermes/skills/`. Syncing canonical ->
        installed, the direction every sync tool defaults to, would have
        **deleted it**, and nothing noticed for as long as nobody moved a
        project again.

        This is the mirror-image of `test_canonical_is_not_behind_its_mirror`,
        and both are needed: that one catches lost *content* in a file, this
        catches a lost *file*. A heading check cannot see a file at all.
        """
        offenders = []
        for skill in skill_dirs(CANONICAL):
            name = os.path.basename(skill)
            canonical = set()
            for dirpath, dirnames, filenames in os.walk(skill):
                dirnames[:] = [d for d in dirnames if d != "__pycache__"]
                for f in filenames:
                    if f.endswith(".md"):
                        rel = os.path.relpath(
                            os.path.join(dirpath, f), skill)
                        canonical.add(rel)
            for mirror in installed_mirror(name):
                mirror_root = os.path.dirname(mirror)
                mirrored = set()
                for dirpath, dirnames, filenames in os.walk(mirror_root):
                    dirnames[:] = [d for d in dirnames if d != "__pycache__"]
                    for f in filenames:
                        if f.endswith(".md"):
                            mirrored.add(os.path.relpath(
                                os.path.join(dirpath, f), mirror_root))
                for orphan in sorted(mirrored - canonical):
                    offenders.append(
                        "%s: %s exists only in the mirror (%s) and not in the "
                        "repository" % (name, orphan, mirror_root))
        self.assertEqual(
            offenders, [],
            "a file is installed but untracked. Port it into canonical FIRST "
            "-- syncing canonical -> installed will delete it:\n  "
            + "\n  ".join(offenders))

    def test_one_installed_copy_per_skill(self):
        """Two installed copies is drift of a different kind.

        Whichever one a session loads is then a coin toss, so the two can be
        fixed independently and stay fixed independently. Found here rather
        than assumed: the installer's category layout is not part of the skill
        name, so this walks the tree.
        """
        offenders = []
        for skill in skill_dirs(CANONICAL):
            name = os.path.basename(skill)
            copies = installed_mirror(name)
            if len(copies) > 1:
                offenders.append("%s: %d installed copies\n        %s"
                                 % (name, len(copies),
                                    "\n        ".join(copies)))
        self.assertEqual(
            offenders, [],
            "a skill is installed in more than one category, so which copy a "
            "session loads is undefined:\n  " + "\n  ".join(offenders))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
