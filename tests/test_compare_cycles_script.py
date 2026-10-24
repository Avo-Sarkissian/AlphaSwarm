"""scripts/compare_cycles.py: the shared completeness rule and --group-by with bootstrap intervals."""

from __future__ import annotations

import random
from types import ModuleType
from typing import Any

import pytest

from alphaswarm.graph.rows import _EFFECTIVE_STATUS
from tests.support.scripts import load_script


@pytest.fixture(scope="module")
def cc() -> ModuleType:
    return load_script("compare_cycles")


def _cycle(cycle_id: str, **props: Any) -> dict[str, Any]:
    return {"cycle_id": cycle_id, "worker_model": "alphaswarm-worker", **props}


def test_compare_cycles_lists_complete_cycles_by_the_shared_status_rule(cc: ModuleType) -> None:
    """A second rule (metrics stamped) would list failed cycles the app hides (docs/DECISIONS.md#adr-cycle-metrics)."""
    query = cc.CYCLES_QUERY

    assert f"WHERE {_EFFECTIVE_STATUS} = 'complete'" in query
    assert "metrics_recorded_at" not in query.replace(_EFFECTIVE_STATUS, "")


def test_group_key_reads_missing_and_empty_as_dash(cc: ModuleType) -> None:
    assert cc.group_key({"experiment_tag": "p7"}, ["experiment_tag", "git_sha"]) == ("p7", "-")
    assert cc.group_key({"experiment_tag": ""}, ["experiment_tag"]) == ("-",)


def test_untagged_and_partial_cycles_group_safely(cc: ModuleType) -> None:
    """Legacy cycles, missing metrics and nulls never crash or read as 0."""
    cycles = [
        _cycle("a1", experiment_tag="p7-3-control", r2_flips=10),
        _cycle("a2", experiment_tag="p7-3-control", r2_flips=14),
        _cycle("a3", experiment_tag="p7-3-control"),
        _cycle("a4", experiment_tag="p7-3-control", r2_flips=None),
        _cycle("b1", r2_flips=12),
    ]

    summaries = cc.summarize_groups(
        cycles,
        ["experiment_tag"],
        ["r2_flips", "r2_citation_validity_rate"],
        rng=random.Random(1),
        n_boot=200,
    )

    by_key = {s.key: s for s in summaries}
    assert list(by_key) == [("-",), ("p7-3-control",)]
    tagged = by_key[("p7-3-control",)]
    assert tagged.cycles == 4
    assert (tagged.stats["r2_flips"].n, tagged.stats["r2_flips"].mean) == (2, 12.0)
    ci = tagged.stats["r2_flips"].ci
    assert ci is not None and ci[0] <= 12.0 <= ci[1]
    assert tagged.stats["r2_citation_validity_rate"].mean is None
    assert by_key[("-",)].stats["r2_flips"].mean == 12.0


def test_single_value_group_has_no_interval(cc: ModuleType) -> None:
    summaries = cc.summarize_groups([_cycle("b1", r2_flips=12)], ["experiment_tag"], ["r2_flips"], rng=random.Random(1))
    stat = summaries[0].stats["r2_flips"]

    assert (stat.n, stat.mean, stat.ci) == (1, 12.0, None)
    assert cc.format_stat(stat) == "12.000 [n/a]"
    assert cc.format_stat(cc.MetricStat(n=0, mean=None, ci=None)) == "-"


def test_booleans_and_text_are_not_averaged(cc: ModuleType) -> None:
    cycles = [_cycle("a", git_dirty=True, git_sha="abc"), _cycle("b", git_dirty=False)]

    assert cc.metric_values(cycles, "git_dirty") == []
    assert cc.metric_values(cycles, "git_sha") == []


def test_intervals_are_reproducible_with_the_same_seed(cc: ModuleType) -> None:
    cycles = [_cycle(f"c{i}", experiment_tag="t", r2_flips=float(i)) for i in range(8)]

    first = cc.summarize_groups(cycles, ["experiment_tag"], ["r2_flips"], rng=random.Random(7), n_boot=300)
    again = cc.summarize_groups(cycles, ["experiment_tag"], ["r2_flips"], rng=random.Random(7), n_boot=300)

    assert first == again


def test_two_field_groups_render_as_markdown(cc: ModuleType) -> None:
    cycles = [
        _cycle("a", experiment_tag="arm-a", r2_flips=4),
        _cycle("b", experiment_tag="arm-a", r2_flips=6),
        _cycle("c", experiment_tag="arm-b", worker_model="fictional-cloud-worker", r2_flips=9),
    ]
    fields = ["experiment_tag", "worker_model"]
    summaries = cc.summarize_groups(cycles, fields, ["r2_flips"], rng=random.Random(3), n_boot=200)

    lines = cc.render(cc.group_table(summaries, fields, ["r2_flips"]), markdown=True).splitlines()

    assert lines[0] == "| experiment_tag | worker_model | n | r2_flips |"
    assert lines[1] == "|---|---|---|---|"
    assert lines[2].startswith("| arm-a | alphaswarm-worker | 2 | 5.000 [")
    assert lines[3] == "| arm-b | fictional-cloud-worker | 1 | 9.000 [n/a] |"


