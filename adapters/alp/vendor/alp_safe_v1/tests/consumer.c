#include "alp_port.h"
#include <string.h>
int main(void) {
    double x[2] = {1.25, -0.0}, y[2]; unsigned char b[40000];
    size_t n, used, consumed; uint64_t count; uint8_t dtype, method;
    if (alp_port_encode(x, 2, 8, 0, b, sizeof(b), &n)) return 1;
    if (alp_port_decode(b, n, y, sizeof(y), &used, &consumed, &count, &dtype, &method)) return 2;
    return used != 16 || consumed != n || count != 2 || dtype != 8 || method != 0 || memcmp(x, y, 16);
}
