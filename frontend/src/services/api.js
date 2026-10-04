const runtimeEnv = import.meta.env || {};
const baseUrl =
  runtimeEnv.VITE_API_URL ||
  "https://fitlife-756089913717.us-central1.run.app/api/v1";

export async function api(path, { method = "GET", token, body, signal } = {}) {
  let response;
  const controller = new AbortController();
  let timedOut = false;
  const abortFromCaller = () => controller.abort();
  if (signal?.aborted) controller.abort();
  else signal?.addEventListener("abort", abortFromCaller, { once: true });
  const timeout = globalThis.setTimeout(() => { timedOut = true; controller.abort(); }, 60000);
  try { response = await fetch(`${baseUrl}${path}`, { method, headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) }, ...(body ? { body: JSON.stringify(body) } : {}), signal: controller.signal }); }
  catch (error) {
    const next = new Error(error?.name === "AbortError" ? timedOut ? "No pude completar la respuesta en este momento. Intenta nuevamente." : "La solicitud fue cancelada." : "No fue posible conectar con FitLife. Revisa tu conexión e intenta nuevamente.");
    next.kind = error?.name === "AbortError" ? "cancelled" : "network";
    throw next;
  }
  finally { globalThis.clearTimeout(timeout); signal?.removeEventListener("abort", abortFromCaller); }
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = data?.detail;
    const fallback = response.status >= 500 ? "No fue posible completar la solicitud. Intenta nuevamente." : "Revisa los datos enviados e intenta nuevamente.";
    const error = new Error(typeof detail === "string" ? detail : detail?.message || fallback);
    error.status = response.status;
    error.code = typeof detail === "object" ? detail?.code : undefined;
    error.kind = response.status === 409 ? "conflict" : response.status === 401 ? "auth" : response.status >= 500 ? "server" : "validation";
    if (detail?.field_errors && typeof detail.field_errors === "object") error.fieldErrors = detail.field_errors;
    throw error;
  }
  if (!data || typeof data !== "object") throw new Error("FitLife devolvió una respuesta no válida. Inténtalo de nuevo.");
  if (import.meta.env.DEV && typeof data.message === "string") console.debug("[FitLife chat] caracteres recibidos por API:", [...data.message].length);
  return data;
}
