import test from "node:test";
import assert from "node:assert/strict";
import { validateCredentials } from "./authRules.js";

test("authentication rules return specific username errors", () => {
  assert.equal(validateCredentials({ username: "", password: "valid-password" }).username, "Ingresa un nombre de usuario.");
  assert.match(validateCredentials({ username: "ab", password: "valid-password" }).username, /al menos 3/);
  assert.match(validateCredentials({ username: "a".repeat(81), password: "valid-password" }).username, /80/);
  assert.match(validateCredentials({ username: "hola mundo", password: "valid-password" }).username, /solo puede contener/);
});

test("authentication rules return specific password errors", () => {
  assert.equal(validateCredentials({ username: "valid.user", password: "" }).password, "Ingresa una contraseña.");
  assert.match(validateCredentials({ username: "valid.user", password: "short" }).password, /al menos 12/);
  assert.match(validateCredentials({ username: "valid.user", password: "x".repeat(129) }).password, /128/);
  assert.deepEqual(validateCredentials({ username: "valid.user", password: "strong-password-123" }), {});
});
