/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef SHENG_QTI_FG_MATH_H
#define SHENG_QTI_FG_MATH_H
#ifdef SHENG_QTI_FG_HOST_TEST
#include <errno.h>
#include <stdbool.h>
#include <stdint.h>
#include <limits.h>
typedef uint32_t u32;
typedef int32_t s32;
typedef int64_t s64;
#else
#include <linux/errno.h>
#include <linux/types.h>
#include <linux/limits.h>
#endif

struct sheng_fg_state {
	int previous;
	bool full, pogo;
};

static inline int sheng_fg_raw_soc(s32 rm, s32 fcc, int *out)
{
	s64 result;
	s32 denominator = fcc / 1000;

	if (!out || rm < 0 || denominator <= 0)
		return -ERANGE;
	result = (s64)rm * 10 / denominator;
	if (result > INT_MAX)
		return -ERANGE;
	*out = (int)result;
	return 0;
}

/* This is the shipping binary's rule, not the older public source rule.
 * On taper/termination -> disabled it requires SOC == 100, and excludes
 * warm high-voltage termination. Its current threshold uses signed uA. */
static inline int sheng_fg_charge_result(struct sheng_fg_state *state, int adc,
		s32 temperature, u32 voltage_uv, u32 soc_x100, s32 current_ua,
		int fake_soc, int *out)
{
	int status;
	u32 soc = soc_x100 / 100;
	bool full;

	if (!state || !out || adc < 0 || adc > 8)
		return -ERANGE;
	full = state->full;
	if (fake_soc >= 0 && fake_soc <= 100)
		soc = fake_soc;
	if (adc >= 1 && adc <= 5)
		status = 1; /* POWER_SUPPLY_STATUS_CHARGING */
	else if (adc == 0)
		status = 4; /* POWER_SUPPLY_STATUS_FULL */
	else if (adc == 6 || adc == 7)
		status = 3; /* POWER_SUPPLY_STATUS_NOT_CHARGING */
	else
		status = 0; /* POWER_SUPPLY_STATUS_UNKNOWN */
	if ((state->previous == 4 || state->previous == 5) && adc == 7)
		full = !(temperature >= 4800 && voltage_uv / 1000 >= 4085) && soc == 100;
	if (state->pogo && adc == 7)
		status = current_ua > -200000 && full ? 4 : 1;
	state->full = full;
	state->previous = adc;
	*out = status;
	return adc;
}
#endif
