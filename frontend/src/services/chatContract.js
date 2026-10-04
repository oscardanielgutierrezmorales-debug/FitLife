let localMessageSequence = 0;

export function chatEntry(role, content, id = null) {
  localMessageSequence += 1;
  return {
    id: typeof id === "string" && id ? id : `local-${Date.now()}-${localMessageSequence}`,
    role: role === "user" ? "user" : "assistant",
    content: typeof content === "string" ? content : "No fue posible mostrar este mensaje.",
  };
}

export function parseChatResponse(payload) {
  const message = typeof payload?.message === "string" ? payload.message : payload?.response;
  if (typeof message !== "string" || !message.trim()) throw new Error("FitLife devolvió una respuesta no válida. Inténtalo de nuevo.");
  if (Number.isInteger(payload?.message_length) && payload.message_length !== [...message].length) throw new Error("La respuesta llegó incompleta. Inténtalo de nuevo.");
  return { message, sessionId: typeof payload.session_id === "string" ? payload.session_id : null };
}
