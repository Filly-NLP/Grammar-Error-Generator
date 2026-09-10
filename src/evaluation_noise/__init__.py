"""Controlled informal-noise and end-to-end evaluation data contracts.

This package is deliberately separate from :mod:`src.geg`.  It may create
controlled evaluation fixtures, but it must never be used to add informal
noise to the formal GEC training corpus.
"""

from .schema import EvaluationValidationError, load_records_bytes, validate_dataset

__all__ = ["EvaluationValidationError", "load_records_bytes", "validate_dataset"]
