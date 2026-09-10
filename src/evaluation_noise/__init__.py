"""Controlled informal-noise and end-to-end evaluation data contracts.

This package is deliberately separate from :mod:`src.geg`.  It may create
controlled evaluation fixtures, but it must never be used to add informal
noise to the formal GEC training corpus.
"""

from .schema import EvaluationValidationError, load_records_bytes, validate_dataset
from .injector import (
    NoiseInjectionError,
    NoiseResourceError,
    NoiseRule,
    build_controlled_row,
    freeze_noise_rules,
    inject_informal_noise,
    load_frozen_noise_rules,
)

__all__ = [
    "EvaluationValidationError",
    "NoiseInjectionError",
    "NoiseResourceError",
    "NoiseRule",
    "build_controlled_row",
    "freeze_noise_rules",
    "inject_informal_noise",
    "load_frozen_noise_rules",
    "load_records_bytes",
    "validate_dataset",
]
