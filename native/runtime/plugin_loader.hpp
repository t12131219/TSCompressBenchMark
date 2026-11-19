#pragma once
#include "tsbench/plugin_abi.h"

#include <cstdint>
#include <filesystem>
#include <memory>
#include <stdexcept>
#include <string_view>

namespace tsbench {

// Native plugins execute code at load time. Callers must independently bind
// the path to a trusted build. This is structural ABI checking, not a sandbox.
class PluginError final : public std::runtime_error {
public:
    PluginError(bmk_status code, const std::string &message);
    bmk_status status() const noexcept { return status_; }
private:
    bmk_status status_;
};

class PluginModule;
using Module = std::shared_ptr<const PluginModule>;

class PluginModule final {
public:
    static Module load(const std::filesystem::path &path, std::string_view expected_id);
    // Diagnostic lane: use the same DSO through its link-time entry, with no dlopen.
    static Module from_linked(const std::filesystem::path &path, std::string_view expected_id,
                              decltype(&bmk_get_plugin) entry);
    ~PluginModule();
    PluginModule(const PluginModule &) = delete;
    PluginModule &operator=(const PluginModule &) = delete;
    const bmk_plugin_v1 &api() const noexcept { return *api_; }
private:
    PluginModule(void *handle, const bmk_plugin_v1 *api) : handle_(handle), api_(api) {}
    void *handle_;
    const bmk_plugin_v1 *api_;
};

// Every owned output pins the producer, but not its creating context. Any
// error that supplies a release callback is also unwound through that callback.
class Blob final {
public:
    ~Blob();
    Blob(const Blob &) = delete;
    Blob &operator=(const Blob &) = delete;
    const bmk_blob &get() const noexcept { return result_; }
private:
    friend class Context;
    explicit Blob(Module module);
    Module module_;
    bmk_blob result_{};
};

class Object final {
public:
    ~Object();
    Object(const Object &) = delete;
    Object &operator=(const Object &) = delete;
    const bmk_object_view &get() const noexcept { return result_.view; }
private:
    friend class Context;
    explicit Object(Module module);
    Module module_;
    bmk_owned_object result_{};
};

class Context final {
public:
    explicit Context(Module module, std::string_view options);
    ~Context();
    Context(const Context &) = delete;
    Context &operator=(const Context &) = delete;
    static std::unique_ptr<Blob> probe(Module module, const bmk_object_view &input, std::string_view request);
    std::unique_ptr<Blob> encode(const bmk_object_view &input);
    std::unique_ptr<Object> decode(const uint8_t *stream, uint64_t size);
    std::unique_ptr<Blob> execution_info();
    void reset(uint32_t kind);
private:
    void check(bmk_status status, const char *operation);
    void require_usable() const;
    Module module_;
    bmk_host_v1 host_{};
    bmk_context *ctx_{};
    bool usable_{true};
};

}
