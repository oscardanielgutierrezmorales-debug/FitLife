import test from "node:test";
import assert from "node:assert/strict";
import { api } from "./api.js";

test("api distinguishes a network failure", async (context) => {
  const original = globalThis.fetch;
  context.after(() => { globalThis.fetch = original; });
  globalThis.fetch = async () => { throw new TypeError("offline"); };
  await assert.rejects(api("/health"), (error) => error.kind === "network" && /conexión/.test(error.message));
});

test("api preserves structured validation errors", async (context) => {
  const original = globalThis.fetch;
  context.after(() => { globalThis.fetch = original; });
  globalThis.fetch = async () => ({
    ok: false,
    status: 422,
    json: async () => ({ detail: { code: "AUTH_VALIDATION_ERROR", message: "Ingresa una contraseña.", field_errors: { password: "Ingresa una contraseña." } } }),
  });
  await assert.rejects(api("/auth/signup", { method: "POST", body: {} }), (error) => error.kind === "validation" && error.fieldErrors.password === "Ingresa una contraseña.");
});

test("api uses the safe fallback only for an unexpected server failure", async (context) => {
  const original = globalThis.fetch;
  context.after(() => { globalThis.fetch = original; });
  globalThis.fetch = async () => ({ ok: false, status: 500, json: async () => null });
  await assert.rejects(api("/auth/signup", { method: "POST", body: {} }), (error) => error.kind === "server" && /Intenta nuevamente/.test(error.message));
});
