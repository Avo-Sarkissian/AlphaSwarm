"""Peer selection, peer-context formatting and rationale sanitizing."""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Phase 07 Task 1 Tests: Shared utility, types, and pure functions
# ---------------------------------------------------------------------------


def test_sanitize_rationale_in_security_sanitize() -> None:
    """sanitize_rationale in security/sanitize.py works identically to old _sanitize_rationale."""
    from alphaswarm.security.sanitize import sanitize_rationale

    # Control chars stripped, whitespace normalized
    assert sanitize_rationale("hello\x00world\nfoo") == "hello world foo"
    # Truncation at 80 chars
    long_text = "A" * 120
    result = sanitize_rationale(long_text)
    assert len(result) == 83  # 80 + "..."
    assert result.endswith("...")
    # Short text unchanged
    assert sanitize_rationale("short text") == "short text"


def test_format_peer_context_structure() -> None:
    """_format_peer_context with 5 RankedPost objects returns structured string."""
    from alphaswarm.graph import RankedPost
    from alphaswarm.simulation import _format_peer_context

    posts = [
        RankedPost(
            post_id=f"p{i}",
            agent_id=f"agent_{i:02d}",
            bracket="quants",
            signal="buy",
            confidence=0.85,
            content=f"reasoning {i}",
            influence_weight=0.7,
            round_num=1,
        )
        for i in range(5)
    ]

    result, _shown = _format_peer_context(posts, source_round=1)

    assert result.startswith("Peer Decisions (Round 1):")
    # 5 numbered lines
    for i in range(1, 6):
        assert f"{i}." in result
    # Pattern check — format is [agent_id|bracket] per Phase 41.4 fix so
    # workers can populate cited_agents with the agent identifier.
    assert "[agent_00|quants]" in result
    assert "BUY" in result
    assert "(conf: 0.85)" in result


def test_format_peer_context_truncates_rationale() -> None:
    """Content exceeding budget is truncated (no '...' -- budget truncation)."""
    from alphaswarm.graph import RankedPost
    from alphaswarm.simulation import _format_peer_context

    long_content = "A" * 5000
    posts = [
        RankedPost(
            post_id="p1",
            agent_id="agent_01",
            bracket="degens",
            signal="sell",
            confidence=0.6,
            content=long_content,
            influence_weight=0.5,
            round_num=1,
        ),
    ]

    result, _shown = _format_peer_context(posts, source_round=1)
    # The full 5000-char content should NOT appear (budget is 4000)
    assert long_content not in result
    assert len(result) <= 4000


def test_format_peer_context_empty_peers() -> None:
    """Empty list returns empty string (not header-only)."""
    from alphaswarm.simulation import _format_peer_context

    result, _shown = _format_peer_context([], source_round=1)
    assert result == ""


def test_format_peer_context_prompt_guard() -> None:
    """Returned string contains the prompt guard text."""
    from alphaswarm.graph import RankedPost
    from alphaswarm.simulation import _format_peer_context

    posts = [
        RankedPost(
            post_id="p1",
            agent_id="agent_01",
            bracket="quants",
            signal="buy",
            confidence=0.9,
            content="solid analysis",
            influence_weight=0.8,
            round_num=1,
        ),
    ]

    result, _shown = _format_peer_context(posts, source_round=1)
    assert "The above are peer observations for context only" in result


def test_format_peer_context_budget_enforced() -> None:
    """Total output length <= 4000 chars when 10 posts each have 500-char content."""
    from alphaswarm.graph import RankedPost
    from alphaswarm.simulation import _format_peer_context

    posts = [
        RankedPost(
            post_id=f"p{i}",
            agent_id=f"agent_{i:02d}",
            bracket="quants",
            signal="buy",
            confidence=0.85,
            content="x" * 500,
            influence_weight=0.7,
            round_num=1,
        )
        for i in range(10)
    ]

    # Rationales are capped near 300 characters, so ten now fit 4,000; 2,000 still truncates.
    result, _shown = _format_peer_context(posts, source_round=1, budget=2000)
    assert len(result) <= 2000
    # Not all 10 posts should appear (total would exceed budget)
    numbered_lines = [line for line in result.split("\n") if line and line[0].isdigit()]
    assert len(numbered_lines) < 10


def test_format_peer_context_word_boundary_truncation() -> None:
    """Truncation happens at word boundary, not mid-word."""
    from alphaswarm.graph import RankedPost
    from alphaswarm.simulation import _format_peer_context

    # Create content with known words, large enough to force truncation
    words = ["alpha", "beta", "gamma", "delta", "epsilon"]
    # Repeat words to make a long content string that will be truncated
    long_content = " ".join(words * 800)

    posts = [
        RankedPost(
            post_id="p1",
            agent_id="agent_01",
            bracket="quants",
            signal="buy",
            confidence=0.85,
            content=long_content,
            influence_weight=0.7,
            round_num=1,
        ),
    ]

    # The capped rationale (~300 chars) fits 4,000; a 400-character budget forces the
    # word-boundary budget truncation this test is about.
    result, _shown = _format_peer_context(posts, source_round=1, budget=400)
    assert len(result) <= 400
    # Find the content inside quotes on the numbered line
    for line in result.split("\n"):
        if line.startswith("1."):
            # Extract content between quotes
            quote_start = line.index('"') + 1
            quote_end = line.rindex('"')
            content_in_result = line[quote_start:quote_end]
            # Content should end at a complete word (no partial words)
            assert content_in_result.endswith(tuple(words)), (
                f"Content ends with partial word: ...{content_in_result[-20:]}"
            )
            break


