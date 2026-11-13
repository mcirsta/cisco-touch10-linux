#!/usr/bin/env python3
"""Inspect final compiled/configured artifacts before authorizing this RAM trial."""
import hashlib
import json
from pathlib import Path
import struct

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]

def fdt_nodes(blob):
    header = struct.unpack_from('>10I', blob)
    assert header[0] == 0xd00dfeed and header[1] == len(blob)
    pos, strings = header[2], header[3]
    nodes, stack = {}, []
    while True:
        token = struct.unpack_from('>I', blob, pos)[0]; pos += 4
        if token == 1:
            end = blob.index(0, pos)
            name = blob[pos:end].decode()
            pos = (end + 4) & ~3
            path = ('/' + '/'.join(stack[1:] + [name])).rstrip('/') or '/'
            stack.append(name)
            nodes[path] = {}
        elif token == 2:
            stack.pop()
        elif token == 3:
            length, nameoff = struct.unpack_from('>II', blob, pos); pos += 8
            end = blob.index(0, strings + nameoff)
            name = blob[strings + nameoff:end].decode()
            path = '/' + '/'.join(stack[1:]) if len(stack) > 1 else '/'
            nodes[path][name] = blob[pos:pos+length]
            pos = (pos + length + 3) & ~3
        elif token == 4:
            pass
        elif token == 9:
            break
        else:
            raise ValueError(f'bad FDT token {token}')
    return nodes

