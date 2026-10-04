#!/usr/bin/env python3
"""Build or rebuild FitLife's local vector index without an external AI API."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
os.environ.setdefault("VECTOR_DB_PATH", str(ROOT / "data" / "vectors"))

from app.rag.retriever import LocalRetriever  # noqa: E402

retriever = LocalRetriever(os.environ["VECTOR_DB_PATH"])
retriever.store.source_path = ROOT / "data" / "knowledge_base.json"
retriever.initialize()
print(f"Índice FitLife creado en {retriever.store.path}")
