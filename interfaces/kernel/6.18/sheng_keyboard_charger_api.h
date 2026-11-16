/* SPDX-License-Identifier: GPL-2.0-only */
/* Include after write_property_id; this is the shipping keyboard event API. */
static DEFINE_MUTEX(sheng_keyboard_charger_lock);
static struct battery_chg_dev *sheng_keyboard_bcdev;

int qti_set_keyboard_plugin(int plugin)
{
	struct battery_chg_dev *bcdev;
	int ret;

	if (plugin != 0 && plugin != 1)
		return -EINVAL;
	mutex_lock(&sheng_keyboard_charger_lock);
	bcdev = sheng_keyboard_bcdev;
	if (!bcdev) {
		ret = -ENODEV;
	} else if (!bcdev->initialized ||
		   atomic_read(&bcdev->state) != PMIC_GLINK_STATE_UP ||
		   (bcdev->debug_battery_detected && bcdev->block_tx)) {
		ret = -EAGAIN;
	} else {
		/* Shipping sheng qti_set_keyboard_plugin sends XM property 228.
		 * This is a board-specific event, not the phone's PACK_VENDOR ABI. */
		ret = write_property_id(bcdev, &bcdev->psy_list[PSY_TYPE_XM], 228, plugin);
		if (!ret && atomic_read(&bcdev->state) != PMIC_GLINK_STATE_UP)
			ret = -EAGAIN;
	}
	mutex_unlock(&sheng_keyboard_charger_lock);
	return ret;
}
EXPORT_SYMBOL_GPL(qti_set_keyboard_plugin);
