// SPDX-License-Identifier: GPL-2.0-only
/* Native input switches for sheng's original GPIO + ADSP SMP2P hall binding.
 * Report the lid directly from its wake-capable TLMM GPIO. ADSP delays close
 * notifications; treat those as a request to sample, never as a stale state.
 * Tablet-mode events retain the original named SMP2P interrupts.
 */
#include <linux/gpio.h>
#include <linux/input.h>
#include <linux/interrupt.h>
#include <linux/module.h>
#include <linux/mutex.h>
#include <linux/of_gpio.h>
#include <linux/of_irq.h>
#include <linux/platform_device.h>
#include <linux/pm_wakeup.h>
#include <linux/pm_wakeirq.h>
#include <dt-bindings/gpio/gpio.h>

struct sheng_hall_switch {
	struct input_dev *input;
	struct device *dev;
	struct mutex *lock;
	unsigned int code;
	int gpio;
	int open_irq, close_irq;
	int gpio_irq;
	bool active_low;
};

struct sheng_hall {
	struct mutex lock;
	unsigned int count;
	struct sheng_hall_switch switches[];
};

static void sheng_hall_wakeup_disable(void *data)
{
	device_init_wakeup(data, false);
}

static void sheng_hall_sample(struct sheng_hall_switch *hall)
{
	int value;

	mutex_lock(hall->lock);
	value = gpio_get_value_cansleep(hall->gpio);
	if (value >= 0) {
		input_report_switch(hall->input, hall->code, !!value ^ hall->active_low);
		input_sync(hall->input);
	}
	mutex_unlock(hall->lock);
}

static irqreturn_t sheng_hall_gpio_irq(int irq, void *data)
{
	struct sheng_hall_switch *hall = data;

	pm_wakeup_event(hall->dev, 500);
	sheng_hall_sample(hall);
	return IRQ_HANDLED;
}

static irqreturn_t sheng_hall_irq(int irq, void *data)
{
	struct sheng_hall_switch *hall = data;
	bool value = irq == hall->close_irq ? hall->active_low : !hall->active_low;

	if (hall->code == SW_LID)
		return sheng_hall_gpio_irq(irq, data);

	pm_wakeup_event(hall->dev, 500);
	mutex_lock(hall->lock);
	input_report_switch(hall->input, hall->code, value);
	input_sync(hall->input);
	mutex_unlock(hall->lock);
	return IRQ_HANDLED;
}

