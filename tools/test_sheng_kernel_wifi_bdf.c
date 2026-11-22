/* SPDX-License-Identifier: GPL-2.0-only */
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
typedef uint32_t u32;
#include "../interfaces/kernel/6.18/helpers/sheng_wifi_bdf.h"

int main(void)
{
	/* Filenames and conditions independently decoded from shipping CNSS ELF. */
	const char *cn[] = { "bd_m2.elf", "bd_m3.elf", "bdwlan.elf", "bd_m11.elf",
		"bd_m1.elf", "bd_m18.elf", "bd_n11.elf", "bd_n81a.elf" };
	const char *gl[] = { "bd_m2gl.elf", "bd_m3gl.elf", "bdwlan.elf", "bd_m11gl.elf",
		"bd_m1gl.elf", "bd_m18gl.elf", "bd_n11gl.elf", "bd_n81agl.elf" };
	unsigned int cases = 0;
	for (u32 platform = 1; platform <= 8; platform++) {
		for (u32 country = 0; country < 4096; country++) {
			int global = platform >= 7 ? country != 0 : country == 1;
			const char *result = sheng_wifi_bdf_name(platform, country);
			assert(result && !strcmp(result, (global ? gl : cn)[platform - 1]));
			if (platform == 8)
				assert(!strstr(result, "bd_m2"));
			cases++;
		}
	}
	u32 unknown[] = { 0, 9, 255, 65535, UINT32_MAX };
	for (unsigned int i = 0; i < sizeof(unknown)/sizeof(unknown[0]); i++) {
		assert(!sheng_wifi_bdf_name(unknown[i], 0));
		assert(!sheng_wifi_bdf_name(unknown[i], 1));
		cases += 2;
	}
	printf("%u shipping board/country selection cases passed\n", cases);
	return 0;
}
