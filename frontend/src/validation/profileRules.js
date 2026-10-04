export const profileOptions = {
  languages: ["es", "en"],
  sex: ["female", "male", "non_binary", "prefer_not_to_say"],
  goals: ["weight_loss", "hypertrophy", "endurance", "general_fitness"],
  restrictions: ["vegetarian", "vegan", "lactose_free", "dairy_free", "gluten_free", "nut_free"],
};
export const profileNumericRules = {
  age: { min: 13, max: 120, step: 1 },
  height_cm: { min: 80, max: 250, step: 0.1 },
  weight_kg: { min: 25, max: 400, step: 0.1 },
  workout_hours_per_week: { min: 1, max: 28, step: 0.1 },
};

const legacyNoRestriction = new Set(["", "none", "nothing", "ninguna", "ninguno", "sin restricciones"]);
const aliases = {
  vegetariana: "vegetarian", vegetariano: "vegetarian", vegan: "vegan", vegana: "vegan", vegano: "vegan",
  "sin lactosa": "lactose_free", "sin lácteos": "dairy_free", "sin lacteos": "dairy_free", "sin gluten": "gluten_free", "sin frutos secos": "nut_free", "sin nueces": "nut_free",
};

export function normalizeRestrictions(values) {
  if (!Array.isArray(values)) return values;
  const normalized = values.map((item) => String(item).trim().toLowerCase()).filter((item) => !legacyNoRestriction.has(item)).map((item) => aliases[item] || item);
  return [...new Set(normalized)].filter((item) => item !== "vegetarian" || !normalized.includes("vegan"));
}

const matchesStep = (value, step) => Math.abs(value / step - Math.round(value / step)) < 1e-8;

export function parseLocalizedNumber(value) {
  if (value === "" || value === null || value === undefined) return null;
  const normalized = String(value).trim().replace(",", ".");
  if (!/^-?\d+(?:\.\d+)?$/.test(normalized)) return Number.NaN;
  return Number(normalized);
}

export function validateProfile(profile) {
  const errors = {};
  if (!profileOptions.languages.includes(profile.language)) errors.language = "El idioma debe ser Español o English.";
  if (!profileOptions.sex.includes(profile.sex)) errors.sex = "Selecciona una de las opciones de sexo disponibles.";
  if (!Number.isInteger(profile.age) || profile.age < 13 || profile.age > 120) errors.age = "La edad debe ser un número entero entre 13 y 120 años.";
  if (!Number.isFinite(profile.height_cm) || profile.height_cm < 80 || profile.height_cm > 250) errors.height_cm = "La estatura debe estar entre 80 y 250.";
  else if (!matchesStep(profile.height_cm, 0.1)) errors.height_cm = "La estatura debe indicarse en incrementos de 0.1.";
  if (!Number.isFinite(profile.weight_kg) || profile.weight_kg < 25 || profile.weight_kg > 400) errors.weight_kg = "El peso debe estar entre 25 y 400.";
  else if (!matchesStep(profile.weight_kg, 0.1)) errors.weight_kg = "El peso debe indicarse en incrementos de 0.1.";
  if (!Number.isFinite(profile.workout_hours_per_week)) errors.workout_hours_per_week = "Las horas semanales deben ser un número entre 1 y 28.";
  else if (profile.workout_hours_per_week > 28) errors.workout_hours_per_week = "Las horas semanales ingresadas superan el límite seguro permitido (máximo 28 hrs/semana).";
  else if (profile.workout_hours_per_week < 1) errors.workout_hours_per_week = "Las horas semanales deben ser de al menos 1 hr/semana.";
  else if (!matchesStep(profile.workout_hours_per_week, 0.1)) errors.workout_hours_per_week = "Las horas semanales deben indicarse en incrementos de 0.1 horas (por ejemplo: 1, 1.1 o 1.5).";
  if (!profileOptions.goals.includes(profile.goal)) errors.goal = "Selecciona uno de los objetivos disponibles de FitLife.";
  const restrictions = normalizeRestrictions(profile.dietary_restrictions);
  if (!Array.isArray(restrictions) || restrictions.some((item) => !profileOptions.restrictions.includes(item))) errors.dietary_restrictions = "Selecciona únicamente las restricciones alimentarias disponibles.";
  else if (Array.isArray(profile.dietary_restrictions) && new Set(profile.dietary_restrictions.map((item) => String(item).trim().toLowerCase())).size !== profile.dietary_restrictions.length) errors.dietary_restrictions = "No repitas restricciones alimentarias.";
  const days = profile.available_days;
  if (!Array.isArray(days) || days.length === 0) errors.available_days = "Selecciona al menos un día disponible.";
  else if (days.length > 7 || days.some((day) => !Number.isInteger(day) || day < 0 || day > 6)) errors.available_days = "Los días disponibles deben estar entre lunes (0) y domingo (6).";
  else if (new Set(days).size !== days.length) errors.available_days = "No repitas días disponibles.";
  if (!errors.available_days && !errors.workout_hours_per_week && profile.workout_hours_per_week > days.length * 6) errors.workout_hours_per_week = `Con ${days.length} día(s) disponible(s), el máximo seguro es ${days.length * 6} hrs/semana (hasta 6 hrs por día).`;
  return errors;
}
