const baseUrl = import.meta.env.VITE_API_URL || "http://localhost:8010/api/v1";

export async function api(path, { method = "GET", token, body } = {}) {
  let response;
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), 60000);
  try { response = await fetch(`${baseUrl}${path}`, { method, headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) }, ...(body ? { body: JSON.stringify(body) } : {}), signal: controller.signal }); }
  catch (error) { throw new Error(error?.name === "AbortError" ? "La solicitud tardó demasiado. Inténtalo de nuevo." : "No fue posible conectar con FitLife. Revisa que el servicio esté activo."); }
  finally { window.clearTimeout(timeout); }
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = data?.detail;
    const error = new Error(typeof detail === "string" ? detail : detail?.message || "No fue posible completar la solicitud.");
    if (detail?.field_errors && typeof detail.field_errors === "object") error.fieldErrors = detail.field_errors;
    throw error;
  }
  if (!data || typeof data !== "object") throw new Error("FitLife devolvió una respuesta no válida. Inténtalo de nuevo.");
  return data;
}
