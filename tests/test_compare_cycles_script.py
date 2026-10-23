"""scripts/compare_cycles.py lists cycles by the app's own completeness rule."""

from __future__ import annotations

from alphaswarm.graph.rows import _EFFECTIVE_STATUS
from tests.support.scripts import load_script


def test_compare_cycles_lists_complete_cycles_by_the_shared_status_rule() -> None:
    """A second rule (metrics stamped) would list failed cycles the app hides (docs/DECISIONS.md#adr-cycle-metrics)."""
    query = load_script("compare_cycles").CYCLES_QUERY

    assert f"WHERE {_EFFECTIVE_STATUS} = 'complete'" in query
    assert "metrics_recorded_at" not in query.replace(_EFFECTIVE_STATUS, "")
