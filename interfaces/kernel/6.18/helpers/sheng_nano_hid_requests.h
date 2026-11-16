/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef SHENG_NANO_HID_REQUESTS_H
#define SHENG_NANO_HID_REQUESTS_H
#ifdef SHENG_NANO_HID_HOST_TEST
#include <errno.h>
#include <stddef.h>
#include <stdint.h>
typedef uint8_t u8;
#else
#include <linux/errno.h>
#include <linux/hid.h>
#endif

/* The shipping keyboard has one Caps Lock output, ID 5, one payload byte.
 * Touch Feature reports are a separate contract and are not handled here. */
static inline int sheng_nano_hid_output(const u8 *buf, size_t len)
{
	if (!buf || !len)
		return -EINVAL;
	if (buf[0] != 5)
		return -EOPNOTSUPP;
	return len == 2 ? 0 : -EINVAL;
}

#endif
