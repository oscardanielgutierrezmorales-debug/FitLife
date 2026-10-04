from __future__ import annotations

import logging
import re
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .agents.conversation import asks_last_completed_exercise, classify_conversation_intent, contextual_focus
from .agents.fitness import exercise_response, extract_exercise_entity, find_exercise, find_exercise_in_user_plan
from .agents.nutrition import nutrition_context, plan_nutrition_response
from .agents.planner import generate_plan
from .agents.router import route
from .config import settings
from .db import ChatMessage, ChatSession, Plan, PlanDay, Profile, Progress, SessionLocal, User, UserMemory, init_db
from .guardrails import evaluate_input, validate_output
from .guardrails.input_guardrail import GuardrailDecision
from .llm import LLMUnavailable, LocalLLM
from .rag import LocalRetriever
from .security import hash_password, issue_token, read_token, verify_password
from .validation import ProfileValidationError, validate_profile_data


logger = logging.getLogger("fitlife")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
bearer = HTTPBearer(auto_error=False)
retriever = LocalRetriever(settings.vector_db_path)
llm = LocalLLM()


class Credentials(BaseModel):
    username: str = Field(min_length=3, max_length=80, pattern=r"^[A-Za-z0-9._-]+$")
    password: str = Field(min_length=12, max_length=128)


class ChatPayload(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    session_id: str | None = None


class ProgressPayload(BaseModel):
    date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    completed: bool


def db_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def current_user(credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)], db: Annotated[Session, Depends(db_session)]) -> User:
    if not credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Se requiere iniciar sesión.")
    token = read_token(credentials.credentials)
    user = db.get(User, token["sub"])
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="La sesión ya no existe.")
    return user


def profile_input(profile: Profile) -> dict[str, Any]:
    return {
        "language": profile.language,
        "sex": profile.sex,
        "age": profile.age,
        "height_cm": profile.height_cm,
        "weight_kg": profile.weight_kg,
        "workout_hours_per_week": profile.workout_hours_per_week,
        "goal": profile.goal,
        "dietary_restrictions": profile.dietary_restrictions or [],
        "available_days": profile.available_days or [],
    }


def profile_dict(profile: Profile) -> dict[str, Any]:
    return {**profile_input(profile), "version": profile.version}


def _memory_view(memory: UserMemory | None) -> dict[str, Any] | None:
    if not memory:
        return None
    return {
        "plan_id": memory.plan_id,
        "last_intent": memory.last_intent,
        "last_exercise": memory.last_exercise,
        "last_meal": memory.last_meal,
        "last_workout": memory.last_workout,
        "last_topic": memory.last_topic,
        "updated_at": memory.updated_at,
    }


def invalid_profile_response(exc: ProfileValidationError, *, user_id: str, operation: str) -> HTTPException:
    """Return precise errors without logging personal or health data."""
    logger.info("profile_validation_rejected user_id=%s operation=%s fields=%s", user_id, operation, ",".join(sorted(exc.errors)))
    return HTTPException(status_code=422, detail=exc.detail())


def get_plan(db: Session, user_id: str) -> tuple[Plan, list[PlanDay]]:
    plan = db.scalar(select(Plan).where(Plan.user_id == user_id))
    if not plan:
        raise HTTPException(status_code=404, detail="Aún no tienes un plan. Completa tu perfil y genera uno.")
    days = list(db.scalars(select(PlanDay).where(PlanDay.plan_id == plan.id).order_by(PlanDay.day_index)))
    return plan, days


def plan_view(plan: Plan, days: list[PlanDay]) -> dict[str, Any]:
    return {"id": plan.id, "profile_version": plan.profile_version, "generated_at": plan.generated_at, "completed_days": plan.completed_days or [], "days": [day.payload for day in days]}


def selected_day(days: list[PlanDay]) -> PlanDay:
    today = date.today().isoformat()
    return next((day for day in days if day.date >= today), days[0])


