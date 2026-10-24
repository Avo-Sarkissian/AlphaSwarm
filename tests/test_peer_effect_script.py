"""scripts/peer_effect.py: flip rate minus control, shock arm, noise floor, exposure checks."""

from __future__ import annotations

import contextlib
import json
import random
from collections.abc import Iterator
from types import ModuleType
from typing import Any

import pytest

from alphaswarm.graph.rows import _EFFECTIVE_STATUS
from tests.support.scripts import load_script


@pytest.fixture(scope="module")
def pe() -> ModuleType:
    return load_script("peer_effect")


def _row(pe: ModuleType, cycle: str, agent: str, rnd: int, signal: str, **kw: Any) -> Any:
    return pe.DecisionRow(
        cycle_id=cycle,
        agent_id=agent,
        bracket=kw.get("bracket", agent.rsplit("_", 1)[0]),
        round_num=rnd,
        signal=signal,
        control=kw.get("control", False),
        shock_treated=kw.get("shock"),
        peer_ids=kw.get("peers"),
        cited=tuple(kw.get("cited", ())),
    )


def _pair(pe: ModuleType, cycle: str, agent: str, *, flipped: bool, control: bool = False) -> list[Any]:
    """Round 1 BUY, then Round 2 SELL (flip) or BUY (no flip)."""
    return [
        _row(pe, cycle, agent, 1, "buy", control=control),
        _row(pe, cycle, agent, 2, "sell" if flipped else "buy", control=control),
    ]


def test_parse_errors_are_not_flips(pe: ModuleType) -> None:
    """A failure on either side, or no previous decision, is no observation."""
    rows = [
        _row(pe, "c1", "quants_01", 1, "parse_error"),
        _row(pe, "c1", "quants_01", 2, "buy"),
        _row(pe, "c1", "quants_02", 1, "buy"),
        _row(pe, "c1", "quants_02", 2, "parse_error"),
        _row(pe, "c1", "quants_03", 1, "buy"),
        _row(pe, "c1", "quants_03", 2, "sell"),
        _row(pe, "c1", "quants_04", 2, "sell"),
    ]

    obs = pe.flip_observations(rows)

    assert [(o.round_num, o.flipped) for o in obs] == [(2, True)]


def test_a_missing_control_property_reads_as_treated(pe: ModuleType) -> None:
    row = pe.to_row(
        {
            "cycle_id": "c",
            "agent_id": "quants_01",
            "bracket": "quants",
            "round_num": 2,
            "signal": "BUY",
            "control": None,
            "shock_treated": None,
            "peer_ids": None,
            "cited": [],
        }
    )

    assert (row.control, row.signal, row.peer_ids, row.shock_treated) == (False, "buy", None, None)


def test_bracket_effect_is_the_mean_of_per_cycle_differences(pe: ModuleType) -> None:
    rows = []
    # c1: treated 2/4 flip (0.5), control 0/2 (0.0) -> +0.5
    for i, flipped in enumerate([True, True, False, False]):
        rows += _pair(pe, "c1", f"quants_0{i + 1}", flipped=flipped)
    rows += _pair(pe, "c1", "quants_05", flipped=False, control=True)
    rows += _pair(pe, "c1", "quants_06", flipped=False, control=True)
    # c2: treated 1/4 (0.25), control 1/2 (0.5) -> -0.25
    for i, flipped in enumerate([True, False, False, False]):
        rows += _pair(pe, "c2", f"quants_0{i + 1}", flipped=flipped)
    rows += _pair(pe, "c2", "quants_05", flipped=True, control=True)
    rows += _pair(pe, "c2", "quants_06", flipped=False, control=True)

    effects = pe.bracket_effects(pe.flip_observations(rows), rng=random.Random(1), n_boot=500)
    quants = next(e for e in effects if e.label == "quants")

    assert (quants.cycles, quants.n_treated, quants.n_control) == (2, 8, 4)
    assert quants.diff == pytest.approx(0.125)
    assert quants.treated_rate == pytest.approx(3 / 8) and quants.control_rate == pytest.approx(1 / 4)
    assert quants.ci is not None and quants.ci[0] <= quants.diff <= quants.ci[1]
    assert quants.ci_basis == "cycles"
    assert effects[-1].label == "all"


