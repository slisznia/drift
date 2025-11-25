#include <stdio.h>
#include "../runtime/error_runtime.h"

extern struct Pair raise_many(void);

int main(void) {
    struct Pair p = raise_many();
    if (p.err) {
        const char* msg = error_to_cstr(p.err);
        if (msg) fprintf(stderr, "%s\n", msg);
        error_free(p.err);
        return 1;
    }
    printf("ok %ld\n", p.val);
    return 0;
}
