from __future__ import annotations

import hashlib
import math
import re
import unicodedata


class LocalHashEmbeddings:
    """Deterministic local embeddings; no remote model or API is consulted."""
    dimensions = 256

    @staticmethod
    def tokens(text: str) -> list[str]:
        folded = "".join(char for char in unicodedata.normalize("NFD", text.casefold()) if not unicodedata.combining(char))
        return re.findall(r"[a-z0-9]+", folded)

    def embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        for token in self.tokens(text):
            index = int(hashlib.sha256(token.encode()).hexdigest(), 16) % self.dimensions
            vector[index] += 1.0
        magnitude = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / magnitude for value in vector]

    @staticmethod
    def similarity(left: list[float], right: list[float]) -> float:
        return sum(a * b for a, b in zip(left, right))

