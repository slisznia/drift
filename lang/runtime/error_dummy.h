// Minimal dummy error constructor for SSA error-path testing.
#pragma once

#include <stdint.h>

struct DriftError {
    int64_t code; // matches Drift Int (word-sized)
};

// Returns a non-null Error* for testing error-edge lowering.
struct DriftError* drift_error_new_dummy(int64_t code);
int64_t drift_error_get_code(struct DriftError* err);
