// Copyright 2026 TSDataCompressBenchMark contributors.
// SPDX-License-Identifier: Apache-2.0 AND BSD-3-Clause

#include "prometheus_xor2_chunk_c.h"

#include "prometheus_xor2_chunk.hpp"

#include <cstdio>
#include <cstring>
#include <limits>
#include <new>
#include <vector>

namespace codec = prometheus_xor2;

static_assert(sizeof(pxor2_sample_v1) == 24, "pxor2_sample_v1 ABI size must remain 24 bytes");

struct pxor2_codec_v1 {
    std::uint64_t sample_count = 0;
    std::uint64_t serialized_bytes = 0;
    bool compressed = false;
    bool finalized = false;
    char last_error[256]{};
};

namespace {

constexpr char kManifestJson[] =
    "{\"standalone_api_version\":1,"
    "\"algorithm_id\":\"prometheus-xor2-chunk\","
    "\"implementation_id\":\"prometheus-xor2-chunk-canonical-cpp\","
    "\"object_level\":\"P3_SYSTEM\","
    "\"compatibility_target\":\"CROSS_DECODE\","
    "\"input\":{\"record\":\"pxor2_sample_v1\","
    "\"fields\":[\"start_timestamp\",\"timestamp\",\"value_bits\"]},"
    "\"streaming\":false,\"append_resume\":true,\"query\":false,"
    "\"safe_overread_bytes\":0,\"isa\":\"SCALAR\",\"threads\":1}";

void clear_error(pxor2_codec_v1* codec_handle) noexcept {
    codec_handle->last_error[0] = '\0';
}

void set_error(pxor2_codec_v1* codec_handle, const char* message) noexcept {
    if (codec_handle != nullptr) {
        std::snprintf(codec_handle->last_error, sizeof(codec_handle->last_error), "%s", message);
    }
}

bool valid_samples(const pxor2_sample_v1* samples, std::uint64_t count) noexcept {
    return count <= codec::kMaxSampleCount &&
           count <= std::numeric_limits<std::size_t>::max() &&
           (count == 0 || samples != nullptr);
}

std::vector<codec::Sample> copy_samples(
    const pxor2_sample_v1* samples,
    std::uint64_t count) {
    std::vector<codec::Sample> result(static_cast<std::size_t>(count));
    for (std::size_t index = 0; index < result.size(); ++index) {
        result[index] = {
            samples[index].start_timestamp,
            samples[index].timestamp,
            samples[index].value_bits,
        };
    }
    return result;
}

pxor2_status_v1 map_status(pxor2_codec_v1* codec_handle, codec::Status status) noexcept {
    if (status.ok()) {
        return PXOR2_STATUS_OK_V1;
    }
    set_error(codec_handle, status.message);
    switch (status.code) {
    case codec::StatusCode::kInvalidArgument:
        return PXOR2_STATUS_INVALID_ARGUMENT_V1;
    case codec::StatusCode::kOutputTooSmall:
        return PXOR2_STATUS_DST_TOO_SMALL_V1;
    case codec::StatusCode::kMalformedStream:
        return PXOR2_STATUS_CORRUPT_STREAM_V1;
    case codec::StatusCode::kSampleLimitExceeded:
        return PXOR2_STATUS_SAMPLE_LIMIT_EXCEEDED_V1;
    case codec::StatusCode::kOk:
        return PXOR2_STATUS_OK_V1;
    }
    return PXOR2_STATUS_CORRUPT_STREAM_V1;
}

pxor2_status_v1 exact_size(
    pxor2_codec_v1* codec_handle,
    const std::vector<codec::Sample>& samples,
    std::uint64_t* result) {
    std::size_t maximum = 0;
    codec::Status status = codec::max_compressed_size(samples.size(), &maximum);
    if (!status.ok()) {
        return map_status(codec_handle, status);
    }
    std::vector<std::uint8_t> scratch(maximum);
    std::size_t written = 0;
    status = codec::encode(samples.data(), samples.size(), scratch.data(), scratch.size(), &written);
    if (!status.ok()) {
        return map_status(codec_handle, status);
    }
    *result = static_cast<std::uint64_t>(written);
    return PXOR2_STATUS_OK_V1;
}

}  // namespace

