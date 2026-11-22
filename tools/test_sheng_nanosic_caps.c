/* SPDX-License-Identifier: GPL-2.0-only */
#include <assert.h>
#include <stdbool.h>
#include <stdio.h>
#include "../interfaces/kernel/6.18/helpers/sheng_nanosic_caps.h"

int main(void)
{
	struct sheng_nano_caps caps = {0};
	assert(!sheng_nano_caps_pending(&caps, true, true));
	for (int state = 0; state < 2; state++) {
		sheng_nano_caps_request(&caps, state);
		assert(!sheng_nano_caps_pending(&caps, false, true));
		assert(!sheng_nano_caps_pending(&caps, true, false));
		assert(sheng_nano_caps_pending(&caps, true, true));
		/* Failed transport: do not commit, so the real change remains pending. */
		assert(sheng_nano_caps_pending(&caps, true, true));
		sheng_nano_caps_commit(&caps, state);
		for (int replay = 0; replay < 100; replay++) {
			sheng_nano_caps_request(&caps, state);
			assert(!sheng_nano_caps_pending(&caps, true, true));
		}
		sheng_nano_caps_reset(&caps);
		assert(!sheng_nano_caps_pending(&caps, false, true));
		assert(sheng_nano_caps_pending(&caps, true, true));
		sheng_nano_caps_commit(&caps, state);
	}
	/* Multiple sleeping updates coalesce to the final desired value. */
	sheng_nano_caps_request(&caps, false);
	sheng_nano_caps_request(&caps, true);
	assert(!sheng_nano_caps_pending(&caps, true, true));
	sheng_nano_caps_request(&caps, false);
	assert(sheng_nano_caps_pending(&caps, true, true));
	puts("PASS caps duplicate suppression, deferred state, failed write and reset replay");
	return 0;
}
