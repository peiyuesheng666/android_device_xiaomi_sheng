/* SPDX-License-Identifier: GPL-2.0-only */
/* Original IRQ state and notifier. Queue packets rather than overwrite a
 * shared message; GLINK receive must remain able to complete real requests. */
struct sheng_qti_irq_entry {
	struct sheng_qti_irq_entry *next;
	struct sheng_qti_irq irq;
	u32 epoch;
};

static struct sheng_qti_irq_entry *sheng_qti_irq_pop(struct battery_chg_dev *bcdev)
{
	struct sheng_qti_irq_entry *entry;
	unsigned long flags;

	spin_lock_irqsave(&bcdev->sheng_irq_lock, flags);
	entry = bcdev->sheng_irq_head;
	if (entry) {
		bcdev->sheng_irq_head = entry->next;
		if (!entry->next)
			bcdev->sheng_irq_tail = NULL;
	}
	spin_unlock_irqrestore(&bcdev->sheng_irq_lock, flags);
	return entry;
}

static void sheng_qti_irq_work(struct work_struct *work)
{
	struct battery_chg_dev *bcdev = container_of(work, struct battery_chg_dev,
							sheng_irq_work);
	struct sheng_qti_irq_entry *entry;

	while ((entry = sheng_qti_irq_pop(bcdev))) {
		struct battmngr_notify *data;
		int cookie, thermal;
		bool live;

		mutex_lock(&sheng_keyboard_charger_lock);
		live = sheng_keyboard_bcdev == bcdev && READ_ONCE(bcdev->initialized) &&
			atomic_read(&bcdev->state) == PMIC_GLINK_STATE_UP &&
			READ_ONCE(bcdev->sheng_pogo.epoch) == entry->epoch;
		thermal = READ_ONCE(bcdev->curr_thermal_level);
		if (live) {
			/* Stock changes this on all three IRQ types, not just DCIN. */
			bcdev->sheng_fg.pogo = entry->irq.value != 0;
			if (!entry->irq.value)
				bcdev->sheng_fg.full = false;
		}
		mutex_unlock(&sheng_keyboard_charger_lock);
		if (!live)
			goto free;
		if (!entry->irq.type)
			qti_deal_report();
		data = battmngr_notify_acquire(&cookie);
		if (data) {
			mutex_lock(&data->notify_lock);
			data->irq_msg.irq_type = entry->irq.type;
			data->irq_msg.value = entry->irq.value;
			if (entry->irq.value)
				data->misc_msg.thermal_level = thermal;
			/* No driver owner lock is held: consumers may request GLINK. */
			battmngr_notifier_call_chain(BATTMNGR_EVENT_IRQ, data);
			mutex_unlock(&data->notify_lock);
			battmngr_notify_release(cookie);
		}
free:
		kfree(entry);
	}
}

static int sheng_qti_irq_receive(struct battery_chg_dev *bcdev,
				 void *bytes, size_t len)
{
	struct sheng_qti_irq irq;
	struct sheng_qti_irq_entry *entry;
	unsigned long flags;
	int ret = sheng_qti_irq_decode(bytes, len, &irq);

	if (ret)
		return ret;
	entry = kmalloc(sizeof(*entry), GFP_ATOMIC);
	if (!entry)
		return -ENOMEM;
	entry->irq = irq;
	entry->next = NULL;
	spin_lock_irqsave(&bcdev->sheng_irq_lock, flags);
	if (bcdev->sheng_irq_stopping || !READ_ONCE(bcdev->initialized)) {
		ret = -ENODEV;
		goto unlock;
	}
	entry->epoch = READ_ONCE(bcdev->sheng_pogo.epoch);
	if (bcdev->sheng_irq_tail)
		bcdev->sheng_irq_tail->next = entry;
	else
		bcdev->sheng_irq_head = entry;
	bcdev->sheng_irq_tail = entry;
	/* Schedule under the queue lock so removal cannot miss a late producer. */
	schedule_work(&bcdev->sheng_irq_work);
unlock:
	spin_unlock_irqrestore(&bcdev->sheng_irq_lock, flags);
	if (ret)
		kfree(entry);
	return ret;
}

static void sheng_qti_irq_stop(struct battery_chg_dev *bcdev)
{
	struct sheng_qti_irq_entry *entry;
	unsigned long flags;

	spin_lock_irqsave(&bcdev->sheng_irq_lock, flags);
	bcdev->sheng_irq_stopping = true;
	spin_unlock_irqrestore(&bcdev->sheng_irq_lock, flags);
	cancel_work_sync(&bcdev->sheng_irq_work);
	while ((entry = sheng_qti_irq_pop(bcdev)))
		kfree(entry);
}
