"""Find or remove the UNH changes to JLab's PyNMR files.

UNH-only code lives in unh/. Where it has to touch a JLab file, the change is marked
(see unh/README.md, "Labelling UNH changes"):

    # >>> UNH-HOOK <feature>: why
    ...lines UNH added...
    # JLab: <a JLab line this block replaced, kept so it can be put back>
    # <<< UNH-HOOK <feature>

    one_added_line()   # UNH-HOOK <feature>

Removing a feature deletes its blocks and tagged lines, puts each `# JLab:` line back, and
deletes the feature's files in unh/. Removing everything also deletes unh/ itself.

Run from anywhere in the repo (standard library only, no conda env needed):
    python -m unh.strip_unh                              # dry run: list every UNH change
    python -m unh.strip_unh --apply                      # remove all of them, and unh/
    python -m unh.strip_unh --feature nmr-sim --apply    # remove one feature
"""

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# Every feature tag in use, with the unh/ files that belong only to it.
# A new UNH feature adds its tag here (unh/tests/test_hooks.py rejects unknown tags).
FEATURES = {
    'freq-window': {
        'about': 'Interactive NMR frequency window on the Run tab',
        'paths': ['unh/tests/test_freq_window.py'],
    },
    'data-streamer': {
        'about': 'Stream each finished event to LabView-NMR-Fitter',
        'paths': ['unh/data_streamer.py', 'unh/data_streamer.yaml', 'unh/tests/test_data_streamer.py'],
    },
    'nmr-sim': {
        'about': 'Simulated deuteron NMR as a Test-mode data source (TestSim profile)',
        'paths': ['unh/nmr_sim'],
    },
    'fork-tools': {
        'about': 'Repository tooling for the UNH fork (local Claude Code notes)',
        'paths': [],
    },
}

# Paths that belong to the UNH fork as a whole, not to JLab: never scanned for hooks.
# .claude/settings.local.json holds the fork's Claude Code push guardrails; JSON cannot carry marker comments.
UNH_OWNED = ('unh/', 'changelog/', 'notes/', '.claude/')

_FEATURE = r'([a-z][a-z0-9-]*)'
START = re.compile(r'^\s*# >>> UNH-HOOK ' + _FEATURE + r'\b')
END = re.compile(r'^\s*# <<< UNH-HOOK ' + _FEATURE + r'\b')
LINE = re.compile(r'# UNH-HOOK ' + _FEATURE + r'\b')
JLAB = re.compile(r'^(\s*)# JLab:(?: (.*))?$')


class HookError(ValueError):
    """Badly formed UNH-HOOK markers."""


def parse(text):
    """Find the UNH hooks in a file's text.

    Args:
        text: file contents

    Returns:
        list of dicts: {'feature', 'kind' ('block' or 'line'), 'start', 'end'} with 0-based,
        inclusive line indices (start == end for a tagged line)

    Raises:
        HookError: unbalanced or mismatched markers, nested blocks, `# JLab:` outside a block,
            or an unknown feature
    """
    hooks = []
    open_block = None
    for i, line in enumerate(text.split('\n')):
        start, end = START.search(line), END.search(line)
        if start:
            if open_block:
                raise HookError(f'line {i + 1}: block opened inside the block from line {open_block["start"] + 1}')
            open_block = {'feature': start.group(1), 'kind': 'block', 'start': i}
        elif end:
            if not open_block:
                raise HookError(f'line {i + 1}: block end without a start')
            if end.group(1) != open_block['feature']:
                raise HookError(f'line {i + 1}: block from line {open_block["start"] + 1} is '
                                f'{open_block["feature"]} but ends as {end.group(1)}')
            open_block['end'] = i
            hooks.append(open_block)
            open_block = None
        elif LINE.search(line):
            if open_block:
                raise HookError(f'line {i + 1}: tagged line inside a block')
            feature = LINE.search(line).group(1)
            hooks.append({'feature': feature, 'kind': 'line', 'start': i, 'end': i})
        elif JLAB.match(line) and not open_block:
            raise HookError(f'line {i + 1}: "# JLab:" line outside a UNH-HOOK block')
    if open_block:
        raise HookError(f'line {open_block["start"] + 1}: block never closed')
    for hook in hooks:
        if hook['feature'] not in FEATURES:
            raise HookError(f'line {hook["start"] + 1}: unknown feature "{hook["feature"]}" '
                            f'(known: {", ".join(FEATURES)}; add new ones to FEATURES in unh/strip_unh.py)')
    return hooks


