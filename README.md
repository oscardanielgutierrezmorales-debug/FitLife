# FitLife AI (autónomo)

FitLife AI es una aplicación independiente para planes de fitness y nutrición. No necesita AgentOS, su panel, sus APIs, sus agentes ni su base de datos.

## Arquitectura

`React/Vite → FastAPI → PostgreSQL` guarda usuarios, perfiles, calendarios de 28 días, progreso y chat. El backend ejecuta guardrails antes del router. Los datos estructurados del plan son la fuente de verdad; el agente local consulta el índice vectorial propio y Ollama sólo para orientación que no puede resolverse desde el plan.

Servicios de Docker:

- `frontend`: `http://localhost:5180`
- `backend`: `http://localhost:8010`, salud en `/health`
- `postgres`: base exclusiva `fitlife`
- `ollama` y `ollama-init`: modelo local configurado, sin API key externa

## Inicio con Docker

```bash
cd fitlife-app
cp .env.example .env
docker compose up --build
```

La primera ejecución descarga el modelo de Ollama definido por `LLM_MODEL` (por defecto `llama3.2:3b`), por lo que puede tardar. La interfaz queda disponible de inmediato en `http://localhost:5180`; las preguntas que requieran el modelo muestran un estado claro mientras `ollama-init` termina. Si el LLM no está disponible, la API devuelve un mensaje explícito y un identificador de error; nunca el genérico “Unable to process…”.

Para observarlo:

```bash
docker compose ps
docker compose logs -f backend
docker compose logs -f ollama-init
curl http://localhost:8010/health
```

Para detener sólo esta aplicación: `docker compose down`. Para borrar sus datos persistentes: `docker compose down -v`.

## Desarrollo local

Requiere Python 3.11+, Node 20+ y PostgreSQL. Copia `.env.example`, cambia `DATABASE_URL` a tu PostgreSQL local, luego:

```bash
cd backend
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8010

cd ../frontend
npm install
VITE_API_URL=http://localhost:8010/api/v1 npm run dev
```

Para el modelo local fuera de Docker instala Ollama, ejecuta `ollama pull llama3.2:3b` y `ollama serve`.

## Variables de entorno

Todas las variables reales están en `.env.example`: `DATABASE_URL`, `JWT_SECRET`, `JWT_EXPIRES_MINUTES`, `LLM_BASE_URL`, `LLM_MODEL`, `LLM_TIMEOUT_SECONDS`, `VECTOR_DB_PATH`, `CORS_ORIGINS` y `VITE_API_URL`. No se requiere una clave de proveedor externo.

## RAG local

El índice local se crea con `data/knowledge_base.json` y un embedding determinista local (`LocalHashEmbeddings`), sin enviar textos a proveedores externos. Para agregar fuentes como USDA, Open Food Facts, WGER, RepDB o Free Exercise DB, normalízalas a `id`, `kind`, `name`, `aliases`, `text` y ejecuta:

```bash
cd backend
PYTHONPATH=. python -m app.rag.ingest
```

Para descargar y normalizar de forma opcional Open Food Facts y WGER, sin
introducir una dependencia de ejecución, usa `python scripts/ingest_public_sources.py`.

La carpeta de vectores se persiste en el volumen `fitlife-vectors`.

## Tests

```bash
cd backend
PYTHONPATH=. pytest tests -q
```

En el frontend:

```bash
cd frontend
npm test
npm run build
```

Cubren guardrails, plan de 28 días, restricciones/días disponibles, matching de ejercicio, aislamiento de usuarios y la matriz de validación del perfil. Incluyen regresiones de historial ruidoso: una pregunta previa no puede impedir recuperar una `flexión inclinada` visible en la rutina. La prueba de chat OFF_TOPIC demuestra que se bloquea antes de llamar al LLM.

## Reglas del perfil seguro

El backend es la fuente de verdad y vuelve a validar el perfil antes de guardar y antes de generar un plan. El formulario replica estas reglas para dar feedback inmediato, pero una llamada directa a la API no puede omitirlas.

