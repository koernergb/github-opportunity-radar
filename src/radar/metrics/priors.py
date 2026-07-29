"""Bayesian shrinkage helpers for sparse repository history."""


def shrunk_rate(
    *,
    successes: int,
    sample_size: int,
    global_prior: float,
    prior_strength: float,
) -> float:
    """Return a beta-binomial-style weighted rate."""
    if sample_size < 0 or successes < 0 or successes > sample_size:
        raise ValueError("successes and sample_size must describe a valid count")
    if not 0 <= global_prior <= 1 or prior_strength <= 0:
        raise ValueError("prior must be [0,1] and strength must be positive")
    return (successes + prior_strength * global_prior) / (sample_size + prior_strength)
