#!/usr/bin/env python3
"""Test the OEM keyboard panel-state packets in a host C harness."""
from pathlib import Path
import subprocess
import tempfile

workspace = Path(__file__).resolve().parents[4]
source_header = workspace / 'device/xiaomi/sheng/interfaces/kernel/6.18/helpers/sheng_nanosic_panel.h'
assert source_header.is_file()

source = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
typedef uint8_t u8;
#include "sheng_nanosic_panel.h"

static void verify(bool screen_on, uint8_t command_low, uint8_t command_high)
{
    uint8_t packet[SHENG_NANO_PANEL_PACKET_SIZE];
    static const uint8_t factory_prefix[] = {
        0x32, 0x00, 0x4e, 0x31, 0x80, 0x38, 0x25, 0x01,
    };
    sheng_nano_panel_packet(packet, screen_on);
    for (unsigned int i = 0; i < sizeof(factory_prefix); i++)
        assert(packet[i] == factory_prefix[i]);
    assert(packet[8] == command_low && packet[9] == command_high);
    for (unsigned int i = 10; i < sizeof(packet); i++)
        assert(packet[i] == 0);
}

int main(void)
{
    verify(false, 0x00, 0x5d);
    verify(true, 0x01, 0x5e);
    return 0;
}
'''

with tempfile.TemporaryDirectory(prefix='sheng-keyboard-panel-') as directory:
    root = Path(directory)
    c_source = root / 'packet_test.c'
    binary = root / 'packet_test'
    c_source.write_text(source)
    subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror',
                    '-I', str(source_header.parent), str(c_source), '-o', str(binary)],
                   check=True)
    subprocess.run([str(binary)], check=True)
print('Factory keyboard sleep and resume packet tests passed')
