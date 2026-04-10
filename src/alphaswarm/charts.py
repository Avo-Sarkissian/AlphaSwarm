"""pygal chart builders for HTML report SVG generation."""
from __future__ import annotations

import re

import pygal  # type: ignore[import-untyped]
from pygal.style import Style  # type: ignore[import-untyped]

# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------

_SCRIPT_RE = re.compile(r"<script[^>]*>.*?</script>", re.DOTALL)


def _strip_scripts(svg: str) -> str:
    """Remove pygal's inline JS config block from rendered SVG.

    pygal always emits a window.pygal.config <script> block even when js=[].
    That block is only needed for interactive tooltips; for static inline SVG
    inside HTML we strip it to satisfy the self-contained / no-JS requirement.
    """
    return _SCRIPT_RE.sub("", svg)


# ---------------------------------------------------------------------------
# Shared chart style — mirrors TUI ALPHASWARM_THEME colors exactly
# (D-04, D-11, RESEARCH Pattern 1, UI-SPEC pygal Chart Style Contract)
# ---------------------------------------------------------------------------

ALPHASWARM_CHART_STYLE = Style(
    background="#121212",
    plot_background="#1E1E1E",
    foreground="#E0E0E0",
    foreground_strong="#FFFFFF",
    foreground_subtle="#78909C",
    colors=("#66BB6A", "#EF5350", "#78909C"),
    font_family="'Segoe UI', 'Helvetica Neue', Arial, sans-serif",
    label_font_size=12,
    title_font_size=14,
    value_font_size=11,
    guide_stroke_color="#333333",
    major_guide_stroke_color="#444444",
)

# ---------------------------------------------------------------------------
# Shared chart config — enforces self-contained SVG (no external JS,
# no XML declaration) so output can be safely inlined into HTML templates
# ---------------------------------------------------------------------------

CHART_CONFIG: dict[str, object] = {
    "style": ALPHASWARM_CHART_STYLE,
    "disable_xml_declaration": True,
    "js": [],
    "show_legend": True,
    "print_values": True,
    "explicit_size": False,
}


# ---------------------------------------------------------------------------
# Chart builder functions
# ---------------------------------------------------------------------------


def render_consensus_bar(consensus_data: dict[str, object]) -> str:
    """Render a horizontal bar chart showing final consensus (Round 3).

    Returns an inline SVG string, or an empty string when total == 0.
    """
    if consensus_data.get("total", 0) == 0:
        return ""

    chart = pygal.HorizontalBar(**CHART_CONFIG, width=600, height=300)
    chart.title = "Final Consensus (Round 3)"
    chart.add("BUY", consensus_data["buy_count"])
    chart.add("SELL", consensus_data["sell_count"])
    chart.add("HOLD", consensus_data["hold_count"])
    return _strip_scripts(chart.render(is_unicode=True))


def render_round_timeline(timeline_data: list[dict[str, object]]) -> str:
    """Render a line chart showing signal distribution across rounds 1–3.

    Returns an inline SVG string, or an empty string when timeline_data is empty.
    """
    if not timeline_data:
        return ""

    chart = pygal.Line(**CHART_CONFIG, width=600, height=300, dots_size=4)
    chart.title = "Signal Distribution by Round"
    chart.x_labels = [f"Round {r['round_num']}" for r in timeline_data]
    chart.add("BUY", [r["buy_count"] for r in timeline_data])
    chart.add("SELL", [r["sell_count"] for r in timeline_data])
    chart.add("HOLD", [r["hold_count"] for r in timeline_data])
    return _strip_scripts(chart.render(is_unicode=True))


def render_bracket_breakdown(bracket_data: list[dict[str, object]]) -> str:
    """Render a horizontal stacked bar chart breaking consensus down by bracket.

    Returns an inline SVG string, or an empty string when bracket_data is empty.
    """
    if not bracket_data:
        return ""

    chart = pygal.HorizontalStackedBar(**CHART_CONFIG, width=600, height=400)
    chart.title = "Bracket Consensus Breakdown"
    chart.x_labels = [b["bracket"] for b in bracket_data]
    chart.add("BUY", [b["buy_count"] for b in bracket_data])
    chart.add("SELL", [b["sell_count"] for b in bracket_data])
    chart.add("HOLD", [b["hold_count"] for b in bracket_data])
    return _strip_scripts(chart.render(is_unicode=True))


def render_ticker_consensus(ticker_data: dict[str, object]) -> str:
    """Render a mini horizontal bar chart for a single ticker's majority signal.

    Returns an inline SVG string, or an empty string when ticker is empty/missing.
    """
    if not ticker_data.get("ticker"):
        return ""

    chart = pygal.HorizontalBar(**CHART_CONFIG, width=400, height=200, margin=10)
    chart.title = f"{ticker_data['ticker']} Consensus"

    pct = float(ticker_data.get("majority_pct", 0)) * 100  # type: ignore[arg-type]
    majority_signal = str(ticker_data.get("majority_signal", "HOLD")).upper()

    if majority_signal == "BUY":
        chart.add("BUY", pct)
        chart.add("SELL", 0)
        chart.add("HOLD", max(0.0, 100.0 - pct))
    elif majority_signal == "SELL":
        chart.add("BUY", 0)
        chart.add("SELL", pct)
        chart.add("HOLD", max(0.0, 100.0 - pct))
    else:
        chart.add("BUY", 0)
        chart.add("SELL", 0)
        chart.add("HOLD", pct)

    return _strip_scripts(chart.render(is_unicode=True))
