#include "plugin_loader.hpp"

#include <dlfcn.h>
#include <elf.h>
#include <array>
#include <fstream>
#include <utility>

namespace tsbench {
namespace {
using Entry = decltype(&bmk_get_plugin);
struct DlClose { void operator()(void *handle) const noexcept { dlclose(handle); } };
using DlHandle = std::unique_ptr<void, DlClose>;

void check_platform(const std::filesystem::path &path) {
#if defined(__linux__) && defined(__x86_64__) && __BYTE_ORDER__ == __ORDER_LITTLE_ENDIAN__
    static_assert(sizeof(void *) == 8);
    Elf64_Ehdr header{};
    std::ifstream file(path, std::ios::binary);
    if (!file.read(reinterpret_cast<char *>(&header), sizeof(header)) ||
        std::string_view(reinterpret_cast<const char *>(header.e_ident), SELFMAG) != ELFMAG ||
        header.e_ident[EI_CLASS] != ELFCLASS64 || header.e_ident[EI_DATA] != ELFDATA2LSB ||
        header.e_ident[EI_VERSION] != EV_CURRENT || header.e_version != EV_CURRENT ||
        header.e_machine != EM_X86_64 || header.e_type != ET_DYN) {
        throw PluginError(BMK_UNSUPPORTED, "plugin is not a Linux x86-64 ELF shared object");
    }
#else
    (void)path;
    throw PluginError(BMK_UNSUPPORTED, "worker platform is not supported");
#endif
}

const bmk_plugin_v1 *check_entry(const std::filesystem::path &path, std::string_view expected_id,
                                 Entry entry) {
    // dlsym searches dependencies; a linked worker can also be interposed.
    // Both lanes must resolve to the exact staged DSO supplied by the binding.
    Dl_info symbol{};
    if (!dladdr(reinterpret_cast<void *>(entry), &symbol) || !symbol.dli_fname ||
        !std::filesystem::equivalent(path, symbol.dli_fname))
        throw PluginError(BMK_UNSUPPORTED, "entry symbol is owned by a different module");
    const bmk_plugin_v1 *api = entry(BMK_ABI_V1);
    if (!api || api->struct_size < sizeof(bmk_plugin_v1) || api->abi_version != BMK_ABI_V1)
        throw PluginError(BMK_UNSUPPORTED, "ABI negotiation failed");
    if (!api->plugin_id || expected_id != api->plugin_id)
        throw PluginError(BMK_BAD_INPUT, "plugin ID does not match binding");
    if (!api->probe || !api->create || !api->reset || !api->encode || !api->decode ||
        !api->execution_info || !api->error_text || !api->destroy || !api->extension)
        throw PluginError(BMK_UNSUPPORTED, "plugin ABI table has missing callbacks");
    return api;
}

const uint8_t *bytes(std::string_view s) { return reinterpret_cast<const uint8_t *>(s.data()); }

void check_blob(const bmk_blob &b) {
    if (b.struct_size < sizeof(b) || !b.release || b.size > b.capacity || (b.size && !b.data))
        throw PluginError(BMK_INTERNAL, "plugin returned an invalid owned blob");
}
}

PluginError::PluginError(bmk_status code, const std::string &message)
    : std::runtime_error(message), status_(code) {}

Module PluginModule::load(const std::filesystem::path &path, std::string_view expected_id) {
    if (!path.is_absolute() || expected_id.empty() || !std::filesystem::is_regular_file(path))
        throw PluginError(BMK_BAD_INPUT, "plugin loading requires an absolute regular file and an expected ID");
    check_platform(path);
    DlHandle library(dlopen(path.c_str(), RTLD_NOW | RTLD_LOCAL));
    if (!library) {
        const char *error = dlerror();
        throw PluginError(BMK_INTERNAL, std::string("dlopen: ") + (error ? error : "unknown error"));
    }
    auto entry = reinterpret_cast<Entry>(dlsym(library.get(), "bmk_get_plugin"));
    if (!entry) throw PluginError(BMK_UNSUPPORTED, "missing bmk_get_plugin symbol");
    const auto *api = check_entry(path, expected_id, entry);
    // Transfer only after construction (if shared_ptr allocation fails it
    // deletes the object and closes the handle itself).
    auto *loaded = new PluginModule(library.get(), api);
    library.release();
    return Module(loaded);
}
Module PluginModule::from_linked(const std::filesystem::path &path, std::string_view expected_id, Entry entry) {
    if (!path.is_absolute() || expected_id.empty() || !entry || !std::filesystem::is_regular_file(path))
        throw PluginError(BMK_BAD_INPUT, "linked lane requires an absolute bound plugin and an entry");
    check_platform(path);
    return Module(new PluginModule(nullptr, check_entry(path, expected_id, entry)));
}
PluginModule::~PluginModule() { if (handle_) dlclose(handle_); }

Blob::Blob(Module module) : module_(std::move(module)) { result_.struct_size = sizeof(result_); }
Blob::~Blob() { if (result_.release) result_.release(&result_); }
Object::Object(Module module) : module_(std::move(module)) { result_.struct_size = sizeof(result_); }
Object::~Object() { if (result_.release) result_.release(&result_); }

Context::Context(Module module, std::string_view options) : module_(std::move(module)) {
    if (!module_) throw PluginError(BMK_BAD_INPUT, "missing plugin module");
    host_.struct_size = sizeof(host_);
    host_.abi_version = BMK_ABI_V1;
    const auto rc = module_->api().create(&host_, bytes(options), options.size(), &ctx_);
    if (rc != BMK_OK || !ctx_) {
        if (ctx_) module_->api().destroy(ctx_);
        throw PluginError(rc == BMK_OK ? BMK_INTERNAL : rc, "plugin context creation failed");
    }
}
Context::~Context() { module_->api().destroy(ctx_); }

void Context::require_usable() const {
    if (!usable_) throw PluginError(BMK_BAD_INPUT, "failed context cannot be reused; create a new context");
}
void Context::check(bmk_status status, const char *operation) {
    if (status == BMK_OK) return;
    usable_ = false;
    std::array<char, 512> message{};
    const auto rc = module_->api().error_text(ctx_, message.data(), message.size());
    message.back() = '\0';
    throw PluginError(status, std::string(operation) + " failed (" + std::to_string(status) + ")" +
        (rc == BMK_OK && message.front() ? std::string(": ") + message.data() : ""));
}
std::unique_ptr<Blob> Context::probe(Module module, const bmk_object_view &input, std::string_view request) {
    if (!module) throw PluginError(BMK_BAD_INPUT, "missing plugin module");
    auto out = std::unique_ptr<Blob>(new Blob(module));
    const auto rc = module->api().probe(&input, bytes(request), request.size(), &out->result_);
    if (rc != BMK_OK) throw PluginError(rc, "plugin probe rejected input or request");
    check_blob(out->result_);
    return out;
}
std::unique_ptr<Blob> Context::encode(const bmk_object_view &input) {
    require_usable();
    auto out = std::unique_ptr<Blob>(new Blob(module_));
    check(module_->api().encode(ctx_, &input, &out->result_), "encode");
    try { check_blob(out->result_); } catch (...) { usable_ = false; throw; }
    return out;
}
std::unique_ptr<Object> Context::decode(const uint8_t *stream, uint64_t size) {
    require_usable();
    auto out = std::unique_ptr<Object>(new Object(module_));
    check(module_->api().decode(ctx_, stream, size, &out->result_), "decode");
    const auto &r = out->result_;
    if (r.struct_size < sizeof(r) || !r.release || r.view.struct_size < sizeof(r.view) ||
        (r.view.column_count && !r.view.columns) || (r.view.schema_bytes && !r.view.schema_json)) {
        usable_ = false;
        throw PluginError(BMK_INTERNAL, "plugin returned an invalid owned object");
    }
    return out;
}
std::unique_ptr<Blob> Context::execution_info() {
    require_usable();
    auto out = std::unique_ptr<Blob>(new Blob(module_));
    check(module_->api().execution_info(ctx_, &out->result_), "execution_info");
    try { check_blob(out->result_); } catch (...) { usable_ = false; throw; }
    return out;
}
void Context::reset(uint32_t kind) {
    require_usable();
    check(module_->api().reset(ctx_, kind), "reset");
}
}
