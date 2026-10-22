/* SPDX-License-Identifier: Apache-2.0 */
#include "cameo_family_c.h"
#include <stdio.h>
#include <stdlib.h>
int main(void) {
    double x[5] = {1, 2, 3, 2, 1}, y[5];
    cf_config_v1 c = {0};
    size_t used = 0, need = 0;
    c.version = 1;
    c.algorithm = 7;
    c.error_bound = .1;
    c.fraction = .5;
    c.window_fraction = .5;
    c.nlags = 1;
    c.hops = 1;
    c.kappa = 1;
    c.threads = 1;
    if (cf_api_version_v1() != 1 || cf_encode_v1(x, 5, &c, NULL, 0, &used, &need) != CF_CAPACITY)
        return 1;
    unsigned char *b = (unsigned char *)malloc(need);
    if (!b)
        return 2;
    size_t capacity = need;
    if (cf_encode_v1(x, 5, &c, b, capacity, &used, &need) != CF_OK || used != capacity)
        return 3;
    if (cf_decode_v1(b, capacity, y, 5, &used, &need) != CF_OK || used != 5)
        return 4;
    for (int i = 0; i < 5; ++i)
        if (y[i] != x[i])
            return 5;
    free(b);
    puts("C11 installed consumer PASS");
    return 0;
}
