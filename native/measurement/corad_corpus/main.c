/* Time the exact frozen corpus controller without changing its configuration or wire. */
#define _POSIX_C_SOURCE 200809L
#include "corad.h"
#include <inttypes.h>
#include <stdarg.h>
#include <stdio.h>
#include <string.h>
#include <time.h>
#include <stdlib.h>

static struct { const char *name; uint64_t wall; uint64_t cpu; } trace[12];
static unsigned used_trace;
static char observation[2048];

static uint64_t clock_ns(clockid_t id) {
    struct timespec t;
    if (clock_gettime(id, &t) != 0) exit(5);
    return (uint64_t)t.tv_sec * 1000000000u + (uint64_t)t.tv_nsec;
}

static int capture(const char *format, ...) {
    va_list ap;
    va_start(ap, format);
    int n = vsnprintf(observation, sizeof(observation), format, ap);
    va_end(ap);
    if (n <= 0 || (size_t)n >= sizeof(observation) || observation[n - 1] != '\n') exit(5);
    observation[n - 1] = '\0';
    return n;
}

#define TIMED(api, args, forwarded) \
    static int timed_##api args { \
        if (used_trace >= sizeof(trace) / sizeof(trace[0])) exit(5); \
        uint64_t w = clock_ns(CLOCK_MONOTONIC), cpu_start = clock_ns(CLOCK_PROCESS_CPUTIME_ID); \
        int r = api forwarded; \
        trace[used_trace].cpu = clock_ns(CLOCK_PROCESS_CPUTIME_ID) - cpu_start; \
        trace[used_trace].wall = clock_ns(CLOCK_MONOTONIC) - w; \
        trace[used_trace++].name = #api; \
        return r; \
    }
TIMED(corad_model_train, (const corad_config *a,const double *b,const corad_train_options *c,corad_model **d,corad_train_stats *e), (a,b,c,d,e))
TIMED(corad_model_save, (const corad_model *a,uint8_t *b,size_t c,size_t *d), (a,b,c,d))
TIMED(corad_model_load, (const uint8_t *a,size_t b,corad_model **c), (a,b,c))
TIMED(corad_model_config, (const corad_model *a,uint32_t b,uint16_t c,double d,corad_config *e), (a,b,c,d,e))
TIMED(corad_model_encode, (const corad_model *a,const corad_config *b,const double *c,uint8_t *d,size_t e,size_t *f), (a,b,c,d,e,f))
TIMED(corad_model_pack, (const corad_config *a,const double *b,const double *c,const double *d,uint8_t *e,size_t f,size_t *g), (a,b,c,d,e,f,g))
TIMED(corad_decode, (const uint8_t *a,size_t b,double *c,size_t d,size_t e,size_t *f,corad_config *g), (a,b,c,d,e,f,g))

#define corad_model_train timed_corad_model_train
#define corad_model_save timed_corad_model_save
#define corad_model_load timed_corad_model_load
#define corad_model_config timed_corad_model_config
#define corad_model_encode timed_corad_model_encode
#define corad_model_pack timed_corad_model_pack
#define corad_decode timed_corad_decode
#define main functional_main
#define printf capture
#include "../../../plugins/codecs/corad-frozen/corpus_control.c"
#undef printf
#undef main

int main(int argc, char **argv) {
    uint64_t start = clock_ns(CLOCK_MONOTONIC);
    int rc = functional_main(argc, argv);
    uint64_t duration = clock_ns(CLOCK_MONOTONIC) - start;
    if (!observation[0]) return rc ? rc : 5;
    printf("{\"functional\":%s,\"driver_wall_ns\":%" PRIu64 ",\"calls\":[",observation,duration);
    for (unsigned i = 0; i < used_trace; i++)
        printf("%s{\"call\":\"%s\",\"wall_ns\":%" PRIu64 ",\"cpu_ns\":%" PRIu64 "}",
               i ? "," : "",trace[i].name,trace[i].wall,trace[i].cpu);
    puts("]}");
    return rc;
}
