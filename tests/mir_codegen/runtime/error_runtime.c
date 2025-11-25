#include <stdlib.h>
#include <string.h>
#include <stdio.h>
#include "error_runtime.h"

struct Error* drift_error_new(DriftStr* keys, DriftStr* values, size_t attr_count, DriftStr event, DriftStr domain) {
    struct Error* err = (struct Error*)calloc(1, sizeof(struct Error));
    if (!err) return NULL;
    err->event = event ? event : "unknown";
    err->domain = domain ? domain : "main";
    err->attr_count = attr_count;
    err->keys = keys;
    err->values = values;
    return err;
}

const char* error_to_cstr(struct Error* err) {
    if (!err) return NULL;
    static char buf[256];
    if (err->attr_count > 0 && err->keys && err->values) {
        snprintf(buf, sizeof(buf), "{\"%s\":\"%s\"}", err->keys[0], err->values[0] ? err->values[0] : "unknown");
        return buf;
    }
    if (err->event) {
        snprintf(buf, sizeof(buf), "{\"msg\":\"%s\"}", err->event);
        return buf;
    }
    return "{\"msg\":\"unknown\"}";
}

void error_free(struct Error* err) {
    if (!err) return;
    free(err);
}

struct Error* error_new(const char* msg) {
    static const char* keys[1] = {"msg"};
    const char* vals_arr[1];
    vals_arr[0] = msg ? msg : "unknown";
    /* Casting away const for simplicity; in real runtime we'd copy or enforce const. */
    return drift_error_new((DriftStr*)keys, (DriftStr*)vals_arr, 1, "Error", "main");
}
