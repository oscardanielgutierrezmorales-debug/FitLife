/** Canonical API contract for the editable FitLife profile. */
export const profileFields = [
  "language", "sex", "age", "height_cm", "weight_kg",
  "workout_hours_per_week", "goal", "dietary_restrictions", "available_days",
];

export function toProfilePayload(source) {
  return Object.fromEntries(profileFields.map((field) => [field, source[field]]));
}
