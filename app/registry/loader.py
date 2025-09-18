"""ONNX model loader placeholder."""

from dataclasses import dataclass


@dataclass
class ModelHandle:
    name: str
    version: str

    def session(self):  # pragma: no cover
        """Return a dummy session object."""
        return None
