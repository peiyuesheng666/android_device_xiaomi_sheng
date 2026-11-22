/* SPDX-License-Identifier: GPL-2.0-only */
#define SHENG_QTI_IRQ_LIBRARY
#include "test_sheng_kernel_qti_irq.c"
static DEFINE_MUTEX(nano_api_lock);
static void *g_nodev;
static int nano_ret,nano_calls;
static atomic_bool nano_block,nano_entered,nano_release,nano_removal_done;
static struct battmngr_notify *nano_expected;
static int nano_get_real_locked(int *out,struct battmngr_notify *data)
{
	assert(data==nano_expected);
	assert(pthread_mutex_trylock(&nano_api_lock)==EBUSY);
	/* notify_lock may already belong to the calling consumer. */
	nano_calls++;
	atomic_store(&nano_entered,true);
	while(atomic_load(&nano_block)&&!atomic_load(&nano_release))brief_wait();
	*out=data->irq_msg.value;
	return nano_ret;
}
static int nano_get_usb_locked(int *out,struct battmngr_notify *data)
{ return nano_get_real_locked(out,data); }
static int nano_online_locked(u8 *out,struct battmngr_notify *data)
{ int value;int ret=nano_get_real_locked(&value,data);*out=value;return ret; }
#include "../interfaces/kernel/6.18/helpers/sheng_nano_notify_get.h"
SHENG_NANO_NOTIFY_GETTER(nano_get_real,int,nano_get_real_locked)
SHENG_NANO_NOTIFY_GETTER(nano_get_usb,int,nano_get_usb_locked)
SHENG_NANO_NOTIFY_GETTER(nano_get_online,u8,nano_online_locked)
static void *nano_reader(void *arg)
{ (void)arg;int value=-1;assert(nano_get_real(&value)==0&&value==71);return NULL; }
static void *nano_remover(void *arg)
{ assert(!battmngr_notify_unpublish(arg));atomic_store(&nano_removal_done,true);return NULL; }
int main(void)
{
	setup();int value=123;u8 online=123;
	assert(nano_get_real(NULL)==-EINVAL&&nano_get_usb(NULL)==-EINVAL&&nano_get_online(NULL)==-EINVAL);
	assert(nano_get_real(&value)==-ENODEV&&value==123);
	g_nodev=&dev;assert(nano_get_usb(&value)==-ENODEV&&value==123);
	assert(!battmngr_notify_publish(&notify));nano_expected=&notify;notify.irq_msg.value=71;
	g_nodev=NULL;assert(nano_get_real(&value)==-ENODEV&&value==123);g_nodev=&dev;
	assert(!nano_calls);nano_ret=0;
	assert(nano_get_real(&value)==0&&value==71);
	assert(nano_get_usb(&value)==0&&value==71);
	nano_ret=1;assert(nano_get_online(&online)==1&&online==71);
	/* Calls from a notifier already holding notify_lock cannot deadlock. */
	pthread_mutex_lock(&notify.notify_lock);
	assert(nano_get_usb(&value)==1&&value==71);
	pthread_mutex_unlock(&notify.notify_lock);
	nano_ret=-EREMOTEIO;value=555;online=99;
	assert(nano_get_real(&value)==-EREMOTEIO&&value==555);
	assert(nano_get_usb(&value)==-EREMOTEIO&&value==555);
	assert(nano_get_online(&online)==-EREMOTEIO&&online==99);
	nano_ret=0;atomic_store(&nano_block,true);atomic_store(&nano_entered,false);
	pthread_t reader_thread,remover_thread;
	assert(!pthread_create(&reader_thread,NULL,nano_reader,NULL));while(!atomic_load(&nano_entered))brief_wait();
	assert(!pthread_create(&remover_thread,NULL,nano_remover,&notify));
	while(atomic_load(&g_battmngr_noti))brief_wait();assert(!atomic_load(&nano_removal_done));
	atomic_store(&nano_release,true);
	assert(!pthread_join(reader_thread,NULL));assert(!pthread_join(remover_thread,NULL));
	assert(atomic_load(&nano_removal_done));
	assert(nano_get_real(&value)==-ENODEV&&value==555);
	assert(!sheng_notify_srcu.readers);
	puts("Production nano getters preserve values/errors and drain sleeping readers; nested notifier queries passed");
	return 0;
}
