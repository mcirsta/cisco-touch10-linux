#!/usr/bin/env python3
"""Execute the actual shutdown function against retained latch states and defaults."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

HERE = Path(__file__).resolve().parents[1]
source = HERE / 'source/drivers/gpio/gpio-pcf857x.c'
text = source.read_text()
function = re.search(r'(?m)^static void pcf857x_shutdown\([\s\S]*?^}', text)[0]
assert 'device_property_read_bool(&client->dev, "retain-state-shutdown")' in text
prefix = r'''
#include <assert.h>
#include <stdbool.h>
#define BIT(n) (1U << (n))
struct i2c_client { void *data; };
struct pcf857x {
    struct { unsigned ngpio; } chip;
    struct i2c_client *client;
    bool retain_state_shutdown;
    int (*write)(struct i2c_client *, unsigned);
};
static unsigned latch, writes;
static void *i2c_get_clientdata(struct i2c_client *c) { return c->data; }
static int capture(struct i2c_client *c, unsigned data) {
    (void)c; ++writes; latch = data; return 0;
}
'''
main = r'''
int main(void) {
    struct pcf857x gpio = { .write = capture };
    struct i2c_client client = { .data = &gpio };
    gpio.client = &client;
    gpio.retain_state_shutdown = true;
    gpio.chip.ngpio = 8;
    for (unsigned value = 0; value <= 255; ++value) {
        latch = value; writes = 0;
        pcf857x_shutdown(&client);
        assert(latch == value && writes == 0);
    }
    gpio.chip.ngpio = 16;
    const unsigned cases[] = {0, 0x00ff, 0xff00, 0x5555, 0xffff};
    for (unsigned i = 0; i < sizeof(cases) / sizeof(cases[0]); ++i) {
        latch = cases[i]; writes = 0;
        pcf857x_shutdown(&client);
        assert(latch == cases[i] && writes == 0);
    }
    gpio.retain_state_shutdown = false;
    for (unsigned bits = 8; bits <= 16; bits += 8) {
        gpio.chip.ngpio = bits; latch = 0; writes = 0;
        pcf857x_shutdown(&client);
        assert(writes == 1 && latch == (1U << bits) - 1);
    }
    return 0;
}
'''
out = HERE / 'tests/out/pcf-shutdown'
out.mkdir(exist_ok=True)
(out / 'test.c').write_text(prefix + function + '\n' + main)
subprocess.run(['clang', '-std=c11', '-Wall', '-Wextra', '-Werror',
                '-fsanitize=address,undefined', out / 'test.c', '-o', out / 'test'], check=True)
subprocess.run([out / 'test'], check=True, env=dict(os.environ, ASAN_OPTIONS='detect_leaks=0'))
result = {'passed': True, 'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
          'eight_bit_retained_latch_states': 256, 'sixteen_bit_retained_latch_states': 5,
          'unchanged_default_shutdowns': 2, 'asan_ubsan': True,
          'leak_detection': 'Disabled: no heap allocation in fixture; sandbox restricts ptrace'}
(HERE / 'out/pcf-shutdown-tests.json').write_text(json.dumps(result, indent=2) + '\n')
print('PASS: actual PCF shutdown preserves 261 latch states; default 8/16-bit behavior preserved')