def main():
    cfg = (HERE / 'build/.config').read_text()
    for symbol in ['ARCH_OMAP4','ARCH_MULTIPLATFORM','ARM_PATCH_PHYS_VIRT','AUTO_ZRELADDR',
                   'COMPAT_32BIT_TIME',
                   'MMU','AEABI','VFP','NEON','SERIAL_8250_CONSOLE','SERIAL_8250_OMAP',
                   'BINFMT_ELF','BLK_DEV_INITRD','PROC_FS','SYSFS','DEVMEM','CMDLINE_FORCE',
                   'NET','INET','USB','USB_EHCI_HCD','USB_EHCI_HCD_OMAP',
                   'MFD_OMAP_USB_HOST','USB_USBNET','USB_NET_SMSC95XX',
                   'REGULATOR','REGULATOR_FIXED_VOLTAGE','DMADEVICES','DMA_OMAP',
                   'MMC','MMC_BLOCK','MMC_OMAP_HS','BLOCK','BLK_DEV','EFI_PARTITION','DEVTMPFS',
                   'EXT4_FS','BLK_DEV_LOOP','MISC_FILESYSTEMS','SQUASHFS','SQUASHFS_ZLIB',
                   'SQUASHFS_XATTR','I2C','I2C_OMAP','I2C_CHARDEV',
                   'FB','FB_SIMPLE','FB_DEVICE']:
        assert f'CONFIG_{symbol}=y\n' in cfg, symbol
    for symbol in ['SMP','CPU_IDLE','CPU_FREQ','SUSPEND',
                   'GPIO_OMAP','PINCTRL_SINGLE','WATCHDOG',
                   'PERF_EVENTS','MODULES','DRM','VT','FRAMEBUFFER_CONSOLE']:
        assert f'CONFIG_{symbol}=y\n' not in cfg and f'CONFIG_{symbol}=m\n' not in cfg, symbol
    for item in ['clk_ignore_unused','pd_ignore_unused','console=ttyS0,115200']:
        assert item in cfg
    # AUTO_ZRELADDR detects the 0x80000000 load base and patches phys/virt
    # translation at boot; PHYS_OFFSET is deliberately hidden in this mode.
    assert 'CONFIG_PHYS_OFFSET=' not in cfg
    nodes = fdt_nodes((HERE / 'build/omap4-perrier-ram.dtb').read_bytes())
    assert b'cisco,perrier-ram\0' in nodes['/']['compatible']
    assert nodes['/memory@80000000']['reg'] == struct.pack('>II',0x80000000,0x19000000)
    assert nodes['/ocp']['status'] == b'disabled\0'
    for path in ['/ocp/interconnect@4a300000/segment@10000/target-module@4000',
                 '/ocp/interconnect@40100000/segment@0/target-module@30000']:
        assert nodes[path]['status'] == b'disabled\0', path
        assert nodes[path+'/wdt@0']['status'] == b'disabled\0', path
    active = []
    clocks = []
    for path, props in nodes.items():
        if '#clock-cells' in props: clocks.append(path)
        assert 'gpio-hog' not in props
        ancestors = ['/'] + ['/'+'/'.join(path.strip('/').split('/')[:i])
                            for i in range(1,len(path.strip('/').split('/'))+1)] if path!='/' else ['/']
        enabled = all(nodes.get(a,{}).get('status', b'okay\0') in [b'okay\0',b'ok\0'] for a in ancestors)
        if enabled:
            active.append({'path':path,'compatible':props.get('compatible',b'').replace(b'\0',b',').decode()})
            assert not any(k.startswith(('assigned-clock','reset-gpio','enable-gpio')) for k in props), path
            assert not any('gpio' in k or 'pinctrl' in k for k in props), path
            if path != '/regulator-emmc-vcc':
                assert not any(k.startswith('regulator-') for k in props), path
    # Only reviewed storage, LAN, adapter-only I2C, and passive simplefb can probe.
    allowed = {'/','/chosen','/aliases','/cpus','/cpus/cpu@0','/sram@40304000',
                   '/chosen/framebuffer@7ec78000',
               '/interrupt-controller@48241000','/cache-controller@48242000',
                   '/interrupt-controller@48281000','/memory@80000000','/serial@48020000',
                   '/target-module@4a064000','/target-module@4a064000/usbhshost@0',
                   '/target-module@4a064000/usbhshost@0/usb@c00',
                   '/target-module@4a064000/usbhshost@0/usb@c00/ethernet@1',
                   '/regulator-emmc-vcc',
                   '/target-module@48060000','/target-module@48060000/i2c@0',
                   '/target-module@48072000','/target-module@48072000/i2c@0',
                   '/target-module@4a056000','/target-module@4a056000/dma-controller@0',
                   '/target-module@480b4000','/target-module@480b4000/mmc@0'}
    assert set(n['path'] for n in active) <= allowed, [x for x in active if x['path'] not in allowed]
    assert nodes['/chosen']['ranges'] == b''
    fb = nodes['/chosen/framebuffer@7ec78000']
    assert fb['compatible'] == b'simple-framebuffer\0'
    assert fb['reg'] == struct.pack('>II', 0x7ec78000, 3*1280*800*4)
    assert fb['width'] == struct.pack('>I', 1280)
    assert fb['height'] == struct.pack('>I', 800)
    assert fb['stride'] == struct.pack('>I', 5120)
    assert fb['format'] == b'a8r8g8b8\0'
    assert not any(key in fb for key in ('clocks', 'power-domains', 'display', 'panel'))
    assert not any(key.endswith('-supply') for key in fb)
    for path in ['/target-module@4a064000',
                 '/target-module@4a064000/usbhshost@0',
                 '/target-module@4a064000/usbhshost@0/usb@c00']:
        assert path in {n['path'] for n in active}, path
    host = nodes['/target-module@4a064000/usbhshost@0']
    assert host['port1-mode'] == b'ehci-phy\0'
    assert host['num-ports'] == struct.pack('>I',2)
    lan = nodes['/target-module@4a064000/usbhshost@0/usb@c00/ethernet@1']
    assert lan['compatible'] == b'usb424,9e00\0'
    assert lan['local-mac-address'] == bytes.fromhex('24 16 9d b6 77 bb')
    regulator = nodes['/regulator-emmc-vcc']
    assert regulator['compatible'] == b'regulator-fixed\0'
    assert regulator['regulator-min-microvolt'] == struct.pack('>I', 2950000)
    assert regulator['regulator-max-microvolt'] == struct.pack('>I', 2950000)
    assert 'regulator-always-on' in regulator
    assert not any('gpio' in key or 'enable' in key for key in regulator)
    sdma = nodes['/target-module@4a056000/dma-controller@0']
    mmc = nodes['/target-module@480b4000/mmc@0']
    assert sdma['compatible'] == b'ti,omap4430-sdma\0ti,omap-sdma\0'
    assert mmc['compatible'] == b'ti,omap4-hsmmc\0'
    assert mmc['vmmc-supply'] == regulator['phandle']
    assert mmc['bus-width'] == struct.pack('>I', 8)
    assert mmc['max-frequency'] == struct.pack('>I', 26000000)
    assert 'non-removable' in mmc and 'ti,non-removable' in mmc
    for controller, address, alias, interrupt in [(2,0x48072000,'i2c1',57),
                                                  (3,0x48060000,'i2c2',61)]:
        parent = nodes[f'/target-module@{address:x}']
        assert parent['reg'] == struct.pack('>IIIIII',address,8,address+0x10,8,address+0x90,8)
        assert parent['ranges'] == struct.pack('>III',0,address,0x1000)
        assert parent['clock-names'] == b'fck\0'
        path = f'/target-module@{address:x}/i2c@0'
        i2c = nodes[path]
        assert i2c['compatible'] == b'ti,omap4-i2c\0'
        assert i2c['clock-frequency'] == struct.pack('>I', 100000)
        assert i2c['interrupts'] == struct.pack('>III', 0, interrupt, 4)
        assert not any(child.startswith(path + '/') for child in nodes)
        assert nodes['/aliases'][alias] == (path + '\0').encode()
    assert nodes['/aliases']['i2c1'] == b'/target-module@48072000/i2c@0\0'
    assert mmc['dmas'] == struct.pack('>IIII',
        struct.unpack('>I',sdma['phandle'])[0],47,
        struct.unpack('>I',sdma['phandle'])[0],48)
    block_source = (ROOT / 'development/sources/linux-6.18.48/drivers/mmc/core/block.c').read_text()
    assert 'if (of_machine_is_compatible("cisco,perrier-ram"))\n\t\tmd->read_only = 1;' in block_source
    report = {'passed':True,'platform_nodes':active,'early_clock_provider_count':len(clocks),
              'early_clock_providers':clocks,'watchdog_parent_and_child_disabled':True,
              'memory_start':0x80000000,'memory_size':0x19000000,
              'kexec_image_reservation':0x02000000,'kernel':'6.18.48-perrier-ram14',
              'early_initializers':['OMAP4 clock metadata (USB/ABE PLL changes skipped)',
                 'OMAP timer1 and counter32k','GIC/wakeupgen/L2 secure init',
                 'single OMAP EHCI controller, SMSC95xx USB Ethernet',
                 'OMAP SDMA and MMC2 eMMC with board-gated read-only block access',
                 'ext4 mount with ro,noload for stock base volume',
                 'three read-only loop mounts of stock gzip SquashFS images with xattrs',
                 'OMAP I2C2 and I2C3 adapters with no child devices',
                 'one register-zero pointer write and 16-byte read from touch I2C address 0x67',
                 'mainline simplefb maps inherited three-buffer TILER pool with fbdev; no fbcon',
                 'PID 1 saves, marks, and restores 96x48 pixels in each inherited buffer',
                 'bounded 30-second I2C Gen4 raw report sampler without reset or handshake'],
              'artifacts':{}}
    for name,path in {'zImage':HERE/'build/arch/arm/boot/zImage',
                      'board.dtb':HERE/'build/omap4-perrier-ram.dtb',
                      'kexec':HERE/'kexec-legacy-fdt'}.items():
        report['artifacts'][name]={'size':path.stat().st_size,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
    image_end = next(int(line.split()[0],16) for line in (HERE/'build/System.map').read_text().splitlines() if line.endswith(' _end'))
    assert image_end - 0xc0000000 < 0x02000000
    report['decompressed_kernel_bss_end'] = image_end - 0xc0000000 + 0x80000000
    (HERE/'reviewed-trial.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k!='early_clock_providers'},indent=2))

if __name__=='__main__':main()
