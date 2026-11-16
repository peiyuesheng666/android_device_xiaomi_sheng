/* SPDX-License-Identifier: GPL-2.0-only */
/* Included by the genuine QTI driver after its device and request definitions. */
static DEFINE_MUTEX(sheng_keyboard_charger_lock);
static struct battery_chg_dev *sheng_keyboard_bcdev;

static void sheng_pogo_state_change(struct battery_chg_dev *bcdev, int state)
{
	unsigned long flags;

	spin_lock_irqsave(&bcdev->sheng_pogo_lock, flags);
	atomic_set(&bcdev->state, state);
	bcdev->sheng_pogo.epoch++;
	if (state == PMIC_GLINK_STATE_DOWN) {
		if (bcdev->sheng_pogo.active) {
			bcdev->sheng_pogo.error = -ENOTCONN;
			bcdev->sheng_pogo.active = false;
			complete(&bcdev->sheng_pogo_ack);
		}
		/* A transport reset drains the previous response stream. */
		bcdev->sheng_pogo.fenced = false;
	}
	spin_unlock_irqrestore(&bcdev->sheng_pogo_lock, flags);
}

static bool sheng_pogo_response(struct battery_chg_dev *bcdev, void *data, size_t len)
{
	struct sheng_pogo_reply reply = {};
	unsigned long flags;
	int matched = 0;

	spin_lock_irqsave(&bcdev->sheng_pogo_lock, flags);
	if (bcdev->sheng_pogo.active)
		matched = sheng_pogo_decode(&bcdev->sheng_pogo.request, data, len, &reply);
	if (matched) {
		bcdev->sheng_pogo.reply = reply;
		bcdev->sheng_pogo.error = matched < 0 ? matched : reply.error;
		if (matched < 0)
			bcdev->sheng_pogo.fenced = true;
		bcdev->sheng_pogo.active = false;
		complete(&bcdev->sheng_pogo_ack);
	}
	spin_unlock_irqrestore(&bcdev->sheng_pogo_lock, flags);
	return matched != 0;
}

/* The owner mutex protects device lifetime. rw_lock serializes against the
 * driver's ordinary requests; only the dedicated matching ACK can finish us. */
static int sheng_pogo_transfer(struct battery_chg_dev *bcdev,
		const struct sheng_pogo_request *request, u32 value, u32 *result)
{
	u8 frame[28];
	unsigned long flags, waited;
	u32 epoch;
	int len, ret;

	len = sheng_pogo_encode(frame, sizeof(frame), request, value);
	if (len < 0)
		return len;
	mutex_lock(&bcdev->rw_lock);
	spin_lock_irqsave(&bcdev->sheng_pogo_lock, flags);
	if (!READ_ONCE(bcdev->initialized))
		ret = -ENODEV;
	else if (atomic_read(&bcdev->state) != PMIC_GLINK_STATE_UP)
		ret = -ENOTCONN;
	else if (READ_ONCE(bcdev->debug_battery_detected) && READ_ONCE(bcdev->block_tx))
		ret = -EACCES;
	else if (bcdev->sheng_pogo.fenced)
		ret = -EPIPE;
	else
		ret = 0;
	if (ret) {
		spin_unlock_irqrestore(&bcdev->sheng_pogo_lock, flags);
		goto unlock;
	}
	reinit_completion(&bcdev->sheng_pogo_ack);
	bcdev->sheng_pogo.request = *request;
	bcdev->sheng_pogo.active = true;
	bcdev->sheng_pogo.error = -EINPROGRESS;
	epoch = bcdev->sheng_pogo.epoch;
	spin_unlock_irqrestore(&bcdev->sheng_pogo_lock, flags);
	ret = pmic_glink_write(bcdev->client, frame, len);
	waited = ret ? 0 : wait_for_completion_timeout(&bcdev->sheng_pogo_ack,
						 msecs_to_jiffies(BC_WAIT_TIME_MS));
	spin_lock_irqsave(&bcdev->sheng_pogo_lock, flags);
	if (bcdev->sheng_pogo.epoch != epoch ||
	    atomic_read(&bcdev->state) != PMIC_GLINK_STATE_UP)
		ret = -ENOTCONN;
	else if (!ret && !waited) {
		ret = -ETIMEDOUT;
		/* No wire transaction ID exists. Do not let a late identical ACK
		 * falsely complete a retry; require a real GLINK reset first. */
		bcdev->sheng_pogo.fenced = true;
	} else if (!ret) {
		ret = bcdev->sheng_pogo.error;
		if (!ret && result)
			*result = bcdev->sheng_pogo.reply.value;
	}
	bcdev->sheng_pogo.active = false;
	spin_unlock_irqrestore(&bcdev->sheng_pogo_lock, flags);
unlock:
	mutex_unlock(&bcdev->rw_lock);
	return ret;
}

