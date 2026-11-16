/* SPDX-License-Identifier: GPL-2.0-only */
/* Bounds for the newest bytes of the original persistent pmsg ring. */
#ifndef MTDOOPS_SHENG_RING_H
#define MTDOOPS_SHENG_RING_H

struct sheng_pmsg_chunks {
	size_t offset;
	size_t first;
	size_t second;
};

static inline bool sheng_pmsg_chunks(size_t capacity, size_t start, size_t size,
				    size_t limit, struct sheng_pmsg_chunks *out)
{
	size_t count, begin;

	if (!capacity || start > capacity || size > capacity)
		return false;
	if (start == capacity)
		start = 0;
	count = size < limit ? size : limit;
	begin = start >= count ? start - count : capacity - (count - start);
	out->offset = begin;
	out->first = count < capacity - begin ? count : capacity - begin;
	out->second = count - out->first;
	return true;
}
#endif