extern "C" {

std::uint32_t pxor2_get_api_version_v1(void) {
    return PXOR2_STANDALONE_API_VERSION_V1;
}

pxor2_status_v1 pxor2_get_manifest_json_v1(const char** json, std::uint64_t* length) {
    if (json == nullptr || length == nullptr) {
        return PXOR2_STATUS_INVALID_ARGUMENT_V1;
    }
    *json = kManifestJson;
    *length = sizeof(kManifestJson) - 1U;
    return PXOR2_STATUS_OK_V1;
}

pxor2_status_v1 pxor2_create_v1(pxor2_codec_v1** codec_handle) {
    if (codec_handle == nullptr) {
        return PXOR2_STATUS_INVALID_ARGUMENT_V1;
    }
    *codec_handle = new (std::nothrow) pxor2_codec_v1{};
    return *codec_handle == nullptr ? PXOR2_STATUS_ALLOCATION_FAILED_V1 : PXOR2_STATUS_OK_V1;
}

pxor2_status_v1 pxor2_destroy_v1(pxor2_codec_v1* codec_handle) {
    delete codec_handle;
    return PXOR2_STATUS_OK_V1;
}

pxor2_status_v1 pxor2_reset_v1(pxor2_codec_v1* codec_handle) {
    if (codec_handle == nullptr) {
        return PXOR2_STATUS_INVALID_ARGUMENT_V1;
    }
    *codec_handle = pxor2_codec_v1{};
    return PXOR2_STATUS_OK_V1;
}

pxor2_status_v1 pxor2_compress_bound_v1(
    pxor2_codec_v1* codec_handle,
    const pxor2_sample_v1* samples,
    std::uint64_t sample_count,
    std::uint64_t* bound_bytes) {
    if (codec_handle == nullptr || bound_bytes == nullptr || !valid_samples(samples, sample_count)) {
        return sample_count > codec::kMaxSampleCount ?
            PXOR2_STATUS_SAMPLE_LIMIT_EXCEEDED_V1 : PXOR2_STATUS_INVALID_ARGUMENT_V1;
    }
    clear_error(codec_handle);
    try {
        return exact_size(codec_handle, copy_samples(samples, sample_count), bound_bytes);
    } catch (const std::bad_alloc&) {
        set_error(codec_handle, "allocation failed while calculating compressed size");
        return PXOR2_STATUS_ALLOCATION_FAILED_V1;
    } catch (...) {
        set_error(codec_handle, "unexpected exception while calculating compressed size");
        return PXOR2_STATUS_INVALID_ARGUMENT_V1;
    }
}

pxor2_status_v1 pxor2_compress_v1(
    pxor2_codec_v1* codec_handle,
    const pxor2_sample_v1* samples,
    std::uint64_t sample_count,
    std::uint8_t* output,
    std::uint64_t output_capacity,
    std::uint64_t* bytes_written) {
    if (codec_handle == nullptr || bytes_written == nullptr ||
        output_capacity > std::numeric_limits<std::size_t>::max() ||
        (output_capacity != 0 && output == nullptr) || !valid_samples(samples, sample_count)) {
        return sample_count > codec::kMaxSampleCount ?
            PXOR2_STATUS_SAMPLE_LIMIT_EXCEEDED_V1 : PXOR2_STATUS_INVALID_ARGUMENT_V1;
    }
    *bytes_written = 0;
    clear_error(codec_handle);
    if (codec_handle->compressed || codec_handle->finalized) {
        set_error(codec_handle, "compress may be called once per reset");
        return PXOR2_STATUS_INVALID_STATE_V1;
    }
    try {
        const std::vector<codec::Sample> copied = copy_samples(samples, sample_count);
        std::size_t written = 0;
        const pxor2_status_v1 mapped = map_status(
            codec_handle,
            codec::encode(copied.data(), copied.size(), output,
                          static_cast<std::size_t>(output_capacity), &written));
        if (mapped != PXOR2_STATUS_OK_V1) {
            return mapped;
        }
        *bytes_written = static_cast<std::uint64_t>(written);
        codec_handle->sample_count = sample_count;
        codec_handle->serialized_bytes = *bytes_written;
        codec_handle->compressed = true;
        return PXOR2_STATUS_OK_V1;
    } catch (const std::bad_alloc&) {
        set_error(codec_handle, "allocation failed during compression");
        return PXOR2_STATUS_ALLOCATION_FAILED_V1;
    } catch (...) {
        set_error(codec_handle, "unexpected exception during compression");
        return PXOR2_STATUS_INVALID_ARGUMENT_V1;
    }
}

pxor2_status_v1 pxor2_finalize_v1(
    pxor2_codec_v1* codec_handle,
    std::uint8_t* output,
    std::uint64_t output_capacity,
    std::uint64_t* bytes_written) {
    if (codec_handle == nullptr || bytes_written == nullptr ||
        (output_capacity != 0 && output == nullptr)) {
        return PXOR2_STATUS_INVALID_ARGUMENT_V1;
    }
    *bytes_written = 0;
    clear_error(codec_handle);
    if (!codec_handle->compressed || codec_handle->finalized) {
        set_error(codec_handle, !codec_handle->compressed ?
            "compress must precede finalize" : "finalize may be called once per reset");
        return PXOR2_STATUS_INVALID_STATE_V1;
    }
    codec_handle->finalized = true;
    return PXOR2_STATUS_OK_V1;
}

pxor2_status_v1 pxor2_decompress_v1(
    pxor2_codec_v1* codec_handle,
    const std::uint8_t* input,
    std::uint64_t input_size,
    pxor2_sample_v1* samples,
    std::uint64_t sample_capacity,
    std::uint64_t* samples_written) {
    if (codec_handle == nullptr || samples_written == nullptr || input == nullptr ||
        input_size > std::numeric_limits<std::size_t>::max() ||
        sample_capacity > std::numeric_limits<std::size_t>::max() ||
        (sample_capacity != 0 && samples == nullptr)) {
        return PXOR2_STATUS_INVALID_ARGUMENT_V1;
    }
    *samples_written = 0;
    clear_error(codec_handle);
    try {
        std::vector<codec::Sample> decoded(static_cast<std::size_t>(sample_capacity));
        std::size_t written = 0;
        const pxor2_status_v1 mapped = map_status(
            codec_handle,
            codec::decode(input, static_cast<std::size_t>(input_size), decoded.data(),
                          decoded.size(), &written));
        if (mapped != PXOR2_STATUS_OK_V1) {
            return mapped;
        }
        for (std::size_t index = 0; index < written; ++index) {
            samples[index] = {
                decoded[index].start_timestamp,
                decoded[index].timestamp,
                decoded[index].value_bits,
            };
        }
        *samples_written = static_cast<std::uint64_t>(written);
        return PXOR2_STATUS_OK_V1;
    } catch (const std::bad_alloc&) {
        set_error(codec_handle, "allocation failed during decompression");
        return PXOR2_STATUS_ALLOCATION_FAILED_V1;
    } catch (...) {
        set_error(codec_handle, "unexpected exception during decompression");
        return PXOR2_STATUS_INVALID_ARGUMENT_V1;
    }
}

pxor2_status_v1 pxor2_get_accounting_v1(
    pxor2_codec_v1* codec_handle,
    pxor2_accounting_v1* accounting) {
    if (codec_handle == nullptr || accounting == nullptr ||
        accounting->struct_size != sizeof(pxor2_accounting_v1)) {
        return PXOR2_STATUS_INVALID_ARGUMENT_V1;
    }
    if (!codec_handle->compressed || !codec_handle->finalized) {
        set_error(codec_handle, "accounting requires successful compression and finalize");
        return PXOR2_STATUS_INVALID_STATE_V1;
    }
    const std::uint64_t serialized_bits = codec_handle->serialized_bytes * 8;
    *accounting = {
        sizeof(pxor2_accounting_v1),
        codec_handle->sample_count,
        codec_handle->sample_count * 192,
        codec_handle->serialized_bytes,
        serialized_bits,
        24,
        serialized_bits - 24,
        0,
        serialized_bits,
    };
    return PXOR2_STATUS_OK_V1;
}

pxor2_status_v1 pxor2_get_last_error_v1(
    pxor2_codec_v1* codec_handle,
    const char** message,
    std::uint64_t* length) {
    if (codec_handle == nullptr || message == nullptr || length == nullptr) {
        return PXOR2_STATUS_INVALID_ARGUMENT_V1;
    }
    *message = codec_handle->last_error;
    *length = std::strlen(codec_handle->last_error);
    return PXOR2_STATUS_OK_V1;
}

}  // extern "C"
