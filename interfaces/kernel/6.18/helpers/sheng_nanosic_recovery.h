/* SPDX-License-Identifier: GPL-2.0-only */
/* Match the shipping driver's timeout recovery, with a bounded reset rate. */
static void sheng_nano_recover_after_timeout_locked(struct nanosic_wn8030 *nano, int error)
{
	lockdep_assert_held(&nano->io_lock);
	if (error != -ETIMEDOUT || !nano->ready || nano->removing || nano->suspended)
		return;
	if (!nano->recovery_count || time_after(jiffies, nano->recovery_window + 60 * HZ)) {
		nano->recovery_window = jiffies;
		nano->recovery_count = 0;
	}
	if (nano->recovery_count >= 3)
		return;
	nano->recovery_count++;
	nano->ready = false;
	nano->fw_attempts = 0;
	mutex_lock(&nano->conn_mutex);
	nano->connection_known = false;
	mutex_unlock(&nano->conn_mutex);
	/* Never wait for a threaded IRQ while its I/O mutex is held. */
	disable_irq_nosync(nano->client->irq);
	mod_delayed_work(system_wq, &nano->fw_worker, 0);
	dev_warn(nano->dev, "MCU wake timeout; restoring volatile firmware (attempt %u)\n",
		 nano->recovery_count);
}
