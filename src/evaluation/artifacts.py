"""Prediction-artifact schema and deterministic JSONL I/O."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping


CONDITION_NAMES = {
    "A": "raw_to_gec",
    "B": "raw_to_normalizer_to_gec",
    "C": "oracle_normalized_to_gec",
    "raw_to_gec": "raw_to_gec",
    "raw_to_normalizer_to_gec": "raw_to_normalizer_to_gec",
    "oracle_normalized_to_gec": "oracle_normalized_to_gec",
}


@dataclass(frozen=True)
class PredictionArtifact:
    sample_id: str
    condition: str
    raw_input: str
    normalizer_output: str | None
    gec_input: str
    gec_output: str
    predicted_tags: tuple[str, ...] | None = None
    predicted_edits: tuple[dict[str, Any], ...] | None = None
    model_version: str = "dependency_injected"
    evaluation_mode: str = "dependency_injected"
    frozen_evaluation_sha256: str | None = None
    normalizer_version: str | None = None
    gec_version: str | None = None
    predicted_edits_coordinate_space: str = "gec_input"

    def __post_init__(self) -> None:
        if not self.sample_id:
            raise ValueError("prediction sample_id must be non-empty")
        if self.condition not in CONDITION_NAMES:
            raise ValueError(f"unknown prediction condition: {self.condition}")
        if not isinstance(self.raw_input, str):
            raise ValueError("prediction raw_input must be a string")
        if self.normalizer_output is not None and not isinstance(self.normalizer_output, str):
            raise ValueError("prediction normalizer_output must be a string or null")
        if not isinstance(self.gec_input, str) or not isinstance(self.gec_output, str):
            raise ValueError("prediction GEC input/output must be strings")
        if self.predicted_tags is not None and not all(isinstance(tag, str) for tag in self.predicted_tags):
            raise ValueError("predicted_tags must contain strings")
        if self.predicted_edits is not None and not all(isinstance(edit, Mapping) for edit in self.predicted_edits):
            raise ValueError("predicted_edits must contain objects")

    @property
    def canonical_condition(self) -> str:
        return CONDITION_NAMES[self.condition]

    def as_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["predicted_tags"] = list(self.predicted_tags) if self.predicted_tags is not None else None
        result["predicted_edits"] = list(self.predicted_edits) if self.predicted_edits is not None else None
        result["condition"] = self.canonical_condition
        return result


def _row_to_artifact(row: Mapping[str, Any]) -> PredictionArtifact:
    tags = row.get("predicted_tags")
    if tags is not None:
        if not isinstance(tags, (list, tuple)):
            raise ValueError("prediction predicted_tags must be a list")
        tags = tuple(str(tag) for tag in tags)
    edits = row.get("predicted_edits")
    if edits is not None:
        if not isinstance(edits, (list, tuple)):
            raise ValueError("prediction predicted_edits must be a list")
        edits = tuple(dict(edit) for edit in edits)
    artifact = PredictionArtifact(
        sample_id=str(row["sample_id"]),
        condition=str(row["condition"]),
        raw_input=str(row["raw_input"]),
        normalizer_output=None if row["normalizer_output"] is None else str(row["normalizer_output"]),
        gec_input=str(row["gec_input"]),
        gec_output=str(row["gec_output"]),
        predicted_tags=tags,
        predicted_edits=edits,
        model_version=str(row["model_version"]),
        evaluation_mode=str(row.get("evaluation_mode", "dependency_injected")),
        frozen_evaluation_sha256=None if row.get("frozen_evaluation_sha256") is None else str(row["frozen_evaluation_sha256"]),
        normalizer_version=None if row.get("normalizer_version") is None else str(row["normalizer_version"]),
        gec_version=None if row.get("gec_version") is None else str(row["gec_version"]),
        predicted_edits_coordinate_space=str(row.get("predicted_edits_coordinate_space", "gec_input")),
    )
    if not artifact.frozen_evaluation_sha256 or not artifact.normalizer_version or not artifact.gec_version:
        raise ValueError("prediction artifact requires frozen evaluation, normalizer, and GEC bindings")
    return artifact


def write_prediction_artifact(path: Path, predictions: Iterable[PredictionArtifact | Mapping[str, Any]], *, metadata: Mapping[str, Any] | None = None) -> None:
    """Write JSONL predictions atomically without overwriting an existing artifact."""

    # Check the requested leaf before resolving it.  ``Path.resolve()`` follows
    # symlinks and would otherwise make a dangling leaf look like a new path.
    requested_path = Path(path)
    if requested_path.is_symlink():
        raise FileExistsError(f"refusing to overwrite symlink prediction artifact: {requested_path}")
    path = requested_path.parent.resolve() / requested_path.name
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"refusing to overwrite prediction artifact: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            if metadata:
                stream.write(json.dumps({"_metadata": dict(metadata)}, ensure_ascii=False, sort_keys=True) + "\n")
            for item in predictions:
                try:
                    artifact = item if isinstance(item, PredictionArtifact) else _row_to_artifact(item)
                except (KeyError, TypeError, ValueError) as error:
                    raise ValueError(f"invalid prediction row during write: {error}") from error
                if not artifact.model_version or not artifact.frozen_evaluation_sha256 or not artifact.normalizer_version or not artifact.gec_version:
                    raise ValueError("prediction artifact requires frozen evaluation, normalizer, and GEC bindings")
                stream.write(json.dumps(artifact.as_dict(), ensure_ascii=False, sort_keys=True) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        if path.exists() or path.is_symlink():
            raise FileExistsError(f"refusing to overwrite prediction artifact: {path}")
        try:
            os.link(str(temporary_path), str(path))
        except FileExistsError as error:
            raise FileExistsError(f"refusing to overwrite prediction artifact: {path}") from error
        temporary_path.unlink()
        temporary_path = None
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def load_prediction_artifact(path: Path) -> tuple[dict[str, Any], list[PredictionArtifact]]:
    if not path.exists():
        raise FileNotFoundError(path)
    metadata: dict[str, Any] = {}
    rows: list[PredictionArtifact] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        row = json.loads(line)
        if isinstance(row, dict) and "_metadata" in row:
            metadata = dict(row["_metadata"])
            continue
        try:
            rows.append(_row_to_artifact(row))
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(f"invalid prediction row at {path}:{line_number}: {error}") from error
    return metadata, rows
