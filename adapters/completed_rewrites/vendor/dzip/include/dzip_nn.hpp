#pragma once
#include <cstddef>
#include <cstdint>
#include <memory>
#include <string>
#include <vector>

namespace dzip {
using Bytes = std::vector<std::uint8_t>;
enum class AdamRule { tensorflow, keras };
enum class ModelProfile { bootstrap_cpu, combined_cpu, bootstrap_training };
enum class ExecutionBackend { scalar, cuda };
struct TrainOptions {
    float learning_rate = 5e-4f;
    float beta1 = .9f;
    float beta2 = .999f;
    float epsilon = 1e-8f;
    float clipnorm = 0.f;
    AdamRule rule = AdamRule::tensorflow;
    // Zero processes the whole batch. Nonzero accumulates gradients at unchanged
    // weights before one Adam update, bounding bootstrap working memory.
    unsigned microbatch = 0;
    ExecutionBackend backend = ExecutionBackend::scalar;
};
// Owns a native graph, its weights and Adam slots. Independent copies have
// independent state; callers synchronize simultaneous use of the same handle.
// Frozen CUDA backend calls are serialized across independent handles; CPU
// handles execute concurrently. GPU overlap/parallel speedup is not promised.
class Network {
public:
    static Network load(const Bytes& bytes, std::size_t max_bytes = 512u * 1024u * 1024u);
    // Native seeded initializer is declared separately from NumPy/TF seeds.
    // The resulting complete initial state is stored in the encoded frame.
    static Network create(unsigned alphabet, ModelProfile profile, std::uint32_t seed = 0);
    static Network from_hdf5(const std::string& path, ModelProfile profile,
                             std::uint32_t supporter_seed = 0);
    void import_bootstrap(const Network& bootstrap);
    // Source CPU codec uses hard_sigmoid even when its checkpoint was trained
    // by CuDNN's sigmoid graph. Canonical kernels remain unchanged.
    Network cpu_bootstrap() const;
    Network(const Network&);
    Network& operator=(const Network&);
    Network(Network&&) noexcept;
    Network& operator=(Network&&) noexcept;
    ~Network();
    unsigned alphabet() const;
    unsigned context() const;
    // Export graph/weights for a fresh codec. Adam slots are not a checkpoint.
    Bytes serialize() const;
    static bool cuda_compiled() noexcept;
    std::vector<float> predict(const std::vector<std::int32_t>& contexts,
                               ExecutionBackend backend = ExecutionBackend::scalar);
    // Test/diagnostic export in graph tensor order; computes gradients without
    // changing weights or Adam slots. Uses the source loss in bits.
    Bytes gradient_graph(const std::vector<std::int32_t>& contexts,
                         const std::vector<std::int32_t>& labels,
                         ExecutionBackend backend = ExecutionBackend::scalar);
    // Diagnostic activation/adjoint trace, without weight or optimizer updates.
    // DZIPTR01 contains node count then rows,cols and two float32 arrays/node.
    Bytes trace_graph(const std::vector<std::int32_t>& contexts,
                     const std::vector<std::int32_t>& labels,
                     ExecutionBackend backend = ExecutionBackend::scalar);
    float train(const std::vector<std::int32_t>& contexts,
                const std::vector<std::int32_t>& labels,
                const TrainOptions& options = {});
    void reset_optimizer();
private:
    struct Impl;
    explicit Network(std::unique_ptr<Impl>);
    std::unique_ptr<Impl> impl_;
};
}  // namespace dzip
