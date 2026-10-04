import { api } from "./api";
export const sendChat = (token, body, signal) => api("/chat", { method: "POST", token, body, signal });
export const getChatHistory = (token, sessionId) => api(`/chat/${sessionId}`, { token });
export const getChatContext = (token) => api("/context", { token });