def _plan_state(plan: Plan, days: list[PlanDay]) -> dict[str, Any]:
    """Derive current plan/progress facts from persisted plan rows, not chat memory."""
    completed = set(plan.completed_days or [])
    today = date.today().isoformat()
    calendar_day = next((day for day in days if day.date >= today), days[-1])
    pending = [day for day in days if day.date not in completed and day.date >= today]
    next_day = pending[0] if pending else next((day for day in days if day.date not in completed), None)
    next_workout = next((day for day in pending if day.kind == "workout"), next((day for day in days if day.date not in completed and day.kind == "workout"), None))
    return {
        "day": calendar_day,
        "next_day": next_day,
        "next_workout": next_workout,
        "completed_count": len(completed),
        "total_days": len(days),
        "week": calendar_day.week,
        "day_number": calendar_day.day_index + 1,
    }


def get_current_plan_context(db: Session, user_id: str) -> tuple[Plan, list[PlanDay], dict[str, Any]]:
    """Central source of truth for plan state and completed-workout facts."""
    plan, days = get_plan(db, user_id)
    state = _plan_state(plan, days)
    last_progress = db.scalar(
        select(Progress)
        .where(Progress.user_id == user_id, Progress.plan_id == plan.id, Progress.completed.is_(True))
        .order_by(Progress.completed_at.desc(), Progress.id.desc())
    )
    completed_day = None
    if last_progress:
        completed_day = next((day for day in days if day.date == last_progress.date), None)
    else:
        completed_dates = set(plan.completed_days or [])
        completed_day = next((day for day in reversed(days) if day.date in completed_dates), None)
    if completed_day:
        exercises = completed_day.payload.get("workout", {}).get("exercises", []) if completed_day else []
        state.update({
            "last_completed_day": completed_day,
            "last_completed_at": last_progress.completed_at if last_progress else None,
            "last_completed_workout": _workout_name(completed_day),
            "last_completed_exercise": exercises[-1].get("name") if exercises else None,
        })
    else:
        state.update({"last_completed_day": None, "last_completed_at": None, "last_completed_workout": None, "last_completed_exercise": None})
    return plan, days, state


def _workout_name(day: PlanDay | None) -> str | None:
    if not day:
        return None
    workout = day.payload.get("workout", {})
    return str(workout.get("type") or day.title) if isinstance(workout, dict) else day.title


def _programming(match: dict[str, Any]) -> str:
    exercise = match["exercise"]
    return f"{exercise['sets']} series de {exercise['repetitions']} repeticiones, con {exercise['rest_seconds']} segundos de descanso"


def _plan_question_answer(state: dict[str, Any], *, progress: bool) -> ChatAnswer:
    day, next_day, next_workout = state["day"], state["next_day"], state["next_workout"]
    if progress:
        next_name = _workout_name(next_workout)
        suffix = f" Tu siguiente entrenamiento es {next_name}." if next_name else " Ya no tienes entrenamientos pendientes en este plan."
        return ChatAnswer(
            f"Vas en el día {state['day_number']} de {state['total_days']} de tu plan, correspondiente a la semana {state['week']}. "
            f"Llevas {state['completed_count']} días completados.{suffix}",
            "plan",
            {"conversation_intent": "progress_question", "plan_day": day.date, "last_workout": next_name},
        )
    target = next_day or day
    workout = _workout_name(target)
    meals = target.payload.get("nutrition", {}).get("meals", [])
    meal_names = ", ".join(str(meal.get("name")) for meal in meals[:2] if isinstance(meal, dict))
    return ChatAnswer(
        f"Para el {target.date}, tu plan indica {target.title}. "
        f"Actividad: {workout} durante {target.payload['workout']['duration_minutes']} min."
        + (f" Comidas destacadas: {meal_names}." if meal_names else ""),
        "plan",
        {"conversation_intent": "plan_question", "plan_day": target.date, "last_workout": workout},
    )


