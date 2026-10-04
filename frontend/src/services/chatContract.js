export function chatEntry(role, content) {
  return { role: role === "user" ? "user" : "assistant", content: typeof content === "string" ? content : "No fue posible mostrar este mensaje." };
}

export function parseChatResponse(payload) {
  const message = typeof payload?.message === "string" ? payload.message : payload?.response;
  if (typeof message !== "string" || !message.trim()) throw new Error("FitLife devolvió una respuesta no válida. Inténtalo de nuevo.");
  return { message, sessionId: typeof payload.session_id === "string" ? payload.session_id : null };
}
