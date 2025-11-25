#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>

struct Error;
struct Pair {
    int64_t val;
    struct Error* err;
};

extern struct Pair maybe_fail(int64_t);
extern const char* error_to_cstr(struct Error*);
extern void error_free(struct Error*);

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
