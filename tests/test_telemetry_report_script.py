"""scripts/telemetry_report.py: telemetry rows, A/B verdicts, rationale stats, read-only queries."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "telemetry_report.py"
CYCLE_A = "00000000-0000-4000-8000-0000000000a1"
CYCLE_B = "00000000-0000-4000-8000-0000000000b2"


@pytest.fixture(scope="module")
def report() -> ModuleType:
    spec = importlib.util.spec_from_file_location("telemetry_report_script", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses resolve annotations through sys.modules
    spec.loader.exec_module(module)
    return module


def _props(
    *,
    prefill: float = 600.0,
    completion: float = 150.0,
    seconds: float = 300.0,
    final: tuple[int, int, int] = (40, 30, 30),
) -> dict[str, Any]:
    props: dict[str, Any] = {
        "num_rounds": 3,
        "seed_seconds": 95.0,
        "total_seconds": 1000.0,
        "final_buy": final[0],
        "final_sell": final[1],
        "final_hold": final[2],
        "worker_model": "alphaswarm-worker",
        "git_sha": "abc1234",
    }
    for n in (1, 2, 3):
        props.update(
            {
                f"r{n}_seconds": seconds,
                f"r{n}_latency_p50_ms": 3000.0,
                f"r{n}_latency_p95_ms": 9000.0,
                f"r{n}_mean_prompt_tokens": 1400.0,
                f"r{n}_mean_completion_tokens": completion,
                f"r{n}_mean_prefill_ms": prefill,
                f"r{n}_mean_decode_ms": 2700.0,
                f"r{n}_total_load_ms": 0.0,
                f"r{n}_cold_loads": 0,
                f"r{n}_truncations": 0,
                f"r{n}_ctx_warnings": 0,
                f"r{n}_parse_errors": 1,
            }
        )
    return props


def test_round_rows_follow_num_rounds(report: ModuleType) -> None:
    props = _props()
    props["num_rounds"] = 2
    rows = report.round_rows("A0", CYCLE_A, props)
    assert [r.round_num for r in rows] == [1, 2]
    assert (rows[0].prefill_ms, rows[0].decode_ms, rows[0].cycle) == (600.0, 2700.0, CYCLE_A[:8])


def test_format_rows_markdown_and_missing_values(report: ModuleType) -> None:
    props = _props()
    del props["r1_mean_prefill_ms"]
    text = report.format_rows(report.round_rows("A0", CYCLE_A, props), markdown=True)
    lines = text.splitlines()
    assert lines[0].startswith("| arm | cycle | round |")
    assert lines[1].startswith("|---")
    assert "| A0 | 00000000 | 1 | 300.0 |" in lines[2]
    assert " - |" in lines[2]  # the missing prefill mean prints as "-"


def test_format_rows_plain_text_is_aligned(report: ModuleType) -> None:
    text = report.format_rows(report.round_rows("A0", CYCLE_A, _props()), markdown=False)
    lines = text.splitlines()
    assert lines[0].startswith("arm  cycle")
    assert len(lines) == 4


def test_cycle_summary_reports_seed_time_and_decode_share(report: ModuleType) -> None:
    line = report.cycle_summary("A0", CYCLE_A, _props())
    assert "seed_s=95.0" in line and "total_s=1000.0" in line
    assert "decode_share=0.82" in line  # 2700 / (600 + 2700)
    assert "final=40/30/30" in line and "git=abc1234" in line


def test_tv_distance(report: ModuleType) -> None:
    assert report.tv_distance({"buy": 50, "sell": 25, "hold": 25}, {"buy": 50, "sell": 25, "hold": 25}) == 0.0
    assert report.tv_distance({"buy": 100, "sell": 0, "hold": 0}, {"buy": 0, "sell": 100, "hold": 0}) == 1.0
    shifted = report.tv_distance({"buy": 60, "sell": 20, "hold": 20}, {"buy": 40, "sell": 40, "hold": 20})
    assert shifted == pytest.approx(0.2)


def test_change_pct(report: ModuleType) -> None:
    assert report.change_pct(200.0, 150.0) == pytest.approx(-25.0)
    assert report.change_pct(None, 150.0) is None
    assert report.change_pct(0.0, 150.0) is None


def test_final_counts_need_all_three_signals(report: ModuleType) -> None:
    props = _props()
    assert report.final_counts(props) == {"buy": 40, "sell": 30, "hold": 30}
    del props["final_hold"]
    assert report.final_counts(props) is None


def test_ab_verdict_keeps_a_real_prefill_drop(report: ModuleType) -> None:
    rows = [
        report.ab_row("s1", CYCLE_A, _props(prefill=600.0), CYCLE_B, _props(prefill=500.0)),
        report.ab_row("s2", CYCLE_A, _props(prefill=600.0), CYCLE_B, _props(prefill=510.0)),
    ]
    assert rows[0].prefill_change_pct == pytest.approx(-16.7, abs=0.1)
    verdict = "\n".join(report.ab_verdict(rows))
    assert "distribution: mean TV 0.000, max TV 0.000 -> UNCHANGED" in verdict
    assert "prefill (R2-R3): mean change -15.8% -> DROPPED" in verdict


def test_ab_verdict_flags_a_shift_and_no_drop(report: ModuleType) -> None:
    rows = [report.ab_row("s1", CYCLE_A, _props(final=(70, 15, 15)), CYCLE_B, _props(final=(20, 40, 40)))]
    verdict = "\n".join(report.ab_verdict(rows))
    assert "-> SHIFTED" in verdict and "-> NOT DROPPED" in verdict


def test_ab_verdict_without_data(report: ModuleType) -> None:
    before = {"num_rounds": 3}
    rows = [report.ab_row("s1", CYCLE_A, before, CYCLE_B, dict(before))]
    verdict = report.ab_verdict(rows)
    assert verdict[0] == "distribution: final counts missing -> UNKNOWN"
    assert verdict[1] == "prefill (R2-R3): no data -> NOT DROPPED"
    table = report.format_ab(rows, markdown=True)
    assert table.splitlines()[0].startswith("| seed | before | after |")


def test_rationale_stats(report: ModuleType) -> None:
    texts = ["Deal is accretive.", "x" * 300, "Antitrust risk caps the upside and the"]
    stats = report.rationale_stats(texts)
    assert (stats.count, stats.max_chars, stats.over_cap, stats.unterminated) == (3, 300, 1, 2)


def test_sample_rows_is_deterministic(report: ModuleType) -> None:
    rows = [(f"quants_{i:02d}", "buy", f"r{i}") for i in range(30)]
    assert report.sample_rows(rows, 5, 7) == report.sample_rows(rows, 5, 7)
    assert len(report.sample_rows(rows, 50, 7)) == 30


class _Result:
    def __init__(self, single: dict[str, Any] | None = None, data: list[dict[str, Any]] | None = None) -> None:
        self._single = single
        self._data = data or []

    def single(self) -> dict[str, Any] | None:
        return self._single

    def data(self) -> list[dict[str, Any]]:
        return self._data


class _Session:
    def __init__(self, props: dict[str, Any] | None, rows: list[dict[str, Any]]) -> None:
        self._props = props
        self._rows = rows
        self.queries: list[str] = []

    def run(self, query: str, **params: Any) -> _Result:
        self.queries.append(query)
        if "properties(c)" in query:
            return _Result(single=None if self._props is None else {"props": self._props})
        return _Result(data=self._rows)


def test_queries_are_read_only(report: ModuleType) -> None:
    session = _Session(_props(), [{"agent_id": "quants_01", "signal": "buy", "rationale": None}])
    assert report.read_props(session, CYCLE_A)["num_rounds"] == 3
    assert report.read_rationales(session, CYCLE_A, 3) == [("quants_01", "buy", "")]
    assert report.read_props(_Session(None, []), CYCLE_A) is None
    for query in session.queries:
        assert not any(word in query.upper() for word in ("CREATE", "MERGE", "SET ", "DELETE"))


def test_help_needs_no_database(report: ModuleType, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        report.main(["--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "rows" in out and "ab" in out and "rationales" in out