def _last_completed_exercise_answer(state: dict[str, Any]) -> ChatAnswer:
    exercise = state.get("last_completed_exercise")
    workout = state.get("last_completed_workout")
    completed_day = state.get("last_completed_day")
    if not exercise or not completed_day:
        return ChatAnswer(
            "Aún no tienes un entrenamiento marcado como completado en este plan, así que no puedo determinar un último ejercicio realizado.",
            "plan",
            {"conversation_intent": "progress_question", "last_completed_exercise": None},
        )
    return ChatAnswer(
        f"El último ejercicio que realizaste fue {exercise}, dentro de {workout}, marcado como completado el {completed_day.date}.",
        "plan",
        {
            "conversation_intent": "progress_question",
            "last_completed_exercise": exercise,
            "last_workout": workout,
            "plan_day": completed_day.date,
        },
    )


def _contextual_answer(memory: UserMemory | None, plan: Plan, days: list[PlanDay], question: str, state: dict[str, Any] | None = None) -> ChatAnswer:
    state = state or _plan_state(plan, days)
    if not memory or not any((memory.last_exercise, memory.last_meal, memory.last_topic, memory.last_workout)):
        return ChatAnswer(
            "Aún no tengo un tema anterior guardado. Tu contexto actual sí está disponible: "
            + _plan_question_answer(state, progress=True).message,
            "memory",
            {"conversation_intent": "contextual_followup"},
        )
    focus = contextual_focus(question)
    if focus == "meal" and memory.last_meal:
        return ChatAnswer(
            f"La última comida que revisamos fue {memory.last_meal}. Nos quedamos en {memory.last_topic or 'esa consulta'}.",
            "memory",
            {"conversation_intent": "contextual_followup", "meal": memory.last_meal},
        )
    if memory.last_exercise:
        match = find_exercise_in_user_plan(extract_exercise_entity(memory.last_exercise), [{"payload": item.payload} for item in days])
        # Older releases could store an unverified parser fragment as the last
        # exercise. Discard it rather than echoing a false conversational fact.
        if not match:
            memory.last_exercise = None
            if memory.last_topic in {"la técnica del ejercicio", "la programación del ejercicio", "la pertenencia a tu rutina"}:
                memory.last_topic = None
            return _contextual_answer(memory, plan, days, question, state)
        detail = f"Nos quedamos en {memory.last_topic or 'esa consulta'} sobre {memory.last_exercise}."
        if match:
            detail += f" En tu rutina de {match['day']['workout']['type']} está programada como {_programming(match)}."
        if state.get("last_completed_exercise"):
            detail += f" Tu último ejercicio marcado como realizado fue {state['last_completed_exercise']}."
        if next_workout := _workout_name(state.get("next_workout")):
            detail += f" Tu próximo entrenamiento es {next_workout}."
        if focus == "exercise":
            response = f"El último ejercicio por el que me preguntaste fue {memory.last_exercise}."
        else:
            response = detail
        return ChatAnswer(
            response,
            "memory",
            {"conversation_intent": "contextual_followup", "exercise": memory.last_exercise, "last_workout": memory.last_workout},
        )
    if memory.last_meal:
        return ChatAnswer(
            f"La última comida que revisamos fue {memory.last_meal}. Nos quedamos en {memory.last_topic or 'esa consulta'}.",
            "memory",
            {"conversation_intent": "contextual_followup", "meal": memory.last_meal},
        )
    return ChatAnswer(
        f"Nos quedamos en {memory.last_topic or 'tu plan'}" + (f", relacionado con {memory.last_workout}." if memory.last_workout else "."),
        "memory",
        {"conversation_intent": "contextual_followup", "last_workout": memory.last_workout},
    )


