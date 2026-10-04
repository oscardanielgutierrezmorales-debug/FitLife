import assert from "node:assert/strict";
import test from "node:test";

import { markdownBlocks } from "./chatMarkdown.js";

test("estructura encabezados, listas y párrafos sin interpretar HTML", () => {
  const blocks = markdownBlocks("### Receta\n\n**Ingredientes**\n- Garbanzos\n- Limón\n\n1. Mezcla\n2. Sirve\n\n<script>alert(1)</script>");
  assert.deepEqual(blocks.map((block) => block.type), ["heading", "paragraph", "unordered-list", "ordered-list", "paragraph"]);
  assert.equal(blocks[2].items.length, 2);
  assert.equal(blocks.at(-1).text, "<script>alert(1)</script>");
});

test("el parser conserva íntegro el contenido largo", () => {
  const content = Array.from({ length: 80 }, (_, index) => `${index + 1}. Paso **${index + 1}**`).join("\n");
  const blocks = markdownBlocks(content);
  assert.equal(blocks[0].items.length, 80);
  assert.equal(blocks[0].items.at(-1), "Paso **80**");
});
