// SPDX-License-Identifier: MIT
#include "abba_family.hpp"
#include <fstream>
#include <iostream>
#include <iterator>
#include <string>
int main(int argc, char **argv) {
  using namespace abba_family;
  try {
    if (argc == 4 && std::string(argv[1]) == "decode-file") {
      std::ifstream f(argv[2], std::ios::binary);
      if (!f)
        throw std::invalid_argument("cannot open input");
      f.seekg(0, std::ios::end);
      auto size = f.tellg();
      if (size < 0 || size > 268435456)
        throw std::invalid_argument("file size limit");
      f.seekg(0);
      std::vector<std::uint8_t> b(static_cast<std::size_t>(size));
      f.read(reinterpret_cast<char *>(b.data()), size);
      if (!f)
        throw std::invalid_argument("file read");
      auto result = decode(b.data(), b.size());
      std::ofstream out(argv[3]);
      out << result.dump() << '\n';
      if (!out)
        throw std::invalid_argument("file write");
      return 0;
    }
    if (argc == 4 && std::string(argv[1]) == "encode-file") {
      std::ifstream f(argv[2]);
      if (!f)
        throw std::invalid_argument("cannot open input");
      f.seekg(0, std::ios::end);
      auto size = f.tellg();
      if (size < 0 || size > 16777216)
        throw std::invalid_argument("JSON file size limit");
      f.seekg(0);
      std::string text(static_cast<std::size_t>(size), ' ');
      f.read(text.data(), size);
      if (!f)
        throw std::invalid_argument("file read");
      Json r = parse_request(text);
      auto b = encode(r);
      std::ofstream out(argv[3], std::ios::binary);
      out.write(reinterpret_cast<const char *>(b.data()),
                std::streamsize(b.size()));
      if (!out)
        throw std::invalid_argument("file write");
      return 0;
    }
    std::string line;
    while (std::cin.peek() != std::char_traits<char>::eof()) {
      line.clear();
      bool oversized = false;
      char ch;
      while (std::cin.get(ch) && ch != '\n') {
        if (line.size() < 16777216)
          line += ch;
        else
          oversized = true;
      }
      if (oversized) {
        std::cout << "{\"ok\":false,\"error\":\"JSON byte limit\"}\n";
        continue;
      }
      try {
        auto r = execute(parse_request(line));
        std::cout << Json{{"ok", true}, {"result", r}}.dump() << '\n';
      } catch (const std::exception &e) {
        std::cout << Json{{"ok", false}, {"error", e.what()}}.dump() << '\n';
      }
    }
  } catch (const std::exception &e) {
    std::cerr << e.what() << '\n';
    return 1;
  }
}
