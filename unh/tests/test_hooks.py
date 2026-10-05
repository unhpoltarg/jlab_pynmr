"""Every UNH change to a JLab file must be labelled, so unh/strip_unh.py can remove it cleanly.

The main check strips all UNH hooks from each JLab file this branch changed and compares the result
with JLab's own version of that file (the last upstream commit merged in). Any difference is an
unlabelled UNH change.

Run from the repo root in the pynmr env:
    conda run -n pynmr --no-capture-output python -m pytest unh/tests -p no:cacheprovider
"""
import difflib
import fnmatch
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from unh import strip_unh as su

# Files PyNMR itself rewrites while it runs; differences there are run data, not code
RUNTIME_STATE = ['config/*session.yaml', 'config/*history.json', 'data/recent_baselines.txt']


def git(*args):
    return subprocess.run(['git', *args], cwd=REPO, capture_output=True)


def jlab_base():
    """Last upstream (JLab) commit merged into this branch, or None if the upstream remote isn't set up."""
    r = git('merge-base', 'HEAD', 'upstream/master')
    return r.stdout.decode().strip() if r.returncode == 0 else None


def normalised(text):
    """Lines without line-ending or trailing-whitespace differences."""
    return [line.rstrip() for line in text.replace('\r\n', '\n').split('\n')]


# --- Marker parsing ------------------------------------------------------------------------------------

JLAB_TEXT = """def f(self):
    a = 1
    b = 2
    return a + b
"""

UNH_TEXT = """def f(self):
    a = 1
    # >>> UNH-HOOK freq-window: why
    # JLab: b = 2
    b = 3
    c = 4
    # <<< UNH-HOOK freq-window
    d = 5   # UNH-HOOK nmr-sim
    # >>> UNH-HOOK data-streamer
    e = 6
    # <<< UNH-HOOK data-streamer
    return a + b
"""


def test_strip_all_restores_jlab_text():
    new, hooks = su.strip_text(UNH_TEXT)
    assert new == JLAB_TEXT
    assert [(h['feature'], h['kind']) for h in hooks] == [
        ('freq-window', 'block'), ('nmr-sim', 'line'), ('data-streamer', 'block')]


def test_strip_one_feature_keeps_the_others():
    new, _ = su.strip_text(UNH_TEXT, {'nmr-sim'})
    assert 'd = 5' not in new
    assert 'b = 3' in new and '# JLab: b = 2' in new and 'e = 6' in new


def test_strip_keeps_crlf_line_endings():
    new, _ = su.strip_text(UNH_TEXT.replace('\n', '\r\n'))
    assert new == JLAB_TEXT.replace('\n', '\r\n')


def test_jlab_line_keeps_its_relative_indent():
    text = "    # >>> UNH-HOOK freq-window\n    # JLab: if x:\n    # JLab:     y()\n    # <<< UNH-HOOK freq-window\n"
    assert su.strip_text(text)[0] == "    if x:\n        y()\n"


@pytest.mark.parametrize('text, message', [
    ("# >>> UNH-HOOK nmr-sim\nx = 1\n", 'never closed'),
    ("x = 1\n# <<< UNH-HOOK nmr-sim\n", 'without a start'),
    ("# >>> UNH-HOOK nmr-sim\n# <<< UNH-HOOK freq-window\n", 'ends as'),
    ("# >>> UNH-HOOK nmr-sim\n# >>> UNH-HOOK nmr-sim\n", 'inside the block'),
    ("# >>> UNH-HOOK nmr-sim\nx = 1   # UNH-HOOK nmr-sim\n# <<< UNH-HOOK nmr-sim\n", 'tagged line inside'),
    ("# JLab: x = 1\n", 'outside'),
    ("x = 1   # UNH-HOOK no-such-feature\n", 'unknown feature'),
])
def test_bad_markers_are_rejected(text, message):
    with pytest.raises(su.HookError, match=message):
        su.parse(text)


# --- This repository ----------------------------------------------------------------------------------

def test_every_hook_in_the_repo_is_well_formed():
    files = su.hooked_files()
    assert files, 'no UNH-HOOK markers found outside unh/'
    for rel in files:
        su.parse((REPO / rel).read_text(encoding='utf-8'))


def test_feature_paths_exist():
    for feature, info in su.FEATURES.items():
        for p in info['paths']:
            assert (REPO / p).exists(), f'{feature}: {p} is listed in strip_unh.FEATURES but missing'


@pytest.mark.parametrize('features', [None] + [{f} for f in su.FEATURES], ids=lambda f: 'all' if f is None else next(iter(f)))
def test_python_still_compiles_after_strip(features):
    for rel in su.hooked_files():
        if rel.endswith('.py'):
            text = (REPO / rel).read_text(encoding='utf-8')
            compile(su.strip_text(text, features)[0], rel, 'exec')


def test_unh_changes_to_jlab_files_are_all_labelled():
    base = jlab_base()
    if base is None:
        pytest.skip('no upstream/master ref (set up the upstream remote, see .claude/CLAUDE.md)')
    r = git('diff', '--name-status', '-M', base)
    assert r.returncode == 0, r.stderr.decode()
    problems = []
    for row in r.stdout.decode('utf-8').splitlines():
        status, *paths = row.split('\t')
        if all(p.startswith(su.UNH_OWNED) or any(fnmatch.fnmatch(p, pat) for pat in RUNTIME_STATE) for p in paths):
            continue
        if status != 'M':
            problems.append(f'{status} {" -> ".join(paths)}: JLab files are never added, deleted or renamed; '
                            f'put new UNH files in unh/')
            continue
        rel = paths[0]
        jlab = git('show', f'{base}:{rel}').stdout.decode('utf-8')
        ours = (REPO / rel).read_bytes().decode('utf-8')
        try:
            stripped = su.strip_text(ours)[0]
        except su.HookError as e:
            problems.append(f'{rel}: {e}')
            continue
        if normalised(stripped) != normalised(jlab):
            diff = difflib.unified_diff(normalised(jlab), normalised(stripped), f'JLab {rel}',
                                        f'{rel} with UNH hooks removed', lineterm='', n=1)
            problems.append('\n'.join(list(diff)[:40]))
    assert not problems, ('Unlabelled UNH changes to JLab files (wrap them in UNH-HOOK markers, '
                          'see unh/README.md):\n\n' + '\n\n'.join(problems))
