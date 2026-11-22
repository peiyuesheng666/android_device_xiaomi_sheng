/* SPDX-License-Identifier: GPL-2.0-only */
#define _POSIX_C_SOURCE 200809L
#include <assert.h>
#include <errno.h>
#include <pthread.h>
#include <stdbool.h>
#include <stdatomic.h>
#include <stdio.h>
#include <time.h>
struct battmngr_ops { int (*get)(int *); int (*set)(int); };
struct battmngr_device { pthread_mutex_t ops_lock; const struct battmngr_ops *ops; };
#define mutex_lock pthread_mutex_lock
#define mutex_unlock pthread_mutex_unlock
#include "../interfaces/kernel/6.18/helpers/sheng_battmngr_calls.h"
SHENG_BATTMNGR_GETTER(test_get, int, get)
SHENG_BATTMNGR_SETTER(test_set, set)
static int result, calls, sent;
static atomic_bool blocking, entered, release_call, stopped;
static int get(int *out)
{
	calls++;
	if (atomic_load(&blocking)) {
		atomic_store(&entered, true);
		while (!atomic_load(&release_call)) {
			struct timespec delay = { .tv_nsec = 1000000 };
			nanosleep(&delay, NULL);
		}
	}
	*out = 43;
	return result;
}
static int set(int value) { calls++; sent = value; return result; }
static void *reader(void *arg) { assert(test_get(arg) == 43); return NULL; }
static void *stopper(void *arg)
{ sheng_battmngr_stop_ops(arg); atomic_store(&stopped, true); return NULL; }
int main(void)
{
	struct battmngr_ops ops = { get, set }, empty = { 0 };
	struct battmngr_device dev = { .ops_lock = PTHREAD_MUTEX_INITIALIZER, .ops = &ops };
	assert(test_get(NULL) == -EOPNOTSUPP);
	assert(test_set(NULL, 1) == -EOPNOTSUPP);
	assert(test_get(&dev) == 43);
	assert(test_set(&dev, 7) == 7 && sent == 7);
	result = -EREMOTEIO;
	assert(test_get(&dev) == -EREMOTEIO);
	assert(test_set(&dev, 9) == -EREMOTEIO);
	dev.ops = &empty;
	assert(test_get(&dev) == -EOPNOTSUPP);
	assert(test_set(&dev, 1) == -EOPNOTSUPP);
	dev.ops = &ops; result = 0;
	atomic_store(&blocking, true);
	pthread_t read_thread, stop_thread;
	assert(!pthread_create(&read_thread, NULL, reader, &dev));
	while (!atomic_load(&entered)) {
		struct timespec delay = { .tv_nsec = 1000000 };
		nanosleep(&delay, NULL);
	}
	assert(!pthread_create(&stop_thread, NULL, stopper, &dev));
	struct timespec delay = { .tv_nsec = 20000000 };
	nanosleep(&delay, NULL);
	assert(!atomic_load(&stopped));
	atomic_store(&release_call, true);
	assert(!pthread_join(read_thread, NULL));
	assert(!pthread_join(stop_thread, NULL));
	assert(atomic_load(&stopped) && !dev.ops);
	assert(test_get(&dev) == -EOPNOTSUPP);
	assert(test_set(&dev, 0) == -EOPNOTSUPP);
	assert(calls == 5);
	pthread_mutex_destroy(&dev.ops_lock);
	puts("Battery-manager callback errors and concurrent unregister passed");
	return 0;
}
