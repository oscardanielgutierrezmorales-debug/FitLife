import assert from "node:assert/strict";
import test from "node:test";

import { profileFields, toProfilePayload } from "./profileContract.js";

test("el payload de perfil nunca reenvía metadatos de la respuesta", () => {
  const response = {
    language: "es", sex: "non_binary", age: 32, height_cm: 120, weight_kg: 40,
    workout_hours_per_week: 24, goal: "general_fitness", dietary_restrictions: [], available_days: [0, 1, 2, 3],
    version: 7, plan_needs_regeneration: true,
  };
  const payload = toProfilePayload(response);

  assert.deepEqual(Object.keys(payload), profileFields);
  assert.equal(payload.version, undefined);
  assert.equal(payload.plan_needs_regeneration, undefined);
  assert.deepEqual(payload.available_days, [0, 1, 2, 3]);
});
