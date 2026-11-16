/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef SHENG_QTI_IRQ_WIRE_H
#define SHENG_QTI_IRQ_WIRE_H
#include "sheng_qti_pogo_wire.h"
struct sheng_qti_irq {
	u32 type;
	u8 value;
};
/* Shipping IRQ layout is 20 bytes: hdr, u8 value, padding, u32 IRQ type.
 * Shipping dispatch uses opcode, without constraining hdr.type. Padding is
 * not firmware payload. Never read an unaligned native struct from GLINK. */
static inline int sheng_qti_irq_decode(const void *data, size_t len,
				     struct sheng_qti_irq *out)
{
	const u8 *bytes = data;
	u32 type;

	if (!data || !out)
		return -EINVAL;
	if (len != 20)
		return -EMSGSIZE;
	if (sheng_pogo_get32(bytes) != SHENG_POGO_OWNER ||
	    sheng_pogo_get32(bytes + 8) != 0x52)
		return -EPROTO;
	type = sheng_pogo_get32(bytes + 16);
	if (type > 2)
		return -ERANGE;
	out->type = type;
	out->value = bytes[12];
	return 0;
}
#endif
