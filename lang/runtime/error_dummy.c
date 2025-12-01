// Minimal dummy error constructor for SSA error-path testing.
#include "error_dummy.h"
#include <stdlib.h>

struct DriftError* drift_error_new_dummy(int64_t code, struct DriftString payload) {
    struct DriftError* err = malloc(sizeof(struct DriftError));
    if (!err) {
        abort();
    }
    uint64_t payload60 = ((uint64_t)code) & DRIFT_EVENT_PAYLOAD_MASK;
    uint64_t event_code = (((uint64_t)DRIFT_EVENT_KIND_TEST) << 60) | payload60;
    err->code = (int64_t)event_code;
    err->payload = payload;
    return err;
}

int64_t drift_error_get_code(struct DriftError* err) {
    if (!err) return 0;
    return err->code;
}
