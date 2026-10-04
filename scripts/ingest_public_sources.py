#!/usr/bin/env python3
"""Optional ingestion of public sources into a local, reviewable JSON corpus.

FitLife never calls these URLs at runtime. This script is only for refreshing
the on-disk RAG corpus before indexing it locally.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data" / "knowledge_base.public.json"


def make_doc(identifier: str, kind: str, name: str, text: str, aliases: list[str] | None = None) -> dict:
    return {"id": identifier, "kind": kind, "name": name, "aliases": aliases or [], "text": text}


def main() -> None:
    with httpx.Client(timeout=30, follow_redirects=True) as client:
        food = client.get("https://world.openfoodfacts.org/cgi/search.pl", params={"search_terms": "chickpeas", "search_simple": 1, "action": "process", "json": 1, "page_size": 20})
        food.raise_for_status()
        exercises = client.get("https://wger.de/api/v2/exerciseinfo/", params={"limit": 50, "language": 2})
        exercises.raise_for_status()
    docs = []
    for product in food.json().get("products", []):
        name, nutrients = str(product.get("product_name") or "").strip(), product.get("nutriments") or {}
        if name:
            docs.append(make_doc(f"off-{product.get('_id', name)}", "nutrition", name, f"Por 100 g: {nutrients.get('energy-kcal_100g', 'N/D')} kcal; proteína {nutrients.get('proteins_100g', 'N/D')} g.", ["chickpeas"]))
    for exercise in exercises.json().get("results", []):
        name, description = str(exercise.get("name") or "").strip(), str(exercise.get("description") or "").strip()
        if name and description:
            docs.append(make_doc(f"wger-{exercise.get('id')}", "exercise", name, description))
    OUTPUT.write_text(json.dumps(docs, ensure_ascii=False, indent=2))
    print(f"{len(docs)} documentos normalizados en {OUTPUT}")


if __name__ == "__main__":
    try:
        main()
    except httpx.HTTPError as exc:
        print(f"No se pudo descargar una fuente pública: {exc}", file=sys.stderr)
        raise SystemExit(1)
