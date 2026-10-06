// Copyright The Prometheus Authors
// Copyright (c) 2015,2016 Damian Gryski <damian@gryski.com>
// Copyright 2026 TSDataCompressBenchMark contributors.
// SPDX-License-Identifier: Apache-2.0 AND BSD-3-Clause

#include "prometheus_xor_chunk_c.h"

#include "prometheus_xor_chunk.hpp"

#include <cstdio>
#include <cstring>
#include <limits>
#include <new>
#include <vector>

namespace xor_codec = prometheus_xor;

static_assert(sizeof(pxor_sample_v1) == 16, "pxor_sample_v1 ABI size must remain 16 bytes");

struct pxor_codec_v1 {
    std::uint64_t sample_count = 0;
    std::uint64_t serialized_bytes = 0;
    bool compressed = false;
    bool finalized = false;
    char last_error[256]{};
};

namespace {

constexpr char kManifestJson[] =
    "{\"standalone_api_version\":1,"
    "\"algorithm_id\":\"prometheus-xor-chunk\","
    "\"implementation_id\":\"prometheus-xor-chunk-canonical-cpp\","
    "\"object_level\":\"P3_SYSTEM\","
    "\"compatibility_target\":\"CROSS_DECODE\","
    "\"input\":{\"record\":\"pxor_sample_v1\",\"fields\":[\"timestamp\",\"value_bits\"]},"
    "\"streaming\":false,\"append_resume\":true,\"query\":false,"
    "\"safe_overread_bytes\":0,\"isa\":\"SCALAR\",\"threads\":1}";

void clear_error(pxor_codec_v1* codec) noexcept {
    if (codec != nullptr) {
        codec->last_error[0] = '\0';
    }
}

void set_error(pxor_codec_v1* codec, const char* message) noexcept {
    if (codec != nullptr) {
        std::snprintf(codec->last_error, sizeof(codec->last_error), "%s", message);
    }
}

bool valid_samples(const pxor_sample_v1* samples, std::uint64_t count) noexcept {
    return count <= xor_codec::kMaxSampleCount &&
           count <= std::numeric_limits<std::size_t>::max() &&
           (count == 0 || samples != nullptr);
}

std::vector<xor_codec::Sample> copy_samples(
    const pxor_sample_v1* samples,
    std::uint64_t count) {
    std::vector<xor_codec::Sample> result(static_cast<std::size_t>(count));
    for (std::size_t index = 0; index < result.size(); ++index) {
        result[index] = {samples[index].timestamp, samples[index].value_bits};
    }
    return result;
}

pxor_status_v1 map_status(pxor_codec_v1* codec, xor_codec::Status status) noexcept {
    if (status.ok()) {
        return PXOR_STATUS_OK_V1;
    }
    set_error(codec, status.message);
    switch (status.code) {
    case xor_codec::StatusCode::kInvalidArgument:
        return PXOR_STATUS_INVALID_ARGUMENT_V1;
    case xor_codec::StatusCode::kOutputTooSmall:
        return PXOR_STATUS_DST_TOO_SMALL_V1;
    case xor_codec::StatusCode::kMalformedStream:
        return PXOR_STATUS_CORRUPT_STREAM_V1;
    case xor_codec::StatusCode::kSampleLimitExceeded:
        return PXOR_STATUS_SAMPLE_LIMIT_EXCEEDED_V1;
    case xor_codec::StatusCode::kOk:
        return PXOR_STATUS_OK_V1;
    }
    set_error(codec, "unknown canonical status");
    return PXOR_STATUS_CORRUPT_STREAM_V1;
}

pxor_status_v1 exact_encoded_size(
    pxor_codec_v1* codec,
    const std::vector<xor_codec::Sample>& samples,
    std::uint64_t* encoded_size) {
    std::size_t maximum = 0;
    xor_codec::Status status = xor_codec::max_compressed_size(samples.size(), &maximum);
    if (!status.ok()) {
        return map_status(codec, status);
    }
    std::vector<std::uint8_t> scratch(maximum);
    std::size_t written = 0;
    status = xor_codec::encode(
        samples.data(), samples.size(), scratch.data(), scratch.size(), &written);
    if (!status.ok()) {
        return map_status(codec, status);
    }
    *encoded_size = static_cast<std::uint64_t>(written);
    return PXOR_STATUS_OK_V1;
}

}  // namespace

