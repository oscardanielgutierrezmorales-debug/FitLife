import assert from "node:assert/strict";
import test from "node:test";

import { chatEntry, parseChatResponse } from "./chatContract.js";

test("normaliza las respuestas de chat y conserva el mensaje visible", () => {
  assert.deepEqual(parseChatResponse({ message: "Respuesta", session_id: "session-1" }), { message: "Respuesta", sessionId: "session-1" });
  assert.deepEqual(parseChatResponse({ response: "Compatible" }), { message: "Compatible", sessionId: null });
  assert.deepEqual(chatEntry("assistant", null), { role: "assistant", content: "No fue posible mostrar este mensaje." });
});

test("una respuesta incompleta se convierte en error de chat, no en fallo de renderizado", () => {
  assert.throws(() => parseChatResponse({ session_id: "session-1" }), /respuesta no válida/);
});
