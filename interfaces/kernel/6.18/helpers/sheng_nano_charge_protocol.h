/* SPDX-License-Identifier: GPL-2.0-only */
/* Bounds for the original sheng-u-oss nano charge protocol, not HID reports. */
#ifndef SHENG_NANO_CHARGE_PROTOCOL_H
#define SHENG_NANO_CHARGE_PROTOCOL_H
#ifdef SHENG_NANO_CHARGE_HOST_TEST
#include <errno.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>
typedef uint8_t u8;
#else
#include <linux/errno.h>
#include <linux/string.h>
#include <linux/types.h>
#endif

#define SHENG_NANO_CHARGE_READ 68
#define SHENG_NANO_CHARGE_WRITE 66
#define SHENG_NANO_CHARGE_PAYLOAD 26
#define SHENG_NANO_CHARGE_REG_DATA 6

static inline int sheng_nano_charge_validate(const u8 *buf, size_t len)
{
	size_t minimum;

	if (!buf || len < 5 || len > SHENG_NANO_CHARGE_READ)
		return -EINVAL;
	switch (buf[4]) {
	case 0xa2: minimum = 11; break;
	case 0x01: minimum = 14; break;
	case 0xf0: minimum = 8; break;
	case 0x43: minimum = 7; break;
	case 0x41:
		if (len < 11 || buf[10] > 19)
			return -EMSGSIZE;
		minimum = 11 + buf[10];
		break;
	default: return -EOPNOTSUPP;
	}
	return len < minimum ? -EMSGSIZE : 0;
}

static inline u8 sheng_nano_charge_crc(const u8 *buf, size_t end)
{
	u8 crc = 0;
	size_t i;

	for (i = 2; i < end; i++)
		crc += buf[i];
	return crc;
}

/* Construct exactly the original 66-byte command and sum header+payload. */
static inline int sheng_nano_charge_command(u8 *out, u8 object, u8 command,
					   u8 address, u8 count,
					   const u8 *data, size_t len, u8 power)
{
	size_t checksum;

	if (!out || (object != 0x38 && object != 0x3b))
		return -ENODEV;
	if (command == 0x42) {
		if (count && !address)
			return -EINVAL;
		if (address) {
			if (!data || !count || count > SHENG_NANO_CHARGE_REG_DATA ||
			    len > SHENG_NANO_CHARGE_REG_DATA || count > len)
				return -EINVAL;
		} else if (len > SHENG_NANO_CHARGE_PAYLOAD || (len && !data)) {
			return -EINVAL;
		}
	} else if (command != 0x40 || len || count > 1) {
		return -EINVAL;
	}
	memset(out, 0, SHENG_NANO_CHARGE_WRITE);
	out[0] = 0x32; out[2] = 0x4e; out[3] = 0x31;
	out[4] = 0x81; out[5] = object; out[6] = command;
	if (command == 0x40) {
		checksum = count ? 10 : 8;
		if (count) {
			out[7] = 2; out[8] = address; out[9] = 1;
		}
	} else {
		checksum = 33;
		out[8] = power;
		if (address) {
			out[7] = 25; out[8] = power;
			out[10] = address; out[11] = count;
			memcpy(out + 12, data, len);
		} else if (data) {
			/* The full original payload starts at byte 7. */
			memcpy(out + 7, data, len);
		} else {
			out[7] = 25; out[8] = power;
		}
	}
	out[checksum] = sheng_nano_charge_crc(out, checksum);
	return 0;
}
#endif
