#include <cstdint>
#include <cstddef>
#include <cstdio>
#include <cstdlib>
#include <cstring>
extern "C" {
#include "huf.h"
#include "error_private.h"
}
int64_t lzbench_huff0_compress(char *inbuf, size_t insize, char *outbuf,
    size_t outsize, size_t, size_t, void*)
{
    // if (insize < 10) {
    //     printf("------ HUFF0 requires larger data; received input of size %lu\n", insize);
    //     return 0;
    // }

    *(uint32_t*)outbuf = insize;  // Huff0 decomp needs original input size

    // fprintf(stderr, "HUF compress final 2 bytes: %d %d\n", (int)inbuf[insize - 2], (int)inbuf[insize - 1]);

    // auto ret = HUF_compress(outbuf, outsize, inbuf, insize);
    // fprintf(stderr, "HUF compress: received raw data size, outsize: %lub, %lub\n", insize, outsize);
    auto ret = HUF_compress(outbuf + 4, outsize - 4, inbuf, insize);
    if (HUF_isError(ret)) {
        printf("HUFF0 compression had error: %s\n", HUF_getErrorName(ret));
        if (ret == ZSTD_error_srcSize_wrong) {
            printf("Maximum block size is 128KiB; try lzbench arg: '-b127'\n");
        }
    }

    // huff0 does nothing if it deems input incompressible; we also have to
    // catch ret == 9 case because we would be incorrect when that happened
    if (ret == 0 || ret == 9) {
        // printf("input incompressible; just memcpy-ing\n");
        *(uint32_t*)outbuf = 0;
        *(uint32_t*)(outbuf + 4) = insize;
        memcpy(outbuf + 8, inbuf, insize);
        return insize + 8;
    } else if (ret == 1) { // whole input is a constant
        *(uint64_t*)outbuf = insize;
        *(outbuf + 8) = *inbuf;
        return 9;
    }
    // fprintf(stderr, "HUF compress: compressed %lu bytes -> %lu bytes\n", insize, ret + 4);
    return ret + 4;
}
int64_t lzbench_huff0_decompress(char *inbuf, size_t insize, char *outbuf,
    size_t outsize, size_t, size_t, void*)
{
    // LZBENCH_PRINT(1, "HUF decompress: received compressed size: %lu\n", insize);
    if (insize == 9) {
        uint64_t size = *(uint64_t*)inbuf;
        uint8_t val = *(inbuf + 8);
        memset(outbuf, val, size);
        return size;
    }

    uint32_t orig_size = *(uint32_t*)inbuf;
    // printf("read back insize: %u\n", orig_size);

    // fprintf(stderr, "HUF decompress: received compressed "
    //     "size, orig_size, outsize: %lub, %ub, %lub\n",
    //     insize, orig_size, outsize);

    // printf("HUF decompress: first few bytes of compressed data = ");
    // for (int i = 0; i < 10; i++) {
    //     printf("%d ", (int)inbuf[i]);
    // }
    // printf("\n");

    if (orig_size == 0) {
        // printf("WARNING: Huffman decompress just memcpying "
        //     " (%lld bytes)\n", (long long)orig_size);
        orig_size = *(uint32_t*)(inbuf + 4);
        memcpy(outbuf, inbuf + 8, orig_size);
        return orig_size;
    }

    // auto ret = HUF_decompress(outbuf, outsize, inbuf + 8, insize);
    // auto ret = HUF_decompress(outbuf, orig_size, inbuf + 8, insize - 8);
    auto ret = HUF_decompress(outbuf, orig_size, inbuf + 4, insize - 4);
    if (HUF_isError(ret)) {
        printf("HUFF0 decompression had error: %s\n", HUF_getErrorName(ret));
        exit(1);
    }
    if (ret > outsize) {
        fprintf(stderr, "ERROR: Huffman decompression wrote past end of output"
            " buffer! (Wrote %lu bytes to buffer of length %lu)\n",
            ret, outsize);
        exit(1);
    }
    if (ret != orig_size) {
        printf("ERROR: Huffman decompression returned output of the wrong size"
            " (%ld instead of %lu)!", (long)ret, (unsigned long)orig_size);
        exit(1);
    }
    // fprintf(stderr, "ran HUF decompress; returning size %lub\n", ret);

    // fprintf(stderr, "HUF decompress wrote to : %d %d\n", (int)outbuf[orig_size - 2], (int)outbuf[orig_size - 1]);
    // fprintf(stderr, "HUF decompress final 2 bytes: %d %d\n", (int)outbuf[orig_size - 2], (int)outbuf[orig_size - 1]);
    // fprintf(stderr, "HUF decompress final 2 bytes: %d %d\n", (int)outbuf[orig_size - 2], (int)outbuf[orig_size - 1]);

    return ret;
}
