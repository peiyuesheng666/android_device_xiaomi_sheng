/* SPDX-License-Identifier: GPL-2.0-only */
/* Keep the original exported object, but guard readers through removal. */
static DEFINE_MUTEX(sheng_notify_owner_lock);
DEFINE_STATIC_SRCU(sheng_notify_srcu);

int battmngr_notify_publish(struct battmngr_notify *data)
{
	int ret = 0;

	if (!data)
		return -EINVAL;
	mutex_lock(&sheng_notify_owner_lock);
	if (rcu_access_pointer(g_battmngr_noti))
		ret = -EBUSY;
	else
		rcu_assign_pointer(g_battmngr_noti, data);
	mutex_unlock(&sheng_notify_owner_lock);
	return ret;
}
EXPORT_SYMBOL(battmngr_notify_publish);

int battmngr_notify_unpublish(struct battmngr_notify *data)
{
	int ret = 0;

	if (!data)
		return -EINVAL;
	mutex_lock(&sheng_notify_owner_lock);
	if (rcu_access_pointer(g_battmngr_noti) != data)
		ret = -ENOENT;
	else
		rcu_assign_pointer(g_battmngr_noti, NULL);
	mutex_unlock(&sheng_notify_owner_lock);
	/* Hold no owner lock while waiting: callbacks can nest guarded reads. */
	if (!ret)
		synchronize_srcu(&sheng_notify_srcu);
	return ret;
}
EXPORT_SYMBOL(battmngr_notify_unpublish);

struct battmngr_notify *battmngr_notify_acquire(int *cookie)
{
	struct battmngr_notify *data;

	if (!cookie)
		return NULL;
	*cookie = srcu_read_lock(&sheng_notify_srcu);
	data = srcu_dereference(g_battmngr_noti, &sheng_notify_srcu);
	if (!data) {
		srcu_read_unlock(&sheng_notify_srcu, *cookie);
		*cookie = -1;
	}
	return data;
}
EXPORT_SYMBOL(battmngr_notify_acquire);

void battmngr_notify_release(int cookie)
{
	if (cookie >= 0)
		srcu_read_unlock(&sheng_notify_srcu, cookie);
}
EXPORT_SYMBOL(battmngr_notify_release);
