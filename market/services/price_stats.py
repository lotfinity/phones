"""Multiple averaging methods for price analysis.

Provides different statistical approaches to handle outlier prices:
- median: Basic median (current approach)
- iqr_median: Median after removing outliers outside Q1-1.5*IQR to Q3+1.5*IQR
- trimmed_mean: Mean after removing top/bottom 20% of values
- winsorized_mean: Mean with extreme values capped at 10th/90th percentiles
"""
import statistics
from decimal import Decimal
from typing import List, Optional


def median(values: List[float]) -> Optional[float]:
    """Basic median."""
    if not values:
        return None
    return statistics.median(values)


def iqr_filtered_median(values: List[float]) -> Optional[float]:
    """Median after removing outliers using IQR method.
    
    Removes values outside Q1 - 1.5*IQR to Q3 + 1.5*IQR.
    Falls back to basic median if filtered set is empty.
    """
    if not values:
        return None
    
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    
    if n < 4:
        return statistics.median(sorted_vals)
    
    q1_idx = n // 4
    q3_idx = (3 * n) // 4
    q1 = float(sorted_vals[q1_idx])
    q3 = float(sorted_vals[q3_idx])
    iqr = q3 - q1
    
    lower_fence = q1 - 1.5 * iqr
    upper_fence = q3 + 1.5 * iqr
    
    filtered = [v for v in sorted_vals if lower_fence <= float(v) <= upper_fence]
    
    return statistics.median(filtered) if filtered else statistics.median(sorted_vals)


def trimmed_mean(values: List[float], trim_pct: float = 0.2) -> Optional[float]:
    """Mean after removing top/bottom trim_pct of values.
    
    Default trim_pct=0.2 removes 20% from each end.
    Falls back to basic mean if too few values remain.
    """
    if not values:
        return None
    
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    
    if n < 5:
        return statistics.mean([float(v) for v in sorted_vals])
    
    trim_count = max(1, int(n * trim_pct))
    trimmed = sorted_vals[trim_count:-trim_count] if trim_count < n // 2 else sorted_vals
    
    return statistics.mean([float(v) for v in trimmed]) if trimmed else statistics.mean([float(v) for v in sorted_vals])


def winsorized_mean(values: List[float], lower_pct: float = 0.1, upper_pct: float = 0.9) -> Optional[float]:
    """Mean with values capped at percentile boundaries.
    
    Values below lower_pct percentile are set to that percentile value.
    Values above upper_pct percentile are set to that percentile value.
    """
    if not values:
        return None
    
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    
    if n < 3:
        return statistics.mean([float(v) for v in sorted_vals])
    
    lower_idx = max(0, int(n * lower_pct))
    upper_idx = min(n - 1, int(n * upper_pct))
    
    lower_bound = float(sorted_vals[lower_idx])
    upper_bound = float(sorted_vals[upper_idx])
    
    winsorized = [
        max(lower_bound, min(upper_bound, float(v)))
        for v in sorted_vals
    ]
    
    return statistics.mean(winsorized)


def compute_all_averages(values: List[float]) -> dict:
    """Compute all averaging methods and return as dictionary.
    
    Returns dict with keys: median, iqr_median, trimmed_mean, winsorized_mean
    """
    return {
        "median": median(values),
        "iqr_median": iqr_filtered_median(values),
        "trimmed_mean": trimmed_mean(values),
        "winsorized_mean": winsorized_mean(values),
    }


def compute_all_averages_decimal(values: List[Decimal]) -> dict:
    """Compute all averaging methods for Decimal values.
    
    Returns dict with Decimal values for database storage.
    """
    float_values = [float(v) for v in values if v is not None]
    results = compute_all_averages(float_values)
    return {k: Decimal(str(v)) if v is not None else None for k, v in results.items()}
