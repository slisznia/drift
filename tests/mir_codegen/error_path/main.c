#include <stdio.h>
#include "../runtime/error_runtime.h"

extern struct Pair maybe_fail(int64_t);

int main(void) {
    struct Pair p = maybe_fail(0);
    if (p.err) {
        const char* msg = error_to_cstr(p.err);
        if (msg) {
            fprintf(stderr, "%s\n", msg);
        }
        error_free(p.err);
        return 1;
    }
    printf("ok %ld\n", p.val);
    return 0;
}
