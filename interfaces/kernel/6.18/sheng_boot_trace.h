/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef SHENG_BOOT_TRACE_H
#define SHENG_BOOT_TRACE_H
#include <linux/delay.h>
#include <linux/kernel.h>
#include <linux/printk.h>

extern unsigned int sheng_probe_delay_ms;

/* These pauses only gave the diagnostic rawdump worker time to save stages.
 * Keep them available for fault capture without delaying normal boot. */
static inline void sheng_probe_pause(void)
{
	unsigned int delay = READ_ONCE(sheng_probe_delay_ms);

	if (delay)
		msleep(min(delay, 350U));
}

static inline void sheng_probe_checkpoint(const char *stage)
{
	pr_notice("sheng_display_probe: %s\n", stage);
	sheng_probe_pause();
}
#endif
