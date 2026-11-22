/* SPDX-License-Identifier: GPL-2.0-only */
#include <assert.h>
#include <stdbool.h>
#include <errno.h>
#include <stdio.h>
struct i2c_client { int irq; };
struct nanosic_wn8030 {
    bool ready, removing, suspended, connection_known;
    unsigned recovery_count, fw_attempts;
    unsigned long recovery_window;
    int io_lock, conn_mutex, fw_worker, dev;
    struct i2c_client *client;
};
static unsigned long jiffies;
static unsigned disables, queues;
#define HZ 100
#define time_after(a,b) ((long)((b)-(a)) < 0)
#define lockdep_assert_held(p) assert(*(p) == 1)
#define mutex_lock(p) do { assert(*(p)==0); *(p)=1; } while(0)
#define mutex_unlock(p) do { assert(*(p)==1); *(p)=0; } while(0)
#define system_wq 1
#define dev_warn(...) ((void)0)
static void disable_irq_nosync(int irq) { assert(irq==7); ++disables; }
static void mod_delayed_work(int queue,int *work,int delay) {
    assert(queue==1 && delay==0); ++queues;
}
#include "../interfaces/kernel/6.18/helpers/sheng_nanosic_recovery.h"
int main(void) {
    struct i2c_client client={7};
    struct nanosic_wn8030 n={.ready=true,.connection_known=true,.io_lock=1,.client=&client};
    sheng_nano_recover_after_timeout_locked(&n,-EIO); assert(queues==0 && n.ready);
    n.suspended=true; sheng_nano_recover_after_timeout_locked(&n,-ETIMEDOUT); assert(queues==0);
    n.suspended=false; n.removing=true;
    sheng_nano_recover_after_timeout_locked(&n,-ETIMEDOUT); assert(queues==0);
    n.removing=false;
    sheng_nano_recover_after_timeout_locked(&n,-ETIMEDOUT);
    assert(queues==1 && disables==1 && !n.ready && !n.connection_known);
    sheng_nano_recover_after_timeout_locked(&n,-ETIMEDOUT); assert(queues==1);
    for(int i=0;i<3;i++) { n.ready=true; sheng_nano_recover_after_timeout_locked(&n,-ETIMEDOUT); }
    assert(queues==3 && disables==3 && n.ready);
    jiffies=60*HZ+1;
    sheng_nano_recover_after_timeout_locked(&n,-ETIMEDOUT);
    assert(queues==4 && disables==4 && n.recovery_count==1);
    puts("Recovery error gating, coalescing, IRQ safety and rate limit passed");
}
