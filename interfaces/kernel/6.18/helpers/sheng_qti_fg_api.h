/* SPDX-License-Identifier: GPL-2.0-only */
/* Original qti_ops ABI; all inputs come from real matched GLINK requests. */
struct battery_chg_dev *g_bcdev;
EXPORT_SYMBOL(g_bcdev);

bool check_g_bcdev_ops(void)
{
	bool ready;

	mutex_lock(&sheng_keyboard_charger_lock);
	ready = g_bcdev && g_bcdev == sheng_keyboard_bcdev &&
		g_bcdev->sheng_qti_ops && READ_ONCE(g_bcdev->initialized);
	mutex_unlock(&sheng_keyboard_charger_lock);
	return ready;
}
EXPORT_SYMBOL(check_g_bcdev_ops);

int qti_deal_report(void)
{
	struct battery_chg_dev *bcdev;
	struct psy_state *usb;
	int ret = -ENODEV;

	mutex_lock(&sheng_keyboard_charger_lock);
	bcdev = sheng_keyboard_bcdev;
	if (bcdev && READ_ONCE(bcdev->initialized)) {
		usb = &bcdev->psy_list[PSY_TYPE_USB];
		schedule_work(&bcdev->usb_type_work);
		if (usb->psy) {
			power_supply_changed(usb->psy);
			schedule_delayed_work(&bcdev->xm_prop_change_work, 0);
		}
		ret = NOTIFY_OK;
	}
	mutex_unlock(&sheng_keyboard_charger_lock);
	return ret;
}
EXPORT_SYMBOL(qti_deal_report);

static int sheng_fg_read_locked(struct battery_chg_dev *bcdev, u32 opcode,
				u32 property, u32 *out)
{
	struct sheng_pogo_request request = { .opcode = opcode, .property = property };

	return sheng_pogo_transfer(bcdev, &request, 0, out);
}

static int sheng_fg_get(u32 opcode, u32 property, unsigned int divisor,
			bool signed_value, bool soc_override, int *out)
{
	struct battery_chg_dev *bcdev;
	u32 raw;
	int ret;

	if (!out)
		return -EINVAL;
	mutex_lock(&sheng_keyboard_charger_lock);
	bcdev = sheng_keyboard_bcdev;
	ret = bcdev ? sheng_fg_read_locked(bcdev, opcode, property, &raw) : -ENODEV;
	if (!ret) {
		int value = signed_value ? (s32)raw / (int)divisor : raw / divisor;
		/* Retain the pre-existing explicit debug SOC override; a real
		 * successful battery request remains necessary even in that mode. */
		int fake = READ_ONCE(bcdev->fake_soc);

		if (soc_override && fake >= 0 && fake <= 100)
			value = fake;
		*out = value;
	}
	mutex_unlock(&sheng_keyboard_charger_lock);
	return ret;
}

#define SHENG_FG_GETTER(name, opcode, property, divisor, sign, override) \
static int name(int *out) \
{ return sheng_fg_get(opcode, property, divisor, sign, override, out); }

/* Individually verified property IDs from the actual shipping FG functions. */
SHENG_FG_GETTER(sheng_fg_soc, SHENG_FG_BATTERY_GET, 4, 100, false, true)
SHENG_FG_GETTER(sheng_fg_current, SHENG_FG_BATTERY_GET, 9, 1000, true, false)
SHENG_FG_GETTER(sheng_fg_voltage, SHENG_FG_BATTERY_GET, 7, 1000, false, false)
SHENG_FG_GETTER(sheng_fg_temperature, SHENG_POGO_GET, 226, 1, true, false)
SHENG_FG_GETTER(sheng_fg1_current, SHENG_POGO_GET, 172, 1, true, false)
SHENG_FG_GETTER(sheng_fg2_current, SHENG_POGO_GET, 173, 1, true, false)
SHENG_FG_GETTER(sheng_fg1_voltage, SHENG_POGO_GET, 176, 1, true, false)
SHENG_FG_GETTER(sheng_fg2_voltage, SHENG_POGO_GET, 177, 1, true, false)
SHENG_FG_GETTER(sheng_fg1_fcc, SHENG_POGO_GET, 139, 1, true, false)
SHENG_FG_GETTER(sheng_fg2_fcc, SHENG_POGO_GET, 167, 1, true, false)
SHENG_FG_GETTER(sheng_fg1_rm, SHENG_POGO_GET, 138, 1, true, false)
SHENG_FG_GETTER(sheng_fg2_rm, SHENG_POGO_GET, 166, 1, true, false)
SHENG_FG_GETTER(sheng_fg1_soc, SHENG_POGO_GET, 183, 1, true, false)
SHENG_FG_GETTER(sheng_fg2_soc, SHENG_POGO_GET, 184, 1, true, false)
SHENG_FG_GETTER(sheng_fg1_fastcharge, SHENG_POGO_GET, 43, 1, true, false)
SHENG_FG_GETTER(sheng_fg1_temperature, SHENG_POGO_GET, 174, 1, true, false)
SHENG_FG_GETTER(sheng_fg2_temperature, SHENG_POGO_GET, 175, 1, true, false)
SHENG_FG_GETTER(sheng_fg_authentic, SHENG_POGO_GET, 3, 1, true, false)
SHENG_FG_GETTER(sheng_fg_chip_ok, SHENG_POGO_GET, 5, 1, true, false)
#undef SHENG_FG_GETTER

