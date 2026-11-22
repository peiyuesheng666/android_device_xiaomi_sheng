/* SPDX-License-Identifier: GPL-2.0-only */
#define _POSIX_C_SOURCE 200809L
#define SHENG_QTI_POGO_HOST_TEST
#include "../interfaces/kernel/6.18/helpers/sheng_qti_pogo_wire.h"
#include "../interfaces/kernel/6.18/helpers/sheng_qti_pogo.h"
#include <assert.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>
#ifdef SHENG_QTI_FG_API_TEST
#define SHENG_QTI_FG_HOST_TEST
#include "../interfaces/kernel/6.18/helpers/sheng_qti_fg_math.h"
struct power_supply { unsigned int events; };
struct psy_state { struct power_supply *psy; };
struct work_struct { unsigned int queued; };
struct delayed_work { unsigned int queued; };
#define PSY_TYPE_USB 1
#define NOTIFY_OK 1
static void schedule_work(struct work_struct *work) { work->queued++; }
static void schedule_delayed_work(struct delayed_work *work, int delay)
{ (void)delay; work->queued++; }
static void power_supply_changed(struct power_supply *psy) { psy->events++; }
#endif

struct mutex { pthread_mutex_t value; };
typedef struct mutex spinlock_t;
#define DEFINE_MUTEX(name) struct mutex name = { PTHREAD_MUTEX_INITIALIZER }
#define mutex_lock(p) ((void)pthread_mutex_lock(&(p)->value))
#define mutex_unlock(p) ((void)pthread_mutex_unlock(&(p)->value))
#define spin_lock_irqsave(p, f) do { (f) = 0; mutex_lock(p); } while (0)
#define spin_unlock_irqrestore(p, f) do { (void)(f); mutex_unlock(p); } while (0)
#define READ_ONCE(x) (x)
#define EXPORT_SYMBOL(x)
#define PMIC_GLINK_STATE_DOWN 0
#define PMIC_GLINK_STATE_UP 1
#define BC_WAIT_TIME_MS 5
#define msecs_to_jiffies(x) (x)
#define atomic_set(p, x) atomic_store(p, x)
#define atomic_read(p) atomic_load(p)
struct completion {
	pthread_mutex_t lock;
	pthread_cond_t cond;
	bool done;
};
static void complete(struct completion *p)
{
	pthread_mutex_lock(&p->lock);
	p->done = true;
	pthread_cond_broadcast(&p->cond);
	pthread_mutex_unlock(&p->lock);
}
static void reinit_completion(struct completion *p)
{
	pthread_mutex_lock(&p->lock);
	p->done = false;
	pthread_mutex_unlock(&p->lock);
}
static unsigned long wait_for_completion_timeout(struct completion *p, unsigned int ms)
{
	struct timespec deadline;
	bool done;
	clock_gettime(CLOCK_REALTIME, &deadline);
	deadline.tv_nsec += (long)ms * 1000000;
	deadline.tv_sec += deadline.tv_nsec / 1000000000;
	deadline.tv_nsec %= 1000000000;
	pthread_mutex_lock(&p->lock);
	while (!p->done)
		if (pthread_cond_timedwait(&p->cond, &p->lock, &deadline) == ETIMEDOUT)
			break;
	done = p->done;
	pthread_mutex_unlock(&p->lock);
	return done;
}
struct battery_chg_dev {
#ifdef SHENG_QTI_FG_API_TEST
	struct sheng_fg_state sheng_fg;
	struct battmngr_device *sheng_qti_ops;
	int fake_soc;
	struct psy_state psy_list[4];
	struct work_struct usb_type_work;
	struct delayed_work xm_prop_change_work;
#endif
	struct mutex rw_lock;
	spinlock_t sheng_pogo_lock;
	struct completion sheng_pogo_ack;
	struct sheng_pogo_pending sheng_pogo;
	atomic_int state;
	bool initialized, debug_battery_detected, block_tx;
	void *client;
};
static int pmic_glink_write(void *client, void *data, int len);
#include "../interfaces/kernel/6.18/helpers/sheng_qti_pogo_api.h"

