#include <stdio.h>
long add(long a, long b);
int main(void) {
    long r = add(40, 2);
    printf("add(40, 2) = %ld\n", r);
    return 0;
}
