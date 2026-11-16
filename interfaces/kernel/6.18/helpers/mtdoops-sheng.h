/* SPDX-License-Identifier: GPL-2.0-only */
/* sheng OEM long-press/reboot records, using the actual MTD and pmsg buffers. */
#include <linux/io.h>
#include <linux/mm.h>
#include <linux/of_address.h>
#include <linux/reboot.h>
#include <linux/mutex.h>
#include <linux/notifier.h>
#include <linux/slab.h>
#include "mtdoops-sheng-ring.h"

enum sheng_mtd_reason {
	SHENG_MTD_UNDEFINED, SHENG_MTD_PANIC, SHENG_MTD_OOPS,
	SHENG_MTD_EMERG, SHENG_MTD_SHUTDOWN, SHENG_MTD_RESTART,
	SHENG_MTD_POWEROFF, SHENG_MTD_LONG_PRESS,
};

extern struct atomic_notifier_head pwrkey_irq_notifier_list;
/* Serializes sleeping OEM captures against MTD attach/detach. */
static DEFINE_MUTEX(sheng_mtd_lock);
void mtdoops_do_dump_if(int reason);

static void sheng_mtd_long_press_work(struct work_struct *work)
{
	mtdoops_do_dump_if(SHENG_MTD_LONG_PRESS);
}
static DECLARE_WORK(sheng_mtd_long_press, sheng_mtd_long_press_work);

static int sheng_mtd_pwrkey_event(struct notifier_block *nb, unsigned long event, void *data)
{
	/* Atomic notifier callbacks cannot sleep in block-backed MTD writes. */
	queue_work(system_highpri_wq, &sheng_mtd_long_press);
	return NOTIFY_DONE;
}
static struct notifier_block sheng_mtd_pwrkey_nb = {
	.notifier_call = sheng_mtd_pwrkey_event,
};

static const char * const sheng_mtd_reasons[] = {
	"Unknown", "Kernel Panic", "Oops!", "Emerg", "Shut Down",
	"Restart", "PowerOff", "Long Press",
};
static char build_fingerprint[64];
module_param_string(fingerprint, build_fingerprint, sizeof(build_fingerprint), 0644);

/* Same three 32-bit fields as persistent_ram_buffer; never modify them. */
struct sheng_pmsg_header {
	u32 sig;
	u32 start;
	u32 size;
	u8 data[];
};
static struct sheng_pmsg_header *sheng_pmsg;
static size_t sheng_pmsg_capacity;

static size_t sheng_copy_pmsg(void *target, size_t limit)
{
	struct sheng_pmsg_chunks chunks;
	u32 start, size;

	if (!sheng_pmsg || READ_ONCE(sheng_pmsg->sig) != 0x43474244)
		return 0;
	start = READ_ONCE(sheng_pmsg->start);
	size = READ_ONCE(sheng_pmsg->size);
	if (!sheng_pmsg_chunks(sheng_pmsg_capacity, start, size, limit, &chunks)) {
		pr_warn_ratelimited("Invalid pmsg ring bounds; preserving kernel log\n");
		return 0;
	}
	memcpy(target, sheng_pmsg->data + chunks.offset, chunks.first);
	memcpy(target + chunks.first, sheng_pmsg->data, chunks.second);
	return chunks.first + chunks.second;
}

void mtdoops_do_dump_if(int reason)
{
	struct mtdoops_context *cxt = &oops_cxt;
	struct kmsg_dump_iter iter;
	struct timespec64 now;
	struct tm tm;
	size_t offset, used = 0, budget;
	bool panic;

	if (reason <= SHENG_MTD_UNDEFINED || reason > SHENG_MTD_LONG_PRESS)
		return;
	panic = reason == SHENG_MTD_PANIC || reason == SHENG_MTD_OOPS;
	if (!panic && WARN_ON_ONCE(in_interrupt() || irqs_disabled()))
		return;
	if (!panic) {
		mutex_lock(&sheng_mtd_lock);
		flush_work(&cxt->work_write);
		flush_work(&cxt->work_erase);
	}
	if (!cxt->mtd) {
		pr_warn("MTD not attached; cannot persist %s record\n", sheng_mtd_reasons[reason]);
		goto unlock;
	}
	if (test_and_set_bit(0, &cxt->oops_buf_busy))
		goto unlock;
	memset(cxt->oops_buf, 0xff, record_size);
	ktime_get_coarse_real_ts64(&now);
	time64_to_tm(now.tv_sec, 0, &tm);
	offset = mtdoops_header_size();
	offset += scnprintf(cxt->oops_buf + offset, record_size - offset,
		"\n## Index: %d\n### Build: %s\n## REASON: %s\n"
		"#### LOG TYPE: LAST KMSG\n##### %04ld-%02d-%02d %02d:%02d:%02d\n",
		cxt->nextcount, build_fingerprint, sheng_mtd_reasons[reason],
		tm.tm_year + 1900, tm.tm_mon + 1, tm.tm_mday, tm.tm_hour, tm.tm_min, tm.tm_sec);
	/* Preserve the OEM split: up to 512 KiB of kernel log, then pmsg. */
	budget = min_t(size_t, record_size - offset, 512 * 1024);
	kmsg_dump_rewind(&iter);
	kmsg_dump_get_buffer(&iter, true, cxt->oops_buf + offset, budget, &used);
	offset += used;
	if (record_size - offset > 32) {
		offset += scnprintf(cxt->oops_buf + offset, record_size - offset,
				    "\n#### LOG TYPE: LAST LOGCAT\n");
		sheng_copy_pmsg(cxt->oops_buf + offset, record_size - offset);
	}
	/* Sleeping context owns the MTD device through the completed write. */
	mtdoops_write_locked(cxt, panic);
unlock:
	if (!panic)
		mutex_unlock(&sheng_mtd_lock);
}
EXPORT_SYMBOL_GPL(mtdoops_do_dump_if);

