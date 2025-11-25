#pragma once
#include <stdint.h>

typedef const char* DriftStr;

struct Error {
    DriftStr event;
    DriftStr domain;
    DriftStr* keys;
    DriftStr* values;
    size_t attr_count;
};

struct Pair {
    int64_t val;
    struct Error* err;
};

struct Error* error_new(const char* msg); /* legacy helper for tests */
struct Error* drift_error_new(DriftStr* keys, DriftStr* values, size_t attr_count, DriftStr event, DriftStr domain);
const char* error_to_cstr(struct Error*);
void error_free(struct Error*);
