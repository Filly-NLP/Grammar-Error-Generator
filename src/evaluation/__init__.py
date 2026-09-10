"""Dependency-injected FILLY end-to-end evaluation and metrics."""

from .artifacts import PredictionArtifact, load_prediction_artifact, write_prediction_artifact
from .metrics import evaluate_predictions, mcnemar_exact, paired_bootstrap_delta, per_tag_metrics
from .routing import CONDITIONS, route_samples
from .validation import validate_prediction_bundle

__all__ = [
    "CONDITIONS",
    "PredictionArtifact",
    "evaluate_predictions",
    "load_prediction_artifact",
    "mcnemar_exact",
    "paired_bootstrap_delta",
    "per_tag_metrics",
    "route_samples",
    "write_prediction_artifact",
    "validate_prediction_bundle",
]