static int sheng_hall_probe(struct platform_device *pdev)
{
	struct device *dev = &pdev->dev;
	struct sheng_hall *halls;
	struct input_dev *input;
	unsigned int count = of_get_available_child_count(dev->of_node), index = 0;
	int ret;

	if (!count || count > 2)
		return -EINVAL;
	halls = devm_kzalloc(dev, struct_size(halls, switches, count), GFP_KERNEL);
	input = devm_input_allocate_device(dev);
	if (!halls || !input)
		return -ENOMEM;
	mutex_init(&halls->lock);
	halls->count = count;
	input->name = "xiaomi_hall";
	input->phys = "sheng/hall0";
	input->id.bustype = BUS_HOST;
	platform_set_drvdata(pdev, halls);

	for_each_available_child_of_node_scoped(dev->of_node, child) {
		struct sheng_hall_switch *hall = &halls->switches[index++];
		struct of_phandle_args gpio_spec;
		u32 type;

		hall->dev = dev;
		hall->input = input;
		hall->lock = &halls->lock;
		ret = of_property_read_u32(child, "linux,input-type", &type);
		if (ret || type != EV_SW)
			return -EINVAL;
		ret = of_property_read_u32(child, "linux,code", &hall->code);
		if (ret || (hall->code != SW_LID && hall->code != SW_TABLET_MODE))
			return -EINVAL;
		hall->gpio = of_get_named_gpio(child, "hall_pin", 0);
		if (hall->gpio < 0)
			return dev_err_probe(dev, hall->gpio, "hall GPIO unavailable\n");
		ret = of_parse_phandle_with_args(child, "hall_pin", "#gpio-cells", 0, &gpio_spec);
		if (ret)
			return ret;
		of_node_put(gpio_spec.np);
		if (gpio_spec.args_count != 2)
			return -EINVAL;
		hall->active_low = gpio_spec.args[1] & GPIO_ACTIVE_LOW;
		ret = devm_gpio_request_one(dev, hall->gpio, GPIOF_IN, child->name);
		if (ret)
			return dev_err_probe(dev, ret, "hall GPIO request failed\n");
		hall->open_irq = of_irq_get_byname(child, "open_irq");
		hall->close_irq = of_irq_get_byname(child, "close_irq");
		if (hall->open_irq < 0 || hall->close_irq < 0)
			return dev_err_probe(dev, hall->open_irq < 0 ? hall->open_irq : hall->close_irq,
				"hall SMP2P IRQ unavailable\n");
		input_set_capability(input, EV_SW, hall->code);
	}
	ret = input_register_device(input);
	if (ret)
		return ret;
	for (index = 0; index < count; index++) {
		struct sheng_hall_switch *hall = &halls->switches[index];

		sheng_hall_sample(hall);
		if (hall->code == SW_LID) {
			hall->gpio_irq = gpio_to_irq(hall->gpio);
			if (hall->gpio_irq < 0)
				return dev_err_probe(dev, hall->gpio_irq, "lid GPIO IRQ unavailable\n");
			ret = devm_request_threaded_irq(dev, hall->gpio_irq, NULL,
				sheng_hall_gpio_irq, IRQF_TRIGGER_RISING | IRQF_TRIGGER_FALLING |
				IRQF_ONESHOT, "sheng-hall-lid-gpio", hall);
			if (ret)
				return dev_err_probe(dev, ret, "lid GPIO IRQ request failed\n");
			/* Reconcile a level change between the initial sample and IRQ setup. */
			sheng_hall_sample(hall);
		}
		ret = devm_request_threaded_irq(dev, hall->open_irq, NULL, sheng_hall_irq,
			IRQF_TRIGGER_RISING | IRQF_ONESHOT, "sheng-hall-open", hall);
		if (ret)
			return dev_err_probe(dev, ret, "hall open IRQ request failed\n");
		ret = devm_request_threaded_irq(dev, hall->close_irq, NULL, sheng_hall_irq,
			IRQF_TRIGGER_RISING | IRQF_ONESHOT, "sheng-hall-close", hall);
		if (ret)
			return dev_err_probe(dev, ret, "hall close IRQ request failed\n");
		dev_info(dev, "switch %u GPIO=%d active_low=%d SMP2P=%d/%d direct_irq=%d\n",
			hall->code, hall->gpio, hall->active_low, hall->open_irq, hall->close_irq,
			hall->gpio_irq);
	}
	ret = device_init_wakeup(dev, true);
	if (ret)
		return ret;
	ret = devm_add_action_or_reset(dev, sheng_hall_wakeup_disable, dev);
	if (ret)
		return ret;
	for (index = 0; index < count; index++) {
		struct sheng_hall_switch *hall = &halls->switches[index];

		if (hall->code == SW_LID) {
			/* TLMM GPIO 171 is mapped to SM8550 PDC wake interrupt 120. */
			ret = devm_pm_set_wake_irq(dev, hall->gpio_irq);
			if (ret)
				return dev_err_probe(dev, ret, "lid wake IRQ setup failed\n");
		}
	}
	return 0;
}

static int sheng_hall_resume(struct device *dev)
{
	struct sheng_hall *halls = dev_get_drvdata(dev);
	unsigned int i;

	for (i = 0; i < halls->count; i++)
		sheng_hall_sample(&halls->switches[i]);
	return 0;
}

static DEFINE_SIMPLE_DEV_PM_OPS(sheng_hall_pm, NULL, sheng_hall_resume);
static const struct of_device_id sheng_hall_match[] = {
	{ .compatible = "xiaomi-hall" },
	{}
};
MODULE_DEVICE_TABLE(of, sheng_hall_match);

static struct platform_driver sheng_hall_driver = {
	.probe = sheng_hall_probe,
	.driver = {
		.name = "xiaomi_hall",
		.of_match_table = sheng_hall_match,
		.pm = pm_sleep_ptr(&sheng_hall_pm),
	},
};
module_platform_driver(sheng_hall_driver);
MODULE_DESCRIPTION("Sheng GPIO lid and SMP2P tablet switches");
MODULE_LICENSE("GPL");
