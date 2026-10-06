#include "fabba_c.h"

#include "fabba.hpp"

#include <algorithm>
#include <new>
#include <stdexcept>

namespace {

fabba::Config to_cpp(const fabba_config_v1* config) {
  if (config == nullptr) {
    return {};
  }
  fabba::Config result;
  result.tolerance = config->tolerance;
  result.alpha = config->alpha;
  result.scl = config->scl;
  result.max_len = config->max_len;
  return result;
}

void copy_accounting(const fabba::Accounting& source,
                     fabba_accounting_v1* destination) {
  if (destination == nullptr) {
    return;
  }
  destination->header_bits = source.header_bits;
  destination->codebook_bits = source.codebook_bits;
  destination->symbol_stream_bits = source.symbol_stream_bits;
  destination->checksum_bits = source.checksum_bits;
  destination->serialized_bits = source.serialized_bits;
  destination->external_side_information_bits = source.external_side_information_bits;
  destination->final_bits = source.final_bits;
}

}  // namespace

extern "C" fabba_config_v1 fabba_config_default_v1(void) {
  const fabba::Config config;
  return {config.tolerance, config.alpha, config.scl, config.max_len};
}

extern "C" size_t fabba_max_encoded_size_v1(const size_t sample_count) {
  return fabba::max_encoded_size(sample_count);
}

extern "C" fabba_status_v1 fabba_encode_v1(
    const double* values, const size_t sample_count,
    const fabba_config_v1* config, uint8_t* output,
    const size_t output_capacity, size_t* output_size,
    fabba_accounting_v1* accounting) {
  if (output_size == nullptr) {
    return FABBA_STATUS_INVALID_ARGUMENT_V1;
  }
  try {
    fabba::Accounting cpp_accounting;
    const auto encoded = fabba::encode(values, sample_count, to_cpp(config),
                                       &cpp_accounting);
    *output_size = encoded.size();
    copy_accounting(cpp_accounting, accounting);
    if (output == nullptr || output_capacity < encoded.size()) {
      return FABBA_STATUS_BUFFER_TOO_SMALL_V1;
    }
    std::copy(encoded.begin(), encoded.end(), output);
    return FABBA_STATUS_OK_V1;
  } catch (const std::invalid_argument&) {
    return FABBA_STATUS_INVALID_ARGUMENT_V1;
  } catch (const std::bad_alloc&) {
    return FABBA_STATUS_ALLOCATION_FAILURE_V1;
  } catch (...) {
    return FABBA_STATUS_INTERNAL_ERROR_V1;
  }
}

extern "C" fabba_status_v1 fabba_decode_v1(
    const uint8_t* encoded, const size_t encoded_size, double* output,
    const size_t output_capacity, size_t* output_count,
    fabba_accounting_v1* accounting) {
  if (output_count == nullptr) {
    return FABBA_STATUS_INVALID_ARGUMENT_V1;
  }
  try {
    fabba::Accounting cpp_accounting;
    const auto decoded = fabba::decode(encoded, encoded_size, &cpp_accounting);
    *output_count = decoded.size();
    copy_accounting(cpp_accounting, accounting);
    if (output == nullptr || output_capacity < decoded.size()) {
      return FABBA_STATUS_BUFFER_TOO_SMALL_V1;
    }
    std::copy(decoded.begin(), decoded.end(), output);
    return FABBA_STATUS_OK_V1;
  } catch (const std::invalid_argument&) {
    return FABBA_STATUS_MALFORMED_INPUT_V1;
  } catch (const std::bad_alloc&) {
    return FABBA_STATUS_ALLOCATION_FAILURE_V1;
  } catch (...) {
    return FABBA_STATUS_INTERNAL_ERROR_V1;
  }
}

extern "C" const char* fabba_status_string_v1(const fabba_status_v1 status) {
  switch (status) {
    case FABBA_STATUS_OK_V1: return "ok";
    case FABBA_STATUS_INVALID_ARGUMENT_V1: return "invalid argument";
    case FABBA_STATUS_BUFFER_TOO_SMALL_V1: return "buffer too small";
    case FABBA_STATUS_MALFORMED_INPUT_V1: return "malformed input";
    case FABBA_STATUS_ALLOCATION_FAILURE_V1: return "allocation failure";
    case FABBA_STATUS_INTERNAL_ERROR_V1: return "internal error";
  }
  return "unknown status";
}
