"""Regression coverage for pipeline destination collision validation."""

from itertools import combinations

import pytest

from scripts.build_eligibility import build_report
from scripts.build_pilot import build_pilot
from scripts.split_base import split_parquet


def _destination_matrix(output_names, input_names):
    return [
        *combinations(output_names, 2),
        *[(output, input_name) for output in output_names for input_name in input_names],
    ]


def _paths(tmp_path, names):
    return {name: tmp_path / f"missing-{name}" for name in names}


def _collision_outputs(paths, output_names, first, second):
    outputs = {name: paths[name] for name in output_names}
    outputs[first] = paths[second]
    return outputs


def _assert_outputs_absent(outputs):
    assert all(not path.exists() for path in outputs.values())


@pytest.mark.parametrize(
    "first,second",
    _destination_matrix(("output", "report"), ("config", "quality_manifest")),
)
def test_split_parquet_rejects_destination_aliases_before_reading_missing_input(
    tmp_path, first, second
):
    paths = _paths(tmp_path, ("input", "output", "report", "config", "quality_manifest"))
    outputs = _collision_outputs(paths, ("output", "report"), first, second)

    with pytest.raises(ValueError, match="aliases"):
        split_parquet(
            paths["input"],
            outputs["output"],
            outputs["report"],
            paths["config"],
            quality_manifest=paths["quality_manifest"],
        )

    _assert_outputs_absent(outputs)


@pytest.mark.parametrize(
    "first,second",
    _destination_matrix(("json_report", "markdown_report"), ("config", "split_report")),
)
def test_build_report_rejects_destination_aliases_before_reading_missing_input(
    tmp_path, first, second
):
    paths = _paths(tmp_path, ("input", "json_report", "markdown_report", "config", "split_report"))
    outputs = _collision_outputs(paths, ("json_report", "markdown_report"), first, second)

    with pytest.raises(ValueError, match="aliases"):
        build_report(
            paths["input"],
            outputs["json_report"],
            outputs["markdown_report"],
            paths["config"],
            paths["split_report"],
        )

    _assert_outputs_absent(outputs)


@pytest.mark.parametrize(
    "first,second",
    _destination_matrix(
        ("output", "json_report", "markdown_report", "review_sample"),
        ("config", "capacity_report"),
    ),
)
def test_build_pilot_rejects_destination_aliases_before_reading_missing_input(
    tmp_path, first, second
):
    paths = _paths(
        tmp_path,
        ("input", "capacity_report", "output", "json_report", "markdown_report", "review_sample", "config"),
    )
    outputs = _collision_outputs(
        paths,
        ("output", "json_report", "markdown_report", "review_sample"),
        first,
        second,
    )

    with pytest.raises(ValueError, match="aliases"):
        build_pilot(
            paths["input"],
            paths["capacity_report"],
            outputs["output"],
            outputs["json_report"],
            outputs["markdown_report"],
            outputs["review_sample"],
            config_path=paths["config"],
        )

    _assert_outputs_absent(outputs)
