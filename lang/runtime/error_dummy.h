// Minimal dummy error constructor for SSA error-path testing.
#pragma once

struct DriftError {
    long long code; // matches Drift Int (word-sized)
};

// Returns a non-null Error* for testing error-edge lowering.
struct DriftError* drift_error_new_dummy(int code);
long long drift_error_get_code(struct DriftError* err);
