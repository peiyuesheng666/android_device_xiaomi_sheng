/* SPDX-License-Identifier: GPL-2.0-only */
/* Driver-core PM/remove serialization protects the wake-depth bookkeeping. */
static int sheng_nano_set_irq_wake(struct nanosic_wn8030 *nano, bool arm)
{
	int ret;

	if (nano->wake_irq_armed == arm)
		return 0;
	ret = arm ? enable_irq_wake(nano->client->irq) :
		disable_irq_wake(nano->client->irq);
	if (!ret)
		nano->wake_irq_armed = arm;
	return ret;
}

/* Shipping Nanosic_PM_try_wakeup: sleep high, then wait for the real IRQ pin. */
static int sheng_nano_wake_locked(struct nanosic_wn8030 *nano)
{
	int level, i;

	lockdep_assert_held(&nano->io_lock);
	if (nano->removing)
		return -ENODEV;
	if (!nano->ready)
		return -EAGAIN;
	if (nano->suspended)
		return -EHOSTDOWN;
	/* sleep_gpio is active-low: logical zero is the original physical high. */
	gpiod_set_value_cansleep(nano->sleep_gpio, 0);
	for (i = 0; i < 100; i++) {
		level = gpiod_get_raw_value_cansleep(nano->irq_gpio);
		if (level < 0)
			return level;
		if (level)
			return 0;
		usleep_range(1000, 1200);
	}
	/* A timeout is not a successful wake and does not authorize an MCU reset. */
	return -ETIMEDOUT;
}
