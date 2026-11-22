/* SPDX-License-Identifier: GPL-2.0-only */
/* Panel packets match keyboard_early_suspend_work/resume_work in stock. */
#define SHENG_NANO_PANEL_PACKET_SIZE 66

static inline void sheng_nano_panel_packet(u8 *buf, bool screen_on)
{
	unsigned int i;

	for (i = 0; i < SHENG_NANO_PANEL_PACKET_SIZE; i++)
		buf[i] = 0;

	buf[0] = 0x32;
	buf[1] = 0x00;
	buf[2] = 0x4e;
	buf[3] = 0x31;
	buf[4] = 0x80;
	buf[5] = 0x38;
	buf[6] = 0x25;
	buf[7] = 0x01;
	/* Little-endian 0x5d00 sleep and 0x5e01 resume OEM commands. */
	buf[8] = screen_on ? 0x01 : 0x00;
	buf[9] = screen_on ? 0x5e : 0x5d;
}
