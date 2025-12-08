// Drift String runtime support (lang2, v1).
#pragma once

#include <stdint.h>
#include <stddef.h>
#include <stdlib.h>

#ifdef __cplusplus
extern "C" {
#endif

// Length carrier: mirror lang2's Uint / %drift.size representation.
typedef uint64_t drift_size_t;

// Simple heap-allocated UTF-8 string representation.
// Ownership: caller owns the heap buffer unless it points to static storage.
typedef struct DriftString {
	drift_size_t len;  // number of bytes (UTF-8)
	char *data;        // pointer to bytes (may be NULL if len == 0); heap buffers include trailing NUL
} DriftString;

// Construct from a null-terminated UTF-8 C string (copies data).
DriftString drift_string_from_cstr(const char *cstr);

// Construct from UTF-8 bytes (copies data).
DriftString drift_string_from_utf8_bytes(const char *data, drift_size_t len);
DriftString drift_string_from_int64(int64_t v);
DriftString drift_string_from_bool(int v);

// Construct a DriftString backed by static storage (no free needed; MUST NOT be passed to drift_string_free).
DriftString drift_string_literal(const char *data, drift_size_t len);

// Concatenate two strings (allocates a new buffer).
DriftString drift_string_concat(DriftString a, DriftString b);

// Free the heap buffer of a DriftString (safe to call on zeroed structs).
void drift_string_free(DriftString s);

// Convert to a null-terminated C string; caller owns the returned buffer.
char *drift_string_to_cstr(DriftString s);

// Accessors for length and data pointer.
static inline drift_size_t drift_string_len(DriftString s) { return s.len; }
static inline const char *drift_string_ptr(DriftString s) { return s.data; }

// Equality (bytewise) check.
int drift_string_eq(DriftString a, DriftString b);

// Empty string helper.
static inline DriftString drift_string_empty(void) {
	DriftString s;
	s.len = 0;
	s.data = (char *)malloc(1);
	if (!s.data) {
		abort();
	}
	s.data[0] = '\0';
	return s;
}

#ifdef __cplusplus
}
#endif
