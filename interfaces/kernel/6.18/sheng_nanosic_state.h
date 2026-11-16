/* SPDX-License-Identifier: GPL-2.0-only */
/* Cached physical attachment only; reading this must not wake or query the MCU. */
static ssize_t connection_show(struct device *dev,
			       struct device_attribute *attr, char *buf)
{
	struct miscdevice *misc = dev_get_drvdata(dev);
	struct nanosic_wn8030 *nano =
		container_of(misc, struct nanosic_wn8030, raw_misc);
	ssize_t ret;

	mutex_lock(&nano->conn_mutex);
	if (!nano->connection_known)
		ret = -ENODATA;
	else
		ret = sysfs_emit(buf, "Connected=[%u]\n",
				 nano->connection_state == SHENG_NANO_KEYBOARD);
	mutex_unlock(&nano->conn_mutex);
	return ret;
}
static DEVICE_ATTR_RO(connection);

static ssize_t firmware_generation_show(struct device *dev,
					struct device_attribute *attr, char *buf)
{
	struct miscdevice *misc = dev_get_drvdata(dev);
	struct nanosic_wn8030 *nano =
		container_of(misc, struct nanosic_wn8030, raw_misc);

	return sysfs_emit(buf, "%u\n", READ_ONCE(nano->firmware_generation));
}
static DEVICE_ATTR_RO(firmware_generation);

static struct attribute *sheng_nano_state_attrs[] = {
	&dev_attr_connection.attr,
	&dev_attr_firmware_generation.attr,
	NULL,
};
ATTRIBUTE_GROUPS(sheng_nano_state);
