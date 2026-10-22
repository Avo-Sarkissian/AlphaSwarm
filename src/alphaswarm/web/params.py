"""Validated request input types shared by the web routes.

Seeds and shocks are bounded so one request cannot add thousands of prefill
tokens to every agent call; cycle ids must be ``str(uuid4())``
(docs/DECISIONS.md#p4-d-10). pydantic's default Rust regex engine treats ``$``
as end-of-text, so an id followed by a newline is rejected.
"""

from __future__ import annotations

from typing import Annotated, Final

import fastapi
from pydantic import StringConstraints

SeedText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=10, max_length=2000)]
ShockText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=10, max_length=1000)]
CYCLE_ID_PATTERN: Final = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
CycleId = Annotated[str, fastapi.Path(pattern=CYCLE_ID_PATTERN)]
CycleIdQuery = Annotated[str, fastapi.Query(pattern=CYCLE_ID_PATTERN)]
