#ifndef LANG2_ARRAY_RUNTIME_H
#define LANG2_ARRAY_RUNTIME_H

#include <stddef.h>
#include <stdint.h>

typedef size_t drift_size;

typedef struct DriftArrayHeader {
	drift_size len;
	drift_size cap;
	void *data;
} DriftArrayHeader;

void *drift_alloc_array(size_t elem_size, size_t elem_align, drift_size len, drift_size cap);
__attribute__((noreturn))
void drift_bounds_check_fail(drift_size idx, drift_size len);

#endif // LANG2_ARRAY_RUNTIME_H
