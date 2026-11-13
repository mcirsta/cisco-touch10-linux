#!/usr/bin/env python3
"""Verify patch application and synchronize only recorded source overrides."""
import argparse
import hashlib
import json
from pathlib import Path
import posixpath
import shutil
import subprocess
import tarfile
import tempfile

from common import HERE, SOURCE, WORK, sha
from export_patches import ARCHIVE, pristine


def audit_work_tree(manifest):
    expected = set(manifest['files'])
    checked = 0
    with tarfile.open(ARCHIVE, 'r|xz') as archive:
        for member in archive:
            if not member.name.startswith('linux-6.18.48/'):
                continue
            name = member.name[len('linux-6.18.48/'):]
            if not name:
                continue
            path = WORK / name
            if member.issym():
                # Python's safe tar extraction may normalize redundant './'
                # components. Require the same lexical target, not spelling.
                assert (path.is_symlink() and
                        posixpath.normpath(str(path.readlink())) ==
                        posixpath.normpath(member.linkname)), name
                expected.add(name)
            elif member.isfile():
                if name in manifest['files']:
                    digest = manifest['files'][name]['after_sha256']
                else:
                    digest = hashlib.sha256(archive.extractfile(member).read()).hexdigest()
                assert path.is_file() and sha(path) == digest, 'Unrecorded source difference: ' + name
                expected.add(name)
                checked += 1
    code_suffixes = {'.c', '.h', '.S', '.rs', '.dts', '.dtsi', '.yaml'}
    extra = [str(p.relative_to(WORK)) for p in WORK.rglob('*')
             if p.is_file() and (p.suffix in code_suffixes or p.name in {'Kconfig', 'Makefile'})
             and str(p.relative_to(WORK)) not in expected]
    assert not extra, 'Unexpected work-tree source files: ' + repr(extra[:20])
    (HERE / 'out/source-tree-verification.json').write_text(json.dumps({
        'passed': True, 'archive_sha256': manifest['base_archive_sha256'],
        'source_manifest_sha256': sha(HERE / 'patches/manifest.json'),
        'pristine_files_checked': checked, 'canonical_overrides': len(manifest['files']),
        'unrecorded_code_files': extra}, indent=2) + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify-only', action='store_true')
    args = parser.parse_args()
    manifest = json.loads((HERE / 'patches/manifest.json').read_text())
    assert sha(ARCHIVE) == manifest['base_archive_sha256']
    for name, digest in manifest['patches'].items():
        assert sha(HERE / 'patches' / name) == digest, name
    for name, entry in manifest['files'].items():
        assert sha(SOURCE / name) == entry['after_sha256'], name
    (HERE / 'out').mkdir(exist_ok=True)
    before = pristine(manifest['files'])
    with tempfile.TemporaryDirectory(prefix='patch-check-', dir=HERE / 'out') as folder:
        directory = Path(folder)
        for name, entry in manifest['files'].items():
            data = before.get(name)
            assert (hashlib.sha256(data).hexdigest() if data is not None else None) == entry['before_sha256'], name
            if data is not None:
                path = directory / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
        for name in manifest['patches']:
            subprocess.run(['patch', '--batch', '--forward', '-p1', '-i', HERE / 'patches' / name],
                           cwd=directory, check=True, stdout=subprocess.DEVNULL)
        for name, entry in manifest['files'].items():
            assert sha(directory / name) == entry['after_sha256'], name
    if not args.verify_only:
        if not WORK.exists():
            WORK.parent.mkdir(parents=True, exist_ok=True)
            with tarfile.open(ARCHIVE, 'r:xz') as archive:
                archive.extractall(WORK.parent, filter='data')
        state_path = HERE / 'out/applied-source.json'
        previous = json.loads(state_path.read_text()) if state_path.exists() else {}
        for name, entry in manifest['files'].items():
            target = WORK / name
            if target.exists() and sha(target) == entry['after_sha256']:
                continue
            if target.exists() and sha(target) not in {entry['before_sha256'], previous.get(name)}:
                raise ValueError('Unrecorded work-tree edits need review: ' + str(target))
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(SOURCE / name, target)
        assert not (WORK / 'drivers/input/touchscreen/cyttsp4.c').exists()
        state_path.write_text(json.dumps({name: entry['after_sha256']
                                         for name, entry in manifest['files'].items()}, indent=2) + '\n')
        audit_work_tree(manifest)
    print('PASS: patch series applies cleanly to the pristine archive and reproduces every canonical source file')


if __name__ == '__main__':
    main()
