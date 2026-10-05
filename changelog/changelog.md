# Changelog — UNH fork of jlab_pynmr

A record of what changed in this repository and why. Commit messages say *what*
changed line by line; each entry here gives the overview and the reasoning behind it.

Conventions:
- Newest entries first, one heading per date (`YYYY-MM-DD`).
- Each entry: a short title, **What** changed (files or areas touched), and **Why**.
- Note changes that are local to a clone (git config, hooks) and not tracked in the
  repo, so anyone setting up a fresh clone knows to repeat them.
- History before 2026-10-05 is James Maxwell's upstream work (jdmax/jlab_pynmr). It
  is recorded only in the git log.

---

## 2026-10-05

### `unh` is now the default branch of the fork

**What**
- On GitHub, set the default branch of `unhpoltarg/jlab_pynmr` to `unh` (was `master`).
  `jdmax/jlab_pynmr` is unchanged and still defaults to `master`.
- In the local clone, updated `origin/HEAD` to point at `origin/unh`
  (`git remote set-head origin -a`).

**Why**
`unh` is where all UNH work happens. With it as the default, new clones check it out,
the repo page shows it, and new in-fork pull requests target it. Nobody has to remember
to switch away from `master`.

### Repository moved to the unhpoltarg organization; pushes restricted to `unh`

**What**
- Transferred the fork from `ellie-long/jlab_pynmr` to `unhpoltarg/jlab_pynmr` on
  GitHub. The fork relationship to `jdmax/jlab_pynmr` is kept.
- Local clone setup (not tracked in the repo; repeat it in any new clone):
  - `origin` → `https://github.com/unhpoltarg/jlab_pynmr.git`
  - `upstream` (`jdmax/jlab_pynmr`) is fetch-only: its push URL is set to `DISABLED`.
  - `remote.pushDefault=origin` and `push.default=upstream`
  - `.git/hooks/pre-push` rejects any push other than `refs/heads/unh` to
    `unhpoltarg/jlab_pynmr`. That includes tags and pushes to other branches.
- `.claude/settings.local.json`: added `deny` rules so Claude Code cannot skip git
  hooks (`--no-verify`), force-push, or push to `upstream`.

**Why**
UNH polarized-target development should be kept separate from upstream.
- All UNH work lives on the `unh` branch under the group's GitHub organization, not
  a personal account.
- Nothing should be pushed by accident to `master` or to James Maxwell's original
  repository.
- Commits are still authored as `Elena Long <ellie@jlab.org>`, which GitHub credits
  to the `ellie-long` account.

### Local Claude Code notes file (gitignored)

**What**
- `.gitignore`: added `.claude/CLAUDE.md`.
- Created `.claude/CLAUDE.md` in the local clone. It is not tracked. It holds the repo rules
  (push only to `unh`, keep this changelog current), the fresh-clone git setup including
  the pre-push hook script, and a short codebase orientation.

**Why**
It gives Claude Code a durable place in the repo for its working context and rules.
Ignoring it keeps machine-specific notes out of the shared history.

### Changelog added

**What**
- New `changelog/changelog.md` (this file).

**Why**
To keep a readable, human-level history of changes and the reasons for them,
alongside commit messages.
