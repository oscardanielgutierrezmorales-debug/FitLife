import { DaysSelector } from "./DaysSelector";
import { normalizeRestrictions, parseLocalizedNumber, profileNumericRules, profileOptions, validateProfile } from "../../validation/profileRules";

const restrictionLabels = { vegetarian: "Vegetariana", vegan: "Vegana", lactose_free: "Sin lactosa", dairy_free: "Sin lácteos", gluten_free: "Sin gluten", nut_free: "Sin frutos secos" };

export function UserProfileForm({ profile, setProfile, onSave, onGenerate, busy, message, serverErrors = {} }) {
  const set = (key, value) => setProfile({ ...profile, [key]: value });
  const clientErrors = validateProfile(profile);
  const errors = { ...clientErrors, ...serverErrors };
  const invalid = Object.keys(clientErrors).length > 0;
  const field = (key, label, child) => <label key={key} className={errors[key] ? "invalid" : ""}>{label}{child}{errors[key] && <small className="field-error">{errors[key]}</small>}</label>;
  const selectedRestrictions = normalizeRestrictions(profile.dietary_restrictions);
  const toggleRestriction = (item) => set("dietary_restrictions", selectedRestrictions.includes(item) ? selectedRestrictions.filter((value) => value !== item) : [...selectedRestrictions, item]);
  const numericFields = [
    ["age", "Edad", "numeric"],
    ["height_cm", "Estatura (cm)", "decimal"],
    ["weight_kg", "Peso (kg)", "decimal"],
    ["workout_hours_per_week", "Horas/semana", "decimal"],
  ];
  return <section className="profile"><div className="form-grid">{field("language", "Idioma", <select value={profile.language} onChange={(e) => set("language", e.target.value)}><option value="es">Español</option><option value="en">English</option></select>)}{field("sex", "Sexo", <select value={profile.sex || ""} onChange={(e) => set("sex", e.target.value)}><option value="">Seleccionar</option><option value="female">Mujer</option><option value="male">Hombre</option><option value="non_binary">No binario</option><option value="prefer_not_to_say">Prefiero no decirlo</option></select>)}{numericFields.map(([key, label, inputMode]) => { const rule = profileNumericRules[key]; return field(key, label, <input type="number" inputMode={inputMode} min={rule.min} max={rule.max} step={rule.step} value={profile[key] ?? ""} onChange={(e) => set(key, parseLocalizedNumber(e.target.value))} />); })}{field("goal", "Objetivo", <select value={profile.goal} onChange={(e) => set("goal", e.target.value)}><option value="general_fitness">Condición general</option><option value="weight_loss">Composición corporal</option><option value="hypertrophy">Fuerza e hipertrofia</option><option value="endurance">Resistencia</option></select>)}</div><fieldset className={errors.dietary_restrictions ? "invalid" : ""}><legend>Restricciones alimentarias</legend><div className="days">{profileOptions.restrictions.map((item) => <label key={item}><input type="checkbox" checked={selectedRestrictions.includes(item)} onChange={() => toggleRestriction(item)} />{restrictionLabels[item]}</label>)}</div>{errors.dietary_restrictions && <small className="field-error">{errors.dietary_restrictions}</small>}</fieldset><DaysSelector value={profile.available_days} onChange={(value) => set("available_days", value)} error={errors.available_days} />{message && <p className="error">{message}</p>}<div className="actions"><button className="secondary" disabled={busy || invalid} onClick={onSave}>Guardar cambios</button><button className="primary" disabled={busy || invalid} onClick={onGenerate}>Generar plan seguro</button></div>{invalid && <p className="notice">Completa los campos marcados para guardar un perfil seguro.</p>}<p className="notice">FitLife ofrece orientación general de bienestar, no diagnóstico médico ni atención de emergencia.</p></section>;
}
