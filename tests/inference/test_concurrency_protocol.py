"""Structural test: ResourceGovernor satisfies ConcurrencyController protocol."""

from alphaswarm.config import GovernorSettings
from alphaswarm.governor import ResourceGovernor
from alphaswarm.inference.concurrency import ConcurrencyController


class TestConcurrencyControllerProtocol:
    """Verify that ResourceGovernor is a structural subtype of ConcurrencyController."""

    def test_resource_governor_is_concurrency_controller(self) -> None:
        settings = GovernorSettings()
        gov = ResourceGovernor(settings)
        assert isinstance(gov, ConcurrencyController)

    def test_protocol_is_runtime_checkable(self) -> None:
        # runtime_checkable means isinstance() works on a plain object
        # (a non-conforming object returns False rather than raising TypeError)
        assert isinstance(object(), ConcurrencyController) is False
