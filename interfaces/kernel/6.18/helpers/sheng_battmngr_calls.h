/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef SHENG_BATTMNGR_CALLS_H
#define SHENG_BATTMNGR_CALLS_H
/* Class lookup owns a device reference. Serialize callbacks with unregister:
 * an old referenced object must never call a removed provider's code. */
#define SHENG_BATTMNGR_GETTER(name, type, field) \
int name(struct battmngr_device *dev) \
{ \
	type value = 0; \
	int ret = -EOPNOTSUPP; \
	if (!dev) \
		return ret; \
	mutex_lock(&dev->ops_lock); \
	if (dev->ops && dev->ops->field) { \
		ret = dev->ops->field(&value); \
		if (ret >= 0) \
			ret = value; \
	} \
	mutex_unlock(&dev->ops_lock); \
	return ret; \
}
#define SHENG_BATTMNGR_SETTER(name, field) \
int name(struct battmngr_device *dev, int value) \
{ \
	int ret = -EOPNOTSUPP; \
	if (!dev) \
		return ret; \
	mutex_lock(&dev->ops_lock); \
	if (dev->ops && dev->ops->field) { \
		ret = dev->ops->field(value); \
		if (ret >= 0) \
			ret = value; \
	} \
	mutex_unlock(&dev->ops_lock); \
	return ret; \
}
static inline void sheng_battmngr_stop_ops(struct battmngr_device *dev)
{
	mutex_lock(&dev->ops_lock);
	dev->ops = NULL;
	mutex_unlock(&dev->ops_lock);
}
#endif