def test_plain_table_is_aligned_without_trailing_spaces(cc: ModuleType) -> None:
    text = cc.render([["a", "bb"], ["ccc", "d"]], markdown=False)

    assert text.splitlines() == ["a    bb", "ccc  d"]


class _FakeResult:
    def __init__(self, records: list[dict[str, Any]]) -> None:
        self._records = records

    def data(self) -> list[dict[str, Any]]:
        return self._records


class _FakeSession:
    def __init__(self, records: list[dict[str, Any]] | None = None) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self._records = records if records is not None else [{"c": {"cycle_id": "x"}}]

    def run(self, query: str, **params: Any) -> _FakeResult:
        self.calls.append((query, params))
        return _FakeResult(self._records)


def test_query_reads_only_complete_cycles_and_filters_the_tag(cc: ModuleType) -> None:
    session = _FakeSession()

    rows = cc.fetch_cycles(session, limit=5, tag="p7-3-control")

    query, params = session.calls[0]
    assert rows == [{"c": {"cycle_id": "x"}}]
    assert params == {"limit": 5, "tag": "p7-3-control"}
    assert f"{_EFFECTIVE_STATUS} = 'complete'" in query
    assert "c.experiment_tag = $tag" in query


def test_help_lists_the_flags_without_touching_the_database(cc: ModuleType, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        cc.main(["--help"])

    assert exc.value.code == 0
    out = capsys.readouterr().out
    for flag in ("--group-by", "--metrics", "--tag", "--markdown", "--n-boot", "--seed", "--limit"):
        assert flag in out


class _FakeDriver:
    def __init__(self, session: _FakeSession) -> None:
        self._session = session
        self.closed = False

    def session(self, *, database: str) -> Any:
        import contextlib

        @contextlib.contextmanager
        def _cm() -> Any:
            yield self._session

        return _cm()

    def close(self) -> None:
        self.closed = True


def _patch_db(cc: ModuleType, monkeypatch: pytest.MonkeyPatch, records: list[dict[str, Any]]) -> _FakeDriver:
    driver = _FakeDriver(_FakeSession(records))
    monkeypatch.setattr(cc.GraphDatabase, "driver", lambda *a, **kw: driver)
    monkeypatch.setenv("ALPHASWARM_NEO4J__PASSWORD", "fictional-test-password")
    return driver


def test_main_groups_fixture_cycles_offline(
    cc: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    records = [
        {"c": _cycle("a", experiment_tag="arm-a", r2_flips=4)},
        {"c": _cycle("b", experiment_tag="arm-a", r2_flips=6)},
    ]
    driver = _patch_db(cc, monkeypatch, records)

    assert cc.main(["--group-by", "experiment_tag", "--metrics", "r2_flips", "--markdown", "--n-boot", "50"]) == 0

    out = capsys.readouterr().out.splitlines()
    assert out[0] == "| experiment_tag | n | r2_flips |"
    assert out[2].startswith("| arm-a | 2 | 5.000 [")
    assert driver.closed


def test_main_prints_the_per_cycle_table_and_hold_share(
    cc: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    records = [{"c": _cycle("abcdef0123", seed_rumor="ZZZT rumor", total_seconds=12.4, final_hold=3, final_buy=1)}]
    _patch_db(cc, monkeypatch, records)

    assert cc.main([]) == 0

    out = capsys.readouterr().out
    assert out.splitlines()[0].startswith("cycle")
    assert "abcdef01  ZZZT rumor" in out
    assert "abcdef01: HOLD share 75%" in out


def test_main_says_when_no_cycle_matches(
    cc: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _patch_db(cc, monkeypatch, [])

    assert cc.main(["--tag", "nothing"]) == 0

    assert "No complete cycles found with tag 'nothing'" in capsys.readouterr().out


@pytest.mark.parametrize("group_args", [[], ["--group-by", "experiment_tag", "--n-boot", "20"]])
def test_main_appends_the_methodology_table_on_both_paths(
    cc: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], group_args: list[str]
) -> None:
    records = [{"c": _cycle("abcdef0123", final_round=2, r2_net_score_headcount=0.25, experiment_tag="arm-a")}]
    _patch_db(cc, monkeypatch, records)

    assert cc.main([*group_args, "--methodology"]) == 0

    out = capsys.readouterr().out
    assert "net_reach" in out
    assert "+0.250" in out
