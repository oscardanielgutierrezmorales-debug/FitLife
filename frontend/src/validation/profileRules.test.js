import assert from "node:assert/strict";
import test from "node:test";

import { normalizeRestrictions, parseLocalizedNumber, validateProfile } from "./profileRules.js";

const valid = (changes = {}) => ({
  language: "es", sex: "female", age: 32, height_cm: 167, weight_kg: 72,
  workout_hours_per_week: 4, goal: "general_fitness", dietary_restrictions: [], available_days: [0, 2, 4], ...changes,
});

test("acepta un perfil válido y normaliza restricciones heredadas", () => {
  assert.deepEqual(validateProfile(valid()), {});
  assert.deepEqual(normalizeRestrictions(["vegana", "vegetariana", "nothing"]), ["vegan"]);
  assert.deepEqual(normalizeRestrictions(["sin lactosa", "sin lácteos"]), ["lactose_free", "dairy_free"]);
});

test("muestra el límite seguro de 28 horas antes de enviar el perfil", () => {
  const errors = validateProfile(valid({ workout_hours_per_week: 132 }));
  assert.equal(errors.workout_hours_per_week, "Las horas semanales ingresadas superan el límite seguro permitido (máximo 28 hrs/semana).");
});

test("rechaza rangos, enums, duplicados y disponibilidad incompatible", () => {
  assert.match(validateProfile(valid({ age: 12 })).age, /13 y 120/);
  assert.match(validateProfile(valid({ height_cm: 300 })).height_cm, /80 y 250/);
  assert.match(validateProfile(valid({ weight_kg: 10 })).weight_kg, /25 y 400/);
  assert.match(validateProfile(valid({ sex: "custom" })).sex, /opciones/);
  assert.match(validateProfile(valid({ available_days: [0, 0] })).available_days, /No repitas/);
  assert.match(validateProfile(valid({ workout_hours_per_week: 7, available_days: [1] })).workout_hours_per_week, /máximo seguro es 6/);
});

test("acepta horas decimales en incrementos de 0.1 y normaliza coma", () => {
  for (const hours of [1, 1.1, 1.5, 2, 28]) {
    const days = hours > 6 ? [0, 1, 2, 3, 4, 5, 6] : [0];
    assert.equal(validateProfile(valid({ workout_hours_per_week: hours, available_days: days })).workout_hours_per_week, undefined);
  }
  assert.match(validateProfile(valid({ workout_hours_per_week: 1.05, available_days: [0] })).workout_hours_per_week, /incrementos de 0.1/);
  assert.equal(parseLocalizedNumber("1,5"), 1.5);
});