static int sheng_mtd_reboot(struct notifier_block *nb, unsigned long event, void *data)
{
	if (event == SYS_RESTART)
		mtdoops_do_dump_if(SHENG_MTD_RESTART);
	else if (event == SYS_POWER_OFF)
		mtdoops_do_dump_if(SHENG_MTD_POWEROFF);
	return NOTIFY_DONE;
}
static struct notifier_block sheng_mtd_reboot_nb = {
	.notifier_call = sheng_mtd_reboot,
};

static int mtdoops_sheng_init(void)
{
	struct device_node *node, *ram;
	struct resource resource, ram_resource;
	struct page **pages;
	phys_addr_t start;
	u32 pmsg_size, mem_type = 0, ecc = 0;
	unsigned int count, i;
	pgprot_t protection;
	bool matched = false;
	int ret;

	node = of_find_compatible_node(NULL, NULL, "mtdoops_pmsg");
	if (!node)
		return -ENODEV;
	ret = of_address_to_resource(node, 0, &resource);
	if (!ret)
		ret = of_property_read_u32(node, "pmsg-size", &pmsg_size);
	of_node_put(node);
	if (ret)
		return ret;
	if (pmsg_size <= sizeof(*sheng_pmsg) || pmsg_size > resource_size(&resource) ||
	    pmsg_size > MTDOOPS_MAX_MTD_SIZE)
		return -EINVAL;
	start = resource.end + 1 - pmsg_size;
	if (!IS_ALIGNED(start, PAGE_SIZE) || !IS_ALIGNED(pmsg_size, PAGE_SIZE))
		return -EINVAL;
	/* Match the actual ramoops owner and its mapping attributes. */
	for_each_compatible_node(ram, NULL, "ramoops") {
		if (of_address_to_resource(ram, 0, &ram_resource) ||
		    resource.start != ram_resource.start || resource.end != ram_resource.end)
			continue;
		mem_type = of_property_read_bool(ram, "unbuffered");
		of_property_read_u32(ram, "mem-type", &mem_type);
		of_property_read_u32(ram, "ecc-size", &ecc);
		matched = true;
		of_node_put(ram);
		break;
	}
	if (!matched || ecc || mem_type > 2)
		return -EINVAL;
	protection = mem_type == 2 ? PAGE_KERNEL : mem_type == 1 ?
		pgprot_noncached(PAGE_KERNEL) : pgprot_writecombine(PAGE_KERNEL);
	count = pmsg_size >> PAGE_SHIFT;
	pages = kmalloc_array(count, sizeof(*pages), GFP_KERNEL);
	if (!pages)
		return -ENOMEM;
	for (i = 0; i < count; i++) {
		unsigned long pfn = (start >> PAGE_SHIFT) + i;

		if (!pfn_valid(pfn)) {
			kfree(pages);
			return -EINVAL;
		}
		pages[i] = pfn_to_page(pfn);
	}
	/* Same mapping as persistent_ram_vmap; this reader never resets the ring. */
	sheng_pmsg = vmap(pages, count, VM_MAP | VM_IOREMAP, protection);
	kfree(pages);
	if (!sheng_pmsg)
		return -ENOMEM;
	sheng_pmsg_capacity = pmsg_size - sizeof(*sheng_pmsg);
	ret = register_reboot_notifier(&sheng_mtd_reboot_nb);
	if (!ret) {
		ret = atomic_notifier_chain_register(&pwrkey_irq_notifier_list, &sheng_mtd_pwrkey_nb);
		if (ret)
			unregister_reboot_notifier(&sheng_mtd_reboot_nb);
	}
	if (ret) {
		vunmap(sheng_pmsg);
		sheng_pmsg = NULL;
	}
	return ret;
}

static void mtdoops_sheng_exit(void)
{
	atomic_notifier_chain_unregister(&pwrkey_irq_notifier_list, &sheng_mtd_pwrkey_nb);
	cancel_work_sync(&sheng_mtd_long_press);
	unregister_reboot_notifier(&sheng_mtd_reboot_nb);
	vunmap(sheng_pmsg);
	sheng_pmsg = NULL;
}
