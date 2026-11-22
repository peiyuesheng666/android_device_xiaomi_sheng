/* SPDX-License-Identifier: GPL-2.0-only */
#define SHENG_QTI_FG_API_TEST
#define main sheng_pogo_baseline_main
#include "test_sheng_kernel_qti_pogo.c"
#undef main

/* Exact original callback types; no invented unsupported FG2 get operation. */
struct battmngr_ops {
	int (*fg_soc)(int *), (*fg_curr)(int *), (*fg_volt)(int *), (*fg_temp)(int *);
	int (*charge_status)(int *), (*fg1_ibatt)(int *), (*fg2_ibatt)(int *);
	int (*fg1_volt)(int *), (*fg2_volt)(int *), (*fg1_fcc)(int *), (*fg2_fcc)(int *);
	int (*fg1_rm)(int *), (*fg2_rm)(int *), (*fg1_raw_soc)(int *), (*fg2_raw_soc)(int *);
	int (*fg1_soc)(int *), (*fg2_soc)(int *);
	int (*set_fg1_fastcharge)(int), (*set_fg2_fastcharge)(int);
	int (*get_fg1_fastcharge)(int *), (*get_fg2_fastcharge)(bool);
	int (*fg1_temp)(int *), (*fg2_temp)(int *), (*fg_suspend)(bool), (*set_term_cur)(int);
	int (*get_batt_auth)(int *), (*get_chip_ok)(int *);
	int (*online)(u8 *), (*real_type)(int *), (*usb_type)(int *);
	int (*input_curr_limit)(int *), (*power_max)(int *);
};
#include "../interfaces/kernel/6.18/helpers/sheng_qti_fg_api.h"
#ifdef SHENG_QTI_FG_STOCK_VECTORS
#include "sheng_qti_fg_stock_vectors.h"
#endif

static void setup_fg(struct battery_chg_dev *bc)
{
	*bc = (struct battery_chg_dev){
		.rw_lock={PTHREAD_MUTEX_INITIALIZER},.sheng_pogo_lock={PTHREAD_MUTEX_INITIALIZER},
		.sheng_pogo_ack={PTHREAD_MUTEX_INITIALIZER,PTHREAD_COND_INITIALIZER,false},
		.initialized=true,.fake_soc=-1,
	};
	bc->client=bc;
	sheng_keyboard_bcdev=g_bcdev=bc;
	reset_link(bc);
	fg_mode=true; fg_error_property=UINT32_MAX; fg_frame_count=0;
	memset(fg_values,0,sizeof(fg_values)); memset(battery_values,0,sizeof(battery_values));
}
static void finish_fg(struct battery_chg_dev *bc)
{
	sheng_keyboard_bcdev=g_bcdev=NULL;
	fg_mode=false;
	pthread_mutex_destroy(&bc->rw_lock.value);
	pthread_mutex_destroy(&bc->sheng_pogo_lock.value);
	pthread_mutex_destroy(&bc->sheng_pogo_ack.lock);
	pthread_cond_destroy(&bc->sheng_pogo_ack.cond);
}

/* Used by the host differential test against the actual AArch64 callback.
 * Outputs: status, full flag, previous ADC, request count; frames are real
 * bytes emitted by the unchanged production GLINK encoder/transfer code. */
int sheng_fg_bridge(int previous,int pogo,int full,int adc,int temperature,
		u32 voltage,u32 soc,int current,int fake,int *outputs,u8 *frames)
{
	struct battery_chg_dev bc;
	int result, value=123456789;
	setup_fg(&bc);
	bc.sheng_fg=(struct sheng_fg_state){previous,full,pogo}; bc.fake_soc=fake;
	fg_values[224]=(u32)adc; fg_values[226]=(u32)temperature;
	battery_values[7]=voltage; battery_values[4]=soc; battery_values[9]=(u32)current;
	result=qti_fg_ops.charge_status(&value);
	outputs[0]=value; outputs[1]=bc.sheng_fg.full; outputs[2]=bc.sheng_fg.previous;
	outputs[3]=(int)fg_frame_count;
	memcpy(frames,fg_frames,fg_frame_count*28);
	finish_fg(&bc);
	return result;
}

