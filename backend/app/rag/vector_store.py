from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .embeddings import LocalHashEmbeddings


class LocalVectorStore:
    def __init__(self, path: str, source_path: str = "/data/seed/knowledge_base.json") -> None:
        self.path = Path(path) / "fitlife-kb.json"
        self.source_path = Path(source_path)
        self.embedder = LocalHashEmbeddings()
        self.documents: list[dict[str, Any]] = []

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            self.documents = json.loads(self.path.read_text())
            return
        self.documents = json.loads(self.source_path.read_text())
        public_source = self.source_path.parent / "knowledge_base.public.json"
        if public_source.exists():
            self.documents.extend(json.loads(public_source.read_text()))
        for document in self.documents:
            document["embedding"] = self.embedder.embed(" ".join([document["name"], *document.get("aliases", []), document["text"]]))
        self.path.write_text(json.dumps(self.documents, ensure_ascii=False))

    def search(self, query: str, *, kind: str | None = None, limit: int = 3) -> list[dict[str, Any]]:
        query_embedding = self.embedder.embed(query)
        scored = []
        for document in self.documents:
            if kind and document.get("kind") != kind:
                continue
            score = self.embedder.similarity(query_embedding, document["embedding"])
            scored.append((score, document))
        return [{**document, "score": round(score, 4)} for score, document in sorted(scored, reverse=True, key=lambda item: item[0])[:limit]]
