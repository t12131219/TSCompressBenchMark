#pragma once
#include <cstddef>
#include <cstdint>
#include <map>
#include <memory>
#include <string>
#include <vector>

namespace at { class Tensor; }

namespace walloc {
using Bytes = std::vector<std::uint8_t>;
struct Config {
  std::uint32_t channels=2, levels=8, encoder_width=0, decoder_width=768;
  std::uint32_t latent_dim=108, latent_bits=8;
  bool lightweight=true, post_filter=true;
};
struct Tensor {
  std::vector<std::int64_t> shape;
  std::vector<float> values;
};
struct Evaluation {
  std::map<std::string,Tensor> stages;
  float waveform_loss=0, transform_loss=0;
};
struct TrainingOptions {
  double learning_rate=1e-7, weight_decay=0, transform_weight=0;
  double beta1=.9, beta2=.999, epsilon=1e-8;
};
struct TrainingResult {
  Evaluation evaluation;
  std::map<std::string,Tensor> gradients;
  std::uint64_t updates=0;
};
struct Ledger {
  std::size_t model_bytes=0,payload_bytes=0,metadata_bytes=0,total_bytes=0;
  std::uint64_t final_bits() const {return static_cast<std::uint64_t>(total_bytes)*8;}
};
enum class EncoderStage {Linear,Uniform,Quantized};
struct TensorEvaluation;

// C++ algorithm graph; native tensor kernels are an explicit dependency.
// Different handles may run concurrently. Calls on one handle are serialized.
// CPU canonical is one-thread by default; CUDA never falls back to CPU.
class Codec {
 public:
  explicit Codec(const Bytes& neutral_model, const std::string& device="cpu");
  static std::unique_ptr<Codec> initialize(const Config&,std::uint64_t seed,
                                          const std::string& device="cpu");
  ~Codec();
  Codec(const Codec&)=delete;
  Codec& operator=(const Codec&)=delete;
  Config config() const;
  // Optional native tensor API (include walloc_tensor.hpp): keeps CPU/CUDA
  // tensors on their device and permits compressed-domain use without WebP.
  // Inference only, finite float32 input; no hidden host snapshots or fitting.
  at::Tensor wavelet_analysis(const at::Tensor&,unsigned levels);
  at::Tensor wavelet_synthesis(const at::Tensor&,unsigned levels);
  at::Tensor encode_stage(const at::Tensor& transformed,EncoderStage);
  at::Tensor decode_transform(const at::Tensor& latent);
  at::Tensor filter_reconstruction(const at::Tensor&,bool clamp=true);
  TensorEvaluation forward_tensor(const at::Tensor&,bool audio_padding=false);
  Bytes model() const;
  Evaluation evaluate(const float* input,std::size_t count,std::size_t batch,
                      std::size_t length,bool audio_padding=false);
  Tensor decode_latent(const Tensor&,std::size_t original_length,bool crop=true);
  Bytes encode(const float* input,std::size_t count,std::size_t length,Ledger* =nullptr);
  static Tensor decode(const Bytes& frame,const std::string& device="cpu",Ledger* =nullptr);
  static Bytes latent_webp(const Tensor&,unsigned bits);
  static Tensor webp_latent(const Bytes&,unsigned latent_dim,unsigned bits,std::size_t length);
  // Exact one update or accumulated mean-loss update. No checkpoint fitting hidden in encode.
  TrainingResult train(const float* input,std::size_t count,std::size_t batch,
                       std::size_t length,const TrainingOptions&,
                       std::uint64_t seed,bool update=true);
  TrainingResult train_replay(const float*,std::size_t count,std::size_t batch,
                             std::size_t length,const TrainingOptions&,
                             const Bytes& cpu_rng,const Bytes& device_rng={},bool update=true);
  TrainingResult train_continue(const float*,std::size_t count,std::size_t batch,
                                std::size_t length,const TrainingOptions&,bool update=true);
  void apply_accumulated(const TrainingOptions&,std::size_t divisor=1);
  Bytes checkpoint() const;
  void restore_checkpoint(const Bytes&);
  void reset_optimizer();
  static Tensor normalize(const Tensor&);
  // C,4,L instrument layout; caller chooses crop/mix without implicit fitting.
  static Tensor mix_crop(const Tensor&,std::size_t start,std::size_t length,
                         const std::vector<float>& four_weights);
  static std::vector<std::vector<float>> mixing_weights();
  static bool cuda_available();
  static void configure_cpu_threads(unsigned intra,unsigned inter=1);
 private:
  struct Impl;
  explicit Codec(std::unique_ptr<Impl>);
  std::unique_ptr<Impl> p_;
};

class Encoder {
 public:
  explicit Encoder(Codec&);
  void compress(const float*,std::size_t count,std::size_t length);
  std::size_t bound() const;
  // Returns exact size; writes nothing if capacity is insufficient.
  std::size_t finalize(std::uint8_t* destination,std::size_t capacity) const;
  void reset();
 private: Codec& codec_; Bytes frame_; bool ready_=false;
};

struct Schedule {
  double min_lr=1e-7,max_lr=3e-5,factor=.98,threshold=1e-5;
  std::uint64_t warmup_steps=5000,plot_update=64,patience=64;
  std::uint64_t scheduler_step=0,bad_epochs=0;
  double best=0,current_lr=1e-7;
  bool has_best=false;
  double observe(std::uint64_t training_step,double smoothed_log_loss);
};
}  // namespace walloc
