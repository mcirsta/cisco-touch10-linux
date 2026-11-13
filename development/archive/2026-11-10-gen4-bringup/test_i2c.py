#!/usr/bin/env python3
"""Check the actual adapter functions' address/framing and failure behavior."""
from pathlib import Path
import os
import re
import subprocess

HERE = Path(__file__).resolve().parent
source = (HERE / 'cyttsp4_i2c.c').read_text()
functions = '\n'.join(re.search(r'(?m)^static int ' + name + r'\([\s\S]*?^}\n', source)[0]
                      for name in ('cyttsp4_i2c_read', 'cyttsp4_i2c_write', 'cyttsp4_i2c_exit_bootloader'))
prefix = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <errno.h>
typedef uint8_t u8;
typedef uint16_t u16;
#define I2C_M_RD 1
#define ARRAY_SIZE(a) (sizeof(a) / sizeof((a)[0]))
#define PERRIER_LOADER_ADDR 0x69
#define dev_info(...) ((void)0)
struct cyttsp4 { bool in_bootloader; };
struct device { struct cyttsp4 *data; };
struct i2c_client { struct device dev; int addr; void *adapter; };
struct i2c_msg { int addr, flags, len; u8 *buf; };
#define to_i2c_client(dev) ((struct i2c_client *)(dev))
#define dev_get_drvdata(dev) ((dev)->data)
static struct i2c_msg seen[2];
static u8 sent[2][257], status[7] = {1, 0, 0, 0, 0, 0, 0x17};
static unsigned int calls;
static int override = 99, nmsgs;
static int i2c_transfer(void *adapter, struct i2c_msg *msgs, int count)
{
    calls++; nmsgs = count; assert(count > 0 && count <= 2);
    if (override != 99) return override;
    for (int i = 0; i < count; i++) {
        seen[i] = msgs[i];
        assert(msgs[i].len >= 0 && msgs[i].len <= 257);
        if (msgs[i].flags & I2C_M_RD) {
            memset(msgs[i].buf, 0, msgs[i].len);
            memcpy(msgs[i].buf, status, msgs[i].len < 7 ? msgs[i].len : 7);
        } else memcpy(sent[i], msgs[i].buf, msgs[i].len);
    }
    return count;
}
static int i2c_master_send(struct i2c_client *client, u8 *data, int size)
{
    struct i2c_msg msg = {.addr = client->addr, .len = size, .buf = data};
    int rc = i2c_transfer(client->adapter, &msg, 1);
    return rc == 1 ? size : rc;
}
'''
main = r'''
int main(void)
{
    struct cyttsp4 cd = {.in_bootloader = true};
    struct i2c_client client = {.dev.data = &cd, .addr = 0x67};
    u8 scratch[257], data[256]; unsigned int before;
    assert(!cyttsp4_i2c_read(&client.dev, scratch, 0, 3, data));
    assert(nmsgs == 1 && seen[0].addr == 0x69 && seen[0].len == 7 && seen[0].flags == I2C_M_RD);
    assert(!memcmp(data, status, 3));
    before = calls;
    assert(cyttsp4_i2c_read(&client.dev, scratch, 0, 8, data) == -EINVAL && calls == before);
    assert(cyttsp4_i2c_write(&client.dev, scratch, 0, 1, data) == -EINVAL && calls == before);
    override = -121;
    assert(cyttsp4_i2c_exit_bootloader(&client.dev) == -121 && cd.in_bootloader);
    override = 0;
    assert(cyttsp4_i2c_exit_bootloader(&client.dev) == -EIO && cd.in_bootloader);
    override = 99;
    assert(!cyttsp4_i2c_exit_bootloader(&client.dev) && !cd.in_bootloader);
    const u8 expected[] = {1, 0x3b, 0, 0, 0x4f, 0x6d, 0x17};
    assert(nmsgs == 1 && seen[0].addr == 0x69 && seen[0].len == 7 && !seen[0].flags);
    assert(!memcmp(sent[0], expected, 7));
    assert(!cyttsp4_i2c_read(&client.dev, scratch, 9, 82, data));
    assert(nmsgs == 2 && seen[0].addr == 0x67 && seen[1].addr == 0x67);
    assert(seen[0].len == 1 && sent[0][0] == 9 && seen[1].len == 82 && seen[1].flags == I2C_M_RD);
    data[0] = 8;
    assert(!cyttsp4_i2c_write(&client.dev, scratch, 0, 1, data));
    assert(nmsgs == 1 && seen[0].addr == 0x67 && seen[0].len == 2 && !memcmp(sent[0], "\0\10", 2));
    before = calls;
    assert(cyttsp4_i2c_read(&client.dev, scratch, 255, 2, data) == -EINVAL && calls == before);
    assert(cyttsp4_i2c_write(&client.dev, scratch, 255, 2, data) == -EINVAL && calls == before);
    puts("PASS actual I2C adapter: raw 0x69 loader, exact 7-byte launch/CRC, registered 0x67 application traffic, short/error transfers and bounds");
}
'''
test = HERE / 'test-i2c.c'
test.write_text(prefix + functions + main)
binary = HERE / 'test-i2c'
subprocess.run(['clang', '-std=c11', '-g', '-O1', '-Wall', '-Wextra', '-Werror',
    '-Wno-unused-parameter', '-Wno-sign-compare', '-fsanitize=address,undefined',
    '-fno-omit-frame-pointer', test, '-o', binary], check=True)
result = subprocess.run([binary], text=True, capture_output=True,
                        env=dict(os.environ, ASAN_OPTIONS='detect_leaks=0'))
(HERE / 'test-i2c.log').write_text(result.stdout + result.stderr)
result.check_returncode()
print(result.stdout, end='')
