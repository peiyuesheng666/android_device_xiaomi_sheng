/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef SHENG_QTI_POGO_H
#define SHENG_QTI_POGO_H
#ifdef SHENG_QTI_POGO_HOST_TEST
#include "sheng_qti_pogo_wire.h"
#else
#include <linux/types.h>
#endif
int qti_set_keyboard_plugin(int plugin);
int sc8651_wpc_gate_set(int value);
int qti_enale_charge(int enable);
int qti_get_ADC_CHGR_STATUS(void);
int qti_get_DCIN_STATE(void);
int write_voter_prop_id(u8 vote, u32 value);
int read_voter_property_id(u8 vote, u32 prop_id);
struct battery_chg_dev;
extern struct battery_chg_dev *g_bcdev;
bool check_g_bcdev_ops(void);
int qti_deal_report(void);
#endif
