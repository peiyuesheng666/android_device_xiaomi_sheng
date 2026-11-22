/* SPDX-License-Identifier: GPL-2.0-only */
#define _POSIX_C_SOURCE 200809L
#define SHENG_QTI_POGO_HOST_TEST
#include <assert.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>
#include "../interfaces/kernel/6.18/helpers/sheng_qti_irq_wire.h"
struct battmngr_notify {
	struct { int irq_type, value; } irq_msg;
	struct { u8 thermal_level; } misc_msg;
	pthread_mutex_t notify_lock;
};
struct mock_srcu { pthread_mutex_t lock; pthread_cond_t idle; int readers; };
#define DEFINE_STATIC_SRCU(name) static struct mock_srcu name = { PTHREAD_MUTEX_INITIALIZER, PTHREAD_COND_INITIALIZER, 0 }
#define DEFINE_MUTEX(name) pthread_mutex_t name = PTHREAD_MUTEX_INITIALIZER
#define mutex_lock pthread_mutex_lock
#define mutex_unlock pthread_mutex_unlock
#define EXPORT_SYMBOL(name)
#define rcu_access_pointer(ptr) atomic_load(&(ptr))
#define rcu_assign_pointer(ptr, value) atomic_store(&(ptr), (value))
#define srcu_dereference(ptr, srcu) ((void)(srcu), atomic_load(&(ptr)))
static int srcu_read_lock(struct mock_srcu *s)
{ pthread_mutex_lock(&s->lock);s->readers++;pthread_mutex_unlock(&s->lock);return 0; }
static void srcu_read_unlock(struct mock_srcu *s, int cookie)
{ assert(cookie==0);pthread_mutex_lock(&s->lock);assert(s->readers>0);if(!--s->readers)pthread_cond_broadcast(&s->idle);pthread_mutex_unlock(&s->lock); }
static void synchronize_srcu(struct mock_srcu *s)
{ pthread_mutex_lock(&s->lock);while(s->readers)pthread_cond_wait(&s->idle,&s->lock);pthread_mutex_unlock(&s->lock); }
static _Atomic(struct battmngr_notify *) g_battmngr_noti;
#include "../interfaces/kernel/6.18/helpers/sheng_battmngr_notify_api.h"
struct work_struct { void (*fn)(struct work_struct *); pthread_mutex_t lock; pthread_cond_t idle; bool running; };
struct sheng_qti_irq_entry;
struct battery_chg_dev {
	pthread_mutex_t sheng_irq_lock;
	struct sheng_qti_irq_entry *sheng_irq_head, *sheng_irq_tail;
	struct work_struct sheng_irq_work;
	atomic_bool sheng_irq_stopping;
	atomic_bool initialized;
	atomic_int state;
	struct { atomic_uint epoch; } sheng_pogo;
	int curr_thermal_level;
	struct { bool pogo, full; } sheng_fg;
};
#define PMIC_GLINK_STATE_UP 1
#define PMIC_GLINK_STATE_DOWN 0
#define BATTMNGR_EVENT_IRQ 6
#define GFP_ATOMIC 0
#define READ_ONCE(value) (value)
#define atomic_read(ptr) atomic_load(ptr)
#define container_of(ptr, type, member) ((type *)((char *)(ptr) - offsetof(type, member)))
#define spin_lock_irqsave(lock, flags) ((flags)=0, pthread_mutex_lock(lock))
#define spin_unlock_irqrestore(lock, flags) ((void)(flags), pthread_mutex_unlock(lock))
static DEFINE_MUTEX(sheng_keyboard_charger_lock);
static struct battery_chg_dev *sheng_keyboard_bcdev;
static int allocations, frees, scheduled, report_calls, callback_count, allocation_fail;
static int callback_types[4096],callback_values[4096],callback_thermal[4096];
static atomic_bool block_callback,callback_entered,release_callback,stop_done;
static void *kmalloc(size_t bytes,int flags)
{ (void)flags;if(allocation_fail)return NULL;allocations++;return malloc(bytes); }
static void kfree(void *p) { if(p){frees++;free(p);} }
static bool schedule_work(struct work_struct *work) { (void)work;scheduled++;return true; }
static void cancel_work_sync(struct work_struct *work)
{ pthread_mutex_lock(&work->lock);while(work->running)pthread_cond_wait(&work->idle,&work->lock);pthread_mutex_unlock(&work->lock); }
static int qti_deal_report(void) { report_calls++;return 1; }
static void brief_wait(void) { struct timespec d={.tv_nsec=1000000};nanosleep(&d,NULL); }
static int battmngr_notifier_call_chain(unsigned long event,struct battmngr_notify *data)
{
	assert(event==BATTMNGR_EVENT_IRQ);
	assert(!pthread_mutex_trylock(&sheng_keyboard_charger_lock));
	pthread_mutex_unlock(&sheng_keyboard_charger_lock);
	assert(callback_count<4096);
	callback_types[callback_count]=data->irq_msg.irq_type;
	callback_values[callback_count]=data->irq_msg.value;
	callback_thermal[callback_count++]=data->misc_msg.thermal_level;
	/* A callback can nest an SRCU lookup without blocking receive or removal. */
	int cookie;assert(battmngr_notify_acquire(&cookie)==data);battmngr_notify_release(cookie);
	if(atomic_load(&block_callback)) {
		atomic_store(&callback_entered,true);
		while(!atomic_load(&release_callback))brief_wait();
	}
	return 1;
}
#include "../interfaces/kernel/6.18/helpers/sheng_qti_irq_api.h"
static struct battery_chg_dev dev;
static struct battmngr_notify notify;
static bool initialized_once;
static void setup(void)
{
	if(!initialized_once) {
		pthread_mutex_init(&dev.sheng_irq_lock,NULL);
		pthread_mutex_init(&dev.sheng_irq_work.lock,NULL);
		pthread_cond_init(&dev.sheng_irq_work.idle,NULL);
		pthread_mutex_init(&notify.notify_lock,NULL);
		initialized_once=true;
	}
	assert(!dev.sheng_irq_head && !dev.sheng_irq_tail && !dev.sheng_irq_work.running);
	dev.sheng_irq_work.fn=sheng_qti_irq_work;dev.sheng_irq_stopping=false;
	atomic_store(&dev.initialized,true);atomic_store(&dev.state,1);atomic_store(&dev.sheng_pogo.epoch,0);
	dev.curr_thermal_level=7;dev.sheng_fg.full=true;dev.sheng_fg.pogo=true;
	sheng_keyboard_bcdev=&dev;
	notify.irq_msg.irq_type=-1;notify.irq_msg.value=-1;notify.misc_msg.thermal_level=42;
	callback_count=report_calls=scheduled=0;
	atomic_store(&block_callback,false);atomic_store(&callback_entered,false);
	atomic_store(&release_callback,false);atomic_store(&stop_done,false);
}
static void frame(u8 *bytes,u32 type,u8 value)
{
	memset(bytes,0,20);sheng_pogo_put32(bytes,32778);sheng_pogo_put32(bytes+4,2);
	sheng_pogo_put32(bytes+8,0x52);bytes[12]=value;sheng_pogo_put32(bytes+16,type);
}
static void *run_worker(void *arg)
{
	struct work_struct *work=arg;
	pthread_mutex_lock(&work->lock);assert(!work->running);work->running=true;pthread_mutex_unlock(&work->lock);
	work->fn(work);
	pthread_mutex_lock(&work->lock);work->running=false;pthread_cond_broadcast(&work->idle);pthread_mutex_unlock(&work->lock);
	return NULL;
}
int sheng_irq_bridge(int type,int value,int pogo,int full,int thermal,int present,int *out)
{
	u8 bytes[20];setup();dev.sheng_fg.pogo=pogo;dev.sheng_fg.full=full;dev.curr_thermal_level=thermal;
	if(present)assert(!battmngr_notify_publish(&notify));
	frame(bytes,type,value);int ret=sheng_qti_irq_receive(&dev,bytes,20);assert(!ret);
	assert(!callback_count);run_worker(&dev.sheng_irq_work);
	out[0]=dev.sheng_fg.pogo;out[1]=dev.sheng_fg.full;out[2]=notify.irq_msg.irq_type;
	out[3]=notify.irq_msg.value;out[4]=notify.misc_msg.thermal_level;
	out[5]=callback_count;out[6]=report_calls;
	if(present)assert(!battmngr_notify_unpublish(&notify));
	sheng_qti_irq_stop(&dev);
	assert(allocations==frees);return ret;
}
#ifndef SHENG_QTI_IRQ_LIBRARY
static void *unpublish(void *arg)
{ assert(!battmngr_notify_unpublish(arg));atomic_store(&stop_done,true);return NULL; }
static void *stop_irq(void *arg)
{ sheng_qti_irq_stop(arg);atomic_store(&stop_done,true);return NULL; }
int main(void)
{
	u8 bytes[21];struct sheng_qti_irq irq={.type=99,.value=99};int cookie;
	assert(!battmngr_notify_acquire(&cookie)&&cookie==-1);battmngr_notify_release(cookie);
	assert(!battmngr_notify_acquire(NULL));
	assert(battmngr_notify_publish(NULL)==-EINVAL && battmngr_notify_unpublish(NULL)==-EINVAL);
	setup();assert(!battmngr_notify_publish(&notify));assert(battmngr_notify_publish(&notify)==-EBUSY);
	struct battmngr_notify other={0};assert(battmngr_notify_unpublish(&other)==-ENOENT);
	assert(battmngr_notify_acquire(&cookie)==&notify);
	pthread_t thread;assert(!pthread_create(&thread,NULL,unpublish,&notify));
	while(atomic_load(&g_battmngr_noti))brief_wait();
	assert(!atomic_load(&stop_done));battmngr_notify_release(cookie);assert(!pthread_join(thread,NULL));
	assert(atomic_load(&stop_done));
	frame(bytes,0,1);
	for(size_t len=0;len<=21;len++)if(len!=20){
		u8 *exact=malloc(len?len:1);memcpy(exact,bytes,len);
		assert(sheng_qti_irq_decode(exact,len,&irq)==-EMSGSIZE);free(exact);
		assert(irq.type==99&&irq.value==99);
	}
	assert(sheng_qti_irq_decode(NULL,20,&irq)==-EINVAL);
	assert(sheng_qti_irq_decode(bytes,20,NULL)==-EINVAL);
	bytes[0]^=1;assert(sheng_qti_irq_decode(bytes,20,&irq)==-EPROTO);bytes[0]^=1;
	bytes[8]^=1;assert(sheng_qti_irq_decode(bytes,20,&irq)==-EPROTO);bytes[8]^=1;
	sheng_pogo_put32(bytes+16,3);assert(sheng_qti_irq_decode(bytes,20,&irq)==-ERANGE);
	/* The valid-byte/padding/type matrix keeps the original compatibility. */
	int cases=0;for(int type=0;type<3;type++)for(int value=0;value<256;value++)for(int hdr=0;hdr<4;hdr++){
		frame(bytes,type,value);bytes[13]=0x7f;bytes[14]=0xff;bytes[15]=0x55;sheng_pogo_put32(bytes+4,hdr);
		assert(!sheng_qti_irq_decode(bytes,20,&irq));assert(irq.type==(u32)type&&irq.value==value);cases++;
	}
	setup();assert(!battmngr_notify_publish(&notify));
	for(int i=0;i<1000;i++){frame(bytes,i%3,(u8)i);assert(!sheng_qti_irq_receive(&dev,bytes,20));}
	assert(!callback_count&&scheduled==1000);run_worker(&dev.sheng_irq_work);assert(callback_count==1000);
	for(int i=0;i<1000;i++)assert(callback_types[i]==i%3&&callback_values[i]==(u8)i);
	assert(report_calls==334 && allocations==frees);assert(!battmngr_notify_unpublish(&notify));
	setup();frame(bytes,0,1);allocation_fail=1;assert(sheng_qti_irq_receive(&dev,bytes,20)==-ENOMEM);allocation_fail=0;
	assert(!dev.sheng_irq_head);assert(!sheng_qti_irq_receive(&dev,bytes,20));
	atomic_fetch_add(&dev.sheng_pogo.epoch,1);run_worker(&dev.sheng_irq_work);assert(!callback_count&&!report_calls);
	setup();assert(!sheng_qti_irq_receive(&dev,bytes,20));atomic_store(&dev.state,0);run_worker(&dev.sheng_irq_work);assert(!report_calls);
	setup();assert(!battmngr_notify_publish(&notify));assert(!sheng_qti_irq_receive(&dev,bytes,20));
	atomic_store(&block_callback,true);pthread_t worker,stopper;
	assert(!pthread_create(&worker,NULL,run_worker,&dev.sheng_irq_work));while(!atomic_load(&callback_entered))brief_wait();
	atomic_store(&dev.initialized,false);assert(!pthread_create(&stopper,NULL,stop_irq,&dev));
	while(!atomic_load(&dev.sheng_irq_stopping))brief_wait();
	assert(!atomic_load(&stop_done));assert(sheng_qti_irq_receive(&dev,bytes,20)==-ENODEV);
	atomic_store(&release_callback,true);assert(!pthread_join(worker,NULL));assert(!pthread_join(stopper,NULL));
	assert(atomic_load(&stop_done));assert(!battmngr_notify_unpublish(&notify));assert(allocations==frees);
	setup();assert(!sheng_qti_irq_receive(&dev,bytes,20));sheng_qti_irq_stop(&dev);assert(!dev.sheng_irq_head&&!dev.sheng_irq_tail);
	assert(sheng_qti_irq_receive(&dev,bytes,20)==-ENODEV);assert(allocations==frees);
	printf("%d IRQ byte cases; 1000 FIFO packets, stale sessions, allocation errors, guarded removal and worker drain passed\n",cases);
	return 0;
}
#endif
