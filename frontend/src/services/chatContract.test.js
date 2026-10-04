import assert from "node:assert/strict";
import test from "node:test";

import { chatEntry, chatRequestPayload, parseChatResponse } from "./chatContract.js";

test("normaliza las respuestas de chat y conserva el mensaje visible", () => {
  assert.deepEqual(parseChatResponse({ message: "Respuesta", session_id: "session-1" }), { message: "Respuesta", sessionId: "session-1" });
  assert.deepEqual(parseChatResponse({ response: "Compatible" }), { message: "Compatible", sessionId: null });
  assert.deepEqual(chatEntry("assistant", null, "message-1"), { id: "message-1", role: "assistant", content: "No fue posible mostrar este mensaje." });
});

test("una respuesta incompleta se convierte en error de chat, no en fallo de renderizado", () => {
  assert.throws(() => parseChatResponse({ session_id: "session-1" }), /respuesta no válida/);
  assert.throws(() => parseChatResponse({ message: "completa", message_length: 99 }), /llegó incompleta/);
});

test("conserva respuestas largas sin recortar caracteres", () => {
  for (const length of [500, 1500, 3000]) {
    const content = "x".repeat(length);
    assert.equal(parseChatResponse({ message: content, message_length: length }).message.length, length);
  }
  assert.equal(parseChatResponse({ message: "🥗", message_length: 1 }).message, "🥗");
});

test("envía únicamente la fecha seleccionada como contexto y no datos manipulables del workout", () => {
  assert.deepEqual(chatRequestPayload("Pregunta", "session-1", "2026-10-06"), {
    message: "Pregunta",
    session_id: "session-1",
    selected_plan_date: "2026-10-06",
  });
});
