import { api } from "./api";
export const sendChat = (token, body) => api("/chat", { method: "POST", token, body });
export const getChatHistory = (token, sessionId) => api(`/chat/${sessionId}`, { token });
export const getChatContext = (token) => api("/context", { token });