def _remember(db: Session, *, user_id: str, plan: Plan, result: ChatAnswer) -> None:
    """Persist compact, non-sensitive conversational facts for the account."""
    metadata = result.metadata
    intent = metadata.get("exercise_intent") or metadata.get("conversation_intent")
    if not intent and result.source not in {"plan", "rag", "llm"}:
        return
    memory = db.get(UserMemory, user_id)
    if not memory:
        memory = UserMemory(user_id=user_id)
        db.add(memory)
    memory.plan_id = plan.id
    memory.last_intent = str(intent or "conversation")
    if intent == "contextual_followup":
        return
    if exercise := metadata.get("exercise"):
        memory.last_exercise = str(exercise)
        memory.last_topic = {
            "exercise_instruction": "la técnica del ejercicio",
            "exercise_programming": "la programación del ejercicio",
            "routine_membership": "la pertenencia a tu rutina",
        }.get(str(intent), "tu ejercicio")
    if meal := metadata.get("meal"):
        memory.last_meal = str(meal)
        memory.last_topic = "esa comida del plan"
    if workout := metadata.get("last_workout"):
        memory.last_workout = str(workout)


def _history(db: Session, session_id: str) -> list[str]:
    messages = list(db.scalars(select(ChatMessage).where(ChatMessage.session_id == session_id, ChatMessage.role == "user").order_by(ChatMessage.created_at.desc()).limit(4)))
    return [item.content for item in reversed(messages)]


@dataclass(frozen=True)
class ChatAnswer:
    message: str
    source: str
    metadata: dict[str, Any]


def _plan_summary(day: PlanDay) -> str:
    payload = day.payload
    meals = payload["nutrition"]["meals"]
    return f"Para el {payload['date']} tu plan indica {payload['title']}. Actividad: {payload['workout']['type']} durante {payload['workout']['duration_minutes']} min. Comidas: " + "; ".join(f"{meal['meal_type']}: {meal['name']}" for meal in meals) + "."


async def _agent_answer(*, question: str, intent: str, day: PlanDay, days: list[PlanDay], history: list[str]) -> ChatAnswer:
    if intent == "FITNESS":
        lookup = find_exercise(question, [{"payload": item.payload} for item in days], retriever, history)
        source = (
            "routine_rag"
            if lookup.intent == "exercise_instruction" and lookup.routine_match and lookup.knowledge
            else "routine"
            if lookup.routine_match
            else "rag"
            if lookup.knowledge
            else "not_found"
        )
        metadata = {
            "exercise_intent": lookup.intent,
            "routine_found": lookup.routine_match is not None,
            "technical_guide_found": lookup.knowledge is not None,
            "exercise": (
                lookup.routine_match["exercise"]["name"]
                if lookup.routine_match
                else lookup.knowledge["name"]
                if lookup.knowledge
                else None
            ),
        }
        if lookup.routine_match:
            metadata.update({
                "exercise": lookup.routine_match["exercise"]["name"],
                "date": lookup.routine_match["day"]["date"],
                "last_workout": lookup.routine_match["day"]["workout"]["type"],
            })
        return ChatAnswer(exercise_response(lookup), source, metadata)
    if intent in {"PLAN", "NUTRITION"}:
        exact = plan_nutrition_response(question, {"payload": day.payload}, [{"payload": item.payload} for item in days], history)
        if exact:
            return ChatAnswer(exact, "plan", {"date": day.date, "meal": next((meal["name"] for meal in day.payload["nutrition"]["meals"] if meal["name"].casefold() in exact.casefold()), None)})
    if intent == "PLAN":
        return ChatAnswer(_plan_summary(day), "plan", {"date": day.date})
    source = nutrition_context(question, retriever) if intent == "NUTRITION" else ""
    if source and any(term in question.casefold() for term in ("prepar", "cocin", "receta", "ingrediente")):
        return ChatAnswer(source, "rag", {})
    agent = "nutrición" if intent == "NUTRITION" else "bienestar" if intent == "WELLNESS" else "planificación"
    system = f"Eres el agente local de {agent} de FitLife. Responde en español, de forma concisa y segura. No inventes datos del plan ni fuentes. Para síntomas graves recomienda atención profesional. Contexto recuperado localmente: {source or 'sin resultado específico'}"
    return ChatAnswer(await llm.answer(system=system, user=question), "llm", {})


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    retriever.initialize()
    logger.info("fitlife_started database=%s vector_store=ready", settings.database_url.split("@")[-1])
    yield