static void fg_getter_test(void)
{
	struct battery_chg_dev bc;
	struct {int (*get)(int *); u32 opcode,property; int expected;} rows[]={
		{qti_fg_ops.fg_soc,0x30,4,99}, {qti_fg_ops.fg_curr,0x30,9,-1500},
		{qti_fg_ops.fg_volt,0x30,7,4200}, {qti_fg_ops.fg_temp,0x50,226,2550},
		{qti_fg_ops.fg1_ibatt,0x50,172,-1400000}, {qti_fg_ops.fg2_ibatt,0x50,173,-1300000},
		{qti_fg_ops.fg1_volt,0x50,176,4200000}, {qti_fg_ops.fg2_volt,0x50,177,4200001},
		{qti_fg_ops.fg1_fcc,0x50,139,8000000}, {qti_fg_ops.fg2_fcc,0x50,167,8100000},
		{qti_fg_ops.fg1_rm,0x50,138,4000000}, {qti_fg_ops.fg2_rm,0x50,166,4100000},
		{qti_fg_ops.fg1_soc,0x50,183,5000}, {qti_fg_ops.fg2_soc,0x50,184,5100},
		{qti_fg_ops.get_fg1_fastcharge,0x50,43,1},
		{qti_fg_ops.fg1_temp,0x50,174,2500}, {qti_fg_ops.fg2_temp,0x50,175,2600},
		{qti_fg_ops.get_batt_auth,0x50,3,0}, {qti_fg_ops.get_chip_ok,0x50,5,0},
	};
	size_t i;
	int out;
	struct power_supply usb={};
	setup_fg(&bc);
	CHECK(!check_g_bcdev_ops());
	bc.sheng_qti_ops=(struct battmngr_device *)&usb;
	CHECK(check_g_bcdev_ops());
	for (i=0;i<sizeof(rows)/sizeof(rows[0]);i++) {
		fg_frame_count=0;
		if (rows[i].opcode==0x30)
			battery_values[rows[i].property]=(u32)(rows[i].expected*(rows[i].property==4?100:1000));
		else
			fg_values[rows[i].property]=(u32)rows[i].expected;
		CHECK(rows[i].get(&out)==0 && out==rows[i].expected);
		CHECK(sheng_pogo_get32(sent+8)==rows[i].opcode && sheng_pogo_get32(sent+16)==rows[i].property);
		fg_frame_count=0; fg_error_property=rows[i].property; out=123456789;
		CHECK(rows[i].get(&out)==-EREMOTEIO && out==123456789);
		fg_frame_count=0; fg_error_property=UINT32_MAX;
	}
	CHECK(qti_fg_ops.get_fg2_fastcharge==NULL);
	fg_values[3]=fg_values[5]=0;
	CHECK(qti_fg_ops.get_batt_auth(&out)==0 && out==0);
	CHECK(qti_fg_ops.get_chip_ok(&out)==0 && out==0);
	fg_frame_count=0;
	CHECK(qti_fg_ops.set_fg1_fastcharge(1)==0 && sheng_pogo_get32(sent+16)==143);
	CHECK(qti_fg_ops.set_fg2_fastcharge(0)==0 && sheng_pogo_get32(sent+16)==143);
	CHECK(qti_fg_ops.fg_suspend(true)==0 && sheng_pogo_get32(sent+16)==42);
	CHECK(qti_fg_ops.set_term_cur(200)==0 && sheng_pogo_get32(sent+16)==227);
	fg_frame_count=0;
	fg_values[138]=4000000; fg_values[139]=8000000;
	CHECK(qti_fg_ops.fg1_raw_soc(&out)==0 && out==5000);
	fg_frame_count=0;
	fg_values[166]=4100000; fg_values[167]=8100000;
	CHECK(qti_fg_ops.fg2_raw_soc(&out)==0 && out==5061);
	fg_frame_count=0; fg_values[139]=0; out=123456789;
	CHECK(qti_fg_ops.fg1_raw_soc(&out)==-ERANGE && out==123456789);
	fg_frame_count=0;
	bc.psy_list[PSY_TYPE_USB].psy=&usb;
	CHECK(qti_deal_report()==NOTIFY_OK && usb.events==1 && bc.usb_type_work.queued==1 && bc.xm_prop_change_work.queued==1);
	finish_fg(&bc);
	CHECK(!check_g_bcdev_ops() && qti_deal_report()==-ENODEV);
}
static void fg_failure_test(void)
{
	struct battery_chg_dev bc;
	u32 props[]={224,226,7,4,9};
	size_t i;
	int out;
	setup_fg(&bc);
	fg_values[224]=7; fg_values[226]=2500;
	battery_values[7]=4200000; battery_values[4]=10000; battery_values[9]=(u32)-150000;
	for (i=0;i<sizeof(props)/sizeof(props[0]);i++) {
		bc.sheng_fg=(struct sheng_fg_state){5,false,true}; out=123456789;
		fg_error_property=props[i]; fg_frame_count=0;
		CHECK(qti_fg_ops.charge_status(&out)==-EREMOTEIO && out==123456789);
		CHECK(bc.sheng_fg.previous==5 && !bc.sheng_fg.full);
	}
	fg_error_property=UINT32_MAX; fg_frame_count=0; fg_values[224]=0xffffffffU;
	CHECK(qti_fg_ops.charge_status(&out)==-ERANGE && out==123456789);
	finish_fg(&bc);
}
int main(void)
{
	int out=123456789;
	s32 values[]={0,1,999,1000,1001,INT_MAX,INT_MIN,-1};
	size_t i,j;
	CHECK(sheng_pogo_baseline_main()==0);
	fg_getter_test(); fg_failure_test();
#ifdef SHENG_QTI_FG_STOCK_VECTORS
	for (i=0;i<sizeof(sheng_fg_stock_vectors)/sizeof(sheng_fg_stock_vectors[0]);i++) {
		const struct sheng_fg_stock_vector *v=&sheng_fg_stock_vectors[i];
		int outputs[4]; u8 frames[6*28];
		CHECK(sheng_fg_bridge(v->previous,v->pogo,v->full,v->adc,v->temperature,
			v->voltage,v->soc,v->current,v->fake,outputs,frames)==v->result);
		CHECK(outputs[0]==v->status && outputs[1]==v->next_full && outputs[2]==v->adc);
		CHECK(outputs[3]==v->count);
		for (j=0;j<(size_t)v->count;j++) {
			CHECK(sheng_pogo_get32(frames+j*28+8)==v->opcodes[j]);
			CHECK(sheng_pogo_get32(frames+j*28+16)==v->properties[j]);
		}
	}
#endif
	for (i=0;i<sizeof(values)/sizeof(values[0]);i++)
		for (j=0;j<sizeof(values)/sizeof(values[0]);j++) {
			int ret=sheng_fg_raw_soc(values[i],values[j],&out);
			CHECK(ret==0 || ret==-ERANGE);
		}
	printf("%lu FG production API and boundary assertions passed\n",checks);
	return 0;
}
