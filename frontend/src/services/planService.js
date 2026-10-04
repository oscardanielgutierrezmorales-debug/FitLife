import { api } from "./api";
export const getProfile = (token) => api("/profile", { token });
export const saveProfile = (token, body) => api("/profile", { method: "PUT", token, body });
export const getPlan = (token) => api("/plan", { token });
export const generatePlan = (token) => api("/plan/generate", { method: "POST", token });
export const saveProgress = (token, body) => api("/progress", { method: "POST", token, body });

