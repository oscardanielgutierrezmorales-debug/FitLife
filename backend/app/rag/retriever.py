from __future__ import annotations

from .vector_store import LocalVectorStore


class LocalRetriever:
    def __init__(self, path: str) -> None:
        self.store = LocalVectorStore(path)

    def initialize(self) -> None:
        self.store.initialize()

    def retrieve(self, query: str, kind: str | None = None) -> list[dict]:
        return self.store.search(query, kind=kind)

