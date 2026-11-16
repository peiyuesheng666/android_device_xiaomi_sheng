/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef SHENG_NANO_NOTIFY_GET_H
#define SHENG_NANO_NOTIFY_GET_H
/* nano_api_lock protects the device. SRCU protects the actual manager object;
 * never take notify_lock here because a notifier can query nano_ops itself. */
#define SHENG_NANO_NOTIFY_GETTER(name, type, callback) \
static int name(type *out) \
{ \
	struct battmngr_notify *data; \
	type value = 0; \
	int ret, cookie; \
	if (!out) \
		return -EINVAL; \
	data = battmngr_notify_acquire(&cookie); \
	mutex_lock(&nano_api_lock); \
	ret = g_nodev && data ? callback(&value, data) : -ENODEV; \
	if (ret >= 0) \
		*out = value; \
	mutex_unlock(&nano_api_lock); \
	battmngr_notify_release(cookie); \
	return ret; \
}
#endif
