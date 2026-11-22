/* SPDX-License-Identifier: GPL-2.0-only */
#define SHENG_NANO_HID_HOST_TEST
#include "../interfaces/kernel/6.18/helpers/sheng_nano_hid_requests.h"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>

int main(void)
{
	unsigned long cases = 0;
	unsigned int id, payload;
	size_t len;
	u8 data[2] = {5, 0};

	for (id = 0; id <= 255; id++) {
		for (len = 0; len <= 4; len++) {
			u8 *buf = calloc(len ? len : 1, 1);
			int wanted = !len ? -EINVAL : id != 5 ? -EOPNOTSUPP : len != 2 ? -EINVAL : 0;
			if (len) buf[0] = id;
			assert(sheng_nano_hid_output(buf, len) == wanted);
			cases++;
			free(buf);
		}
	}
	for (payload = 0; payload <= 255; payload++) {
		data[1] = payload;
		assert(sheng_nano_hid_output(data, 2) == 0); cases++;
	}
	assert(sheng_nano_hid_output(NULL, 2) == -EINVAL); cases++;
	printf("%lu HID output boundary assertions passed\n", cases);
	return 0;
}
