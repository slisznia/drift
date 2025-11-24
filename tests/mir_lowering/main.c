// main.c for MIR codegen test
#include <stdio.h>

extern long add(long, long);

int main(void) {
    long r = add(40, 2);
    printf("add(40, 2) = %ld\n", r);
    return 0;
}