app = FastAPI(title="FitLife AI API", version="1.2.4", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=[item.strip() for item in settings.cors_origins.split(",")], allow_credentials=False, allow_methods=["*"], allow_headers=["*"])


@app.exception_handler(Exception)
async def unexpected_error(_: Request, exc: Exception):
    error_id = str(uuid.uuid4())
    logger.exception("request_failed error_id=%s type=%s", error_id, type(exc).__name__)
    return JSONResponse(status_code=500, content={"detail": {"message": "No fue posible completar la operación. Inténtalo de nuevo.", "error_id": error_id}})


@app.get("/health")
def health():
    return {"status": "ok", "service": "fitlife-api", "llm_model": settings.llm_model}


@app.post("/api/v1/auth/signup", status_code=201)
def signup(payload: Credentials, db: Annotated[Session, Depends(db_session)]):
    username = payload.username.casefold()
    if db.scalar(select(User).where(User.username == username)):
        raise HTTPException(status_code=409, detail="Ese nombre de usuario ya está en uso.")
    user = User(username=username, password_hash=hash_password(payload.password))
    db.add(user)
    db.flush()
    db.add(Profile(user_id=user.id))
    db.commit()
    logger.info("auth_signup user_id=%s", user.id)
    return {"access_token": issue_token(user.id, user.username), "token_type": "bearer", "user": {"id": user.id, "username": user.username}}


@app.post("/api/v1/auth/login")
def login(payload: Credentials, db: Annotated[Session, Depends(db_session)]):
    user = db.scalar(select(User).where(User.username == payload.username.casefold()))
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Usuario o contraseña incorrectos.")
    logger.info("auth_login user_id=%s", user.id)
    return {"access_token": issue_token(user.id, user.username), "token_type": "bearer", "user": {"id": user.id, "username": user.username}}


@app.get("/api/v1/auth/me")
def me(user: Annotated[User, Depends(current_user)]):
    return {"id": user.id, "username": user.username}


@app.get("/api/v1/profile")
def read_profile(user: Annotated[User, Depends(current_user)], db: Annotated[Session, Depends(db_session)]):
    profile = db.get(Profile, user.id)
    return profile_dict(profile)


@app.put("/api/v1/profile")
def update_profile(payload: dict[str, Any], user: Annotated[User, Depends(current_user)], db: Annotated[Session, Depends(db_session)]):
    try:
        normalized = validate_profile_data(payload)
    except ProfileValidationError as exc:
        raise invalid_profile_response(exc, user_id=user.id, operation="save") from exc
    profile = db.get(Profile, user.id)
    for name, value in normalized.items():
        setattr(profile, name, value)
    profile.version += 1
    db.commit()
    logger.info("profile_updated user_id=%s profile_version=%s", user.id, profile.version)
    return {**profile_dict(profile), "plan_needs_regeneration": bool(db.scalar(select(Plan).where(Plan.user_id == user.id))) }


