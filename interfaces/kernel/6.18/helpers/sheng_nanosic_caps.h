/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef SHENG_NANOSIC_CAPS_H
#define SHENG_NANOSIC_CAPS_H

/* Protected by the transport io_lock. Only successful writes advance applied. */
struct sheng_nano_caps {
	bool known, desired, valid, applied;
};

static inline void sheng_nano_caps_request(struct sheng_nano_caps *caps, bool on)
{
	caps->known = true;
	caps->desired = on;
}

static inline bool sheng_nano_caps_pending(const struct sheng_nano_caps *caps,
					 bool panel_on, bool usable)
{
	return panel_on && usable && caps->known &&
		(!caps->valid || caps->desired != caps->applied);
}

static inline void sheng_nano_caps_commit(struct sheng_nano_caps *caps, bool sent)
{
	caps->applied = sent;
	caps->valid = true;
}

static inline void sheng_nano_caps_reset(struct sheng_nano_caps *caps)
{
	/* Firmware reset loses hardware state, not the requested lock state. */
	caps->valid = false;
}
#endif