def strip_text(text, features=None):
    """Remove UNH hooks from a file's text and restore the JLab lines they replaced.

    Args:
        text: file contents (LF or CRLF line endings; the original style is kept)
        features: feature tags to remove; None removes all

    Returns:
        (new text, list of the hooks removed)
    """
    eol = '\r\n' if '\r\n' in text else '\n'
    lines = text.replace('\r\n', '\n').split('\n')
    hooks = [h for h in parse('\n'.join(lines)) if features is None or h['feature'] in features]
    drop = {}
    for h in hooks:
        for i in range(h['start'], h['end'] + 1):
            drop[i] = h
    out = []
    for i, line in enumerate(lines):
        if i not in drop:
            out.append(line)
        elif drop[i]['kind'] == 'block' and drop[i]['start'] < i < drop[i]['end']:
            jlab = JLAB.match(line)
            if jlab:
                out.append(jlab.group(1) + (jlab.group(2) or ''))
    return eol.join(out), hooks


def hooked_files(root=REPO):
    """Repo-relative paths (tracked or new, not ignored) of JLab files that contain UNH-HOOK markers."""
    listing = subprocess.run(['git', 'ls-files', '--cached', '--others', '--exclude-standard'],
                             cwd=root, capture_output=True, text=True, check=True).stdout.split('\n')
    found = []
    for rel in sorted(set(filter(None, listing))):
        path = root / rel
        if rel.startswith(UNH_OWNED) or not path.is_file():
            continue
        if b'UNH-HOOK' in path.read_bytes():
            found.append(rel)
    return found


def main(argv=None):
    ap = argparse.ArgumentParser(prog='python -m unh.strip_unh', description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--feature', action='append', choices=sorted(FEATURES),
                    help='remove only this feature (repeatable); default: everything UNH, including unh/')
    ap.add_argument('--apply', action='store_true', help='make the changes (default: dry run)')
    args = ap.parse_args(argv)
    features = set(args.feature) if args.feature else None

    edits = {}
    for rel in hooked_files():
        path = REPO / rel
        text = path.read_bytes().decode('utf-8')
        try:
            new, hooks = strip_text(text, features)
        except HookError as e:
            sys.exit(f'{rel}: {e}')
        if hooks:
            edits[rel] = new
            for h in hooks:
                where = f'line {h["start"] + 1}' + (f'-{h["end"] + 1}' if h['end'] > h['start'] else '')
                print(f'{rel}:{where}  {h["feature"]} ({h["kind"]})')

    if features is None:
        removals = ['unh']
    else:
        removals = [p for f in sorted(features) for p in FEATURES[f]['paths']]
    removals = [p for p in removals if (REPO / p).exists()]
    for p in removals:
        print(f'delete {p}/' if (REPO / p).is_dir() else f'delete {p}')

    if not args.apply:
        print(f'\nDry run: {len(edits)} file(s) to edit, {len(removals)} path(s) to delete. Add --apply to do it.')
        return
    for rel, new in edits.items():
        (REPO / rel).write_bytes(new.encode('utf-8'))
    for p in removals:
        target = REPO / p
        shutil.rmtree(target) if target.is_dir() else target.unlink()
    print(f'\nRemoved. Check with: git status, git diff')


if __name__ == '__main__':
    main()
