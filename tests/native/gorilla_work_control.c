/* M0 only: observe calls in the untouched ELF DSO in a dedicated process. */
#include "gorilla.h"
#include <dlfcn.h>
#include <errno.h>
#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define LIMIT 512
#define CAP 9600
static g_status (*native_next)(g_iterator *, g_sample *, int *);
static void *(*native_copy)(void *, const void *, size_t);
static struct {
    int active;
    const uint8_t *source;
    size_t next_calls, rows, copy_calls, copied;
} work;

static void check(int yes, const char *message) {
    if (!yes) { fprintf(stderr, "Gorilla work control: %s\n", message); exit(2); }
}

/* Exported only by this executable. A cold-start fallback avoids recursion
 * before dlsym is available; the instrumented scope always uses libc memcpy. */
void *memcpy(void *dst, const void *src, size_t n) {
    if (work.active && src == work.source) {
        ++work.copy_calls;
        work.copied += n;
    }
    if (native_copy) return native_copy(dst, src, n);
    volatile unsigned char *d = dst;
    const volatile unsigned char *s = src;
    for (size_t i = 0; i < n; ++i) d[i] = s[i];
    return dst;
}

g_status g_iterator_next(g_iterator *it, g_sample *out, int *present) {
    g_status status = native_next(it, out, present);
    if (work.active) {
        ++work.next_calls;
        if (status == G_OK && present && *present) ++work.rows;
    }
    return status;
}

static void begin(const uint8_t *source) {
    work.source = source;
    work.next_calls = work.rows = work.copy_calls = work.copied = 0;
    work.active = 1;
}

static void emit_work(void) {
    printf("\"next_calls\":%zu,\"rows_scanned\":%zu,\"source_copy_calls\":%zu,\"source_bytes_copied\":%zu",
           work.next_calls, work.rows, work.copy_calls, work.copied);
}

static size_t load(const char *path, uint8_t *data) {
    FILE *file = fopen(path, "rb");
    check(file != NULL, "input open failed");
    const size_t n = fread(data, 1, CAP, file);
    check(!ferror(file) && feof(file) && n >= 2 && n < CAP, "input extent differs");
    check(fclose(file) == 0, "input close failed");
    return n;
}

static void resume(uint8_t *data, size_t n, const char *mode) {
    uint8_t original[CAP];
    const int trailing = strcmp(mode, "trailing") == 0;
    check(trailing || strcmp(mode, "valid") == 0, "unexpected resume mode");
    if (trailing) data[n++] = 0;
    memcpy(original, data, n);
    g_encoder *e = NULL;
    check(g_encoder_create(LIMIT, &e) == G_OK, "encoder create failed");
    begin(data);
    const g_status status = g_encoder_resume(e, data, n);
    work.active = 0;
    check(status == (trailing ? G_CORRUPT : G_OK), "unexpected resume status");
    int detached = 0;
    if (status == G_OK) {
        /* Prove the source was not retained as borrowed storage. This write
         * is outside the counted call and is not part of the codec's work. */
        memset(data, 0xff, n);
        g_buffer snap = {0};
        check(g_encoder_snapshot(e, &snap) == G_OK, "snapshot after resume failed");
        detached = snap.size == n && memcmp(snap.data, original, n) == 0;
        g_free(snap.data);
        check(detached, "snapshot changed after caller source overwrite");
    }
    printf("{\"status\":%d,\"source_bytes\":%zu,\"same_snapshot_after_source_overwrite\":%s,",
           status, n, detached ? "true" : "false");
    emit_work();
    puts("}");
    g_encoder_destroy(e);
}

static void iterate(const uint8_t *data, size_t n, int count, char **ops) {
    g_iterator *it = NULL;
    check(count > 0 && count <= 32 && g_iterator_create(data, n, LIMIT, &it) == G_OK, "iterator create failed");
    putchar('[');
    for (int i = 0; i < count; ++i) {
        g_status status;
        int present = 0;
        g_sample value = {0};
        const int next = strcmp(ops[i], "n") == 0;
        int64_t query = 0;
        if (!next) {
            char *end;
            check(strncmp(ops[i], "s:", 2) == 0, "unexpected iterator operation");
            errno = 0;
            query = strtoimax(ops[i] + 2, &end, 10);
            check(!errno && end != ops[i] + 2 && !*end, "invalid iterator target");
        }
        begin(data);
        status = next ? g_iterator_next(it, &value, &present) : g_iterator_seek(it, query, &value, &present);
        work.active = 0;
        if (i) putchar(',');
        printf("{\"status\":%d,\"pair\":", status);
        if (present) printf("[%" PRId64 ",%" PRIu64 "]", value.timestamp, value.bits);
        else fputs("null", stdout);
        putchar(','); emit_work(); putchar('}');
    }
    puts("]");
    g_iterator_destroy(it);
}

int main(int argc, char **argv) {
    uint8_t data[CAP];
    check(argc >= 5, "expected staged library, resume/iterate, a native frame, and arguments");
    native_copy = dlsym(RTLD_NEXT, "memcpy");
    native_next = dlsym(RTLD_NEXT, "g_iterator_next");
    check(native_copy && native_copy != memcpy && native_next && native_next != g_iterator_next,
          "cannot resolve original implementations");
    Dl_info next, resume_fn, seek_fn;
    check(dladdr(native_next, &next) && dladdr(g_encoder_resume, &resume_fn) && dladdr(g_iterator_seek, &seek_fn) &&
          next.dli_fbase == resume_fn.dli_fbase && next.dli_fbase == seek_fn.dli_fbase, "Gorilla native library identity differs");
    char *resolved = realpath(next.dli_fname, NULL);
    check(resolved && strcmp(resolved, argv[1]) == 0, "unexpected DSO path");
    free(resolved);
    const size_t n = load(argv[3], data);
    if (strcmp(argv[2], "resume") == 0 && argc == 5) resume(data, n, argv[4]);
    else if (strcmp(argv[2], "iterate") == 0) iterate(data, n, argc - 4, argv + 4);
    else check(0, "unexpected mode");
    return 0;
}
