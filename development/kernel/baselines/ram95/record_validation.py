#!/usr/bin/env python3
"""Record a recovered RAM trial against its immutable source and image evidence."""
import argparse
import ast
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import shutil

from common import HERE, ROOT, sha


def ref(path):
    path = Path(path)
    return {'path': str(path.relative_to(ROOT)), 'sha256': sha(path)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', required=True, type=Path)
    parser.add_argument('--status', choices=('passed', 'rejected', 'not-promoted'), default='passed')
    parser.add_argument('--details', required=True, type=Path)
    parser.add_argument('--parent', type=Path)
    parser.add_argument('--fallback', type=Path, default=HERE / 'validation-ram70.json')
    args = parser.parse_args()
    run = args.run.resolve()
    result = json.loads((run / 'result.json').read_text())
    assert result.get('stock_recovered') and result['stock_p8_sha256'] == \
        'f0fefd27f1ca21360dfe437919e03c5a6ee4c119df3e6070301a8f3879d181ad'
    profile = result['profile']
    assert re.fullmatch(r'[a-z0-9-]+', profile)
    image = ROOT / 'development/perrier-ramenv' / profile
    review = json.loads((image / 'reviewed-image.json').read_text())
    kernel = review['kernel']
    match = re.fullmatch(r'6\.18\.48-perrier-(ram\d+)', kernel)
    assert match and review['passed']
    version = match.group(1)
    snapshot = HERE / 'baselines' / version
    assert json.loads((snapshot / 'snapshot.json').read_text())['kernel'] == kernel
    assert result['staged']['zImage']['sha256'] == review['artifacts']['zImage']['sha256']
    assert sha(review['artifacts']['zImage']['path']) == result['staged']['zImage']['sha256']
    physical = sorted(run.glob('*physical-confirmation.json'))
    if args.status == 'passed':
        assert result['status'] == 'passed' and result['ram']['kernel'] == kernel and physical
    destination = HERE / ('validation-' + version + '.json')
    if destination.exists():
        raise FileExistsError('Validation already exists: ' + str(destination))
    fallback = json.loads(args.fallback.read_text())
    assert fallback['status'] == 'passed' and fallback['profile'] != profile
    tree = ast.parse((ROOT / 'tools/touch10_uboot.py').read_text())
    default = next(ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign)
                   and any(isinstance(t, ast.Name) and t.id == 'DEFAULT_PROFILE' for t in n.targets))
    archive = run / 'audited-plan'
    archive.mkdir(exist_ok=True)
    for p in (image / 'uboot').iterdir():
        if p.is_file() and not (archive / p.name).exists():
            shutil.copy2(p, archive / p.name)
    tests = {p.stem: ref(p) for p in sorted((snapshot / 'reports').glob('*-tests.json'))}
    names = ('initial-register-checks.json', 'cycle-checks.json', 'initial-after.log',
             'confirmed-after.log', 'three-cycles-after.log', 'transport-after.log',
             'confirmed-framebuffer.png', 'three-cycles-framebuffer.png',
             'failure-observation.json', 'initial-before.log',
             'leds-checks.json', 'check-leds-executed.py', 'leds-diagnostic-correction.json', 'leds-confirmed.log',
             'leds-before.log', 'leds-red.log', 'leds-green.log', 'leds-final-off.log')
    record = {
        'validated_at': datetime.now(timezone.utc).isoformat(), 'status': args.status,
        'kernel': kernel, 'profile': profile, 'default_uboot_profile': default == profile,
        'details': json.loads(args.details.read_text()),
        'recovery_mode': result['recovery_reason'],
        'recovery_elapsed_seconds': result['recovery_elapsed_seconds'],
        'stock_recovered': True, 'factory_p8_sha256': result['stock_p8_sha256'],
        'guard_sha256': result['guard_sha256'], 'serial_markers': result.get('markers'),
        'source_snapshot': ref(snapshot / 'snapshot.json'),
        'source_manifest': ref(snapshot / 'patches/manifest.json'),
        'source_checks': ref(snapshot / 'reports/source-checks.json'),
        'tests': tests, 'image_review': ref(image / 'reviewed-image.json'),
        'live_result': ref(run / 'result.json'),
        'physical_confirmations': [ref(p) for p in physical],
        'evidence': {name: ref(run / name) for name in names if (run / name).exists()},
        'fallback': {'profile': fallback['profile'], 'kernel': fallback['kernel'],
                     'validation': ref(args.fallback.resolve())},
    }
    if args.parent:
        record['parent_validation'] = ref(args.parent.resolve())
    destination.write_text(json.dumps(record, indent=2) + '\n')
    print(str(destination))


if __name__ == '__main__':
    main()
