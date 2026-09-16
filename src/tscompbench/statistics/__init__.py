"""Read-only Layer-5 statistics over frozen benchmark evidence."""

from .core import descriptive_statistics, pareto_front, rank_values
from .engine import AnalysisBundle, StatisticsError, analyze_run_set

__all__ = [
    "AnalysisBundle",
    "StatisticsError",
    "analyze_run_set",
    "descriptive_statistics",
    "pareto_front",
    "rank_values",
]
