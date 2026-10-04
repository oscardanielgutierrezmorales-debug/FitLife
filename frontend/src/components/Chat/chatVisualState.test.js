import assert from "node:assert/strict";
import test from "node:test";

import { chatVisualReducer, initialChatVisualState } from "./chatVisualState.js";

test("minimizar y restaurar conserva el estado lógico fuera del panel", () => {
  const messages = [{ id: "1", role: "user", content: "Pregunta" }];
  let visual = initialChatVisualState(null);
  visual = chatVisualReducer(visual, { type: "minimize" });
  assert.deepEqual(visual, { minimized: true, unread: 0 });
  assert.equal(messages.length, 1);
  visual = chatVisualReducer(visual, { type: "restore" });
  assert.deepEqual(visual, { minimized: false, unread: 0 });
  assert.equal(messages[0].content, "Pregunta");
});

test("una respuesta recibida mientras está minimizado incrementa y luego limpia el indicador", () => {
  let visual = initialChatVisualState("true");
  visual = chatVisualReducer(visual, { type: "response_received" });
  assert.deepEqual(visual, { minimized: true, unread: 1 });
  visual = chatVisualReducer(visual, { type: "restore" });
  assert.deepEqual(visual, { minimized: false, unread: 0 });
});