static int sheng_fg_raw(u32 rm_property, u32 fcc_property, int *out)
{
	struct battery_chg_dev *bcdev;
	u32 rm, fcc, epoch;
	int ret;

	if (!out)
		return -EINVAL;
	mutex_lock(&sheng_keyboard_charger_lock);
	bcdev = sheng_keyboard_bcdev;
	if (!bcdev) {
		ret = -ENODEV;
		goto unlock;
	}
	epoch = READ_ONCE(bcdev->sheng_pogo.epoch);
	ret = sheng_fg_read_locked(bcdev, SHENG_POGO_GET, rm_property, &rm);
	if (!ret)
		ret = sheng_fg_read_locked(bcdev, SHENG_POGO_GET, fcc_property, &fcc);
	if (!ret && READ_ONCE(bcdev->sheng_pogo.epoch) != epoch)
		ret = -ENOTCONN;
	if (!ret)
		ret = sheng_fg_raw_soc((s32)rm, (s32)fcc, out);
unlock:
	mutex_unlock(&sheng_keyboard_charger_lock);
	return ret;
}

static int sheng_fg1_raw_soc(int *out)
{ return sheng_fg_raw(138, 139, out); }
static int sheng_fg2_raw_soc(int *out)
{ return sheng_fg_raw(166, 167, out); }
static int sheng_fg1_set_fastcharge(int value)
{ return sheng_pogo_property(143, true, value, NULL); }
static int sheng_fg2_set_fastcharge(int value)
{ return sheng_pogo_property(143, true, value, NULL); }
static int sheng_fg_suspend(bool suspend)
{ return sheng_pogo_property(42, true, suspend, NULL); }
static int sheng_fg_termination_current(int value)
{ return sheng_pogo_property(227, true, value, NULL); }

static int sheng_fg_charge_status(int *out)
{
	struct battery_chg_dev *bcdev;
	struct sheng_fg_state next;
	u32 adc, temperature = 0, voltage = 0, soc = 0, current_ua = 0, epoch;
	int ret, value;

	if (!out)
		return -EINVAL;
	mutex_lock(&sheng_keyboard_charger_lock);
	bcdev = sheng_keyboard_bcdev;
	if (!bcdev) {
		ret = -ENODEV;
		goto unlock;
	}
	next = bcdev->sheng_fg;
	epoch = READ_ONCE(bcdev->sheng_pogo.epoch);
	ret = sheng_fg_read_locked(bcdev, SHENG_POGO_GET, SHENG_POGO_ADC_STATUS, &adc);
	if (ret)
		goto unlock;
	if ((next.previous == 4 || next.previous == 5) && adc == 7) {
		ret = sheng_fg_read_locked(bcdev, SHENG_POGO_GET, 226, &temperature);
		if (!ret)
			ret = sheng_fg_read_locked(bcdev, SHENG_FG_BATTERY_GET, 7, &voltage);
		if (!ret)
			ret = sheng_fg_read_locked(bcdev, SHENG_FG_BATTERY_GET, 4, &soc);
		if (ret)
			goto unlock;
	}
	if (next.pogo && adc == 7) {
		ret = sheng_fg_read_locked(bcdev, SHENG_FG_BATTERY_GET, 9, &current_ua);
		if (ret)
			goto unlock;
	}
	if (READ_ONCE(bcdev->sheng_pogo.epoch) != epoch) {
		ret = -ENOTCONN;
		goto unlock;
	}
	ret = sheng_fg_charge_result(&next, (s32)adc, (s32)temperature,
			voltage, soc, (s32)current_ua, READ_ONCE(bcdev->fake_soc), &value);
	if (ret >= 0) {
		bcdev->sheng_fg = next;
		*out = value;
	}
unlock:
	mutex_unlock(&sheng_keyboard_charger_lock);
	return ret;
}

static const struct battmngr_ops qti_fg_ops = {
	.fg_soc = sheng_fg_soc, .fg_curr = sheng_fg_current,
	.fg_volt = sheng_fg_voltage, .fg_temp = sheng_fg_temperature,
	.charge_status = sheng_fg_charge_status,
	.fg1_ibatt = sheng_fg1_current, .fg2_ibatt = sheng_fg2_current,
	.fg1_volt = sheng_fg1_voltage, .fg2_volt = sheng_fg2_voltage,
	.fg1_fcc = sheng_fg1_fcc, .fg2_fcc = sheng_fg2_fcc,
	.fg1_rm = sheng_fg1_rm, .fg2_rm = sheng_fg2_rm,
	.fg1_raw_soc = sheng_fg1_raw_soc, .fg2_raw_soc = sheng_fg2_raw_soc,
	.fg1_soc = sheng_fg1_soc, .fg2_soc = sheng_fg2_soc,
	.set_fg1_fastcharge = sheng_fg1_set_fastcharge,
	.set_fg2_fastcharge = sheng_fg2_set_fastcharge,
	.get_fg1_fastcharge = sheng_fg1_fastcharge, .get_fg2_fastcharge = NULL,
	.fg1_temp = sheng_fg1_temperature, .fg2_temp = sheng_fg2_temperature,
	.fg_suspend = sheng_fg_suspend, .set_term_cur = sheng_fg_termination_current,
	.get_batt_auth = sheng_fg_authentic, .get_chip_ok = sheng_fg_chip_ok,
};
