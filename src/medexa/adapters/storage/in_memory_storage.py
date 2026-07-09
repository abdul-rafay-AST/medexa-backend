from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class InMemoryObjectStorage:
    """Test/dev object storage without AWS credentials."""

    bucket: str = "in-memory"
    _objects: dict[str, bytes] = field(default_factory=dict)

    def put_bytes(self, key: str, data: bytes, *, content_type: str = "application/octet-stream") -> str:
        self._objects[key] = data
        return key

    def get_bytes(self, key: str) -> bytes:
        return self._objects[key]

    def delete(self, key: str) -> None:
        self._objects.pop(key, None)

    def exists(self, key: str) -> bool:
        return key in self._objects

    def uri(self, key: str) -> str:
        return f"memory://{self.bucket}/{key}"
