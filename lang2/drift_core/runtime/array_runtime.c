// Minimal array runtime helpers for lang2 codegen tests.
// NOTE: Test-only runtime (but alignment is honored to catch layout bugs).
// This mirrors the ABI in docs/design/spec-change-requests/drift-array-lowering.md.

#include <inttypes.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

typedef ptrdiff_t drift_isize;
typedef size_t drift_usize;

_Static_assert(sizeof(drift_isize) == sizeof(void *), "drift_isize must be pointer-sized");
_Static_assert(sizeof(drift_usize) == sizeof(void *), "drift_usize must be pointer-sized");

typedef struct DriftArrayHeader {
	drift_usize len;
	drift_usize cap;
	void *data;
} DriftArrayHeader;

__attribute__((noreturn))
void drift_bounds_check_fail(drift_isize idx, drift_usize len);

static unsigned char drift_zst_sentinel;

static size_t drift_round_up_pow2(size_t align) {
	size_t p = 1;
	while (p < align) {
		p <<= 1;
	}
	return p;
}

// Allocate an array backing store and return a pointer to the data region.
void *drift_alloc_array(size_t elem_size, size_t elem_align, drift_usize len, drift_usize cap) {
	if (cap < len) {
		cap = len;
	}
	if (elem_size == 0 || cap == 0) {
		return &drift_zst_sentinel;
	}
	if (cap != 0 && elem_size > (SIZE_MAX / (size_t)cap)) {
		fprintf(stderr, "drift_alloc_array: size overflow (elem_size=%zu cap=%zu)\n", elem_size, (size_t)cap);
		abort();
	}
	size_t align = elem_align;
	if (align < sizeof(void *)) {
		align = sizeof(void *);
	}
	if ((align & (align - 1)) != 0) {
		align = drift_round_up_pow2(align);
	}
	size_t bytes = elem_size * cap;
	void *data = NULL;
	if (posix_memalign(&data, align, bytes) != 0 || !data) {
		fprintf(stderr, "drift_alloc_array: out of memory (bytes=%zu, align=%zu)\n", bytes, align);
		abort();
	}
	return data;
}

void drift_free_array(void *data) {
	if (data == &drift_zst_sentinel) {
		return;
	}
	free(data);
}

void drift_bounds_check(drift_isize idx, drift_usize len) {
	if (idx < 0 || (drift_usize)idx >= len) {
		drift_bounds_check_fail(idx, len);
	}
}

// Bounds check failure helper; for now, print and abort.
__attribute__((noreturn))
void drift_bounds_check_fail(drift_isize idx, drift_usize len) {
	fprintf(stderr, "drift_bounds_check_fail: index %td out of bounds (len=%zu)\n", idx, len);
	abort();
}
