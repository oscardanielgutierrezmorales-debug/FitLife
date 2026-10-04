import { useEffect, useState } from "react";
import { validateCredentials } from "../../validation/authRules";

export function LoginForm({ values, onChange, onSubmit, busy, error, fieldErrors = {}, mode, setMode }) {
  const [touched, setTouched] = useState({});
  useEffect(() => setTouched({}), [mode]);
  const clientErrors = validateCredentials(values);
  const errors = { ...clientErrors, ...fieldErrors };
  const visibleError = (field) => (touched[field] || values[field]) ? errors[field] : "";
  const changeMode = (nextMode) => { if (nextMode !== mode) setMode(nextMode); };
  const field = (name, label, input, help) => <label className={visibleError(name) ? "invalid" : ""}>{label}{input}{help && <small>{help}</small>}{visibleError(name) && <small className="field-error">{visibleError(name)}</small>}</label>;

  return <main className="shell"><section className="card auth">
    <p className="eyebrow">FITLIFE AI</p>
    <div className="auth-mode" role="tablist" aria-label="Acceso a FitLife">
      <button type="button" role="tab" aria-selected={mode === "login"} className={mode === "login" ? "active" : ""} onClick={() => changeMode("login")}>Iniciar sesión</button>
      <button type="button" role="tab" aria-selected={mode === "signup"} className={mode === "signup" ? "active" : ""} onClick={() => changeMode("signup")}>Crear cuenta</button>
    </div>
    <h1>{mode === "signup" ? "Crear cuenta" : "Iniciar sesión"}</h1>
    <p className="auth-tagline">Fitness + nutrición personalizada</p>
    <p>{mode === "signup" ? "Crea una cuenta para guardar tu perfil, plan y progreso." : "Accede a tu perfil, plan y progreso guardados."}</p>
    {field("username", "Usuario", <input autoComplete="username" value={values.username} onChange={(event) => onChange("username", event.target.value)} onBlur={() => setTouched({ ...touched, username: true })} placeholder="ej. alex.fit" aria-invalid={Boolean(visibleError("username"))} />, "3–80 caracteres: letras, números, puntos, guiones o guiones bajos.")}
    {field("password", "Contraseña", <input type="password" minLength="12" maxLength="128" autoComplete={mode === "signup" ? "new-password" : "current-password"} value={values.password} onChange={(event) => onChange("password", event.target.value)} onBlur={() => setTouched({ ...touched, password: true })} aria-invalid={Boolean(visibleError("password"))} />, "12–128 caracteres.")}
    {error && !Object.keys(fieldErrors).length && <p className="error">{error}</p>}
    <button className="primary" disabled={busy || Object.keys(clientErrors).length > 0} onClick={onSubmit}>{busy ? "Espera…" : mode === "signup" ? "Crear cuenta" : "Iniciar sesión"}</button>
  </section></main>;
}
