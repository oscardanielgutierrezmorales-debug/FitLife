import { createContext, useContext, useEffect, useState } from "react";

const AuthContext = createContext(null);
const key = "fitlife.auth.v1";

export function AuthProvider({ children }) {
  const [auth, setAuth] = useState(() => {
    try { return JSON.parse(sessionStorage.getItem(key)); } catch { return null; }
  });
  useEffect(() => { if (auth) sessionStorage.setItem(key, JSON.stringify(auth)); else sessionStorage.removeItem(key); }, [auth]);
  return <AuthContext.Provider value={{ auth, setAuth, logout: () => setAuth(null) }}>{children}</AuthContext.Provider>;
}

export const useAuth = () => useContext(AuthContext);

