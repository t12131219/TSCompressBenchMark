#pragma once
#include "dzip_nn.hpp"
#include <vector>
namespace dzip {
// Original latin-1 reader's universal-newline normalization. Symbols remain
// latin-1 bytes; encoding the original decoder's text as UTF-8 is a caller step.
Bytes normalize_latin1(const Bytes& input);
struct BootstrapOptions {
    unsigned batch_size=2048,epochs=5,microbatch=64,shuffle_seed=0;
    float min_delta=.005f;
    unsigned patience=3;
    ExecutionBackend backend=ExecutionBackend::scalar;
    // Optional explicit source order for deterministic replay. The original
    // Keras 2.2.2 trainer with workers=0 reuses one shuffled order each epoch.
    std::vector<unsigned> order;
};
struct Epoch {
    unsigned index=0;
    float loss=0;
    bool checkpoint=false,early_stop=false;
};
struct BootstrapResult {
    Network checkpoint;
    std::vector<Epoch> epochs;
    std::size_t normalized_bytes=0,training_windows=0,dropped_windows=0;
};
// initial must be the sigmoid bootstrap training graph. No source runtime.
// Best weights are returned separately from the final model/Adam state.
BootstrapResult train_bootstrap(Network& initial,const Bytes& input,const BootstrapOptions& options={});
}
