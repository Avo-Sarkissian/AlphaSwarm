"""Unit tests for alphaswarm.charts — pygal chart builder functions and style validation."""
from __future__ import annotations

import pytest

from alphaswarm.charts import (
    ALPHASWARM_CHART_STYLE,
    CHART_CONFIG,
    render_bracket_breakdown,
    render_consensus_bar,
    render_round_timeline,
    render_ticker_consensus,
)


class TestChartStyle:
    """Verify the shared pygal Style constant matches TUI ALPHASWARM_THEME exactly."""

    def test_background_matches_tui(self) -> None:
        assert ALPHASWARM_CHART_STYLE.background == "#121212"

    def test_plot_background_matches_surface(self) -> None:
        assert ALPHASWARM_CHART_STYLE.plot_background == "#1E1E1E"

    def test_foreground_matches_tui(self) -> None:
        assert ALPHASWARM_CHART_STYLE.foreground == "#E0E0E0"

    def test_foreground_strong(self) -> None:
        assert ALPHASWARM_CHART_STYLE.foreground_strong == "#FFFFFF"

    def test_foreground_subtle_matches_secondary(self) -> None:
        assert ALPHASWARM_CHART_STYLE.foreground_subtle == "#78909C"

    def test_colors_buy_sell_hold(self) -> None:
        """BUY=success, SELL=error, HOLD=secondary from TUI theme."""
        assert ALPHASWARM_CHART_STYLE.colors == ("#66BB6A", "#EF5350", "#78909C")

    def test_chart_config_no_external_js(self) -> None:
        assert CHART_CONFIG["js"] == []

    def test_chart_config_disable_xml_declaration(self) -> None:
        assert CHART_CONFIG["disable_xml_declaration"] is True

    def test_chart_config_no_explicit_size(self) -> None:
        assert CHART_CONFIG["explicit_size"] is False


