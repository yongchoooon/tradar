"""Scoring utilities placeholder."""


def compute_score(sim_image: float, sim_text: float, sim_class: float, risk: float) -> float:
    """Combine individual similarity signals into a single score."""
    return 0.5 * sim_image + 0.25 * sim_text + 0.15 * sim_class + 0.10 * risk
