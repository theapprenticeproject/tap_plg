import abc


class BaseProcessor(abc.ABC):
    """Abstract base class for all processors."""

    @abc.abstractmethod
    async def process(self, data: dict) -> dict:
        """All processors must implement this method."""
        pass
