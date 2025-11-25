#include <stdio.h>
#include "../runtime/error_runtime.h"

extern struct Pair drift_entry(void);

int main(void) {
    struct Pair p = drift_entry();
    if (p.err) {
        fprintf(stderr, "domain=%s\n", p.err->domain ? p.err->domain : "<none>");
        error_free(p.err);
        return 1;
    }
    printf("ok %ld\n", p.val);
    return 0;
}
