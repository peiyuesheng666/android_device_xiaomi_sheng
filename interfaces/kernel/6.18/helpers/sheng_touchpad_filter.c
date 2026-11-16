// SPDX-License-Identifier: GPL-2.0-only
/* Stock sheng touchpad filter and parameter ABI for the original MCU reports. */
#include <linux/device.h>
#include <linux/module.h>
#include <linux/mutex.h>
#include <linux/of.h>
#include <linux/slab.h>
#include "sheng_touchpad_edge.h"

int xiaomi_touchpad_edge_filter_param_init(struct device_node *node);
int xiaomi_touchpad_edge_filter(u8 *packet);

static DEFINE_MUTEX(edge_lock);
static struct sheng_edge_filter edge;
static bool configured, enabled;
static struct class *keyboard_class;
static struct device *touchpad_device;

/* Exact order of param_list in stock xiaomi_keyboard_driver.ko. */
static const char * const param_names[SHENG_TOUCHPAD_PARAMETERS] = {
	"touchpad,edge-area-left-min", "touchpad,edge-area-left-max",
	"touchpad,edge-area-right-min", "touchpad,edge-area-right-max",
	"touchpad,edge-area-top-min", "touchpad,edge-area-top-max",
	"touchpad,edge-area-bottom-min", "touchpad,edge-area-bottom-max",
	"touchpad,shield-frame-count-limit", "touchpad,one-swipe-dis-limit",
	"touchpad,two-swipe-dis-limit", "touchpad,two-pinch-dis-limit",
	"touchpad,three-swipe-dis-limit", "touchpad,two-fingers-gesture-dis",
};

int xiaomi_touchpad_edge_filter_param_init(struct device_node *node)
{
	u32 values[SHENG_TOUCHPAD_PARAMETERS];
	unsigned int i;
	int ret;
	if (!node)
		return -EINVAL;
	for (i = 0; i < ARRAY_SIZE(values); i++) {
		ret = of_property_read_u32(node, param_names[i], &values[i]);
		if (ret)
			return ret;
	}
	mutex_lock(&edge_lock);
	memcpy(edge.param, values, sizeof(values));
	memset(edge.slot, 0, sizeof(edge.slot));
	configured = true;
	enabled = true;
	mutex_unlock(&edge_lock);
	return 0;
}
EXPORT_SYMBOL(xiaomi_touchpad_edge_filter_param_init);

int xiaomi_touchpad_edge_filter(u8 *packet)
{
	int ret;
	mutex_lock(&edge_lock);
	if (!configured)
		ret = -ENODATA;
	else if (!enabled)
		/* Shipping caller forwards the unfiltered frame when disabled. */
		ret = -EINVAL;
	else {
		ret = sheng_touchpad_edge(&edge, packet, SHENG_TOUCHPAD_REPORT_SIZE);
		if (ret == -EINVAL)
			ret = -EPROTO;
	}
	mutex_unlock(&edge_lock);
	return ret;
}
EXPORT_SYMBOL(xiaomi_touchpad_edge_filter);

static ssize_t edge_filter_enable_show(struct device *dev,
		struct device_attribute *attr, char *buf)
{
	ssize_t ret;
	mutex_lock(&edge_lock);
	ret = configured ? sysfs_emit(buf, "%u\n", enabled) : -ENODATA;
	mutex_unlock(&edge_lock);
	return ret;
}

static ssize_t edge_filter_enable_store(struct device *dev,
		struct device_attribute *attr, const char *buf, size_t count)
{
	bool value;
	if (sysfs_streq(buf, "1"))
		value = true;
	else if (sysfs_streq(buf, "0"))
		value = false;
	else
		return -EINVAL;
	mutex_lock(&edge_lock);
	if (!configured) {
		mutex_unlock(&edge_lock);
		return -ENODATA;
	}
	enabled = value;
	mutex_unlock(&edge_lock);
	return count;
}
static DEVICE_ATTR_RW(edge_filter_enable);

static ssize_t edge_filter_param_show(struct device *dev,
		struct device_attribute *attr, char *buf)
{
	size_t len = 0;
	unsigned int i;
	mutex_lock(&edge_lock);
	if (!configured) {
		mutex_unlock(&edge_lock);
		return -ENODATA;
	}
	for (i = 0; i < ARRAY_SIZE(param_names); i++)
		len += sysfs_emit_at(buf, len, "%s: %u\n", param_names[i], edge.param[i]);
	for (i = 0; i < ARRAY_SIZE(param_names); i++)
		len += sysfs_emit_at(buf, len, "%u ", edge.param[i]);
	len += sysfs_emit_at(buf, len, "\n");
	mutex_unlock(&edge_lock);
	return len;
}

static ssize_t edge_filter_param_store(struct device *dev,
		struct device_attribute *attr, const char *buf, size_t count)
{
	u32 values[SHENG_TOUCHPAD_PARAMETERS];
	char *copy, *cursor, *token;
	unsigned int n = 0;
	int ret = 0;
	copy = kstrndup(buf, count, GFP_KERNEL);
	if (!copy)
		return -ENOMEM;
	cursor = copy;
	while ((token = strsep(&cursor, " \t\n"))) {
		if (!*token)
			continue;
		if (n >= ARRAY_SIZE(values)) {
			ret = -E2BIG;
			break;
		}
		ret = kstrtou32(token, 10, &values[n]);
		if (ret)
			break;
		n++;
	}
	if (!ret && n != ARRAY_SIZE(values))
		ret = -EINVAL;
	if (!ret) {
		mutex_lock(&edge_lock);
		if (!configured)
			ret = -ENODATA;
		else
			memcpy(edge.param, values, sizeof(values));
		mutex_unlock(&edge_lock);
	}
	kfree(copy);
	return ret ? ret : count;
}
static DEVICE_ATTR_RW(edge_filter_param);

static struct attribute *touchpad_attrs[] = {
	&dev_attr_edge_filter_enable.attr,
	&dev_attr_edge_filter_param.attr,
	NULL,
};
ATTRIBUTE_GROUPS(touchpad);

static int __init sheng_touchpad_filter_init(void)
{
	keyboard_class = class_create("keyboard");
	if (IS_ERR(keyboard_class))
		return PTR_ERR(keyboard_class);
	touchpad_device = device_create_with_groups(keyboard_class, NULL, 0, NULL,
					    touchpad_groups, "touchpad");
	if (IS_ERR(touchpad_device)) {
		int ret = PTR_ERR(touchpad_device);
		class_destroy(keyboard_class);
		return ret;
	}
	return 0;
}

static void __exit sheng_touchpad_filter_exit(void)
{
	device_unregister(touchpad_device);
	class_destroy(keyboard_class);
}
module_init(sheng_touchpad_filter_init);
module_exit(sheng_touchpad_filter_exit);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("Original sheng touchpad edge filter and parameter control");
