#pragma once
#include "walloc.hpp"
#include <ATen/ATen.h>

namespace walloc {
struct TensorEvaluation {
  std::map<std::string,at::Tensor> stages;
  at::Tensor waveform_loss,transform_loss;
};
} // namespace walloc
