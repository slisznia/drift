#include "argv_runtime.h"

DriftArrayString drift_build_argv(int argc, char **argv) {
	DriftArrayString arr;
	arr.len = (drift_size)argc;
	arr.cap = (drift_size)argc;
	// Allocate backing store for DriftString elements.
	DriftString *data = (DriftString *)drift_alloc_array(sizeof(DriftString), _Alignof(DriftString), arr.len, arr.cap);
	for (int i = 0; i < argc; i++) {
		// Construct from C string; drift_string_from_cstr handles NULL by returning empty.
		data[i] = drift_string_from_cstr(argv[i]);
	}
	arr.data = (void *)data;
	return arr;
}
