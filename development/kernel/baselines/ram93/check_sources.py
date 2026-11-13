#!/usr/bin/env python3
"""Check the exported patches and real touchscreen DT with upstream tools."""
import json
import os
import shutil
import subprocess

from common import HERE, IMAGE, SOURCE, WORK, sha


def run(command, log):
    result = subprocess.run([str(arg) for arg in command], capture_output=True, text=True)
    output = result.stdout + result.stderr
    (HERE / 'out' / log).write_text(output)
    if result.returncode or output.strip():
        raise RuntimeError('Source check failed; see ' + str(HERE / 'out' / log))


def main():
    schema_bin = HERE / '.venv-dtschema/bin'
    tools = {}
    for name in ('dt-doc-validate', 'dt-mk-schema', 'dt-validate'):
        local = schema_bin / name
        tools[name] = str(local) if local.is_file() and os.access(local, os.X_OK) \
            else shutil.which(name)
    if not all(tools.values()):
        raise SystemExit('Install dtschema and put its command-line tools on PATH')
    (HERE / 'out').mkdir(exist_ok=True)
    manifest = json.loads((HERE / 'patches/manifest.json').read_text())
    for name, entry in manifest['files'].items():
        assert sha(SOURCE / name) == sha(WORK / name) == entry['after_sha256'], name
    checkpatch = WORK / 'scripts/checkpatch.pl'
    checks = {}
    for index, patch in enumerate((HERE / 'patches/series').read_text().splitlines()):
        run([checkpatch, '--no-tree', '--terse', HERE / 'patches' / patch],
            f'checkpatch-{index + 1}.log')
        checks[patch] = True
    bindings = WORK / 'Documentation/devicetree/bindings'
    binding = bindings / 'input/touchscreen/cisco,perrier-cyttsp4.yaml'
    run([tools['dt-doc-validate'], binding], 'binding-schema.log')
    schema = HERE / 'out/touch-schema.json'
    run([tools['dt-mk-schema'], '-j', '-o', schema, binding,
         bindings / 'input/touchscreen/touchscreen.yaml', bindings / 'input/input.yaml'],
        'schema-build.log')
    run([tools['dt-validate'], '-s', schema, '-l', 'cisco,perrier-cyttsp4', IMAGE / 'board.dtb'],
        'touch-dtb-schema.log')
    report = {'passed': True, 'patch_style': checks,
              'binding_schema_valid': True, 'actual_touch_node_schema_valid': True,
              'schema_tools': tools,
              'scope': 'Perrier touchscreen binding and node; not full board-schema validation',
              'source_manifest_sha256': sha(HERE / 'patches/manifest.json'),
              'board_dtb_sha256': sha(IMAGE / 'board.dtb')}
    (HERE / 'out/source-checks.json').write_text(json.dumps(report, indent=2) + '\n')
    print(f'PASS: all {len(checks)} patches pass checkpatch; Gen4 binding and actual touch node pass DT schema')


if __name__ == '__main__':
    main()
