"""Deterministic distribution utilities for PR history."""

from collections.abc import Sequence


def median(values: Sequence[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def percentile(values: Sequence[float], probability: float) -> float | None:
    """Linear-interpolated deterministic percentile."""
    if not values:
        return None
    if not 0 <= probability <= 1:
        raise ValueError("probability must be in [0,1]")
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction
