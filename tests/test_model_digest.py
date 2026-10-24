"""model_digest: the Ollama weights digest recorded in the run manifest."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import httpx
from ollama import ListResponse

from alphaswarm.ollama_models import model_digest

DIGEST_W = "sha256:" + "1" * 64
DIGEST_O = "sha256:" + "2" * 64
LISTING = ListResponse(
    models=[
        ListResponse.Model(model="alphaswarm-worker:latest", digest=DIGEST_W),
        ListResponse.Model(model="alphaswarm-orchestrator:latest", digest=DIGEST_O),
    ]
)


def _client(result: ListResponse | BaseException) -> MagicMock:
    client = MagicMock()
    if isinstance(result, BaseException):
        client.raw_client.list = AsyncMock(side_effect=result)
    else:
        client.raw_client.list = AsyncMock(return_value=result)
    return client


async def test_bare_alias_matches_the_latest_tag() -> None:
    assert await model_digest(_client(LISTING), "alphaswarm-worker") == DIGEST_W


async def test_tagged_name_matches_too() -> None:
    assert await model_digest(_client(LISTING), "alphaswarm-orchestrator:latest") == DIGEST_O


async def test_a_model_that_is_not_installed_is_unknown() -> None:
    assert await model_digest(_client(LISTING), "not-installed") is None


async def test_an_unreachable_server_is_unknown_not_an_error() -> None:
    assert await model_digest(_client(httpx.ConnectError("refused")), "alphaswarm-worker") is None