def test_cycle_without_control_reports_none(pe: ModuleType) -> None:
    """No control agents means no effect, not a division by zero."""
    rows = _pair(pe, "c1", "quants_01", flipped=True) + _pair(pe, "c1", "quants_02", flipped=False)

    effects = pe.bracket_effects(pe.flip_observations(rows), rng=random.Random(1), n_boot=200)
    line = pe.effect_row(effects[0])

    assert (effects[0].n_control, effects[0].diff, effects[0].ci) == (0, None, None)
    assert line[0] == "quants" and line[-2:] == ["no control agents", "-"]


def test_one_cycle_falls_back_to_resampling_agents(pe: ModuleType) -> None:
    rows = []
    for i, flipped in enumerate([True, False, True, False]):
        rows += _pair(pe, "c1", f"degens_0{i + 1}", flipped=flipped)
    rows += _pair(pe, "c1", "degens_05", flipped=False, control=True)
    rows += _pair(pe, "c1", "degens_06", flipped=True, control=True)

    effect = pe.bracket_effects(pe.flip_observations(rows), rng=random.Random(2), n_boot=300)[0]

    assert effect.cycles == 1 and effect.ci_basis == "agents"
    assert pe.effect_row(effect)[-1].endswith("(agents)")


def test_shock_effect_uses_only_rounds_with_a_shock_arm(pe: ModuleType) -> None:
    rows = [
        _row(pe, "c1", "macro_01", 1, "buy"),
        _row(pe, "c1", "macro_01", 2, "sell", shock=True),
        _row(pe, "c1", "macro_02", 1, "buy"),
        _row(pe, "c1", "macro_02", 2, "buy", shock=False),
        _row(pe, "c1", "macro_03", 1, "buy"),
        _row(pe, "c1", "macro_03", 2, "sell", shock=True),
        _row(pe, "c1", "macro_04", 1, "buy"),
        _row(pe, "c1", "macro_04", 2, "buy", shock=False),
        _row(pe, "c1", "macro_01", 3, "buy"),
        _row(pe, "c1", "macro_02", 3, "sell"),
    ]

    effect = pe.shock_effect(pe.flip_observations(rows), rng=random.Random(3), n_boot=200)

    assert (effect.n_treated, effect.n_control) == (2, 2)
    assert effect.diff == pytest.approx(1.0)


def test_noise_floor_skips_cycles_without_a_retest(pe: ModuleType) -> None:
    cycles = [
        {"cycle_id": "a", "r1_retest_pairs": 100, "r1_retest_flips": 8, "r1_retest_flip_rate": 0.08},
        {"cycle_id": "b", "r1_retest_pairs": 98, "r1_retest_flips": 12, "r1_retest_flip_rate": 0.122449},
        {"cycle_id": "c"},
    ]

    floor = pe.noise_floor(cycles, rng=random.Random(4), n_boot=300)

    assert (floor.cycles, floor.pairs, floor.flips) == (2, 198, 20)
    assert floor.mean_rate == pytest.approx((0.08 + 0.122449) / 2)
    assert floor.ci is not None


def test_influence_ranks_by_citation_rate_given_exposure(pe: ModuleType) -> None:
    rows = [
        _row(pe, "c1", "quants_01", 2, "buy", peers=("sell_side_01", "degens_01"), cited=("sell_side_01",)),
        _row(pe, "c1", "quants_02", 2, "buy", peers=("sell_side_01",), cited=("sell_side_01",)),
        _row(pe, "c1", "quants_03", 2, "buy", peers=()),
        _row(pe, "c1", "sell_side_01", 1, "buy"),
        _row(pe, "c1", "degens_01", 1, "sell"),
    ]

    table = pe.influence_table(rows, 2, top=5)

    assert [(agent, bracket, shown) for agent, bracket, _, shown in table] == [
        ("sell_side_01", "sell_side", 2),
        ("degens_01", "degens", 1),
    ]
    assert table[0][2] == pytest.approx(3 / 4) and table[1][2] == pytest.approx(1 / 3)


