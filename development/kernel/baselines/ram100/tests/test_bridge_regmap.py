#!/usr/bin/env python3
"""Fault-inject the bridge's proposed checked regmap transport wrappers."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess

HERE = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path,
                        default=HERE / 'source/drivers/gpu/drm/bridge/tc358775.c')
    args = parser.parse_args()
    source = args.source.read_text()
    start = source.index('static void d2l_read(')
    end = source.index('\nstatic void tc_bridge_program(', start)
    functions = source[start:end]
    out = HERE / 'tests/out/bridge-regmap'
    out.mkdir(parents=True, exist_ok=True)
    code = r'''
#include <assert.h>
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
typedef uint16_t u16;
typedef uint32_t u32;
struct regmap { unsigned int calls, fail_at; };
struct tc_data { struct regmap *regmap; int error; };
static int regmap_read(struct regmap *map, unsigned int addr, unsigned int *value)
{
    (void)addr;
    map->calls++;
    /* Even an adversarial failing backend may alter its output buffer. */
    *value = 0xdeadbeef;
    if (map->calls == map->fail_at) return -EIO;
    *value = 0x6500;
    return 0;
}
static int regmap_write(struct regmap *map, unsigned int addr, unsigned int value)
{
    (void)addr; (void)value;
    map->calls++;
    return map->calls == map->fail_at ? -EIO : 0;
}
'''
    code += functions + r'''
int main(void)
{
    for (unsigned int fail = 1; fail <= 6; fail++) {
        struct regmap map = {.fail_at = fail};
        struct tc_data tc = {.regmap = &map};
        u32 value = 0x12345678;
        for (unsigned int i = 0; i < 3; i++) {
            u32 before = value;
            d2l_read(&tc, 0x580, &value);
            if (tc.error) assert(value == before);
            d2l_write(&tc, 0x450, value);
        }
        assert(tc.error == -EIO && map.calls == fail);
        /* A subsequent initialization can explicitly clear the error. */
        tc.error = 0;
        map.fail_at = 0;
        d2l_read(&tc, 0x580, &value);
        assert(!tc.error && value == 0x6500);
        d2l_write(&tc, 0x450, value);
        assert(!tc.error && map.calls == fail + 2);
    }
    puts("PASS: six injected I/O failures preserve read outputs and stop later I/O; retries recover");
    return 0;
}
'''
    test = out / 'bridge-regmap-test.c'
    test.write_text(code)
    executable = out / 'bridge-regmap-test'
    subprocess.run(['clang', '-std=gnu11', '-Wall', '-Wextra', '-Werror', '-g',
                    '-O1', '-fsanitize=address,undefined', '-fno-omit-frame-pointer',
                    str(test), '-o', str(executable)], check=True)
    result = subprocess.run([str(executable)], check=True, capture_output=True,
                            text=True, env=dict(os.environ, ASAN_OPTIONS='detect_leaks=0'))
    report = {'passed': True, 'injected_failure_positions': 6,
              'source': str(args.source), 'sanitizers': ['address', 'undefined'],
              'source_sha256': hashlib.sha256(source.encode()).hexdigest(),
              'output': result.stdout.strip()}
    (out / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
    print(result.stdout, end='')


if __name__ == '__main__':
    main()