extern "C" {

std::uint32_t pxor_get_api_version_v1(void) {
    return PXOR_STANDALONE_API_VERSION_V1;
}

pxor_status_v1 pxor_get_manifest_json_v1(const char** json, std::uint64_t* length) {
    if (json == nullptr || length == nullptr) {
        return PXOR_STATUS_INVALID_ARGUMENT_V1;
    }
    *json = kManifestJson;
    *length = sizeof(kManifestJson) - 1U;
    return PXOR_STATUS_OK_V1;
}

pxor_status_v1 pxor_create_v1(pxor_codec_v1** codec) {
    if (codec == nullptr) {
        return PXOR_STATUS_INVALID_ARGUMENT_V1;
    }
    *codec = new (std::nothrow) pxor_codec_v1{};
    return *codec == nullptr ? PXOR_STATUS_ALLOCATION_FAILED_V1 : PXOR_STATUS_OK_V1;
}

pxor_status_v1 pxor_destroy_v1(pxor_codec_v1* codec) {
    delete codec;
    return PXOR_STATUS_OK_V1;
}

pxor_status_v1 pxor_reset_v1(pxor_codec_v1* codec) {
    if (codec == nullptr) {
        return PXOR_STATUS_INVALID_ARGUMENT_V1;
    }
    *codec = pxor_codec_v1{};
    return PXOR_STATUS_OK_V1;
}

pxor_status_v1 pxor_compress_bound_v1(
    pxor_codec_v1* codec,
    const pxor_sample_v1* samples,
    std::uint64_t sample_count,
    std::uint64_t* bound_bytes) {
    if (codec == nullptr || bound_bytes == nullptr || !valid_samples(samples, sample_count)) {
        return sample_count > xor_codec::kMaxSampleCount
            ? PXOR_STATUS_SAMPLE_LIMIT_EXCEEDED_V1
            : PXOR_STATUS_INVALID_ARGUMENT_V1;
    }
    clear_error(codec);
    try {
        return exact_encoded_size(codec, copy_samples(samples, sample_count), bound_bytes);
    } catch (const std::bad_alloc&) {
        set_error(codec, "allocation failed while calculating exact compressed size");
        return PXOR_STATUS_ALLOCATION_FAILED_V1;
    } catch (...) {
        set_error(codec, "unexpected exception while calculating exact compressed size");
        return PXOR_STATUS_INVALID_ARGUMENT_V1;
    }
}

pxor_status_v1 pxor_compress_v1(
    pxor_codec_v1* codec,
    const pxor_sample_v1* samples,
    std::uint64_t sample_count,
    std::uint8_t* output,
    std::uint64_t output_capacity,
    std::uint64_t* bytes_written) {
    if (codec == nullptr || bytes_written == nullptr ||
        output_capacity > std::numeric_limits<std::size_t>::max() ||
        (output_capacity != 0 && output == nullptr) ||
        !valid_samples(samples, sample_count)) {
        return sample_count > xor_codec::kMaxSampleCount
            ? PXOR_STATUS_SAMPLE_LIMIT_EXCEEDED_V1
            : PXOR_STATUS_INVALID_ARGUMENT_V1;
    }
    *bytes_written = 0;
    clear_error(codec);
    if (codec->compressed || codec->finalized) {
        set_error(codec, "compress may be called once per reset");
        return PXOR_STATUS_INVALID_STATE_V1;
    }
    try {
        const std::vector<xor_codec::Sample> copied = copy_samples(samples, sample_count);
        std::size_t written = 0;
        const xor_codec::Status status = xor_codec::encode(
            copied.data(),
            copied.size(),
            output,
            static_cast<std::size_t>(output_capacity),
            &written);
        const pxor_status_v1 mapped = map_status(codec, status);
        if (mapped != PXOR_STATUS_OK_V1) {
            return mapped;
        }
        *bytes_written = static_cast<std::uint64_t>(written);
        codec->sample_count = sample_count;
        codec->serialized_bytes = *bytes_written;
        codec->compressed = true;
        return PXOR_STATUS_OK_V1;
    } catch (const std::bad_alloc&) {
        set_error(codec, "allocation failed during compression");
        return PXOR_STATUS_ALLOCATION_FAILED_V1;
    } catch (...) {
        set_error(codec, "unexpected exception during compression");
        return PXOR_STATUS_INVALID_ARGUMENT_V1;
    }
}

pxor_status_v1 pxor_finalize_v1(
    pxor_codec_v1* codec,
    std::uint8_t* output,
    std::uint64_t output_capacity,
    std::uint64_t* bytes_written) {
    if (codec == nullptr || bytes_written == nullptr ||
        (output_capacity != 0 && output == nullptr)) {
        return PXOR_STATUS_INVALID_ARGUMENT_V1;
    }
    *bytes_written = 0;
    clear_error(codec);
    if (!codec->compressed || codec->finalized) {
        set_error(codec, !codec->compressed
            ? "compress must precede finalize"
            : "finalize may be called once per reset");
        return PXOR_STATUS_INVALID_STATE_V1;
    }
    codec->finalized = true;
    return PXOR_STATUS_OK_V1;
}

pxor_status_v1 pxor_decompress_v1(
    pxor_codec_v1* codec,
    const std::uint8_t* input,
    std::uint64_t input_size,
    pxor_sample_v1* samples,
    std::uint64_t sample_capacity,
    std::uint64_t* samples_written) {
    if (codec == nullptr || samples_written == nullptr || input == nullptr ||
        input_size > std::numeric_limits<std::size_t>::max() ||
        sample_capacity > std::numeric_limits<std::size_t>::max() ||
        (sample_capacity != 0 && samples == nullptr)) {
        return PXOR_STATUS_INVALID_ARGUMENT_V1;
    }
    *samples_written = 0;
    clear_error(codec);
    try {
        std::vector<xor_codec::Sample> decoded(static_cast<std::size_t>(sample_capacity));
        std::size_t written = 0;
        const xor_codec::Status status = xor_codec::decode(
            input,
            static_cast<std::size_t>(input_size),
            decoded.data(),
            decoded.size(),
            &written);
        const pxor_status_v1 mapped = map_status(codec, status);
        if (mapped != PXOR_STATUS_OK_V1) {
            return mapped;
        }
        for (std::size_t index = 0; index < written; ++index) {
            samples[index] = {decoded[index].timestamp, decoded[index].value_bits};
        }
        *samples_written = static_cast<std::uint64_t>(written);
        return PXOR_STATUS_OK_V1;
    } catch (const std::bad_alloc&) {
        set_error(codec, "allocation failed during decompression");
        return PXOR_STATUS_ALLOCATION_FAILED_V1;
    } catch (...) {
        set_error(codec, "unexpected exception during decompression");
        return PXOR_STATUS_INVALID_ARGUMENT_V1;
    }
}

pxor_status_v1 pxor_get_accounting_v1(
    pxor_codec_v1* codec,
    pxor_accounting_v1* accounting) {
    if (codec == nullptr || accounting == nullptr ||
        accounting->struct_size != sizeof(pxor_accounting_v1)) {
        return PXOR_STATUS_INVALID_ARGUMENT_V1;
    }
    if (!codec->finalized) {
        set_error(codec, "accounting is available after finalize");
        return PXOR_STATUS_INVALID_STATE_V1;
    }
    clear_error(codec);
    const std::uint64_t serialized_bits = codec->serialized_bytes * UINT64_C(8);
    const std::uint64_t container_bits = xor_codec::kChunkHeaderSize * UINT64_C(8);
    accounting->sample_count = codec->sample_count;
    accounting->canonical_raw_bits = codec->sample_count * UINT64_C(128);
    accounting->serialized_bytes = codec->serialized_bytes;
    accounting->serialized_bits = serialized_bits;
    accounting->container_bits = container_bits;
    accounting->timestamp_value_joint_and_padding_bits = serialized_bits - container_bits;
    accounting->external_side_information_bits = 0;
    accounting->final_bits = serialized_bits;
    return PXOR_STATUS_OK_V1;
}

pxor_status_v1 pxor_get_last_error_v1(
    pxor_codec_v1* codec,
    const char** message,
    std::uint64_t* length) {
    if (codec == nullptr || message == nullptr || length == nullptr) {
        return PXOR_STATUS_INVALID_ARGUMENT_V1;
    }
    *message = codec->last_error;
    *length = std::strlen(codec->last_error);
    return PXOR_STATUS_OK_V1;
}

}  // extern "C"