static unsigned long checks;
#define CHECK(x) do { assert(x); checks++; } while (0)
static u8 sent[28];
static int sent_len, transport_error;
static u32 reply_value = 1, firmware_error;
static bool no_reply, wrong_property, link_reset, short_reply;
static atomic_uint sends;
#ifdef SHENG_QTI_FG_API_TEST
static bool fg_mode;
static u32 fg_values[233], battery_values[32], fg_error_property = UINT32_MAX;
static u8 fg_frames[6][28];
static unsigned int fg_frame_count;
#endif

static int pmic_glink_write(void *client, void *data, int len)
{
	struct battery_chg_dev *bc = client;
	u8 reply[28] = {};
	u32 prop;
	sends++;
	CHECK(len == 24 || len == 28);
	memcpy(sent, data, (size_t)len);
	sent_len = len;
	if (transport_error)
		return transport_error;
	if (link_reset) {
		sheng_pogo_state_change(bc, PMIC_GLINK_STATE_DOWN);
		sheng_pogo_state_change(bc, PMIC_GLINK_STATE_UP);
		return 0;
	}
	if (no_reply)
		return 0;
	memcpy(reply, data, 12);
	prop = sheng_pogo_get32(sent + (len == 28 ? 12 : 16));
	sheng_pogo_put32(reply + 12, prop + (wrong_property ? 1 : 0));
	sheng_pogo_put32(reply + 16, reply_value);
#ifdef SHENG_QTI_FG_API_TEST
	if (fg_mode) {
		u32 opcode = sheng_pogo_get32(sent + 8);
		CHECK(fg_frame_count < 6);
		memcpy(fg_frames[fg_frame_count++],sent,(size_t)len);
		CHECK(prop < (opcode == 0x30 ? 32U : 233U));
		sheng_pogo_put32(reply+16,opcode == 0x30 ? battery_values[prop] : fg_values[prop]);
	}
#endif
	if (len == 28) {
		reply[20] = sent[20];
		sheng_pogo_put32(reply + 24, firmware_error);
	} else {
		sheng_pogo_put32(reply + 20, firmware_error);
	}
#ifdef SHENG_QTI_FG_API_TEST
	if (fg_mode && prop == fg_error_property)
		sheng_pogo_put32(reply+20,42);
#endif
	(void)sheng_pogo_response(bc, reply, short_reply ? 17 : (size_t)len);
	return 0;
}