@app.post("/api/v1/plan/generate", status_code=201)
def generate_user_plan(user: Annotated[User, Depends(current_user)], db: Annotated[Session, Depends(db_session)]):
    profile = db.get(Profile, user.id)
    try:
        normalized_profile = validate_profile_data(profile_input(profile))
    except ProfileValidationError as exc:
        raise invalid_profile_response(exc, user_id=user.id, operation="generate") from exc
    existing = db.scalar(select(Plan).where(Plan.user_id == user.id))
    if existing:
        db.execute(delete(PlanDay).where(PlanDay.plan_id == existing.id))
        db.delete(existing)
        db.flush()
    plan = Plan(user_id=user.id, profile_version=profile.version, completed_days=[])
    db.add(plan)
    db.flush()
    generated = generate_plan(normalized_profile)
    for item in generated:
        db.add(PlanDay(plan_id=plan.id, date=item["date"], week=item["week"], day_index=item["day_index"], kind=item["kind"], title=item["title"], payload=item))
    memory = db.get(UserMemory, user.id)
    if not memory:
        memory = UserMemory(user_id=user.id)
        db.add(memory)
    memory.plan_id = plan.id
    memory.last_exercise = memory.last_meal = memory.last_workout = memory.last_topic = None
    memory.last_intent = "plan_generated"
    db.commit()
    logger.info("plan_generated user_id=%s plan_id=%s days=%s", user.id, plan.id, len(generated))
    return plan_view(plan, list(db.scalars(select(PlanDay).where(PlanDay.plan_id == plan.id).order_by(PlanDay.day_index))))


@app.get("/api/v1/plan")
def read_plan(user: Annotated[User, Depends(current_user)], db: Annotated[Session, Depends(db_session)]):
    plan, days = get_plan(db, user.id)
    return plan_view(plan, days)


@app.get("/api/v1/context")
def read_context(user: Annotated[User, Depends(current_user)], db: Annotated[Session, Depends(db_session)]):
    """Load durable, account-scoped context without restoring visual chat history."""
    memory = db.get(UserMemory, user.id)
    try:
        plan, days, state = get_current_plan_context(db, user.id)
    except HTTPException:
        return {"memory": _memory_view(memory), "plan": None}
    return {
        "memory": _memory_view(memory),
        "plan": {
            "id": plan.id,
            "day_number": state["day_number"],
            "week": state["week"],
            "completed_days": state["completed_count"],
            "total_days": state["total_days"],
            "next_workout": _workout_name(state["next_workout"]),
        },
    }


@app.get("/api/v1/plan/{plan_date}")
def read_plan_day(plan_date: str, user: Annotated[User, Depends(current_user)], db: Annotated[Session, Depends(db_session)]):
    plan, _ = get_plan(db, user.id)
    day = db.scalar(select(PlanDay).where(PlanDay.plan_id == plan.id, PlanDay.date == plan_date))
    if not day:
        raise HTTPException(status_code=404, detail="Ese día no pertenece a tu plan.")
    return day.payload


@app.post("/api/v1/progress")
def update_progress(payload: ProgressPayload, user: Annotated[User, Depends(current_user)], db: Annotated[Session, Depends(db_session)]):
    plan, _ = get_plan(db, user.id)
    if not db.scalar(select(PlanDay).where(PlanDay.plan_id == plan.id, PlanDay.date == payload.date)):
        raise HTTPException(status_code=404, detail="Ese día no pertenece a tu plan.")
    entry = db.scalar(select(Progress).where(Progress.user_id == user.id, Progress.date == payload.date))
    if not entry:
        entry = Progress(user_id=user.id, plan_id=plan.id, date=payload.date, completed=payload.completed, completed_at=datetime.now(timezone.utc) if payload.completed else None)
        db.add(entry)
    else:
        entry.completed = payload.completed
        entry.plan_id = plan.id
        entry.completed_at = datetime.now(timezone.utc) if payload.completed else None
    completed = list(plan.completed_days or [])
    if payload.completed and payload.date not in completed:
        completed.append(payload.date)
    if not payload.completed:
        completed = [item for item in completed if item != payload.date]
    plan.completed_days = completed
    db.commit()
    return {"date": payload.date, "completed": payload.completed, "completed_at": entry.completed_at, "completed_days": completed}


