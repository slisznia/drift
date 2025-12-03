#include "runtime/error_dummy.h"
#include <assert.h>
#include <stdio.h>

int main(void) {
    struct DriftString key_a = drift_string_from_cstr("a");
    struct DriftString val_a = drift_string_from_cstr("alpha");
    struct DriftError* err = drift_error_new_dummy(1, key_a, val_a);

    struct DriftString key_b = drift_string_from_cstr("b");
    struct DriftString val_b = drift_string_from_cstr("beta");
    drift_error_add_arg(err, key_b, val_b);

    struct DriftOptionalString opt_a = __exc_args_get(err, key_a);
    struct DriftOptionalString opt_missing = __exc_args_get(err, drift_string_from_cstr("missing"));

    assert(opt_a.is_some == 1);
    assert(opt_a.value.len == val_a.len);
    assert(opt_a.value.data == val_a.data);

    assert(opt_missing.is_some == 0);
    assert(opt_missing.value.len == 0);
    assert(opt_missing.value.data == NULL);

    return 0;
}
