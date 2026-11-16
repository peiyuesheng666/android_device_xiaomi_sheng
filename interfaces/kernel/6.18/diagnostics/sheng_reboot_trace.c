// SPDX-License-Identifier: GPL-2.0-only
/* Diagnostic image only: let the existing bounded rawdump writer finish
 * before normal reboot notifiers shut storage down. No restart is initiated. */
#include <linux/delay.h>
#include <linux/kernel.h>
#include <linux/module.h>
#include <linux/reboot.h>
#include <linux/sched.h>

static int capture_reboot(struct notifier_block *nb, unsigned long action, void *data)
{
    pr_emerg("sheng_reboot_trace: orderly shutdown action=%lu command=%s pid=%d comm=%s\n",
             action, data ? (char *)data : "(none)", current->pid, current->comm);
    dump_stack();
    /* Blocking reboot notifier, before device_shutdown(). */
    msleep(1000);
    return NOTIFY_DONE;
}

static struct notifier_block reboot_trace = {
    .notifier_call = capture_reboot,
    .priority = INT_MAX,
};

static int __init trace_init(void)
{
    int ret = register_reboot_notifier(&reboot_trace);
    pr_notice("sheng_reboot_trace: diagnostic callback registered result=%d\n", ret);
    return ret;
}

static void __exit trace_exit(void)
{
    unregister_reboot_notifier(&reboot_trace);
}

module_init(trace_init);
module_exit(trace_exit);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("Sheng diagnostic reboot log capture window");