def test_exposure_match_and_manifest_diff(pe: ModuleType) -> None:
    a = [
        _row(pe, "A", "quants_01", 2, "buy", peers=("degens_01", "macro_01")),
        _row(pe, "A", "quants_02", 2, "buy", peers=("macro_01",)),
        _row(pe, "A", "quants_01", 3, "buy", peers=("degens_02",)),
    ]
    b = [
        _row(pe, "B", "quants_01", 2, "buy", peers=("degens_01", "macro_01")),
        _row(pe, "B", "quants_02", 2, "buy", peers=("shorts_01",)),
        _row(pe, "B", "quants_01", 3, "buy", peers=("degens_02",)),
    ]
    manifest_a = json.dumps(
        {
            "cycle_id": "A",
            "created_at": "t1",
            "sim_seed": 4242,
            "market_context": "x",
            "simulation": {"peer_limit": 10, "sim_seed": 4242},
        }
    )
    manifest_b = json.dumps(
        {
            "cycle_id": "B",
            "created_at": "t2",
            "sim_seed": 4242,
            "market_context": "y",
            "simulation": {"peer_limit": 8, "sim_seed": 4242},
        }
    )

    matches = pe.exposure_match(a, b)

    assert [(m.round_num, m.readers, m.identical) for m in matches] == [(2, 2, 1), (3, 1, 1)]
    assert pe.manifest_diff(manifest_a, manifest_b) == ["market_context", "simulation.peer_limit"]
    assert pe.manifest_diff(None, manifest_b) == ["<manifest missing>"]


class _FakeResult:
    def __init__(self, records: list[dict[str, Any]]) -> None:
        self._records = records

    def data(self) -> list[dict[str, Any]]:
        return self._records


class _FakeSession:
    """Answers the two read queries from in-memory cycles and decision records."""

    def __init__(self, cycles: list[dict[str, Any]], decisions: list[dict[str, Any]]) -> None:
        self.cycles = cycles
        self.decisions = decisions

    def run(self, query: str, **params: Any) -> _FakeResult:
        if "MATCH (c:Cycle)" in query:
            ids = params.get("cycle_ids")
            tag = params.get("tag")
            found = [
                {"c": c}
                for c in self.cycles
                if (ids is None or c["cycle_id"] in ids) and (tag is None or c.get("experiment_tag") == tag)
            ]
            return _FakeResult(found)
        ids = set(params["cycle_ids"])
        return _FakeResult([d for d in self.decisions if d["cycle_id"] in ids])


def _record(cycle: str, agent: str, rnd: int, signal: str, *, control: bool) -> dict[str, Any]:
    return {
        "cycle_id": cycle,
        "agent_id": agent,
        "bracket": agent.rsplit("_", 1)[0],
        "round_num": rnd,
        "signal": signal,
        "control": control,
        "shock_treated": None,
        "peer_ids": [],
        "cited": [],
    }


def test_effect_command_prints_a_markdown_table(pe: ModuleType, capsys: pytest.CaptureFixture[str]) -> None:
    decisions = []
    for agent, flipped, control in [
        ("quants_01", True, False),
        ("quants_02", False, False),
        ("quants_03", False, True),
        ("quants_04", False, True),
    ]:
        decisions += [
            _record("c1", agent, 1, "buy", control=control),
            _record("c1", agent, 2, "sell" if flipped else "buy", control=control),
        ]
    session = _FakeSession([{"cycle_id": "c1", "experiment_tag": "p7-3-control"}], decisions)
    args = pe._build_parser().parse_args(["effect", "--tag", "p7-3-control", "--markdown"])

    assert pe.run_command(args, session) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[0].startswith("| bracket | cycles | n_treated | n_control |")
    assert any(line.startswith("| quants | 1 | 2 | 2 | 0.500 | 0.000 | +0.500 |") for line in lines)


def test_unknown_cycle_exits_2(pe: ModuleType, capsys: pytest.CaptureFixture[str]) -> None:
    session = _FakeSession([{"cycle_id": "c1"}], [])
    args = pe._build_parser().parse_args(["exposure-diff", "c1", "missing-cycle"])

    assert pe.run_command(args, session) == 2
    assert "missing-cycle" in capsys.readouterr().err


def test_cycles_are_selected_by_the_shared_status_rule(pe: ModuleType) -> None:
    assert f"WHERE {_EFFECTIVE_STATUS} = 'complete'" in pe.CYCLES_QUERY


