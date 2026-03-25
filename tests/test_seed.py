"""Tests for SeedEvent, SeedEntity, EntityType, and ParsedSeedResult models.

Validates:
- Correct construction with valid fields
- Boundary value acceptance (min/max for relevance, sentiment)
- Out-of-range rejection
- Frozen immutability
- Empty entities list is valid
- ParsedSeedResult stores seed_event and parse_tier correctly
"""

from __future__ import annotations

import dataclasses

import pytest
from pydantic import ValidationError

from alphaswarm.types import EntityType, ParsedSeedResult, SeedEntity, SeedEvent


# --- EntityType tests ---


def test_entity_type_values() -> None:
    """EntityType enum has exactly COMPANY, SECTOR, PERSON with correct string values."""
    assert EntityType.COMPANY.value == "company"
    assert EntityType.SECTOR.value == "sector"
    assert EntityType.PERSON.value == "person"
    assert len(EntityType) == 3


# --- SeedEntity tests ---


def test_seed_entity_valid_construction() -> None:
    """SeedEntity validates with all fields within range."""
    e = SeedEntity(name="NVIDIA", type=EntityType.COMPANY, relevance=0.9, sentiment=0.7)
    assert e.name == "NVIDIA"
    assert e.type == EntityType.COMPANY
    assert e.relevance == 0.9
    assert e.sentiment == 0.7


def test_seed_entity_boundary_values() -> None:
    """SeedEntity accepts boundary values for relevance and sentiment."""
    # Min boundaries
    e_min = SeedEntity(name="Test", type=EntityType.SECTOR, relevance=0.0, sentiment=-1.0)
    assert e_min.relevance == 0.0
    assert e_min.sentiment == -1.0

    # Max boundaries
    e_max = SeedEntity(name="Test", type=EntityType.PERSON, relevance=1.0, sentiment=1.0)
    assert e_max.relevance == 1.0
    assert e_max.sentiment == 1.0


def test_seed_entity_relevance_out_of_range() -> None:
    """SeedEntity rejects relevance > 1.0 or < 0.0."""
    with pytest.raises(ValidationError):
        SeedEntity(name="X", type=EntityType.COMPANY, relevance=1.5, sentiment=0.0)
    with pytest.raises(ValidationError):
        SeedEntity(name="X", type=EntityType.COMPANY, relevance=-0.1, sentiment=0.0)


def test_seed_entity_sentiment_out_of_range() -> None:
    """SeedEntity rejects sentiment outside -1.0 to 1.0."""
    with pytest.raises(ValidationError):
        SeedEntity(name="X", type=EntityType.COMPANY, relevance=0.5, sentiment=-1.5)
    with pytest.raises(ValidationError):
        SeedEntity(name="X", type=EntityType.COMPANY, relevance=0.5, sentiment=1.1)


def test_seed_entity_frozen() -> None:
    """SeedEntity is immutable (frozen)."""
    e = SeedEntity(name="NVIDIA", type=EntityType.COMPANY, relevance=0.9, sentiment=0.7)
    with pytest.raises(ValidationError):
        e.name = "changed"  # type: ignore[misc]


# --- SeedEvent tests ---


def test_seed_event_valid_construction() -> None:
    """SeedEvent validates with entities and overall_sentiment."""
    entities = [
        SeedEntity(name="NVIDIA", type=EntityType.COMPANY, relevance=0.95, sentiment=0.8),
        SeedEntity(name="Semiconductors", type=EntityType.SECTOR, relevance=0.7, sentiment=0.5),
    ]
    event = SeedEvent(raw_rumor="NVIDIA quantum breakthrough", entities=entities, overall_sentiment=0.6)
    assert event.raw_rumor == "NVIDIA quantum breakthrough"
    assert len(event.entities) == 2
    assert event.overall_sentiment == 0.6


def test_seed_event_empty_entities() -> None:
    """SeedEvent accepts empty entities list."""
    event = SeedEvent(raw_rumor="test", entities=[], overall_sentiment=0.0)
    assert event.entities == []


def test_seed_event_frozen() -> None:
    """SeedEvent is immutable (frozen)."""
    event = SeedEvent(raw_rumor="test", entities=[], overall_sentiment=0.0)
    with pytest.raises(ValidationError):
        event.raw_rumor = "changed"  # type: ignore[misc]


def test_seed_event_overall_sentiment_boundary() -> None:
    """SeedEvent overall_sentiment rejects values outside -1.0 to 1.0."""
    with pytest.raises(ValidationError):
        SeedEvent(raw_rumor="test", entities=[], overall_sentiment=1.5)
    with pytest.raises(ValidationError):
        SeedEvent(raw_rumor="test", entities=[], overall_sentiment=-1.1)


# --- ParsedSeedResult tests ---


def test_parsed_seed_result_construction() -> None:
    """ParsedSeedResult stores seed_event and parse_tier correctly."""
    event = SeedEvent(raw_rumor="test", entities=[], overall_sentiment=0.0)
    result = ParsedSeedResult(seed_event=event, parse_tier=1)
    assert result.seed_event is event
    assert result.parse_tier == 1


def test_parsed_seed_result_frozen() -> None:
    """ParsedSeedResult is frozen (assignment raises FrozenInstanceError)."""
    event = SeedEvent(raw_rumor="test", entities=[], overall_sentiment=0.0)
    result = ParsedSeedResult(seed_event=event, parse_tier=1)
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.parse_tier = 2  # type: ignore[misc]


def test_parsed_seed_result_all_tiers() -> None:
    """ParsedSeedResult accepts parse_tier values 1, 2, and 3."""
    event = SeedEvent(raw_rumor="test", entities=[], overall_sentiment=0.0)
    for tier in (1, 2, 3):
        result = ParsedSeedResult(seed_event=event, parse_tier=tier)
        assert result.parse_tier == tier
