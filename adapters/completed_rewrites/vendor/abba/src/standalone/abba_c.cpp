#include "abba_c.h"

#include "abba.hpp"

#include <algorithm>
#include <exception>
#include <limits>
#include <new>
#include <stdexcept>

namespace {

abba::Config to_cpp(const abba_config_v1* config) {
  if (config == nullptr) {
    return abba::Config{};
  }
  abba::Config result;
  result.compression_tolerance = config->compression_tolerance;
  result.digitization_tolerance = config->digitization_tolerance;
  result.min_k = config->min_k;
  result.max_k = config->max_k;
  result.max_len = config->max_len;
  return result;
}

void copy_accounting(const abba::Accounting& source,
                     abba_accounting_v1* destination) {
  if (destination == nullptr) {
    return;
  }
  destination->header_bits = source.header_bits;
  destination->codebook_bits = source.codebook_bits;
  destination->symbol_stream_bits = source.symbol_stream_bits;
  destination->checksum_bits = source.checksum_bits;
  destination->serialized_bits = source.serialized_bits;
  destination->external_side_information_bits =
      source.external_side_information_bits;
  destination->final_bits = source.final_bits;
}

}  // namespace

extern "C" abba_config_v1 abba_config_default_v1(void) {
  const abba::Config config;
  return {config.compression_tolerance, config.digitization_tolerance,
          config.min_k, config.max_k, config.max_len};
}

extern "C" size_t abba_max_encoded_size_v1(const size_t sample_count) {
  return abba::max_encoded_size(sample_count);
}

extern "C" abba_status_v1 abba_encode_v1(
    const double* values, const size_t sample_count,
    const abba_config_v1* config, uint8_t* output,
    const size_t output_capacity, size_t* output_size,
    abba_accounting_v1* accounting) {
  if (output_size == nullptr) {
    return ABBA_STATUS_INVALID_ARGUMENT_V1;
  }
  try {
    abba::Accounting cpp_accounting;
    const auto encoded =
        abba::encode(values, sample_count, to_cpp(config), &cpp_accounting);
    *output_size = encoded.size();
    copy_accounting(cpp_accounting, accounting);
    if (output == nullptr || output_capacity < encoded.size()) {
      return ABBA_STATUS_BUFFER_TOO_SMALL_V1;
    }
    std::copy(encoded.begin(), encoded.end(), output);
    return ABBA_STATUS_OK_V1;
  } catch (const std::invalid_argument&) {
    return ABBA_STATUS_INVALID_ARGUMENT_V1;
  } catch (const std::bad_alloc&) {
    return ABBA_STATUS_ALLOCATION_FAILURE_V1;
  } catch (...) {
    return ABBA_STATUS_INTERNAL_ERROR_V1;
  }
}

extern "C" abba_status_v1 abba_decode_v1(
    const uint8_t* encoded, const size_t encoded_size, double* output,
    const size_t output_capacity, size_t* output_count,
    abba_accounting_v1* accounting) {
  if (output_count == nullptr) {
    return ABBA_STATUS_INVALID_ARGUMENT_V1;
  }
  try {
    abba::Accounting cpp_accounting;
    const auto decoded = abba::decode(encoded, encoded_size, &cpp_accounting);
    *output_count = decoded.size();
    copy_accounting(cpp_accounting, accounting);
    if (output == nullptr || output_capacity < decoded.size()) {
      return ABBA_STATUS_BUFFER_TOO_SMALL_V1;
    }
    std::copy(decoded.begin(), decoded.end(), output);
    return ABBA_STATUS_OK_V1;
  } catch (const std::invalid_argument&) {
    return ABBA_STATUS_MALFORMED_INPUT_V1;
  } catch (const std::bad_alloc&) {
    return ABBA_STATUS_ALLOCATION_FAILURE_V1;
  } catch (...) {
    return ABBA_STATUS_INTERNAL_ERROR_V1;
  }
}

extern "C" const char* abba_status_string_v1(const abba_status_v1 status) {
  switch (status) {
    case ABBA_STATUS_OK_V1:
      return "ok";
    case ABBA_STATUS_INVALID_ARGUMENT_V1:
      return "invalid argument";
    case ABBA_STATUS_BUFFER_TOO_SMALL_V1:
      return "buffer too small";
    case ABBA_STATUS_MALFORMED_INPUT_V1:
      return "malformed input";
    case ABBA_STATUS_ALLOCATION_FAILURE_V1:
      return "allocation failure";
    case ABBA_STATUS_INTERNAL_ERROR_V1:
      return "internal error";
  }
  return "unknown status";
}
