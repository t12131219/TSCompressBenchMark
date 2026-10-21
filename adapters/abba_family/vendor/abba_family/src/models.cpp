// SPDX-License-Identifier: MIT AND BSD-3-Clause
#include "Ckmeans.1d.dp.h"
#include "internal.hpp"
#include <algorithm>
#include <cstring>
#include <numeric>
#include <set>
#include <thread>
#include <unordered_map>
namespace abba_family {
namespace {
std::string utf8(unsigned cp) {
  require(cp <= 0x10ffff && !(cp >= 0xd800 && cp <= 0xdfff),
          "invalid alphabet codepoint");
  std::string s;
  if (cp < 128)
    s += char(cp);
  else if (cp < 2048) {
    s += char(192 | (cp >> 6));
    s += char(128 | (cp & 63));
  } else if (cp < 65536) {
    s += char(224 | (cp >> 12));
    s += char(128 | ((cp >> 6) & 63));
    s += char(128 | (cp & 63));
  } else {
    s += char(240 | (cp >> 18));
    s += char(128 | ((cp >> 12) & 63));
    s += char(128 | ((cp >> 6) & 63));
    s += char(128 | (cp & 63));
  }
  return s;
}
void validate_config(const Json &c, const std::string &a) {
  require(c.is_object(), "configuration object");
  std::set<std::string> keys;
  if (a == "abba")
    keys = {"tol",  "scl",  "min_k",    "max_k",    "max_len",  "verbose",
            "seed", "norm", "c_method", "weighted", "symmetric"};
  else if (a == "fabba")
    keys = {"tol",       "alpha",          "sorting",     "scl",
            "verbose",   "max_len",        "return_list", "n_jobs",
            "partition", "partition_rate", "fillna",      "source_backend"};
  else if (a == "qabba")
    keys = {"tol",
            "n_symbols",
            "alpha",
            "digitizer",
            "sorting",
            "sample_rate",
            "scale_length",
            "bits_for_len",
            "bits_for_inc",
            "max_len",
            "max_iter",
            "symbol_codec",
            "include_symbol_model",
            "fill_value",
            "alphabet",
            "n_jobs",
            "random_state",
            "verbose"};
  else
    throw std::invalid_argument("algorithm");
  if (c.contains("source_backend"))
    require(c.value("source_backend", std::string()) == "python" ||
                c.value("source_backend", std::string()) == "cython",
            "source backend");
  for (auto it = c.begin(); it != c.end(); ++it)
    require(keys.count(it.key()) != 0, "unknown parameter");
  if (a == "abba" && c.contains("tol") && c["tol"].is_array()) {
    require(c["tol"].size() == 1 || c["tol"].size() == 2,
            "ABBA tolerance shape");
    for (auto &t : c["tol"])
      require(t.is_number() && std::isfinite(t.get<double>()) &&
                  t.get<double>() >= 0,
              "ABBA tolerance");
  }
  if (a == "abba")
    require(c.value("norm", 2) == 1 || c.value("norm", 2) == 2, "ABBA norm");
  for (auto name :
       {"seed", "weighted", "symmetric", "return_list", "include_symbol_model"})
    if (c.contains(name))
      require(c[name].is_boolean(), "boolean parameter required");
  if (a == "qabba") {
    require(number(c, "tol", .2) > 0, "QABBA tol must be positive");
    if (c.contains("alpha") && !c["alpha"].is_null())
      require(number(c, "alpha", .5) > 0, "QABBA alpha");
    require(integer(c, "n_symbols", 2, MAX_CENTERS) > 0 &&
                integer(c, "max_iter", 100, 10000) > 0,
            "QABBA cluster parameters");
    double rate = number(c, "sample_rate", .5);
    require(rate > 0 && rate <= 1, "sample rate");
  }
}
std::size_t nchars(const std::string &s) {
  std::size_t n = 0;
  for (auto c : s)
    if ((static_cast<unsigned char>(c) & 192) != 128)
      ++n;
  return n;
}
std::size_t workers(const Json &c) { return job_count(c); }
Points model_centers(const Json &m) {
  if (m.at("algorithm").get_ref<const std::string &>() == "qabba") {
    auto x = dequantize(m.at("quantizers").at(0)),
         y = dequantize(m.at("quantizers").at(1));
    require(x.size() == y.size() && !x.empty() && x.size() <= MAX_CENTERS,
            "quantizer codebook shape");
    Points p;
    for (std::size_t i = 0; i < x.size(); ++i) {
      require(x[i] >= 1 - 1e-9, "invalid dequantized length");
      p.push_back({x[i], y[i]});
    }
    return p;
  }
  auto j = m.at("centers");
  require(j.is_array() && !j.empty() && j.size() <= MAX_CENTERS,
          "center count");
  Points out;
  for (auto &row : j) {
    require(row.is_array() && row.size() == 2, "center shape");
    double length = row[0], increment = row[1];
    require(std::isfinite(length) && length > 0 && std::isfinite(increment),
            "invalid model center");
    out.push_back({length, increment});
  }
  return out;
}
void validate_model(const Json &m) {
  require(m.is_object() && m.value("version", 0) == 1, "model version");
  auto a = m.at("algorithm").get<std::string>();
  require(a == "abba" || a == "fabba" || a == "qabba", "model algorithm");
  auto p = model_centers(m);
  auto alphabet = m.at("alphabet");
  require(alphabet.is_array() && alphabet.size() == p.size(),
          "model alphabet size");
  for (auto &s : alphabet)
    require(s.is_string(), "model alphabet type");
}
} // namespace
Json alphabet(std::size_t n, const Json &setting, const std::string &a) {
  require(n >= 1 && n <= MAX_CENTERS, "alphabet size");
  Json out = Json::array();
  if (a == "abba") {
    for (std::size_t i = 0; i < n; ++i)
      out.push_back(utf8(unsigned(i + 97)));
    return out;
  }
  if (setting.is_array()) {
    if (a == "fabba") {
      require(setting.size() >= n, "custom alphabet too short");
      std::set<std::string> seen;
      for (auto &s : setting) {
        auto z = s.get<std::string>();
        require(nchars(z) == 1 && seen.insert(z).second,
                "custom alphabet must be unique characters");
      }
    }
    if (setting.size() >= n) {
      for (std::size_t i = 0; i < n; ++i)
        out.push_back(setting[i].get<std::string>());
      return out;
    }
  }
  std::string base = "AaBbCcDdEeFfGgHhIiJjKkLlMmNnOoPpQqRrSsTtUuVvWwXxYyZz";
  if (a == "fabba") {
    double builtin = setting.is_boolean()
                         ? (setting.get<bool>() ? 1. : 0.)
                         : (setting.is_number() ? setting.get<double>() : 2.);
    if (builtin == 1)
      base = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz";
    else if (builtin != 0)
      base = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ";
  }
  for (std::size_t i = 0; i < n; ++i)
    out.push_back((n > base.size() ||
                   (a == "qabba" && setting.is_array() && setting.size() < n))
                      ? utf8(unsigned(i + 33))
                      : std::string(1, base[i]));
  return out;
}
Json symbolic(const Ids &labels, const Json &alphabet) {
  Json out = Json::array();
  for (auto i : labels) {
    require(i < alphabet.size(), "symbol index");
    out.push_back(alphabet[i]);
  }
  return out;
}
Ids symbol_ids(const Json &input, const Json &alph) {
  Json symbols = input;
  if (input.is_string()) {
    symbols = Json::array();
    auto s = input.get<std::string>();
    for (std::size_t i = 0; i < s.size();) {
      std::size_t end = i + 1;
      while (end < s.size() &&
             (static_cast<unsigned char>(s[end]) & 192) == 128)
        ++end;
      symbols.push_back(s.substr(i, end - i));
      i = end;
    }
  }
  require(symbols.is_array() && symbols.size() <= MAX_SAMPLES, "symbol array");
  require(alph.is_array() && !alph.empty() && alph.size() <= MAX_CENTERS,
          "alphabet limits");
  std::unordered_map<std::string, std::size_t> lookup;
  for (std::size_t i = 0; i < alph.size(); ++i)
    lookup.emplace(alph[i].get<std::string>(), i);
  Ids out;
  for (auto &s : symbols) {
    auto it = lookup.find(s.get_ref<const std::string &>());
    require(it != lookup.end(), "unknown symbol");
    out.push_back(it->second);
  }
  return out;
}
Json inverse(const Json &model, const Json &symbols, const Json &starts) {
  validate_model(model);
  auto a = model.at("algorithm").get<std::string>();
  auto centers = model_centers(model);
  Json sequences = Json::array();
  bool single =
      symbols.is_string() || symbols.empty() || symbols[0].is_string();
  if (single)
    sequences.push_back(symbols);
  else
    sequences = symbols;
  require(sequences.is_array() && sequences.size() <= 4096,
          "inverse series limit");
  Json init = starts;
  if (init.is_null())
    init = model.at("starts");
  if (init.is_number())
    init = make_array(init);
  require(init.is_array() && init.size() == sequences.size(),
          "one start per sequence");
  Json result = Json::array();
  std::size_t total = 0;
  for (std::size_t i = 0; i < sequences.size(); ++i) {
    Ids ids = symbol_ids(sequences[i], model.at("alphabet"));
    require(a == "fabba" || !ids.empty(), "empty ABBA/QABBA symbol sequence");
    Points p;
    for (auto id : ids)
      p.push_back(centers[id]);
    auto aligned = grid(p, a);
    auto x = reconstruct(aligned, init[i].get<double>(), a);
    total += x.size();
    require(total <= MAX_OUTPUT, "total reconstruction limit");
    result.push_back(x);
  }
  return single ? result[0] : result;
}
Json model_transform(const Json &model, const Json &input) {
  validate_model(model);
  require(model.at("algorithm").get_ref<const std::string &>() == "qabba",
          "frozen model transform belongs to QABBA");
  bool single;
  auto series = collection(input, single);
  auto c = model.at("config");
  auto centers = model_centers(model);
  std::vector<Json> out(series.size());
  parallel(series.size(), workers(c), [&](std::size_t i) {
    auto clean = fill(series[i], c.value("fill_value", "ffill"), true);
    auto p = first2(compression(clean, c, "qabba"));
    Ids ids;
    for (auto v : p) {
      std::size_t best = 0;
      double d = dist(v, centers[0]);
      for (std::size_t j = 1; j < centers.size(); ++j) {
        double z = dist(v, centers[j]);
        if (z < d) {
          d = z;
          best = j;
        }
      }
      ids.push_back(best);
    }
    out[i] = symbolic(ids, model.at("alphabet"));
  });
  return single ? out[0] : Json(out);
}
Json fit(const Json &r) {
  std::string a = r.at("algorithm");
  require(a == "abba" || a == "fabba" || a == "qabba", "unknown algorithm");
  Json c = r.value("config", Json::object());
  validate_config(c, a);
  bool single;
  auto input = r.at("values");
  if (a == "fabba" && input.is_array() && !input.empty() &&
      input[0].is_array()) {
    if (input.size() == 1)
      input = input[0];
    else {
      bool column = true;
      for (auto &row : input)
        column = column && row.is_array() && row.size() == 1;
      if (column) {
        Json flattened = Json::array();
        for (auto &row : input)
          flattened.push_back(row[0]);
        input = std::move(flattened);
      }
    }
  }
  auto series = collection(input, single);
  require(a == "qabba" || single,
          "ABBA/fABBA require a single univariate input");
  std::vector<Pieces> pieces(series.size());
  std::vector<V> clean(series.size());
  std::vector<double> starts(series.size());
  parallel(series.size(), a == "qabba" ? workers(c) : 1, [&](std::size_t i) {
    clean[i] =
        a == "abba"
            ? series[i]
            : fill(series[i],
                   r.value("fill", c.value("fill_value",
                                           a == "fabba" ? "bfill" : "ffill")),
                   a == "qabba");
    starts[i] = a == "qabba" ? series[i][0] : clean[i][0];
    require(std::isfinite(starts[i]), "nonfinite original QABBA initial value");
    pieces[i] = compression(clean[i], c, a);
  });
  Points all;
  for (auto &p : pieces) {
    auto z = first2(p);
    all.insert(all.end(), z.begin(), z.end());
  }
  Cluster cl = a == "abba" ? abba_digitize(all, c)
                           : (a == "fabba" ? fabba_digitize(all, c)
                                           : qabba_digitize(all, c));
  Json model = [&]() {
    Json result_object = Json::object();
    result_object["version"] = 1;
    result_object["algorithm"] = a;
    result_object["config"] = c;
    result_object["starts"] = starts;
    result_object["single"] = single;
    return result_object;
  }();
  auto setting =
      r.value("alphabet", a == "qabba" ? c.value("alphabet", Json()) : Json(0));
  auto alph = alphabet(cl.centers.size(), setting, a);
  model["alphabet"] = alph;
  Json out;
  out["centers"] = cl.centers;
  if (a == "qabba") {
    V len, inc;
    for (auto z : cl.centers) {
      len.push_back(z[0]);
      inc.push_back(z[1]);
    }
    auto ql = quantizer(len, int(integer(c, "bits_for_len", 8, 64))),
         qi = quantizer(inc, int(integer(c, "bits_for_inc", 16, 64)));
    model["quantizers"] = make_array(ql, qi);
    Points quant;
    for (std::size_t i = 0; i < len.size(); ++i)
      quant.push_back(
          {ql["values"][i].get<double>(), qi["values"][i].get<double>()});
    out["quantized_centers"] = quant;
    out["quantizers"] = make_array(make_array(ql["scale"], ql["zero"]),
                                   make_array(qi["scale"], qi["zero"]));
    out["centers"] = model_centers(model);
    // Preserve the selected upstream's frequency-remapped symbols without
    // reordering its center rows. This source behavior is intentionally visible
    // in differential.
    Ids count(cl.centers.size()), first(cl.centers.size(), all.size()),
        order(count.size());
    for (std::size_t i = 0; i < cl.labels.size(); ++i) {
      ++count[cl.labels[i]];
      first[cl.labels[i]] = std::min(first[cl.labels[i]], i);
    }
    std::iota(order.begin(), order.end(), 0);
    std::sort(order.begin(), order.end(), [&](auto x, auto y) {
      return count[x] == count[y] ? first[x] < first[y] : count[x] > count[y];
    });
    Ids map(order.size());
    for (std::size_t i = 0; i < order.size(); ++i)
      map[order[i]] = i;
    for (auto &label : cl.labels)
      label = map[label];
  } else
    model["centers"] = cl.centers;
  Json sequences = Json::array();
  std::size_t offset = 0;
  for (auto &p : pieces) {
    Ids ids(cl.labels.begin() + std::ptrdiff_t(offset),
            cl.labels.begin() + std::ptrdiff_t(offset + p.size()));
    sequences.push_back(symbolic(ids, alph));
    offset += p.size();
  }
  model["symbols"] = single ? sequences[0] : sequences;
  model["sample_counts"] = Json::array();
  for (auto &row : series)
    model["sample_counts"].push_back(row.size());
  out["model"] = model;
  out["symbols"] = model["symbols"];
  out["alphabet"] = alph;
  out["pieces"] = a == "qabba" ? Json(pieces) : Json(pieces[0]);
  out["reconstructed"] = inverse(model, model["symbols"], starts);
  if (a == "fabba")
    out["splist"] = cl.splist;
  if (a == "qabba") {
    out["transformed"] = model_transform(model, r.at("values"));
    auto stats =
        symbol_stats(model["symbols"], alph, c.value("symbol_codec", "none"),
                     c.value("include_symbol_model", true));
    out["symbol_stats"] = stats;
    std::size_t samples = 0;
    for (auto &row : series)
      samples += row.size();
    auto symbolbits = stats.at("total_bits").get<std::uint64_t>();
    auto centerbits = cl.centers.size() * (integer(c, "bits_for_len", 8, 64) +
                                           integer(c, "bits_for_inc", 16, 64));
    auto initialbits = series.size() * 32;
    auto total = symbolbits + centerbits + initialbits + 128;
    out["storage"] = [&]() {
      Json result_object = Json::object();
      result_object["total_bits"] = total;
      result_object["symbol_bits"] = symbolbits;
      result_object["center_bits"] = centerbits;
      result_object["initial_bits"] = initialbits;
      result_object["quantizer_bits"] = 128;
      result_object["raw_bits"] = samples * 32;
      result_object["storage_ratio"] = double(total) / double(samples * 32);
      result_object["compression_factor"] =
          double(samples * 32) / double(total);
      return result_object;
    }();
  }
  return out;
}
Json execute(const Json &r) {
  require(r.is_object(), "request object");
  std::string op = r.value("operation", "fit");
  if (op == "input_bits") {
    auto x = values(r.at("values"));
    std::vector<std::uint8_t> bytes;
    for (double d : x) {
      std::uint64_t u;
      std::memcpy(&u, &d, 8);
      for (unsigned i = 0; i < 8; ++i)
        bytes.push_back(std::uint8_t(u >> (8 * i)));
    }
    return [&]() {
      Json result_object = Json::object();
      result_object["binary64_le_hex"] = hex(bytes);
      return result_object;
    }();
  }
  if (op == "argsort")
    return [&]() {
      Json result_object = Json::object();
      result_object["indices"] = argsort(values(r.at("values")));
      return result_object;
    }();
  if (op == "fit")
    return fit(r);
  if (op == "image_fit")
    return image_fit(r);
  if (op == "image_inverse")
    return [&]() {
      Json result_object = Json::object();
      result_object["image"] = image_restore(
          r.at("model"),
          inverse(r.at("model"),
                  (r.contains("symbols") ? r.at("symbols")
                                         : r.at("model").at("symbols")),
                  r.value("starts", Json())));
      return result_object;
    }();
  if (op == "native_ckmeans") {
    auto v = values(r.at("values"));
    auto c = r.value("config", Json::object());
    auto min = integer(c, "min_k", 1, MAX_CENTERS),
         max = integer(c, "max_k", 100, MAX_CENTERS);
    auto method = c.value("method", "linear");
    require(min >= 1 && min <= max && !v.empty() &&
                (method == "linear" || method == "loglinear" ||
                 method == "quadratic"),
            "native CKmeans config");
    auto o = kmeans_1d_dp(v, min, max, number(c, "variance", .1), method);
    return [&]() {
      Json result_object = Json::object();
      result_object["labels"] = o.cluster;
      result_object["centers"] = o.centres;
      result_object["k"] = o.Kopt;
      return result_object;
    }();
  }
  if (op == "encode") {
    auto bytes = encode(r);
    return [&]() {
      Json result_object = Json::object();
      result_object["container_hex"] = hex(bytes);
      result_object["physical_bytes"] = bytes.size();
      result_object["final_bits"] = bytes.size() * 8;
      result_object["external_side_information_bits"] = 0;
      return result_object;
    }();
  }
  if (op == "decode") {
    auto bytes = unhex(r.at("container_hex"));
    return decode(bytes.data(), bytes.size());
  }
  if (op == "inverse") {
    auto &m = r.at("model");
    return [&]() {
      Json result_object = Json::object();
      result_object["reconstructed"] = inverse(
          m, (r.contains("symbols") ? r.at("symbols") : m.at("symbols")),
          r.value("starts", Json()));
      return result_object;
    }();
  }
  if (op == "transform")
    return [&]() {
      Json result_object = Json::object();
      result_object["symbols"] = model_transform(r.at("model"), r.at("values"));
      return result_object;
    }();
  std::string a = r.at("algorithm");
  require(a == "abba" || a == "fabba" || a == "qabba", "unknown algorithm");
  Json c = r.value("config", Json::object());
  validate_config(c, a);
  if (op == "compress") {
    auto v = values(r.at("values"), a != "abba");
    if (a != "abba")
      v = fill(v,
               r.value("fill",
                       c.value("fill_value", a == "fabba" ? "bfill" : "ffill")),
               a == "qabba");
    return [&]() {
      Json result_object = Json::object();
      result_object["pieces"] = compression(v, c, a);
      return result_object;
    }();
  }
  if (op == "digitize") {
    auto p = points(r.at("pieces"));
    auto cl = a == "abba" ? abba_digitize(p, c)
                          : (a == "fabba" ? fabba_digitize(p, c)
                                          : qabba_digitize(p, c));
    if (a == "qabba")
      return [&]() {
        Json result_object = Json::object();
        result_object["labels"] = cl.labels;
        result_object["centers"] = cl.centers;
        return result_object;
      }();
    auto alph = alphabet(cl.centers.size(), r.value("alphabet", Json(0)), a);
    Json out = [&]() {
      Json result_object = Json::object();
      result_object["symbols"] = symbolic(cl.labels, alph);
      result_object["centers"] = cl.centers;
      return result_object;
    }();
    if (a == "fabba") {
      out["alphabet"] = alph;
      out["splist"] = cl.splist;
    }
    return out;
  }
  if (op == "quantize")
    return [&]() {
      Json result_object = Json::object();
      result_object["pieces"] = grid(points(r.at("pieces")), a);
      return result_object;
    }();
  if (op == "symbol_stats")
    return symbol_stats(r.at("symbols"), r.at("alphabet"),
                        c.value("symbol_codec", "none"),
                        c.value("include_symbol_model", true));
  throw std::invalid_argument("unknown operation");
}
} // namespace abba_family