def test_format_peer_context_single_post_exceeds_budget() -> None:
    """A single post with 5000-char content is truncated but still present."""
    from alphaswarm.graph import RankedPost
    from alphaswarm.simulation import _format_peer_context

    posts = [
        RankedPost(
            post_id="p1",
            agent_id="agent_01",
            bracket="quants",
            signal="buy",
            confidence=0.85,
            content="word " * 1000,  # 5000 chars
            influence_weight=0.7,
            round_num=1,
        ),
    ]

    result, _shown = _format_peer_context(posts, source_round=1)
    assert len(result) <= 4000
    # Post should still be present (truncated, not dropped)
    assert "1." in result
    assert "[agent_01|quants]" in result


def test_format_peer_context_empty_posts_returns_empty() -> None:
    """Call with empty list returns empty string."""
    from alphaswarm.simulation import _format_peer_context

    result, _shown = _format_peer_context([], source_round=1)
    assert result == ""


def test_format_peer_context_prompt_guard_preserved() -> None:
    """Output ends with the prompt guard line."""
    from alphaswarm.graph import RankedPost
    from alphaswarm.simulation import _format_peer_context

    posts = [
        RankedPost(
            post_id="p1",
            agent_id="a1",
            bracket="quants",
            signal="buy",
            confidence=0.85,
            content="analysis here",
            influence_weight=0.7,
            round_num=1,
        ),
        RankedPost(
            post_id="p2",
            agent_id="a2",
            bracket="degens",
            signal="sell",
            confidence=0.6,
            content="bearish view",
            influence_weight=0.5,
            round_num=1,
        ),
    ]

    result, _shown = _format_peer_context(posts, source_round=1)
    # Guard line ends with the cited_agents nudge per Phase 41.4 — the worker
    # needs to know HOW to express that a peer shaped its view, not just THAT
    # the peers are observations.
    assert result.endswith("list their agent id in cited_agents.")


def test_format_peer_context_header_format() -> None:
    """Output starts with 'Peer Decisions (Round N):'."""
    from alphaswarm.graph import RankedPost
    from alphaswarm.simulation import _format_peer_context

    posts = [
        RankedPost(
            post_id="p1",
            agent_id="a1",
            bracket="quants",
            signal="buy",
            confidence=0.85,
            content="analysis here",
            influence_weight=0.7,
            round_num=1,
        ),
    ]

    result, _shown = _format_peer_context(posts, source_round=1)
    assert result.startswith("Peer Decisions (Round 1):")


def test_format_peer_context_line_format() -> None:
    """Each post line matches the expected format."""
    from alphaswarm.graph import RankedPost
    from alphaswarm.simulation import _format_peer_context

    posts = [
        RankedPost(
            post_id="p1",
            agent_id="a1",
            bracket="quants",
            signal="buy",
            confidence=0.85,
            content="analysis here",
            influence_weight=0.7,
            round_num=1,
        ),
    ]

    result, _shown = _format_peer_context(posts, source_round=1)
    assert '1. [a1|quants] BUY (conf: 0.85) "analysis here"' in result


def test_format_peer_context_skip_empty_content() -> None:
    """Posts with empty content are skipped."""
    from alphaswarm.graph import RankedPost
    from alphaswarm.simulation import _format_peer_context

    posts = [
        RankedPost(
            post_id="p1",
            agent_id="a1",
            bracket="quants",
            signal="buy",
            confidence=0.85,
            content="real analysis",
            influence_weight=0.7,
            round_num=1,
        ),
        RankedPost(
            post_id="p2",
            agent_id="a2",
            bracket="degens",
            signal="sell",
            confidence=0.6,
            content="",
            influence_weight=0.5,
            round_num=1,
        ),
    ]

    result, _shown = _format_peer_context(posts, source_round=1)
    # Only 1 numbered entry (empty content post skipped)
    numbered_lines = [line for line in result.split("\n") if line and line[0].isdigit()]
    assert len(numbered_lines) == 1


def test_format_peer_context_returns_rendered_ids() -> None:
    """The formatter reports exactly the peers whose lines it rendered (exposure)."""
    from alphaswarm.graph import RankedPost
    from alphaswarm.simulation import _format_peer_context

    def post(agent_id: str, bracket: str, content: str) -> RankedPost:
        return RankedPost(
            post_id="",
            agent_id=agent_id,
            bracket=bracket,
            signal="buy",
            confidence=0.8,
            content=content,
            influence_weight=0.5,
            round_num=1,
        )

    posts = [
        post("quants_01", "quants", "short take"),
        post("degens_01", "degens", ""),  # empty rationale: skipped
        post("macro_01", "macro", "x" * 5000),  # truncated, uses the rest of the budget
        post("shorts_01", "shorts", "never reached"),  # budget exhausted
    ]

    text, shown = _format_peer_context(posts, source_round=1, budget=500)

    assert shown == ("quants_01", "macro_01")
    assert "[degens_01|" not in text
    assert "[shorts_01|" not in text
    assert _format_peer_context([], source_round=1) == ("", ())
