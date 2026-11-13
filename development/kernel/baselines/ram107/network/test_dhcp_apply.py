#!/usr/bin/env python3
"""Exercise DHCP state transitions without touching the host network."""
import os
from pathlib import Path
import subprocess
import tempfile

SCRIPT = Path(__file__).with_name('dhcp-apply-route-dns.sh')

FAKE_IP = '''#!/usr/bin/env python3
import os, sys
from pathlib import Path
p = Path(os.environ['PERRIER_DHCP_RUN_DIR'])
a = sys.argv[1:]
with (p / 'ip-commands').open('a') as f: f.write(' '.join(a) + '\\n')
if a[:3] == ['-4', 'addr', 'show']:
    if (p / 'address').exists(): print('inet ' + (p / 'address').read_text().strip() + ' scope global eth0')
elif a[:3] == ['-4', 'addr', 'add']:
    (p / 'address').write_text(a[3] + '\\n')
elif a[:3] == ['-4', 'addr', 'del']:
    if (p / 'address').exists() and (p / 'address').read_text().strip() == a[3]:
        (p / 'address').unlink()
elif a[:4] == ['-4', 'route', 'replace', 'default']:
    (p / 'gateway').write_text(a[5] + '\\n')
elif a[:4] == ['-4', 'route', 'del', 'default']:
    if (p / 'gateway').exists() and (p / 'gateway').read_text().strip() == a[5]:
        (p / 'gateway').unlink()
else:
    sys.exit(2)
'''

FAKE_IPCALC = '''#!/bin/sh
[ "$1" = -p ] && [ "$3" = 255.255.255.0 ] || exit 1
printf 'PREFIX=24\\n'
'''


def main():
    with tempfile.TemporaryDirectory(prefix='perrier-dhcp-') as tmp:
        run = Path(tmp)
        ip = run / 'ip'
        ip.write_text(FAKE_IP)
        ip.chmod(0o755)
        ipcalc = run / 'ipcalc'
        ipcalc.write_text(FAKE_IPCALC)
        ipcalc.chmod(0o755)
        env = dict(os.environ, PERRIER_DHCP_IP_BIN=str(ip),
                   PERRIER_DHCP_IPCALC_BIN=str(ipcalc),
                   PERRIER_DHCP_RUN_DIR=str(run),
                   PERRIER_DHCP_RESOLV_CONF=str(run / 'resolv.conf'),
                   interface='eth0', ip='10.77.10.10', subnet='255.255.255.0',
                   lease='43200')

        def call(event, **values):
            return subprocess.run(['/bin/sh', str(SCRIPT), event],
                                  env=dict(env, **values), capture_output=True, text=True)

        first = call('bound', router='', dns='')
        assert first.returncode == 0, first.stderr
        assert (run / 'address').read_text() == '10.77.10.10/24\n'
        assert not (run / 'gateway').exists()
        assert not (run / 'resolv.conf').exists()
        assert (run / 'dhcp-event').read_text() == 'bound\n'

        renew = call('renew', router='10.77.10.1', dns='10.77.10.1 192.0.2.53')
        assert renew.returncode == 0, renew.stderr
        assert (run / 'gateway').read_text() == '10.77.10.1\n'
        assert (run / 'resolv.conf').read_text() == (
            'nameserver 10.77.10.1\nnameserver 192.0.2.53\n')
        assert (run / 'dhcp-event').read_text() == 'renew\n'

        commands = (run / 'ip-commands').read_text()
        invalid = call('renew', router='10.77.10.1;touch /tmp/bad', dns='10.77.10.1')
        assert invalid.returncode != 0
        assert (run / 'ip-commands').read_text() == commands
        assert not Path('/tmp/bad').exists()

        missing = call('deconfig')
        assert missing.returncode == 0, missing.stderr
        assert not (run / 'address').exists()
        assert not (run / 'gateway').exists()
        assert not (run / 'resolv.conf').exists()
        assert (run / 'dhcp-event').read_text() == 'deconfig\n'
        print('DHCP apply, renew, invalid option, and lease-loss transitions passed')


if __name__ == '__main__':
    main()
