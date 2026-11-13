#!/usr/bin/env python3
"""Record the native Gen4 additions as exact Linux 6.18.48 diffs."""
import difflib
import hashlib
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
SRC=ROOT/'development/sources/linux-6.18.48'
PATCHES=HERE/'kernel-patches'
PRISTINE=HERE/'pristine'

def sha(data):
    return hashlib.sha256(data).hexdigest()

def main():
    PATCHES.mkdir(exist_ok=True)
    PRISTINE.mkdir(exist_ok=True)
    previous={}
    if (PATCHES/'manifest.json').exists():
        previous={p['path']:p for p in json.loads((PATCHES/'manifest.json').read_text())['patches']}
    originals={}
    for name in ('Kconfig','Makefile'):
        path='drivers/input/touchscreen/'+name
        saved=PRISTINE/name
        if not saved.exists():
            assert path not in previous
            saved.write_bytes((SRC/path).read_bytes())
        originals[path]=saved.read_text()
    kconfig=originals['drivers/input/touchscreen/Kconfig']
    stanza='''config TOUCHSCREEN_CYTTSP4
	tristate "Cypress Gen4 operational handoff for Cisco Perrier"
	depends on I2C
	help
	  Native input for the already-running Gen4 firmware inherited across
	  stock kexec on Cisco Perrier. Uses the report descriptor and threaded
	  IRQs, with no power/reset or firmware-update commands. This driver
	  currently does not support cold-starting the controller.

'''
    assert 'config TOUCHSCREEN_CYTTSP5\n' in kconfig
    changes={
        'drivers/input/touchscreen/Kconfig':kconfig.replace('config TOUCHSCREEN_CYTTSP5\n',stanza+'config TOUCHSCREEN_CYTTSP5\n'),
        'drivers/input/touchscreen/Makefile':originals['drivers/input/touchscreen/Makefile'].replace('obj-$(CONFIG_TOUCHSCREEN_CYTTSP5)', 'obj-$(CONFIG_TOUCHSCREEN_CYTTSP4)\t\t+= cyttsp4.o\nobj-$(CONFIG_TOUCHSCREEN_CYTTSP5)'),
        'drivers/input/touchscreen/cyttsp4.c':(HERE/'cyttsp4.c').read_text(),
        'drivers/input/touchscreen/cyttsp4_protocol.h':(HERE/'cyttsp4_protocol.h').read_text(),
        'Documentation/devicetree/bindings/input/touchscreen/cisco,perrier-cyttsp4.yaml':(HERE/'cisco,perrier-cyttsp4.yaml').read_text(),
    }
    entries=[]
    for index,(path,after) in enumerate(changes.items(),1):
        before=originals.get(path,'')
        name=f'{index:02d}-{Path(path).name}.patch'
        patch=''.join(difflib.unified_diff(before.splitlines(True),after.splitlines(True),
                    fromfile='a/'+path if path in originals else '/dev/null',tofile='b/'+path))
        (PATCHES/name).write_text(patch)
        entry={'path':path,'patch':name,'vanilla_sha256':sha(before.encode()) if path in originals else None,
               'patched_sha256':sha(after.encode()),'patch_sha256':sha(patch.encode())}
        current=(SRC/path).read_bytes() if (SRC/path).exists() else None
        found=sha(current) if current is not None else None
        permitted={entry['vanilla_sha256'],entry['patched_sha256']}
        if path in previous: permitted.add(previous[path]['patched_sha256'])
        assert found in permitted, f'unexpected source change: {path}'
        # Update a previously applied revision only after checking its old hash.
        if path in previous and found==previous[path]['patched_sha256']:
            (SRC/path).write_text(after)
        entries.append(entry)
    (PATCHES/'manifest.json').write_text(json.dumps({'kernel':'linux-6.18.48','patches':entries},indent=2)+'\n')
    print(f'Recorded {len(entries)} native touch patches')

if __name__=='__main__': main()
