/*
Modified version of the C++ code from https://cran.r-project.org/web/packages/Ckmeans.1d.dp/index.html
 */

#include "Ckmeans.1d.dp.h"
#include <algorithm>
#include <cmath>
#include <iostream>
#include <string>
#include <vector>
#include <limits>
#include <stdexcept>

template <class ForwardIterator>
size_t numberOfUnique(ForwardIterator first, ForwardIterator last)
{
  size_t nUnique;

  if (first == last) {
    nUnique = 0;
  } else {
    nUnique = 1;
    for (ForwardIterator itr=first+1; itr!=last; ++itr) {
      if (*itr != *(itr -1)) {
        nUnique ++;
      }
    }
  }
  return nUnique;
}

Output kmeans_1d_dp(std::vector<double> x_v, size_t Kmin, size_t Kmax,
                                  double var, const std::string & method)
{
  const size_t N = x_v.size();
  if(N == 0 || Kmin == 0 || Kmin > Kmax || !std::isfinite(var) || var < 0.0) {
    throw std::invalid_argument("invalid CKmeans input");
  }
  for(const double value : x_v) {
    if(!std::isfinite(value)) {
      throw std::invalid_argument("non-finite CKmeans input");
    }
  }
  const double* x = x_v.data();

  std::vector<int> cluster(N, 0);
  std::vector<double> centres(Kmax, 0.0);
  std::vector<double> withinss(Kmax, 0.0);
  std::vector<double> size(Kmax, 0.0);
  std::vector<double> BIC(Kmax-Kmin+1, 0.0);


  // Input:
  //  x -- an array of double precision numbers, not necessarily sorted
  //  Kmin -- the minimum number of clusters expected
  //  Kmax -- the maximum number of clusters expected
  // NOTE: All vectors in this program is considered starting at position 0.


  // Sort x
  std::vector<size_t> order(N);
  for(size_t i=0; i<order.size(); ++i) {
    order[i] = i;
  }
  bool is_sorted(true);
  for(size_t i=0; i<N-1; ++i) {
    if(x[i] > x[i+1]) {
      is_sorted = false;
      break;
    }
  }
  std::vector<double> x_sorted(x, x+N);
  if(! is_sorted) {
    std::stable_sort(order.begin(), order.end(),
      [&x_v](const size_t i, const size_t j) { return x_v[i] < x_v[j]; });

    for(size_t i=0ul; i<order.size(); ++i) {
      x_sorted[i] = x[order[i]];
    }
  }

  // Find number of unique values
  const size_t nUnique = numberOfUnique(x_sorted.begin(), x_sorted.end());

  // Adjust Kmax according to nUnique
  Kmax = nUnique < Kmax ? nUnique : Kmax;
  Kmin = std::min(nUnique, Kmin);
  size_t Kopt;

  if(nUnique > 1) { // The case when not all elements are equal.

    std::vector< std::vector< double > > S( Kmax, std::vector<double>(N) );
    std::vector< std::vector< size_t > > J( Kmax, std::vector<size_t>(N) );

    fill_dp_matrix(x_sorted, S, J, method);

    // Fill in dynamic programming matrix
    // Choose an optimal number of levels between Kmin and Kmax
    Kopt = select_levels(x_sorted, J, Kmin, Kmax, BIC.data(), var);

    if (Kopt < Kmax) { // Reform the dynamic programming matrix S and J
      J.erase(J.begin() + Kopt, J.end());
    }

    std::vector<int> cluster_sorted(N);

    // Backtrack to find the clusters beginning and ending indices
    backtrack(x_sorted, J, cluster_sorted.data(), centres.data(),
              withinss.data(), size.data());

    for(size_t i = 0; i < N; ++i) {
      // Obtain clustering on data in the original order
      cluster[order[i]] = cluster_sorted[i];
    }

  } else {  // A single cluster that contains all elements
    Kopt = 1;
    for(size_t i=0; i<N; ++i) {
      cluster[i] = 0;
    }
    centres[0] = x[0];
    withinss[0] = 0.0;
    size[0] = N;
  }

  cluster.resize(N);
  centres.resize(Kopt);
  withinss.resize(Kopt);
  size.resize(Kopt);
  BIC.resize(Kmax-Kmin+1);

  return Output(cluster, centres, withinss, size, BIC, Kopt);

}  //end of kmeans_1d_dp()