/* Native OEM struct layouts provide independent expected request bytes. */
struct header { u32 owner, type, opcode; };
struct stock_property { struct header hdr; u32 battery_id, property, value; };
struct stock_voter { struct header hdr; u32 property, value; u8 vote; u32 operation; };
static void codec_test(void)
{
	struct sheng_pogo_request req;
	struct sheng_pogo_reply decoded;
	u8 bytes[28], response[28];
	u32 values[] = {0,1,0x80000000U,0xffffffffU,7000000};
	u32 properties[] = {222,223,224,225,228};
	size_t i, j, len, n;
	unsigned int write, vote;

	CHECK(sizeof(struct stock_property) == 24);
	CHECK(sizeof(struct stock_voter) == 28);
	for (write = 0; write < 2; write++) {
		for (i = 0; i < sizeof(properties)/sizeof(properties[0]); i++) {
			for (j = 0; j < sizeof(values)/sizeof(values[0]); j++) {
				struct stock_property expected = {{32778,1,write ? 0x51 : 0x50},
					0, properties[i], write ? values[j] : 0};
				req = (struct sheng_pogo_request){.opcode=expected.hdr.opcode,.property=properties[i]};
				CHECK(sheng_pogo_encode(bytes, sizeof(bytes), &req, values[j]) == 24);
				CHECK(memcmp(bytes, &expected, 24) == 0);
			}
		}
		for (vote = 0; vote < 3; vote++) {
			for (j = 0; j < sizeof(values)/sizeof(values[0]); j++) {
				struct stock_voter expected;
				memset(&expected,0,sizeof(expected));
				expected.hdr = (struct header){32778,1,write ? 0x51 : 0x50};
				expected.property = 229; expected.value = write ? values[j] : 0;
				expected.vote = vote; expected.operation = write;
				req = (struct sheng_pogo_request){.opcode=expected.hdr.opcode,.property=229,.voter=true,.vote=vote};
				CHECK(sheng_pogo_encode(bytes,sizeof(bytes),&req,values[j]) == 28);
				CHECK(memcmp(bytes,&expected,28) == 0);
			}
		}
	}
	for (vote = 0; vote < 2; vote++) {
		req = (struct sheng_pogo_request){.opcode=0x50,.property=vote ? 229 : 223,.voter=vote,.vote=2};
		len = vote ? 28 : 24;
		memset(response,0,sizeof(response));
		sheng_pogo_put32(response,32778); sheng_pogo_put32(response+4,1);
		sheng_pogo_put32(response+8,0x50); sheng_pogo_put32(response+12,req.property);
		sheng_pogo_put32(response+16,0xabcdef); response[20] = vote ? 2 : 0;
		for (n = 0; n <= 32; n++) {
			u8 *exact = malloc(n ? n : 1);
			memset(exact,0,n);
			memcpy(exact,response,n < len ? n : len);
			CHECK(sheng_pogo_decode(&req,exact,n,&decoded) ==
				(n < 12 ? 0 : n == len ? 1 : -EMSGSIZE));
			free(exact);
		}
		for (i = 0; i < len; i++) {
			for (j = 0; j < 256; j++) {
				u8 old = response[i];
				response[i] = (u8)j;
				CHECK(sheng_pogo_decode(&req,response,len,&decoded) >= 0);
				response[i] = old;
			}
		}
	}
	req = (struct sheng_pogo_request){.opcode=0x50,.property=229,.voter=true,.vote=3};
	CHECK(sheng_pogo_encode(bytes,sizeof(bytes),&req,0) == -EINVAL);
}