def _decisions_for(cycle: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for agent, flipped, control in [
        ("degens_01", True, False),
        ("degens_02", False, False),
        ("degens_03", True, True),
        ("degens_04", False, True),
    ]:
        out += [
            _record(cycle, agent, 1, "buy", control=control),
            _record(cycle, agent, 2, "sell" if flipped else "buy", control=control),
        ]
    return out


def test_noise_and_shock_commands_print_tables(pe: ModuleType, capsys: pytest.CaptureFixture[str]) -> None:
    cycles = [
        {"cycle_id": "c1", "r1_retest_pairs": 100, "r1_retest_flips": 5, "r1_retest_flip_rate": 0.05},
        {"cycle_id": "c2", "r1_retest_pairs": 100, "r1_retest_flips": 9, "r1_retest_flip_rate": 0.09},
    ]
    session = _FakeSession(cycles, _decisions_for("c1"))

    assert pe.run_command(pe._build_parser().parse_args(["noise", "--cycle", "c1", "--cycle", "c2"]), session) == 0
    noise = capsys.readouterr().out.splitlines()
    assert noise[0].split() == ["cycles", "pairs", "flips", "mean_flip_rate", "95%", "CI"]
    assert noise[1].startswith("2       200    14     0.070")

    assert pe.run_command(pe._build_parser().parse_args(["shock", "--cycle", "c1"]), session) == 0
    shock = capsys.readouterr().out.splitlines()
    assert shock[1].startswith("shock arm")
    assert "no control agents" in shock[1]  # no shock-split round in these cycles


def test_influence_and_exposure_diff_commands(pe: ModuleType, capsys: pytest.CaptureFixture[str]) -> None:
    decisions = [
        {**_record("A", "quants_01", 2, "buy", control=False), "peer_ids": ["degens_01"], "cited": ["degens_01"]},
        {**_record("B", "quants_01", 2, "buy", control=False), "peer_ids": ["degens_01"]},
        _record("A", "degens_01", 1, "buy", control=False),
        _record("B", "degens_01", 1, "parse_error", control=False),
    ]
    manifest = json.dumps({"cycle_id": "A", "sim_seed": 1, "simulation": {"peer_limit": 10}})
    session = _FakeSession(
        [{"cycle_id": "A", "run_manifest_json": manifest}, {"cycle_id": "B", "run_manifest_json": manifest}],
        decisions,
    )

    args = pe._build_parser().parse_args(["influence", "--cycle", "A", "--round", "2", "--markdown"])
    assert pe.run_command(args, session) == 0
    influence = capsys.readouterr().out.splitlines()
    assert influence[0] == "| agent | bracket | cite_rate_given_exposure | times_shown |"
    assert influence[2] == "| degens_01 | degens | 0.667 | 1 |"

    assert pe.run_command(pe._build_parser().parse_args(["exposure-diff", "A", "B"]), session) == 0
    assert capsys.readouterr().out.splitlines() == [
        "round 2: 1/1 readers shown identical peers",
        "round 1 PARSE_ERROR sets identical: no",
        "manifest fields that differ: none",
    ]


def test_missing_cycles_and_empty_tags_exit_2(pe: ModuleType, capsys: pytest.CaptureFixture[str]) -> None:
    session = _FakeSession([{"cycle_id": "c1", "experiment_tag": "t"}], [])
    parse = pe._build_parser().parse_args

    assert pe.run_command(parse(["influence", "--cycle", "nope"]), session) == 2
    assert pe.run_command(parse(["effect", "--cycle", "nope"]), session) == 2
    assert pe.run_command(parse(["effect", "--tag", "other"]), session) == 2
    err = capsys.readouterr().err
    assert "nope" in err and "no complete cycles match" in err


def test_main_runs_offline_against_a_fake_driver(
    pe: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    session = _FakeSession([{"cycle_id": "c1", "experiment_tag": "t"}], _decisions_for("c1"))
    closed: list[bool] = []

    class _Driver:
        @contextlib.contextmanager
        def session(self, *, database: str) -> Iterator[_FakeSession]:
            yield session

        def close(self) -> None:
            closed.append(True)

    monkeypatch.setattr(pe.GraphDatabase, "driver", lambda *a, **kw: _Driver())
    monkeypatch.setenv("ALPHASWARM_NEO4J__PASSWORD", "fictional-test-password")

    assert pe.main(["effect", "--tag", "t", "--n-boot", "50"]) == 0
    assert closed == [True]
    assert capsys.readouterr().out.splitlines()[0].startswith("bracket")


def test_help_does_not_touch_the_database(pe: ModuleType, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        pe.main(["--help"])

    assert exc.value.code == 0
    out = capsys.readouterr().out
    for command in ("effect", "shock", "noise", "influence", "exposure-diff"):
        assert command in out
