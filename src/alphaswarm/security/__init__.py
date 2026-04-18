"""Security utilities shared across modules (hashing, PII helpers).

Placed here (rather than in alphaswarm/holdings/) so importers that must not
touch alphaswarm.holdings (per Plan 04 contract) can still access sha256_first8().
"""

from alphaswarm.security.hashing import sha256_first8

__all__ = ["sha256_first8"]