static void reset_link(struct battery_chg_dev *bc)
{
	no_reply = wrong_property = link_reset = short_reply = false;
	transport_error = 0; firmware_error = 0;
	sheng_pogo_state_change(bc,PMIC_GLINK_STATE_DOWN);
	sheng_pogo_state_change(bc,PMIC_GLINK_STATE_UP);
}
static void *pending_request(void *result)
{
	*(int *)result = qti_set_keyboard_plugin(1);
	return NULL;
}
static void *parallel_requests(void *result)
{
	unsigned int i;
	int ret = 0;
	for (i = 0; i < 64; i++) {
		if (qti_get_DCIN_STATE() != 1 || qti_set_keyboard_plugin(1))
			ret = -1;
	}
	*(int *)result = ret;
	return NULL;
}
static void api_test(void)
{
	struct battery_chg_dev bc = {
		.rw_lock = {PTHREAD_MUTEX_INITIALIZER},
		.sheng_pogo_lock = {PTHREAD_MUTEX_INITIALIZER},
		.sheng_pogo_ack = {PTHREAD_MUTEX_INITIALIZER,PTHREAD_COND_INITIALIZER,false},
		.initialized=true,
	};
	unsigned int before;
	pthread_t worker[4];
	int results[4] = {};
	unsigned int i;
	CHECK(qti_set_keyboard_plugin(1) == -ENODEV);
	bc.client = &bc; sheng_keyboard_bcdev = &bc;
	reset_link(&bc);
	CHECK(qti_set_keyboard_plugin(2) == -EINVAL);
	CHECK(qti_set_keyboard_plugin(1) == 0);
	CHECK(sent_len == 24 && sheng_pogo_get32(sent+16) == 228 && sheng_pogo_get32(sent+20) == 1);
	CHECK(sc8651_wpc_gate_set(1) == 0 && sheng_pogo_get32(sent+16) == 222);
	CHECK(qti_enale_charge(0) == 0 && sheng_pogo_get32(sent+16) == 225);
	reply_value = 4;
	CHECK(qti_get_ADC_CHGR_STATUS() == 4 && sheng_pogo_get32(sent+16) == 224);
	reply_value = 1;
	CHECK(qti_get_DCIN_STATE() == 1 && sheng_pogo_get32(sent+16) == 223);
	firmware_error = 77;
	CHECK(qti_get_DCIN_STATE() == -EREMOTEIO);
	/* OEM voter selector is not interpreted as a standard ret_code. */
	CHECK(write_voter_prop_id(2,123456) == 0);
	CHECK(sent_len == 28 && sent[20] == 2 && sheng_pogo_get32(sent+24) == 1);
	CHECK(read_voter_property_id(1,999) == 0 && sheng_pogo_get32(sent+12) == 229);
	CHECK(sheng_pogo_get32(sent+16) == 0 && sheng_pogo_get32(sent+24) == 0);
	CHECK(write_voter_prop_id(3,1) == -EINVAL);
	before = sends;
	bc.block_tx = bc.debug_battery_detected = true;
	CHECK(qti_set_keyboard_plugin(1) == -EACCES && before == sends);
	bc.block_tx = bc.debug_battery_detected = false;
	bc.initialized = false;
	CHECK(qti_get_DCIN_STATE() == -ENODEV && before == sends);
	bc.initialized = true;
	sheng_pogo_state_change(&bc,PMIC_GLINK_STATE_DOWN);
	CHECK(qti_set_keyboard_plugin(1) == -ENOTCONN && before == sends);
	reset_link(&bc);
	transport_error = -EIO;
	CHECK(qti_set_keyboard_plugin(1) == -EIO);
	reset_link(&bc); wrong_property = true;
	CHECK(qti_set_keyboard_plugin(1) == -ETIMEDOUT);
	before = sends;
	CHECK(qti_set_keyboard_plugin(1) == -EPIPE && sends == before);
	reset_link(&bc); short_reply = true;
	CHECK(qti_set_keyboard_plugin(1) == -EMSGSIZE);
	CHECK(qti_set_keyboard_plugin(1) == -EPIPE);
	reset_link(&bc); link_reset = true;
	CHECK(qti_set_keyboard_plugin(1) == -ENOTCONN);
	reset_link(&bc);
	CHECK(qti_set_keyboard_plugin(1) == 0);
	/* Concurrent clients exercise the real owner/rw locks and matching ACK. */
	for (i = 0; i < 4; i++)
		CHECK(pthread_create(&worker[i],NULL,parallel_requests,&results[i]) == 0);
	for (i = 0; i < 4; i++) {
		CHECK(pthread_join(worker[i],NULL) == 0);
		CHECK(results[i] == 0);
	}
	/* Device removal interrupts an outstanding real request, then drains its
	 * lifetime lock; it does not wait for or manufacture a success response. */
	no_reply = true;
	before = sends;
	CHECK(pthread_create(&worker[0],NULL,pending_request,&results[0]) == 0);
	while (sends == before) {
		struct timespec pause = {0,100000};
		nanosleep(&pause,NULL);
	}
	sheng_pogo_state_change(&bc,PMIC_GLINK_STATE_DOWN);
	mutex_lock(&sheng_keyboard_charger_lock);
	sheng_keyboard_bcdev = NULL;
	mutex_unlock(&sheng_keyboard_charger_lock);
	CHECK(pthread_join(worker[0],NULL) == 0);
	CHECK(results[0] == -ENOTCONN);
	CHECK(qti_set_keyboard_plugin(1) == -ENODEV);
	sheng_keyboard_bcdev = NULL;
}
int main(void)
{
	codec_test(); api_test();
	printf("%lu QTI pogo wire and production API assertions passed\n",checks);
	return 0;
}