static int sheng_pogo_property(u32 property, bool write, u32 value, u32 *result)
{
	struct sheng_pogo_request request = {
		.opcode = write ? SHENG_POGO_SET : SHENG_POGO_GET, .property = property,
	};
	int ret;

	mutex_lock(&sheng_keyboard_charger_lock);
	ret = sheng_keyboard_bcdev ? sheng_pogo_transfer(sheng_keyboard_bcdev,
			&request, value, result) : -ENODEV;
	mutex_unlock(&sheng_keyboard_charger_lock);
	return ret;
}

int qti_set_keyboard_plugin(int plugin)
{
	if (plugin != 0 && plugin != 1)
		return -EINVAL;
	return sheng_pogo_property(SHENG_POGO_KEYBOARD, true, plugin, NULL);
}
EXPORT_SYMBOL(qti_set_keyboard_plugin);

int sc8651_wpc_gate_set(int value)
{
	return sheng_pogo_property(SHENG_POGO_WPC_MOS, true, value, NULL);
}
EXPORT_SYMBOL(sc8651_wpc_gate_set);

int qti_enale_charge(int enable)
{
	return sheng_pogo_property(SHENG_POGO_ENABLE, true, enable, NULL);
}
EXPORT_SYMBOL(qti_enale_charge);

int qti_get_ADC_CHGR_STATUS(void)
{
	u32 value;
	int ret = sheng_pogo_property(SHENG_POGO_ADC_STATUS, false, 0, &value);

	return ret ? ret : (int)value;
}
EXPORT_SYMBOL(qti_get_ADC_CHGR_STATUS);

int qti_get_DCIN_STATE(void)
{
	u32 value;
	int ret = sheng_pogo_property(SHENG_POGO_DCIN, false, 0, &value);

	return ret ? ret : (int)value;
}
EXPORT_SYMBOL(qti_get_DCIN_STATE);

static int sheng_pogo_vote(u8 vote, bool write, u32 value)
{
	struct sheng_pogo_request request = {
		.opcode = write ? SHENG_POGO_SET : SHENG_POGO_GET,
		.property = SHENG_POGO_VOTER, .voter = true, .vote = vote,
	};
	int ret;

	mutex_lock(&sheng_keyboard_charger_lock);
	ret = sheng_keyboard_bcdev ? sheng_pogo_transfer(sheng_keyboard_bcdev,
			&request, value, NULL) : -ENODEV;
	mutex_unlock(&sheng_keyboard_charger_lock);
	return ret;
}

int write_voter_prop_id(u8 vote, u32 value)
{
	return sheng_pogo_vote(vote, true, value);
}
EXPORT_SYMBOL(write_voter_prop_id);

int read_voter_property_id(u8 vote, u32 prop_id)
{
	/* The original ABI ignores prop_id and requests ALL_VOTER. */
	(void)prop_id;
	return sheng_pogo_vote(vote, false, 0);
}
EXPORT_SYMBOL(read_voter_property_id);
