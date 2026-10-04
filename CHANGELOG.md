# Changelog

## 1.2.0 — 2026-10-03

- Estabilizado el envío del chat mediante `submit`: Enter y el botón Enviar usan el mismo flujo sin navegación accidental.
- Validación de la respuesta HTTP, timeout compatible con navegador y aislamiento de errores de renderizado dentro del widget de chat.
- Chat con contrato estable: `message`, `intent`, `source` y `metadata`; se conserva `response` por compatibilidad.
- Recuperación de ejercicios normalizada para acentos y variaciones españolas, con prioridad para la rutina persistida y sin inventar movimientos.
- Recuperación de recetas desde los 28 días reales del usuario; la receta solicitada ya no se reemplaza por otra comida.
- Respuesta OFF_TOPIC explícita y bloqueada antes de agentes, RAG o LLM.

## 1.1.1 — 2026-10-03

- Corregido el contrato perfil→plan: los metadatos de respuesta (`version` y `plan_needs_regeneration`) ya no se reenvían al guardar.
- Los campos extra continúan bloqueados y ahora se identifican con `INVALID_PROFILE_FIELD` y su nombre concreto.
- Añadida una prueba del perfil de la captura: se guarda y genera un plan persistido de 28 días.
- El calendario ahora refleja objetivo, edad, estatura, peso, horas y días disponibles en el enfoque y las metas nutricionales generales.

## 1.1.0 — 2026-10-03

- Validación de perfil centralizada en el backend antes de guardar y antes de generar el plan.
- Límite seguro de entrenamiento de 1 a 28 horas por semana, con feedback específico para valores que exceden 28 horas.
- Validación de enums, rangos, restricciones alimentarias, días disponibles, duplicados y capacidad semanal según los días elegidos.
- Guardrail independiente para texto de perfil no permitido, sin registrar datos sensibles.
- Validación inmediata en React, errores por campo y botones de guardar/generar deshabilitados mientras el perfil sea inválido.
- Pruebas de frontend y API directa, incluidos intentos de manipulación y revalidación antes de generar.

## 1.0.0 — 2026-10-03

- Primera versión autónoma de FitLife AI.
- Backend FastAPI propio con autenticación JWT, perfiles, planes, progreso y chat.
- PostgreSQL, guardrails, RAG local basado en embeddings locales y adaptador Ollama.
- Frontend React/Vite independiente de AgentOS.
