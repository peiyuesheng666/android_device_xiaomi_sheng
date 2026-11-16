/* SPDX-License-Identifier: GPL-2.0-only */
/* Reconstructed stock sheng filter; differential tests execute the stock ELF. */
#ifndef SHENG_TOUCHPAD_EDGE_H
#define SHENG_TOUCHPAD_EDGE_H
#ifdef SHENG_TOUCHPAD_HOST_TEST
#include <errno.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>
typedef uint8_t u8;
typedef uint32_t u32;
typedef uint64_t u64;
typedef int64_t s64;
#else
#include <linux/errno.h>
#include <linux/string.h>
#include <linux/types.h>
#endif

#define SHENG_TOUCHPAD_REPORT_SIZE 21
#define SHENG_TOUCHPAD_PARAMETERS 14
#define SHENG_TOUCHPAD_SLOTS 3

struct sheng_edge_slot {
	u32 frames;
	u64 distance;
	u32 point;
	u32 state;
	u8 report;
	u8 sample[6];
	u8 first[6];
};

struct sheng_edge_filter {
	u32 param[SHENG_TOUCHPAD_PARAMETERS];
	struct sheng_edge_slot slot[SHENG_TOUCHPAD_SLOTS];
};

static inline u32 sheng_edge_u16(const u8 *p)
{
	return p[0] | ((u32)p[1] << 8);
}

static inline u64 sheng_edge_distance(const u8 *a, const u8 *b)
{
	s64 x = (s64)sheng_edge_u16(a + 2) - sheng_edge_u16(b + 2);
	s64 y = (s64)sheng_edge_u16(a + 4) - sheng_edge_u16(b + 4);
	return x * x + y * y;
}

static inline int sheng_edge_in_range(u32 value, u32 min, u32 max)
{
	return value >= min && value <= max;
}

static inline int sheng_edge_at_border(const struct sheng_edge_filter *filter,
				     const u8 *contact)
{
	const u32 *p = filter->param;
	u32 x = sheng_edge_u16(contact + 2), y = sheng_edge_u16(contact + 4);
	return sheng_edge_in_range(x, p[0], p[1]) ||
		sheng_edge_in_range(x, p[2], p[3]) ||
		sheng_edge_in_range(y, p[4], p[5]) ||
		sheng_edge_in_range(y, p[6], p[7]);
}

static inline void sheng_edge_release(struct sheng_edge_slot *slot)
{
	slot->frames = 0;
	slot->distance = 0;
	memset(slot->first, 0, sizeof(slot->first));
	slot->state = 1;
}

/* Returns the number of contacts to deliver, exactly as the shipping driver. */
static inline int sheng_touchpad_edge(struct sheng_edge_filter *filter,
				    u8 *packet, size_t len)
{
	u8 output[SHENG_TOUCHPAD_REPORT_SIZE] = { 0x19 };
	unsigned int i, j, count = 0, gesture = 0;
	unsigned int shielded[SHENG_TOUCHPAD_SLOTS], shielded_count;
	u32 threshold;
	if (!filter || !packet || len != SHENG_TOUCHPAD_REPORT_SIZE ||
	    packet[0] != 0x19 || packet[20] > SHENG_TOUCHPAD_SLOTS)
		return -EINVAL;
	/* Reject malformed IDs and duplicate slots before mutating any state. */
	for (i = 0; i < packet[20]; i++) {
		if (packet[3 + i * 6] >= SHENG_TOUCHPAD_SLOTS)
			return -EINVAL;
		for (j = 0; j < i; j++)
			if (packet[3 + i * 6] == packet[3 + j * 6])
				return -EINVAL;
	}
	output[1] = packet[1];
	for (i = 0; i < packet[20]; i++) {
		const u8 *contact = packet + 2 + i * 6;
		struct sheng_edge_slot *slot = &filter->slot[contact[1]];
		memcpy(slot->sample, contact, sizeof(slot->sample));
		switch (slot->point) {
		case 0: slot->point = contact[0] & 1; break;
		case 1:
		case 2: slot->point = contact[0] & 1 ? 2 : 3; break;
		case 3:
			slot->point = contact[0] & 1 ? 1 : 3;
			if (!(contact[0] & 1) && !sheng_edge_u16(contact + 2) &&
			    !sheng_edge_u16(contact + 4))
				slot->point = 0;
			break;
		}
	}
	for (i = 0; i < SHENG_TOUCHPAD_SLOTS; i++) {
		struct sheng_edge_slot *slot = &filter->slot[i];
		switch (slot->state) {
		case 0:
			if (slot->point != 1)
				break;
			goto initial_contact;
		case 1:
			if (slot->point == 0) {
				slot->state = 0;
				slot->report = 1;
				break;
			}
			if (slot->point != 1)
				break;
initial_contact:
			if (packet[1] || !sheng_edge_at_border(filter, slot->sample))
				goto normal_contact;
			slot->state = 3;
			memcpy(slot->first, slot->sample, sizeof(slot->first));
			slot->frames++;
			break;
		case 2:
			if (slot->point == 3)
				sheng_edge_release(slot);
			slot->report = 1;
			break;
		case 3:
			if (packet[1])
				goto normal_contact;
			if (slot->point == 3) {
				sheng_edge_release(slot);
				break;
			}
			if (slot->point != 2)
				break;
			slot->frames++;
			if (slot->frames >= filter->param[8]) {
				slot->state = 4;
				break;
			}
			if (!sheng_edge_at_border(filter, slot->sample) || gesture)
				goto normal_contact;
			shielded_count = 0;
			for (j = 0; j < SHENG_TOUCHPAD_SLOTS; j++)
				if (filter->slot[j].state == 2 || filter->slot[j].state == 3)
					shielded[shielded_count++] = j;
			threshold = 0;
			switch (shielded_count) {
			case 1: gesture = 1; threshold = filter->param[9]; break;
			case 2:
				gesture = sheng_edge_distance(packet + 2 + 6 * shielded[0],
					packet + 2 + 6 * shielded[1]) < filter->param[13] ? 2 : 3;
				threshold = filter->param[gesture == 2 ? 10 : 11];
				break;
			case 3: gesture = 4; threshold = filter->param[12]; break;
			}
			for (j = 0; j < shielded_count; j++) {
				struct sheng_edge_slot *other = &filter->slot[shielded[j]];
				if (other->state != 3)
					continue;
				other->distance = sheng_edge_distance(other->first, other->sample);
				if (other->distance <= threshold) {
					gesture = 0;
					break;
				}
			}
			if (!gesture)
				break;
normal_contact:
			slot->state = 2;
			slot->report = 1;
			break;
		case 4:
			if (packet[1])
				goto normal_contact;
			if (slot->point == 3)
				sheng_edge_release(slot);
			break;
		}
	}
	for (i = 0; i < SHENG_TOUCHPAD_SLOTS; i++) {
		struct sheng_edge_slot *slot = &filter->slot[i];
		if (!slot->report)
			continue;
		memcpy(output + 2 + 6 * count, slot->sample, sizeof(slot->sample));
		output[3 + 6 * count] = i;
		slot->report = 0;
		count++;
	}
	output[20] = count;
	memcpy(packet, output, sizeof(output));
	return count;
}
#endif
