#include "Ckmeans.1d.dp.h"

#include <iomanip>
#include <iostream>
#include <limits>
#include <string>
#include <vector>

int main() {
  std::size_t n = 0;
  std::size_t kmin = 0;
  std::size_t kmax = 0;
  double variance_bound = 0.0;
  if (!(std::cin >> n >> kmin >> kmax >> variance_bound) || n == 0 ||
      kmin == 0 || kmin > kmax) {
    std::cerr << "invalid CKmeans oracle request\n";
    return 2;
  }

  std::vector<double> values(n);
  for (double& value : values) {
    if (!(std::cin >> value)) {
      std::cerr << "missing CKmeans oracle value\n";
      return 2;
    }
  }

  try {
    const Output output =
        kmeans_1d_dp(values, kmin, kmax, variance_bound, "linear");
    std::cout << output.Kopt << '\n';
    for (std::size_t i = 0; i < output.cluster.size(); ++i) {
      std::cout << (i == 0 ? "" : " ") << output.cluster[i];
    }
    std::cout << '\n' << std::setprecision(17);
    for (std::size_t i = 0; i < output.centres.size(); ++i) {
      std::cout << (i == 0 ? "" : " ") << output.centres[i];
    }
    std::cout << '\n';
  } catch (const std::string& error) {
    std::cerr << error << '\n';
    return 3;
  } catch (const std::exception& error) {
    std::cerr << error.what() << '\n';
    return 3;
  }
  return 0;
}

