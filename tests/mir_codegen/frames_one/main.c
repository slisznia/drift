#include <stdio.h>
#include "../runtime/error_runtime.h"

extern struct Pair level1(void);

int main(void) {
    struct Pair p = level1();
    if (p.err) {
        fprintf(stderr, "unexpected err\n");
        error_free(p.err);
        return 1;
    }
    printf("ok %ld\n", p.val);
    return 0;
}
