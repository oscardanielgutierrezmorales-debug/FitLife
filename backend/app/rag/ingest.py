"""Rebuild the local vector index from `data/knowledge_base.json`.

For external datasets, normalize their downloaded JSON into the same fields
(`id`, `kind`, `name`, `aliases`, `text`) and run this module in the backend
container. It never sends documents to a cloud embedding API.
"""
from __future__ import annotations

from app.config import settings
from app.rag.retriever import LocalRetriever


if __name__ == "__main__":
    retriever = LocalRetriever(settings.vector_db_path)
    retriever.initialize()
    print("Índice local de FitLife listo")

