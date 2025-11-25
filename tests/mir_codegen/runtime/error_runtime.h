#pragma once
#include <stdint.h>

struct DriftErrorAttr {
    const char* key;
    const char* value_json;
};

struct DriftFrame {
    const char* file;
    uint32_t line;
    const char* func;
};

struct DriftError {
    const char* event;
    const char* domain;
    struct DriftErrorAttr* attrs;
    size_t attr_count;
    struct DriftFrame* frames;
    size_t frame_count;
    void* ctx;
    void (*free_fn)(struct DriftError*);
};

struct Error {
    struct DriftError* inner;
};

struct Pair {
    int64_t val;
    struct Error* err;
};

struct Error* error_new(const char* msg); /* legacy helper for tests */
struct Error* drift_error_new(const char* event, const char* domain, const struct DriftErrorAttr* attrs, size_t attr_count, const struct DriftFrame* frames, size_t frame_count);
const char* error_to_cstr(struct Error*);
void error_free(struct Error*);
