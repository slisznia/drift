// Minimal array runtime helpers for lang2 codegen tests.
// This mirrors the ABI in docs/design/spec-change-requests/drift-array-lowering.md.

#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

typedef size_t drift_size;

typedef struct DriftArrayHeader {
	drift_size len;
	drift_size cap;
	void *data;
} DriftArrayHeader;

// Allocate an array backing store and return a pointer to the data region.
// For now this is a thin wrapper over malloc; alignment is best-effort.
void *drift_alloc_array(size_t elem_size, size_t elem_align, drift_size len, drift_size cap) {
	(void)elem_align; // alignment is ignored in this test-only runtime
	if (cap < len) {
		cap = len;
	}
	if (elem_size == 0) {
		return NULL;
	}
	size_t bytes = elem_size * cap;
	void *data = malloc(bytes);
	if (!data) {
		fprintf(stderr, "drift_alloc_array: out of memory (bytes=%zu)\n", bytes);
		abort();
	}
	return data;
}

// Bounds check failure helper; for now, print and abort.
__attribute__((noreturn))
void drift_bounds_check_fail(drift_size idx, drift_size len) {
	fprintf(stderr, "drift_bounds_check_fail: index %zu out of bounds (len=%zu)\n", (size_t)idx, (size_t)len);
	abort();
}