- Idioma: `es` o `en`; sexo: mujer, hombre, no binario o prefiero no decirlo.
- Edad: entero de 13 a 120; estatura: 80–250 cm; peso: 25–400 kg.
- Entrenamiento: 1–28 horas por semana y como máximo 6 horas por cada día disponible.
- Objetivos: composición corporal, fuerza/hipertrofia, resistencia o condición general.
- Días: entre lunes (0) y domingo (6), sin repetidos y al menos uno.
- Restricciones compatibles: vegetariana, vegana, sin lactosa, sin gluten y sin frutos secos. Pueden combinarse; una dieta vegana absorbe la vegetariana.

Los errores se devuelven como `422` con `field_errors`, sin almacenar el perfil inválido. Los intentos de texto de control o inyección pasan por un guardrail separado y tampoco se persisten.

### Contrato perfil → plan

El único payload editable de `PUT /api/v1/profile` contiene exactamente:

```json
{
  "language": "es",
  "sex": "non_binary",
  "age": 32,
  "height_cm": 120,
  "weight_kg": 40,
  "workout_hours_per_week": 24,
  "goal": "general_fitness",
  "dietary_restrictions": [],
  "available_days": [0, 1, 2, 3]
}
```

`version` y `plan_needs_regeneration` son metadatos de respuesta, no campos editables. El frontend los separa antes de enviar el `PUT`; el backend mantiene su rechazo explícito para cualquier campo adicional.

## Chat seguro y contextual

El chat usa exclusivamente el plan del usuario autenticado. Para ejercicios, primero extrae el nombre solicitado del mensaje actual y lo busca en todas las jornadas persistidas de esa cuenta; el historial sólo complementa preguntas sin entidad, como `¿cuántas series?`. Después clasifica la petición: una pregunta de técnica consulta la guía verificada en la base local y combina esa explicación con la programación del plan; una pregunta de membresía o series responde únicamente desde la rutina. La prioridad de recuperación es: rutina persistida, comidas persistidas, base local/RAG y, cuando procede, el modelo local. Las consultas fuera de fitness, nutrición, bienestar o el plan se bloquean antes de alcanzar agentes, RAG o LLM.

Cada respuesta incluye `message`, `intent`, `source` (`routine`, `plan`, `rag`, `guardrail` o `not_found`) y `metadata`. La interfaz conserva los mensajes y muestra los errores dentro del widget; Enter y el botón Enviar comparten el mismo envío.

### Memoria y progreso persistentes

El historial visual es una sesión de interfaz y se limpia al cerrar sesión. En
cambio, el backend guarda una memoria estructurada, asociada exclusivamente al
usuario autenticado: último ejercicio, comida, workout, intención y tema. El
endpoint `GET /api/v1/context` recupera esta memoria junto con el día, semana,
progreso y próximo entrenamiento calculados desde el plan persistido. Por eso
preguntas como “¿en qué nos quedamos?” o “¿cuál fue el último ejercicio?” no
dependen del navegador ni se confunden con nombres de ejercicios.

Las marcas de progreso se guardan por plan, fecha y momento de finalización.
Al volver a iniciar sesión, el calendario recupera esos datos reales; una
cuenta nunca puede leer contexto, sesiones ni progreso de otra cuenta.

Las preguntas de seguimiento se clasifican antes de la extracción de
entidades: “último ejercicio que hice” usa progreso real, mientras que
“último ejercicio por el que te pregunté” usa memoria conversacional. El
guardrail de entrada bloquea programación, matemáticas, videojuegos y otros
temas generales antes de llegar al RAG o al modelo local, sin confundir una
solicitud de ejercicio desconocido con una pregunta ajena.

## Límites de seguridad

FitLife ofrece orientación general de bienestar, no diagnóstico médico ni atención de emergencia. El modelo nunca determina qué hay en un plan: las tablas `plans` y `plan_days` son la única fuente para rutina, comidas, calorías, progreso y validación de ejercicios.
