/* SPDX-License-Identifier: GPL-2.0-only */
/* Exercise the production helper against GPIO errors and IRQ wake failures. */
#include <assert.h>
#include <errno.h>
#include <stdbool.h>
#include <stdio.h>
#include <string.h>

struct gpio_desc { int value; };
struct i2c_client { int irq; };
struct nanosic_wn8030 {
	bool removing, ready, suspended, wake_irq_armed;
	int io_lock;
	struct gpio_desc *sleep_gpio, *irq_gpio;
	struct i2c_client *client;
};
static struct gpio_desc sleep_pin, irq_pin;
static struct i2c_client client = { 7 };
static unsigned int reads, sleeps, writes, change_calls;
static int ready_at, error_at, wake_error, wake_depth;
#define lockdep_assert_held(lock) assert(*(lock) == 1)
static void gpiod_set_value_cansleep(struct gpio_desc *pin, int value)
{
	assert(pin == &sleep_pin && value == 0);
	pin->value = value;
	writes++;
}
static int gpiod_get_raw_value_cansleep(struct gpio_desc *pin)
{
	assert(pin == &irq_pin);
	int sample = reads++;
	if (sample == error_at)
		return -EIO;
	return sample >= ready_at;
}
static void usleep_range(unsigned int min, unsigned int max)
{
	assert(min >= 1000 && max >= min && max <= 2000);
	sleeps++;
}
static int enable_irq_wake(int irq)
{
	assert(irq == client.irq);
	change_calls++;
	if (wake_error)
		return wake_error;
	wake_depth++;
	return 0;
}
static int disable_irq_wake(int irq)
{
	assert(irq == client.irq && wake_depth > 0);
	change_calls++;
	if (wake_error)
		return wake_error;
	wake_depth--;
	return 0;
}
#include "../interfaces/kernel/6.18/helpers/sheng_nanosic_wake.h"

static struct nanosic_wn8030 reset(void)
{
	reads = sleeps = writes = change_calls = 0;
	ready_at = 0;
	error_at = -1;
	wake_error = wake_depth = 0;
	return (struct nanosic_wn8030) { .ready = true, .io_lock = 1,
		.sleep_gpio = &sleep_pin, .irq_gpio = &irq_pin, .client = &client };
}

int main(void)
{
	unsigned int cases = 0;
	struct nanosic_wn8030 nano;
	/* Any valid acknowledgement within the OEM polling window must work. */
	for (int delay = 0; delay < 100; delay++) {
		nano = reset();
		ready_at = delay;
		assert(sheng_nano_wake_locked(&nano) == 0);
		assert(writes == 1 && reads == (unsigned int)delay + 1);
		assert(sleeps == (unsigned int)delay);
		cases++;
	}
	/* The same bound must hold for an unplugged/unresponsive controller. */
	nano = reset();
	ready_at = 1000;
	assert(sheng_nano_wake_locked(&nano) == -ETIMEDOUT);
	assert(writes == 1 && reads == 100 && sleeps == 100);
	cases++;
	for (int sample = 0; sample < 100; sample++) {
		nano = reset();
		ready_at = 1000;
		error_at = sample;
		assert(sheng_nano_wake_locked(&nano) == -EIO);
		assert(reads == (unsigned int)sample + 1 && sleeps == (unsigned int)sample);
		cases++;
	}
	/* Invalid lifecycle states must not touch the sleeping I2C/GPIO hardware. */
	for (int flags = 1; flags < 8; flags++) {
		nano = reset();
		nano.removing = flags & 1;
		nano.ready = !(flags & 2);
		nano.suspended = flags & 4;
		int result = sheng_nano_wake_locked(&nano);
		assert(result == (nano.removing ? -ENODEV : !nano.ready ? -EAGAIN : -EHOSTDOWN));
		assert(!reads && !writes && !sleeps);
		cases++;
	}
	/* All six-step arm/disarm/failure sequences: no nested or leaked depth. */
	for (unsigned int sequence = 0; sequence < 4096; sequence++) {
		nano = reset();
		unsigned int state = sequence;
		for (int step = 0; step < 6; step++, state >>= 2) {
			bool arm = state & 1;
			wake_error = state & 2 ? -EIO : 0;
			int old_depth = wake_depth;
			unsigned int old_calls = change_calls;
			int result = sheng_nano_set_irq_wake(&nano, arm);
			assert(wake_depth >= 0 && wake_depth <= 1);
			assert(nano.wake_irq_armed == (wake_depth == 1));
			if (old_depth == (int)arm) {
				assert(!result && old_calls == change_calls);
			} else if (wake_error) {
				assert(result == -EIO && old_depth == wake_depth);
			} else {
				assert(!result && wake_depth == (int)arm);
			}
		}
		wake_error = 0;
		assert(!sheng_nano_set_irq_wake(&nano, false));
		assert(wake_depth == 0);
		cases++;
	}
	printf("%u GPIO/IRQ lifecycle cases passed\n", cases);
	return 0;
}
