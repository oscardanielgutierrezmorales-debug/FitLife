import { api } from "./api";
export const signUp = (values) => api("/auth/signup", { method: "POST", body: values });
export const login = (values) => api("/auth/login", { method: "POST", body: values });