@app.post("/api/v1/chat")
async def chat(payload: ChatPayload, user: Annotated[User, Depends(current_user)], db: Annotated[Session, Depends(db_session)]):
    conversation_intent = classify_conversation_intent(payload.message)
    decision = evaluate_input(payload.message)
    # A contextual/plan follow-up is inside FitLife's domain even if it has no
    # fitness keyword. Security blocks always keep precedence over this route.
    if not decision.allow and decision.intent == "OFF_TOPIC" and conversation_intent:
        decision = GuardrailDecision(True, "FITLIFE_PLAN")
    logger.info("guardrail_decision user_id=%s intent=%s allow=%s", user.id, decision.intent, decision.allow)
    session = db.get(ChatSession, payload.session_id) if payload.session_id else None
    if session and session.user_id != user.id:
        raise HTTPException(status_code=404, detail="La sesión no existe.")
    if not session:
        session = ChatSession(user_id=user.id)
        db.add(session)
        db.flush()
    history = _history(db, session.id)
    db.add(ChatMessage(session_id=session.id, role="user", content=payload.message, intent=decision.intent))
    if not decision.allow:
        result = ChatAnswer(decision.message or "Esta pregunta está fuera del alcance de FitLife. Puedo ayudarte con tu rutina, ejercicios, alimentación, recetas y tu plan personalizado de 28 días.", "guardrail", {})
    else:
        plan, days, state = get_current_plan_context(db, user.id)
        try:
            if conversation_intent == "contextual_followup":
                result = _contextual_answer(db.get(UserMemory, user.id), plan, days, payload.message, state)
            elif conversation_intent in {"plan_question", "progress_question"}:
                result = _last_completed_exercise_answer(state) if asks_last_completed_exercise(payload.message) else _plan_question_answer(state, progress=conversation_intent == "progress_question")
            else:
                result = await _agent_answer(question=payload.message, intent=route(payload.message), day=selected_day(days), days=days, history=history)
        except LLMUnavailable as exc:
            error_id = str(uuid.uuid4())
            logger.warning("llm_unavailable error_id=%s user_id=%s reason=%s", error_id, user.id, type(exc).__name__)
            raise HTTPException(status_code=503, detail={"message": "El asistente local de FitLife no está disponible en este momento. Inténtalo cuando Ollama esté listo.", "error_id": error_id}) from exc
    # Input-guardrail fallbacks are controlled, deterministic text. Do not
    # replace their specific domain explanation with the generic output-policy
    # fallback; generated/allowed answers still pass through output validation.
    answer = result.message if not decision.allow else validate_output(result.message, intent=decision.intent)
    source = "output_guardrail" if answer != result.message else result.source
    db.add(ChatMessage(session_id=session.id, role="assistant", content=answer, intent=decision.intent))
    if decision.allow:
        _remember(db, user_id=user.id, plan=plan, result=result)
    db.commit()
    logger.info(
        "chat_completed user_id=%s session_id=%s intent=%s source=%s exercise_intent=%s routine_found=%s technical_guide_found=%s",
        user.id, session.id, decision.intent, source,
        result.metadata.get("exercise_intent"), result.metadata.get("routine_found"), result.metadata.get("technical_guide_found"),
    )
    return {"session_id": session.id, "intent": decision.intent, "source": source, "metadata": result.metadata, "message": answer, "response": answer}


@app.get("/api/v1/chat/{session_id}")
def chat_history(session_id: str, user: Annotated[User, Depends(current_user)], db: Annotated[Session, Depends(db_session)]):
    """Return only the authenticated owner's persisted conversation."""
    session = db.get(ChatSession, session_id)
    if not session or session.user_id != user.id:
        raise HTTPException(status_code=404, detail="La sesión no existe.")
    messages = list(db.scalars(select(ChatMessage).where(ChatMessage.session_id == session.id).order_by(ChatMessage.created_at)))
    return {"session_id": session.id, "messages": [{"role": message.role, "content": message.content, "intent": message.intent} for message in messages]}
