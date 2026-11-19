#pragma once
#include <iosfwd>
namespace tsbench::trace {
// Exactly one operation per process. The caller must join codec threads before
// closing the operation and reading this collector.
void start(unsigned capacity);
void stop();
void dump(std::ostream &);
}
