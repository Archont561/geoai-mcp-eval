"""Unit tests for ``experiment.analysis.dataset``."""

from __future__ import annotations

from pathlib import Path

import pandera.errors
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from experiment.analysis import (
    AssertionTableSchema,
    CellSummarySchema,
    MeasurementTableSchema,
    RunDataset,
    validate_predicate_matrix,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
REAL_TASKS = REPO_ROOT / "experiment" / "tasks"


@settings(
    max_examples=25, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@given(
    success=st.one_of(
        st.integers(min_value=-100, max_value=-1), st.integers(min_value=2, max_value=100)
    ),
    score=st.floats(min_value=1.01, max_value=10, allow_nan=False, allow_infinity=False),
    trials=st.integers(min_value=-100, max_value=0),
    tier=st.text(alphabet="xyz", min_size=1, max_size=10),
)
def test_pandera_schemas_reject_invalid_values(
    packed_pilot_zip: Path, success: int, score: float, trials: int, tier: str
) -> None:
    with RunDataset.from_zip(packed_pilot_zip) as dataset:
        meas = dataset.measurements_df()
        bad_meas = meas.copy()
        bad_meas.loc[0, "task_success"] = success
        with pytest.raises(pandera.errors.SchemaError):
            MeasurementTableSchema.validate(bad_meas)

        bad_score = meas.copy()
        bad_score.loc[0, "predicate_score"] = score
        with pytest.raises(pandera.errors.SchemaError):
            MeasurementTableSchema.validate(bad_score)

        preds = dataset.predicates_df(REAL_TASKS)
        bad_preds = preds.copy()
        bad_preds["touches"] = bad_preds["touches"].astype(float)
        bad_preds.loc[0, "touches"] = float("nan")
        pred_cols = [c for c in preds.columns if c not in preds.columns[:6]]
        with pytest.raises((pandera.errors.SchemaError, pandera.errors.SchemaErrors)):
            validate_predicate_matrix(bad_preds, pred_cols)

        summary = dataset.cell_summary_df()
        bad_summary = summary.copy()
        bad_summary.loc[0, "n_trials"] = trials
        with pytest.raises(pandera.errors.SchemaError):
            CellSummarySchema.validate(bad_summary)

        asserts = dataset.assertions_df(REAL_TASKS)
        bad_asserts = asserts.copy()
        bad_asserts.loc[0, "tier"] = tier
        with pytest.raises(pandera.errors.SchemaError):
            AssertionTableSchema.validate(bad_asserts)
