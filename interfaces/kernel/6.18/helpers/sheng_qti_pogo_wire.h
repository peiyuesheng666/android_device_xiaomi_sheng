/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef SHENG_QTI_POGO_WIRE_H
#define SHENG_QTI_POGO_WIRE_H
#ifdef SHENG_QTI_POGO_HOST_TEST
#include <errno.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>
typedef uint8_t u8;
typedef uint32_t u32;
#else
#include <linux/errno.h>
#include <linux/string.h>
#include <linux/types.h>
#endif

/* Individually verified from OS3.0.303.0.WNXCNXM's shipping module.
 * The older sheng-u-oss enum has different IDs. Do not apply its numbering. */
#define SHENG_POGO_WPC_MOS 222
#define SHENG_POGO_DCIN 223
#define SHENG_POGO_ADC_STATUS 224
#define SHENG_POGO_ENABLE 225
#define SHENG_POGO_KEYBOARD 228
#define SHENG_POGO_VOTER 229
#define SHENG_POGO_OWNER 32778
#define SHENG_POGO_GET 0x50
#define SHENG_POGO_SET 0x51
#define SHENG_FG_BATTERY_GET 0x30
#define SHENG_FG_BATTERY_SET 0x31

struct sheng_pogo_request {
	u32 opcode, property;
	u8 vote;
	bool voter;
};
struct sheng_pogo_reply {
	u32 value, wire_return;
	int error;
};
struct sheng_pogo_pending {
	struct sheng_pogo_request request;
	struct sheng_pogo_reply reply;
	u32 epoch;
	int error;
	bool active, fenced;
};

static inline u32 sheng_pogo_get32(const u8 *p)
{
	return (u32)p[0] | (u32)p[1] << 8 | (u32)p[2] << 16 | (u32)p[3] << 24;
}
static inline void sheng_pogo_put32(u8 *p, u32 value)
{
	p[0] = value; p[1] = value >> 8;
	p[2] = value >> 16; p[3] = value >> 24;
}

static inline int sheng_pogo_encode(u8 *out, size_t capacity,
		const struct sheng_pogo_request *request, u32 value)
{
	size_t len;
	bool write;

	if (!out || !request || (request->opcode != SHENG_POGO_GET &&
	    request->opcode != SHENG_POGO_SET && request->opcode != SHENG_FG_BATTERY_GET &&
	    request->opcode != SHENG_FG_BATTERY_SET))
		return -EINVAL;
	len = request->voter ? 28 : 24;
	if (capacity < len)
		return -EMSGSIZE;
	if (request->voter && (request->property != SHENG_POGO_VOTER || request->vote > 2 ||
	    (request->opcode != SHENG_POGO_GET && request->opcode != SHENG_POGO_SET)))
		return -EINVAL;
	write = request->opcode == SHENG_POGO_SET || request->opcode == SHENG_FG_BATTERY_SET;
	memset(out, 0, len);
	sheng_pogo_put32(out, SHENG_POGO_OWNER);
	sheng_pogo_put32(out + 4, 1);
	sheng_pogo_put32(out + 8, request->opcode);
	if (request->voter) {
		sheng_pogo_put32(out + 12, request->property);
		sheng_pogo_put32(out + 16, request->opcode == SHENG_POGO_SET ? value : 0);
		out[20] = request->vote;
		/* OEM operation selector, not an errno. Preserve its wire meaning. */
		sheng_pogo_put32(out + 24, request->opcode == SHENG_POGO_SET ? 1 : 0);
	} else {
		sheng_pogo_put32(out + 16, request->property);
		sheng_pogo_put32(out + 20, write ? value : 0);
	}
	return (int)len;
}

/* 0 is unrelated, 1 is a matched full reply; negative is a malformed reply.
 * A standard firmware error is reported through reply.error without updating
 * a property cache. Voter return_code has no documented errno interpretation. */
static inline int sheng_pogo_decode(const struct sheng_pogo_request *request,
		const void *data, size_t len, struct sheng_pogo_reply *reply)
{
	const u8 *p = data;

	if (!request || !p || !reply)
		return -EINVAL;
	if (len < 12)
		return 0;
	if (sheng_pogo_get32(p) != SHENG_POGO_OWNER || sheng_pogo_get32(p + 4) != 1 ||
	    sheng_pogo_get32(p + 8) != request->opcode)
		return 0;
	if (len < 16)
		return -EMSGSIZE;
	if (sheng_pogo_get32(p + 12) != request->property)
		return 0;
	if (len != (request->voter ? 28U : 24U))
		return -EMSGSIZE;
	if (request->voter && p[20] != request->vote)
		return 0;
	reply->value = sheng_pogo_get32(p + 16);
	reply->wire_return = sheng_pogo_get32(p + (request->voter ? 24 : 20));
	reply->error = !request->voter && reply->wire_return ? -EREMOTEIO : 0;
	return 1;
}
#endif
