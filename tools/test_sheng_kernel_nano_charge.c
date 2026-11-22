/* SPDX-License-Identifier: GPL-2.0-only */
#define SHENG_NANO_CHARGE_HOST_TEST
#include "../interfaces/kernel/6.18/helpers/sheng_nano_charge_protocol.h"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>

static unsigned long cases;
static void check(int condition) { assert(condition); cases++; }

int main(void)
{
	u8 out[66], data[32], expected[66];
	u8 commands[] = {0xa2, 0x01, 0xf0, 0x41, 0x43, 0x99};
	size_t i, len, reglen;
	unsigned int object, addr, count;

	for (i = 0; i < sizeof(commands); i++) {
		for (len = 0; len <= 70; len++) {
			for (reglen = 0; reglen <= 255; reglen++) {
				u8 *frame = calloc(len ? len : 1, 1);
				size_t minimum = commands[i] == 0xa2 ? 11 :
					commands[i] == 0x01 ? 14 : commands[i] == 0xf0 ? 8 :
					commands[i] == 0x43 ? 7 : 11 + reglen;
				int result, wanted;
				if (len > 4) frame[4] = commands[i];
				if (len > 10) frame[10] = reglen;
				wanted = len < 5 || len > 68 ? -EINVAL :
					commands[i] == 0x99 ? -EOPNOTSUPP :
					commands[i] == 0x41 && (len < 11 || reglen > 19) ? -EMSGSIZE :
					len < minimum ? -EMSGSIZE : 0;
				result = sheng_nano_charge_validate(frame, len);
				check(result == wanted);
				free(frame);
			}
		}
	}
	check(sheng_nano_charge_validate(NULL, 68) == -EINVAL);
	for (object = 0; object <= 255; object++) {
		int valid = object == 0x38 || object == 0x3b;
		check(sheng_nano_charge_command(out, object, 0x40, 0, 0, NULL, 0, 0) ==
			(valid ? 0 : -ENODEV));
	}
	for (i = 0; i < sizeof(data); i++) data[i] = 0x80 + i;
	for (len = 0; len <= 32; len++) {
		int result = sheng_nano_charge_command(out, 0x38, 0x42, 0, 0, data, len, 1);
		check(result == (len <= 26 ? 0 : -EINVAL));
		if (!result) {
			unsigned int sum = 0;
			memset(expected, 0, sizeof(expected));
			expected[0] = 0x32; expected[2] = 0x4e; expected[3] = 0x31;
			expected[4] = 0x81; expected[5] = 0x38; expected[6] = 0x42;
			expected[8] = 1;
			memcpy(expected + 7, data, len);
			for (i = 2; i <= 32; i++) sum += expected[i];
			expected[33] = sum & 0xff;
			check(!memcmp(out, expected, sizeof(out)));
		}
	}
	for (addr = 0; addr <= 255; addr++) {
		check(!sheng_nano_charge_command(out, 0x3b, 0x40, addr, 1, NULL, 0, 0));
		check(out[7] == 2 && out[8] == addr && out[9] == 1);
		check(out[10] == ((0x4e + 0x31 + 0x81 + 0x3b + 0x40 + 2 + addr + 1) & 0xff));
		for (count = 0; count <= 8; count++) {
			for (len = 0; len <= 8; len++) {
				int invalid = count && !addr ? 1 : addr ?
					!count || count > 6 || len > 6 || count > len : 0;
				int result = sheng_nano_charge_command(out, 0x38, 0x42, addr, count, data, len, 1);
				check(result == (invalid ? -EINVAL : 0));
			}
		}
	}
	for (i = 0; i <= 1; i++) {
		check(!sheng_nano_charge_command(out, 0x38, 0x42, 0, 0, NULL, 0, i));
		check(out[7] == 25 && out[8] == i && out[33] == ((0x4e + 0x31 + 0x81 + 0x38 + 0x42 + 25 + i) & 0xff));
	}
	printf("%lu original charge protocol boundary/vector assertions passed\n", cases);
	return 0;
}
