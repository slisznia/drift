#pragma once
#include <stdint.h>

struct Error {
    char* json;
};
struct Pair {
    int64_t val;
    struct Error* err;
};

const char* error_to_cstr(struct Error*);
void error_free(struct Error*);