class TestChartRenderers:
    """Verify all four chart builder functions produce valid inline SVG."""

    # ------------------------------------------------------------------ #
    # render_consensus_bar                                                 #
    # ------------------------------------------------------------------ #

    def test_consensus_bar_returns_svg(self) -> None:
        result = render_consensus_bar(
            {"buy_count": 50, "sell_count": 30, "hold_count": 20, "total": 100}
        )
        assert "<svg" in result
        assert "</svg>" in result

    def test_consensus_bar_no_xml_declaration(self) -> None:
        result = render_consensus_bar(
            {"buy_count": 50, "sell_count": 30, "hold_count": 20, "total": 100}
        )
        assert "<?xml" not in result

    def test_consensus_bar_no_script_tags(self) -> None:
        result = render_consensus_bar(
            {"buy_count": 50, "sell_count": 30, "hold_count": 20, "total": 100}
        )
        assert "<script" not in result.lower()

    def test_consensus_bar_no_cdn_reference(self) -> None:
        result = render_consensus_bar(
            {"buy_count": 50, "sell_count": 30, "hold_count": 20, "total": 100}
        )
        assert "kozea.github.io" not in result

    def test_consensus_bar_contains_buy_count_value(self) -> None:
        """print_values=True should embed numeric values in SVG."""
        result = render_consensus_bar(
            {"buy_count": 50, "sell_count": 30, "hold_count": 20, "total": 100}
        )
        assert "50" in result

    def test_consensus_bar_empty_returns_empty_string(self) -> None:
        result = render_consensus_bar(
            {"buy_count": 0, "sell_count": 0, "hold_count": 0, "total": 0}
        )
        assert result == ""

    # ------------------------------------------------------------------ #
    # render_round_timeline                                                #
    # ------------------------------------------------------------------ #

    def test_round_timeline_returns_svg(self) -> None:
        result = render_round_timeline(
            [
                {"round_num": 1, "buy_count": 45, "sell_count": 35, "hold_count": 20, "total": 100},
                {"round_num": 2, "buy_count": 48, "sell_count": 32, "hold_count": 20, "total": 100},
                {"round_num": 3, "buy_count": 50, "sell_count": 30, "hold_count": 20, "total": 100},
            ]
        )
        assert "<svg" in result
        assert "</svg>" in result

    def test_round_timeline_no_xml_declaration(self) -> None:
        result = render_round_timeline(
            [
                {"round_num": 1, "buy_count": 45, "sell_count": 35, "hold_count": 20, "total": 100},
            ]
        )
        assert "<?xml" not in result

    def test_round_timeline_no_script_tags(self) -> None:
        result = render_round_timeline(
            [
                {"round_num": 1, "buy_count": 45, "sell_count": 35, "hold_count": 20, "total": 100},
            ]
        )
        assert "<script" not in result.lower()

    def test_round_timeline_no_cdn_reference(self) -> None:
        result = render_round_timeline(
            [
                {"round_num": 1, "buy_count": 45, "sell_count": 35, "hold_count": 20, "total": 100},
            ]
        )
        assert "kozea.github.io" not in result

    def test_round_timeline_contains_round_labels(self) -> None:
        result = render_round_timeline(
            [
                {"round_num": 1, "buy_count": 45, "sell_count": 35, "hold_count": 20, "total": 100},
                {"round_num": 2, "buy_count": 48, "sell_count": 32, "hold_count": 20, "total": 100},
                {"round_num": 3, "buy_count": 50, "sell_count": 30, "hold_count": 20, "total": 100},
            ]
        )
        assert "Round 1" in result
        assert "Round 2" in result
        assert "Round 3" in result

    def test_round_timeline_empty_returns_empty_string(self) -> None:
        result = render_round_timeline([])
        assert result == ""

    # ------------------------------------------------------------------ #
    # render_bracket_breakdown                                             #
    # ------------------------------------------------------------------ #

    def test_bracket_breakdown_returns_svg(self) -> None:
        result = render_bracket_breakdown(
            [
                {
                    "bracket": "Quants",
                    "buy_count": 8,
                    "sell_count": 1,
                    "hold_count": 1,
                    "avg_confidence": 0.85,
                    "avg_sentiment": 0.72,
                }
            ]
        )
        assert "<svg" in result
        assert "</svg>" in result

    def test_bracket_breakdown_contains_bracket_label(self) -> None:
        result = render_bracket_breakdown(
            [
                {
                    "bracket": "Quants",
                    "buy_count": 8,
                    "sell_count": 1,
                    "hold_count": 1,
                    "avg_confidence": 0.85,
                    "avg_sentiment": 0.72,
                }
            ]
        )
        assert "Quants" in result

    def test_bracket_breakdown_no_cdn_reference(self) -> None:
        result = render_bracket_breakdown(
            [
                {
                    "bracket": "Quants",
                    "buy_count": 8,
                    "sell_count": 1,
                    "hold_count": 1,
                    "avg_confidence": 0.85,
                    "avg_sentiment": 0.72,
                }
            ]
        )
        assert "kozea.github.io" not in result

    def test_bracket_breakdown_empty_returns_empty_string(self) -> None:
        result = render_bracket_breakdown([])
        assert result == ""

    # ------------------------------------------------------------------ #
    # render_ticker_consensus                                              #
    # ------------------------------------------------------------------ #

    def test_ticker_mini_charts_returns_svg(self) -> None:
        result = render_ticker_consensus(
            {"ticker": "TSLA", "majority_signal": "SELL", "majority_pct": 0.72, "consensus_score": 0.68}
        )
        assert "<svg" in result
        assert "</svg>" in result

    def test_ticker_mini_charts_contains_ticker_label(self) -> None:
        result = render_ticker_consensus(
            {"ticker": "TSLA", "majority_signal": "SELL", "majority_pct": 0.72, "consensus_score": 0.68}
        )
        assert "TSLA" in result

    def test_ticker_mini_charts_no_xml_declaration(self) -> None:
        result = render_ticker_consensus(
            {"ticker": "TSLA", "majority_signal": "SELL", "majority_pct": 0.72, "consensus_score": 0.68}
        )
        assert "<?xml" not in result

    def test_ticker_mini_charts_no_cdn_reference(self) -> None:
        result = render_ticker_consensus(
            {"ticker": "TSLA", "majority_signal": "SELL", "majority_pct": 0.72, "consensus_score": 0.68}
        )
        assert "kozea.github.io" not in result

    def test_ticker_consensus_empty_ticker(self) -> None:
        result = render_ticker_consensus(
            {"ticker": "", "majority_signal": "HOLD", "majority_pct": 0.0, "consensus_score": 0.0}
        )
        assert result == ""
