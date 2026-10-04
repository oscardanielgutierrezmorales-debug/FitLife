from __future__ import annotations

import logging
import re
import time
import unicodedata
import uuid
from collections import Counter
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
from .agents.nutrition import nutrition_context, plan_nutrition_answer
from .agents.planner import generate_plan
from .agents.router import route, route_domain
from .config import settings
from .db import ChatMessage, ChatSession, Plan, PlanDay, Profile, Progress, SessionLocal, User, UserMemory, init_db
from .guardrails import evaluate_input, validate_output
from .guardrails.domain_classifier import off_topic_category
from .guardrails.input_guardrail import GuardrailDecision
from .llm import LLMUnavailable, LocalLLM, VertexLLM
from .rag import LocalRetriever
from .security import hash_password, issue_token, read_token, verify_password
from .user_context import UserContext, get_user_context
from .validation import ProfileValidationError, validate_plan_against_profile, validate_profile_data


logger = logging.getLogger("fitlife")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
bearer = HTTPBearer(auto_error=False)
retriever = LocalRetriever(settings.vector_db_path)
llm = VertexLLM() if settings.llm_provider.casefold() == "vertex" else LocalLLM()
PLAN_AFFECTING_PROFILE_FIELDS = {"sex", "age", "height_cm", "weight_kg", "workout_hours_per_week", "goal", "dietary_restrictions", "available_days"}


class Credentials(BaseModel):
    username: str = Field(min_length=3, max_length=80, pattern=r"^[A-Za-z0-9._-]+$")
    password: str = Field(min_length=12, max_length=128)


class ChatPayload(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    session_id: str | None = None
    selected_plan_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")


class ProgressPayload(BaseModel):
    date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    completed: bool


def db_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def current_user(request: Request, credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)], db: Annotated[Session, Depends(db_session)]) -> User:
    if not credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Se requiere iniciar sesión.")
    token = read_token(credentials.credentials)
    user = db.get(User, token["sub"])
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="La sesión ya no existe.")
    request.state.auth_completed_at = time.perf_counter()
    logger.info(
        "auth_completed request_id=%s auth_ms=%s",
        getattr(request.state, "request_id", "unknown"),
        round((request.state.auth_completed_at - getattr(request.state, "request_started_at", request.state.auth_completed_at)) * 1000, 2),
    )
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


def plan_view(plan: Plan, days: list[PlanDay], *, current_profile_version: int | None = None) -> dict[str, Any]:
    return {
        "id": plan.id,
        "profile_version": plan.profile_version,
        "generated_at": plan.generated_at,
        "completed_days": plan.completed_days or [],
        "needs_review": bool(plan.needs_review or (current_profile_version is not None and plan.profile_version != current_profile_version)),
        "days": [day.payload for day in days],
    }


MONTHS = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12,
}


def _fold(value: str) -> str:
    return "".join(char for char in unicodedata.normalize("NFD", value.casefold()) if not unicodedata.combining(char))


def _explicit_plan_date(question: str, days: list[PlanDay]) -> str | None:
    if iso_match := re.search(r"\b\d{4}-\d{2}-\d{2}\b", question):
        return iso_match.group(0)
    text = _fold(question)
    named = re.search(r"\b(\d{1,2})\s+de\s+(" + "|".join(MONTHS) + r")(?:\s+de\s+(\d{4}))?\b", text)
    if not named:
        return None
    requested_day, requested_month = int(named.group(1)), MONTHS[named.group(2)]
    requested_year = int(named.group(3)) if named.group(3) else None
    for plan_day in days:
        parsed = date.fromisoformat(plan_day.date)
        if parsed.day == requested_day and parsed.month == requested_month and (requested_year is None or parsed.year == requested_year):
            return plan_day.date
    return f"{requested_year or date.today().year:04d}-{requested_month:02d}-{requested_day:02d}"


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


def resolve_plan_context(db: Session, user_id: str, *, selected_plan_date: str | None = None, question: str = "") -> tuple[Plan, list[PlanDay], dict[str, Any]]:
    """Resolve explicit date, calendar selection and real date against the authenticated plan."""
    plan, days = get_plan(db, user_id)
    state = _plan_state(plan, days)
    explicit_date = _explicit_plan_date(question, days)
    text = _fold(question)
    if explicit_date:
        target_date, context_source = explicit_date, "explicit_date"
    elif re.search(r"\bhoy\b", text):
        target_date, context_source = date.today().isoformat(), "current_date"
    elif selected_plan_date:
        target_date, context_source = selected_plan_date, "selected_plan_date"
    else:
        target_date, context_source = state["day"].date, "current_date"
    target = next((item for item in days if item.date == target_date), None)
    if not target:
        label = "La fecha seleccionada" if context_source == "selected_plan_date" else "La fecha solicitada"
        raise HTTPException(status_code=422, detail=f"{label} no pertenece a tu plan activo.")
    state.update({
        "day": target,
        "week": target.week,
        "day_number": target.day_index + 1,
        "selected_plan_date": selected_plan_date,
        "explicit_plan_date": explicit_date,
        "context_source": context_source,
        "completed": target.date in set(plan.completed_days or []),
    })
    return plan, days, state


def get_current_plan_context(db: Session, user_id: str, *, selected_plan_date: str | None = None, question: str = "") -> tuple[Plan, list[PlanDay], dict[str, Any]]:
    """Central source of truth for plan selection, progress and completed workouts."""
    plan, days, state = resolve_plan_context(db, user_id, selected_plan_date=selected_plan_date, question=question)
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


def _plan_question_answer(state: dict[str, Any], question: str = "", *, progress: bool) -> ChatAnswer:
    day, next_workout = state["day"], state["next_workout"]
    text = _fold(question)
    if progress:
        next_name = _workout_name(next_workout)
        suffix = f" Tu siguiente entrenamiento es {next_name}." if next_name else " Ya no tienes entrenamientos pendientes en este plan."
        return ChatAnswer(
            f"Has completado {state['completed_count']} de los {state['total_days']} días de tu plan. "
            f"Actualmente estás revisando el día {state['day_number']}, correspondiente al {day.date} ({_workout_name(day)}).{suffix}",
            "plan",
            {"conversation_intent": "progress_question", "plan_day": day.date, "context_source": state["context_source"], "last_workout": next_name, "vertex_called": False},
        )
    target = day
    workout = _workout_name(target)
    meals = target.payload.get("nutrition", {}).get("meals", [])
    metadata = {"conversation_intent": "plan_question", "plan_day": target.date, "context_source": state["context_source"], "last_workout": workout, "vertex_called": False}
    if re.search(r"\b(que|cual) dia.*(viendo|seleccionado|revisando)\b", text):
        return ChatAnswer(
            f"Estás viendo el día {state['day_number']} de tu plan: {target.date}, {workout}.",
            "plan",
            metadata,
        )
    if re.search(r"\b(ejercicio|ejercicios|entrenamiento|rutina)\b", text):
        exercises = target.payload.get("workout", {}).get("exercises", [])
        if exercises:
            metadata["exercise"] = exercises[0]["name"]
            exercise_lines = "\n".join(f"{index}. {exercise['name']}" for index, exercise in enumerate(exercises, start=1))
            return ChatAnswer(
                f"Estás viendo **{workout}** del {target.date}. Tienes:\n{exercise_lines}",
                "plan",
                metadata,
            )
        return ChatAnswer(f"Estás viendo {workout} del {target.date}. Ese día no tiene ejercicios programados; sigue la recuperación indicada en tu plan.", "plan", metadata)
    if re.search(r"\b(comida|desayuno|cena|colacion|alimentacion)\b", text):
        requested_type = next((name for name in ("Desayuno", "Comida", "Colación", "Cena") if _fold(name) in text), None)
        selected_meals = [meal for meal in meals if not requested_type or meal.get("meal_type") == requested_type]
        meal_lines = "\n".join(f"- **{meal['meal_type']}:** {meal['name']}" for meal in selected_meals)
        return ChatAnswer(f"Para el {target.date}, tu plan indica:\n{meal_lines}", "plan", metadata)
    meal_names = ", ".join(str(meal.get("name")) for meal in meals[:2] if isinstance(meal, dict))
    return ChatAnswer(
        f"Para el {target.date}, tu plan indica {target.title}. "
        f"Actividad: {workout} durante {target.payload['workout']['duration_minutes']} min."
        + (f" Comidas destacadas: {meal_names}." if meal_names else ""),
        "plan",
        metadata,
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


def _remember(db: Session, *, user_id: str, plan: Plan | None, result: ChatAnswer) -> None:
    """Persist compact, non-sensitive conversational facts for the account."""
    metadata = result.metadata
    intent = metadata.get("exercise_intent") or metadata.get("conversation_intent")
    if not intent and result.source not in {"plan", "rag", "llm"}:
        return
    memory = db.get(UserMemory, user_id)
    if not memory:
        memory = UserMemory(user_id=user_id)
        db.add(memory)
    memory.plan_id = plan.id if plan else None
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
    if str(intent).endswith("_SUMMARY") or intent in {"PROFILE_REVIEW", "PLAN_AUDIT", "PLAN_CONSTRAINT_CONFLICT"}:
        memory.last_topic = {
            "PROFILE_SUMMARY": "el resumen de tu perfil", "PROFILE_REVIEW": "la revisión de tu perfil",
            "PLAN_SUMMARY": "el resumen de tu plan", "ROUTINE_SUMMARY": "el resumen de tu rutina",
            "NUTRITION_SUMMARY": "el resumen de tu alimentación", "PROGRESS_SUMMARY": "tu progreso",
            "PLAN_AUDIT": "la validación de tu plan", "PLAN_CONSTRAINT_CONFLICT": "una restricción de tu perfil",
        }.get(str(intent), memory.last_topic)


def _history(db: Session, session_id: str) -> list[str]:
    messages = list(db.scalars(select(ChatMessage).where(ChatMessage.session_id == session_id, ChatMessage.role == "user").order_by(ChatMessage.created_at.desc()).limit(4)))
    return [item.content for item in reversed(messages)]


@dataclass(frozen=True)
class ChatAnswer:
    message: str
    source: str
    metadata: dict[str, Any]


RESTRICTION_LABELS = {
    "vegetarian": "Vegetariana", "vegan": "Vegana", "lactose_free": "Sin lactosa",
    "dairy_free": "Sin lácteos", "gluten_free": "Sin gluten", "nut_free": "Sin frutos secos",
}
GOAL_LABELS = {
    "general_fitness": "Condición general", "weight_loss": "Composición corporal",
    "hypertrophy": "Fuerza e hipertrofia", "endurance": "Resistencia",
}
DAY_LABELS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")


def _join_labels(items: list[str]) -> str:
    if not items:
        return "ninguna"
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + f" y {items[-1]}"


def _small_talk_answer(question: str) -> ChatAnswer:
    text = _fold(question)
    if "gracias" in text:
        message = "¡Con gusto! Si necesitas revisar tu perfil, entrenamiento, alimentación o progreso, aquí estoy."
    elif any(term in text for term in ("perfecto", "entendido", "ok", "okay")):
        message = "Perfecto. ¿Quieres revisar tu entrenamiento, tus comidas o cómo vas con el plan?"
    elif "como estas" in text:
        message = "¡Muy bien! Listo para ayudarte con FitLife. ¿Revisamos tu entrenamiento, alimentación o progreso?"
    else:
        message = "¡Hola! Puedo ayudarte con tu perfil, entrenamiento, alimentación y progreso. ¿Qué quieres revisar?"
    return ChatAnswer(message, "social", {"conversation_intent": "SMALL_TALK", "vertex_called": False})


def _app_help_answer() -> ChatAnswer:
    return ChatAnswer(
        "Puedo consultar tu perfil y plan reales, resumir tu rutina, comidas y progreso, explicar ejercicios y recetas, y detectar incompatibilidades entre tu perfil y el plan. Los cambios de perfil se confirman desde **Mi perfil**.",
        "app",
        {"conversation_intent": "APP_HELP", "vertex_called": False},
    )


def _profile_answer(context: UserContext, intent: str, question: str) -> ChatAnswer:
    profile = profile_input(context.profile)
    restrictions = [RESTRICTION_LABELS.get(item, item) for item in profile["dietary_restrictions"]]
    days = [DAY_LABELS[item] for item in profile["available_days"]]
    goal = GOAL_LABELS.get(profile["goal"], profile["goal"])
    metadata = {"conversation_intent": intent, "vertex_called": False, "profile_version": context.profile.version}
    text = _fold(question)
    if intent == "USER_QUERY":
        return ChatAnswer(
            f"No tengo un nombre personal guardado en tu perfil. Tu cuenta autenticada usa el nombre de usuario **{context.user.username}**.",
            "profile",
            metadata,
        )
    if intent == "PROFILE_QUERY":
        if "restric" in text or "dieta considera" in text:
            detail = _join_labels(restrictions) if restrictions else "ninguna restricción alimentaria"
            return ChatAnswer(f"En tu perfil tienes: **{detail}**.", "profile", metadata)
        if "objetivo" in text:
            return ChatAnswer(f"Tu objetivo registrado es **{goal}**.", "profile", metadata)
        if "hora" in text:
            return ChatAnswer(f"Indicaste **{profile['workout_hours_per_week']:g} horas por semana**.", "profile", metadata)
        if "dia" in text:
            return ChatAnswer(f"Tienes **{len(days)} días disponibles**: {_join_labels(days)}.", "profile", metadata)
    stale = bool(context.plan and (context.plan.needs_review or context.plan.profile_version != context.profile.version))
    plan_note = " Tu plan actual necesita regenerarse para aplicar la versión más reciente del perfil." if stale else " Tu plan actual corresponde a esta versión del perfil." if context.plan else " Aún no tienes un plan generado."
    return ChatAnswer(
        "Tu perfil actual indica:\n"
        f"- **Objetivo:** {goal}\n"
        f"- **Disponibilidad:** {profile['workout_hours_per_week']:g} horas por semana\n"
        f"- **Restricciones alimentarias:** {_join_labels(restrictions) if restrictions else 'Ninguna'}\n"
        f"- **Días disponibles:** {_join_labels(days)}.\n\n{plan_note.strip()}",
        "profile",
        metadata,
    )


def _summary_answer(intent: str, context: UserContext, state: dict[str, Any]) -> ChatAnswer:
    plan, days = context.plan, context.days
    assert plan is not None
    metadata = {"conversation_intent": intent, "vertex_called": False, "plan_day": state["day"].date}
    if intent == "PLAN_SUMMARY":
        return ChatAnswer(
            f"Tu plan dura **{len(days)} días**, del {days[0].date} al {days[-1].date}. Has completado **{state['completed_count']} de {len(days)} días** y estás revisando la semana {state['week']}. "
            f"Incluye {sum(day.kind == 'workout' for day in days)} sesiones de entrenamiento y {sum(day.kind != 'workout' for day in days)} días de recuperación o descanso. "
            f"Tu siguiente entrenamiento es **{_workout_name(state['next_workout']) or 'ninguno pendiente'}**.",
            "plan",
            metadata,
        )
    if intent == "ROUTINE_SUMMARY":
        workouts = [day for day in days if day.kind == "workout"]
        types = list(dict.fromkeys(_workout_name(day) for day in workouts))
        durations = [int(day.payload["workout"]["duration_minutes"]) for day in workouts]
        exercises = Counter(exercise["name"] for day in workouts for exercise in day.payload["workout"]["exercises"])
        recurrent = [name for name, _ in exercises.most_common(4)]
        return ChatAnswer(
            f"Tu rutina tiene **{len(workouts)} sesiones en 4 semanas** y combina {_join_labels([str(item) for item in types])}. "
            f"Las sesiones duran entre **{min(durations)} y {max(durations)} minutos**. Los ejercicios más recurrentes son {_join_labels(recurrent)}; el resto de los días prioriza movilidad, recuperación o descanso.",
            "plan",
            metadata,
        )
    if intent == "NUTRITION_SUMMARY":
        calories = [int(day.payload["nutrition"]["daily_calories"]) for day in days]
        restrictions = [RESTRICTION_LABELS.get(item, item) for item in context.profile.dietary_restrictions or []]
        return ChatAnswer(
            "Tu alimentación está organizada en **desayuno, comida, colación y cena** cada día, "
            f"con objetivos diarios entre **{min(calories)} y {max(calories)} kcal**. "
            f"Restricciones aplicadas desde tu perfil: **{_join_labels(restrictions) if restrictions else 'ninguna'}**.",
            "plan",
            {**metadata, "dietary_restrictions": list(context.profile.dietary_restrictions or [])},
        )
    return _plan_question_answer(state, progress=True)


def _plan_audit_answer(context: UserContext, intent: str, question: str) -> ChatAnswer:
    assert context.plan is not None
    profile = profile_input(context.profile)
    audit = validate_plan_against_profile(profile, [day.payload for day in context.days])
    text = _fold(question)
    claimed = next((key for phrase, key in (
        ("sin lactosa", "lactose_free"), ("sin lacteos", "dairy_free"), ("vegano", "vegan"),
        ("vegana", "vegan"), ("vegetariano", "vegetarian"), ("vegetariana", "vegetarian"),
        ("sin gluten", "gluten_free"), ("frutos secos", "nut_free"), ("nueces", "nut_free"),
    ) if phrase in text), None)
    restrictions = set(profile["dietary_restrictions"])
    if not claimed and "lacte" in text and "lactose_free" in restrictions:
        claimed = "lactose_free"
    metadata = {"conversation_intent": intent, "vertex_called": False, "plan_valid": audit["valid"], "violation_count": len(audit["violations"])}
    if claimed and claimed not in restrictions:
        return ChatAnswer(
            f"En tu perfil actual no aparece marcada la restricción **{RESTRICTION_LABELS[claimed]}**. Puedes actualizarla en **Mi perfil** y luego regenerar el plan para aplicarla.",
            "profile_audit",
            metadata,
        )
    stale = context.plan.needs_review or context.plan.profile_version != context.profile.version
    relevant = [item for item in audit["violations"] if item.get("type") == "dietary_restriction" and (not claimed or item.get("restriction") == claimed)]
    if relevant:
        issue = relevant[0]
        return ChatAnswer(
            f"Tienes razón: tu perfil marca **{RESTRICTION_LABELS.get(issue['restriction'], issue['restriction'])}**, pero encontré una incompatibilidad en {issue['meal']} del {issue['date']}: **{issue['item']}**. El plan debe regenerarse antes de considerarlo actualizado.",
            "profile_audit",
            metadata,
        )
    if stale or any(item["type"] == "missing_dietary_metadata" for item in audit["violations"]):
        return ChatAnswer(
            "Consulté tu perfil real. La restricción está registrada, pero el plan fue generado con otra versión del perfil o sin metadatos suficientes para validarlo; debes regenerarlo antes de asumir que la aplica.",
            "profile_audit",
            metadata,
        )
    if claimed == "lactose_free" and "lacte" in text:
        return ChatAnswer(
            "Tu perfil marca **Sin lactosa** y el plan validado no contiene lactosa. Recuerda que *sin lactosa* no significa *sin lácteos*: un producto lácteo certificado sin lactosa puede ser compatible. Si necesitas excluir todos los lácteos, marca **Sin lácteos** en tu perfil y regenera el plan.",
            "profile_audit",
            metadata,
        )
    return ChatAnswer(
        "Validé el plan contra tu perfil actual y no encontré incompatibilidades en restricciones alimentarias, días disponibles, horas semanales ni objetivo.",
        "profile_audit",
        metadata,
    )


def _plan_summary(day: PlanDay) -> str:
    payload = day.payload
    meals = payload["nutrition"]["meals"]
    return f"Para el {payload['date']} tu plan indica {payload['title']}. Actividad: {payload['workout']['type']} durante {payload['workout']['duration_minutes']} min. Comidas: " + "; ".join(f"{meal['meal_type']}: {meal['name']}" for meal in meals) + "."


async def _agent_answer(*, question: str, intent: str, day: PlanDay, days: list[PlanDay], profile: dict[str, Any], memory: UserMemory | None, history: list[str], request_id: str, metrics: dict[str, float | bool]) -> ChatAnswer:
    if intent == "FITNESS":
        rag_started = time.perf_counter()
        exercise_history = [*history, memory.last_exercise] if memory and memory.last_exercise else history
        lookup = find_exercise(question, [{"payload": item.payload} for item in days], retriever, exercise_history)
        metrics["rag_ms"] = round((time.perf_counter() - rag_started) * 1000, 2)
        logger.info("rag_completed request_id=%s intent=%s rag_ms=%s", request_id, intent, metrics["rag_ms"])
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
        rag_started = time.perf_counter()
        exact = plan_nutrition_answer(question, {"payload": day.payload}, [{"payload": item.payload} for item in days], history, retriever)
        metrics["rag_ms"] = round((time.perf_counter() - rag_started) * 1000, 2)
        logger.info("rag_completed request_id=%s intent=%s rag_ms=%s", request_id, intent, metrics["rag_ms"])
        if exact:
            return ChatAnswer(
                exact.message,
                "plan_rag" if exact.knowledge else "plan",
                {"date": exact.day["date"], "meal": exact.meal["name"], "technical_guide_found": bool(exact.knowledge), "dietary_restrictions": list(profile.get("dietary_restrictions") or [])},
            )
    if intent == "PLAN":
        return ChatAnswer(_plan_summary(day), "plan", {"date": day.date})
    rag_started = time.perf_counter()
    source = nutrition_context(question, retriever) if intent == "NUTRITION" else ""
    metrics["rag_ms"] = round(metrics.get("rag_ms", 0.0) + ((time.perf_counter() - rag_started) * 1000), 2)
    if intent == "NUTRITION":
        logger.info("rag_completed request_id=%s intent=%s rag_ms=%s", request_id, intent, metrics["rag_ms"])
    if source and any(term in question.casefold() for term in ("prepar", "cocin", "receta", "ingrediente")):
        return ChatAnswer(source, "rag", {})
    agent = "nutrición" if intent == "NUTRITION" else "bienestar" if intent == "WELLNESS" else "planificación"
    relevant_profile = {"goal": profile.get("goal"), "dietary_restrictions": list(profile.get("dietary_restrictions") or [])} if intent == "NUTRITION" else {"goal": profile.get("goal")}
    system = f"Eres el agente local de {agent} de FitLife. Responde en español, de forma concisa y segura. No inventes datos del plan ni fuentes. Para síntomas graves recomienda atención profesional. Contexto de perfil mínimo: {relevant_profile}. Contexto recuperado localmente: {source or 'sin resultado específico'}"
    metrics["vertex_called"] = isinstance(llm, VertexLLM)
    vertex_started = time.perf_counter()
    if metrics["vertex_called"]:
        logger.info("vertex_started request_id=%s intent=%s", request_id, intent)
    message = await llm.answer(system=system, user=question)
    metrics["vertex_ms"] = round((time.perf_counter() - vertex_started) * 1000, 2) if metrics["vertex_called"] else 0.0
    if metrics["vertex_called"]:
        logger.info("vertex_completed request_id=%s intent=%s vertex_ms=%s", request_id, intent, metrics["vertex_ms"])
    return ChatAnswer(message, "llm", {"vertex_called": metrics["vertex_called"], "profile_context_used": True})


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    retriever.initialize()
    logger.info("fitlife_started database=%s vector_store=ready", settings.database_url.split("@")[-1])
    yield


app = FastAPI(title="FitLife AI API", version="1.2.4", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=[item.strip() for item in settings.cors_origins.split(",")], allow_credentials=False, allow_methods=["*"], allow_headers=["*"])


@app.middleware("http")
async def request_metrics(request: Request, call_next):
    request.state.request_id = str(uuid.uuid4())
    request.state.request_started_at = time.perf_counter()
    logger.info("request_received request_id=%s method=%s path=%s", request.state.request_id, request.method, request.url.path)
    response = await call_next(request)
    total_ms = round((time.perf_counter() - request.state.request_started_at) * 1000, 2)
    response.headers["X-Request-ID"] = request.state.request_id
    logger.info("response_sent request_id=%s status=%s total_ms=%s", request.state.request_id, response.status_code, total_ms)
    return response


@app.exception_handler(Exception)
async def unexpected_error(request: Request, exc: Exception):
    error_id = getattr(request.state, "request_id", str(uuid.uuid4()))
    logger.exception("request_failed error_id=%s type=%s", error_id, type(exc).__name__)
    return JSONResponse(status_code=500, content={"detail": {"message": "No fue posible completar la operación. Inténtalo de nuevo.", "error_id": error_id}}, headers={"X-Request-ID": error_id})


@app.get("/health")
def health():
    return {"status": "ok", "service": "fitlife-api", "llm_provider": settings.llm_provider, "llm_model": getattr(llm, "model", settings.llm_model)}


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
    previous = profile_input(profile)
    changed_fields = {name for name, value in normalized.items() if previous.get(name) != value}
    if changed_fields:
        for name, value in normalized.items():
            setattr(profile, name, value)
        profile.version += 1
    plan = db.scalar(select(Plan).where(Plan.user_id == user.id))
    if plan and changed_fields:
        if changed_fields & PLAN_AFFECTING_PROFILE_FIELDS:
            plan.needs_review = True
        else:
            plan.profile_version = profile.version
    db.commit()
    logger.info("profile_updated user_id=%s profile_version=%s", user.id, profile.version)
    return {**profile_dict(profile), "plan_needs_regeneration": bool(plan and plan.needs_review)}


@app.post("/api/v1/plan/generate", status_code=201)
def generate_user_plan(user: Annotated[User, Depends(current_user)], db: Annotated[Session, Depends(db_session)]):
    profile = db.get(Profile, user.id)
    try:
        normalized_profile = validate_profile_data(profile_input(profile))
    except ProfileValidationError as exc:
        raise invalid_profile_response(exc, user_id=user.id, operation="generate") from exc
    generated = generate_plan(normalized_profile)
    validation = validate_plan_against_profile(normalized_profile, generated)
    if not validation["valid"]:
        logger.error("plan_validation_failed user_id=%s violation_types=%s", user.id, ",".join(sorted({item["type"] for item in validation["violations"]})))
        raise HTTPException(status_code=422, detail={"message": "No fue posible generar un plan compatible con tu perfil.", "violations": validation["violations"]})
    existing = db.scalar(select(Plan).where(Plan.user_id == user.id))
    if existing:
        db.execute(delete(PlanDay).where(PlanDay.plan_id == existing.id))
        db.delete(existing)
        db.flush()
    plan = Plan(user_id=user.id, profile_version=profile.version, completed_days=[], needs_review=False)
    db.add(plan)
    db.flush()
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
    return plan_view(plan, list(db.scalars(select(PlanDay).where(PlanDay.plan_id == plan.id).order_by(PlanDay.day_index))), current_profile_version=profile.version)


@app.get("/api/v1/plan")
def read_plan(user: Annotated[User, Depends(current_user)], db: Annotated[Session, Depends(db_session)]):
    plan, days = get_plan(db, user.id)
    profile = db.get(Profile, user.id)
    return plan_view(plan, days, current_profile_version=profile.version)


@app.get("/api/v1/context")
def read_context(user: Annotated[User, Depends(current_user)], db: Annotated[Session, Depends(db_session)]):
    """Load durable, account-scoped context without restoring visual chat history."""
    context = get_user_context(db, user.id)
    try:
        plan, days, state = get_current_plan_context(db, user.id)
    except HTTPException:
        return {"memory": _memory_view(context.memory), "plan": None}
    return {
        "memory": _memory_view(context.memory),
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
async def chat(payload: ChatPayload, request: Request, user: Annotated[User, Depends(current_user)], db: Annotated[Session, Depends(db_session)]):
    request_id = request.state.request_id
    metrics: dict[str, float | bool] = {"db_ms": 0.0, "rag_ms": 0.0, "vertex_ms": 0.0, "vertex_called": False}
    routing_started = time.perf_counter()
    conversation_intent = classify_conversation_intent(payload.message)
    decision = evaluate_input(payload.message)
    routed_intent = route(payload.message)
    agent_intent = route_domain(payload.message)
    # A contextual/plan follow-up is inside FitLife's domain even if it has no
    # fitness keyword. Security blocks always keep precedence over this route.
    if not decision.allow and decision.intent == "OFF_TOPIC" and conversation_intent and not off_topic_category(payload.message):
        decision = GuardrailDecision(True, "FITLIFE_CONTEXT")
    effective_intent = decision.intent if not decision.allow else (conversation_intent or routed_intent)
    metrics["router_ms"] = round((time.perf_counter() - routing_started) * 1000, 2)
    logger.info("routing_completed request_id=%s intent=%s conversation_intent=%s allow=%s router_ms=%s", request_id, agent_intent, conversation_intent, decision.allow, metrics["router_ms"])
    db_started = time.perf_counter()
    session = db.get(ChatSession, payload.session_id) if payload.session_id else None
    if session and session.user_id != user.id:
        raise HTTPException(status_code=404, detail="La sesión no existe.")
    if not session:
        session = ChatSession(user_id=user.id)
        db.add(session)
        db.flush()
    history = _history(db, session.id)
    db.add(ChatMessage(session_id=session.id, role="user", content=payload.message, intent=effective_intent))
    metrics["db_ms"] = round((time.perf_counter() - db_started) * 1000, 2)
    context_started = time.perf_counter()
    context = get_user_context(db, user.id)
    metrics["db_ms"] = round(float(metrics["db_ms"]) + ((time.perf_counter() - context_started) * 1000), 2)
    plan, days = context.plan, context.days
    if not decision.allow:
        result = ChatAnswer(decision.message or "Esta pregunta está fuera del alcance de FitLife. Puedo ayudarte con tu rutina, ejercicios, alimentación, recetas y tu plan personalizado de 28 días.", "guardrail", {})
    elif conversation_intent == "SMALL_TALK":
        result = _small_talk_answer(payload.message)
    elif conversation_intent == "APP_HELP":
        result = _app_help_answer()
    elif conversation_intent in {"PROFILE_QUERY", "PROFILE_SUMMARY", "PROFILE_REVIEW", "USER_QUERY"}:
        result = _profile_answer(context, conversation_intent, payload.message)
    else:
        if not plan or not days:
            result = ChatAnswer(
                "Tu perfil está disponible, pero aún no tienes un plan activo. Genera uno desde **Mi perfil** para consultar rutina, comidas y progreso.",
                "profile",
                {"conversation_intent": effective_intent, "vertex_called": False},
            )
            state = None
        else:
            plan_started = time.perf_counter()
            plan, days, state = get_current_plan_context(db, user.id, selected_plan_date=payload.selected_plan_date, question=payload.message)
            plan_ms = round((time.perf_counter() - plan_started) * 1000, 2)
            metrics["db_ms"] = round(float(metrics["db_ms"]) + plan_ms, 2)
            logger.info("plan_context_loaded request_id=%s plan_ms=%s selected_plan_date=%s resolved_plan_date=%s context_source=%s", request_id, plan_ms, payload.selected_plan_date, state["day"].date, state["context_source"])
        if plan and days and state is not None:
            try:
                if conversation_intent in {"PLAN_AUDIT", "PLAN_CONSTRAINT_CONFLICT"}:
                    result = _plan_audit_answer(context, conversation_intent, payload.message)
                elif conversation_intent in {"PLAN_SUMMARY", "ROUTINE_SUMMARY", "NUTRITION_SUMMARY", "PROGRESS_SUMMARY"}:
                    result = _summary_answer(conversation_intent, context, state)
                elif conversation_intent == "contextual_followup":
                    result = _contextual_answer(context.memory, plan, days, payload.message, state)
                elif conversation_intent in {"plan_question", "progress_question"}:
                    result = _last_completed_exercise_answer(state) if asks_last_completed_exercise(payload.message) else _plan_question_answer(state, payload.message, progress=conversation_intent == "progress_question")
                else:
                    result = await _agent_answer(question=payload.message, intent=agent_intent, day=state["day"], days=days, profile=profile_input(context.profile), memory=context.memory, history=history, request_id=request_id, metrics=metrics)
            except LLMUnavailable as exc:
                error_id = str(uuid.uuid4())
                logger.warning("llm_unavailable request_id=%s error_id=%s user_id=%s reason=%s", request_id, error_id, user.id, type(exc).__name__)
                raise HTTPException(status_code=503, detail={"message": "No pude completar la respuesta en este momento. Intenta nuevamente.", "error_id": error_id}) from exc
    # Input-guardrail fallbacks are controlled, deterministic text. Do not
    # replace their specific domain explanation with the generic output-policy
    # fallback; generated/allowed answers still pass through output validation.
    answer = result.message if not decision.allow else validate_output(result.message, intent=decision.intent)
    source = "output_guardrail" if answer != result.message else result.source
    db.add(ChatMessage(session_id=session.id, role="assistant", content=answer, intent=effective_intent))
    if decision.allow:
        _remember(db, user_id=user.id, plan=plan, result=result)
    commit_started = time.perf_counter()
    db.commit()
    metrics["db_ms"] = round(float(metrics["db_ms"]) + ((time.perf_counter() - commit_started) * 1000), 2)
    total_ms = round((time.perf_counter() - request.state.request_started_at) * 1000, 2)
    logger.info(
        "chat_completed request_id=%s user_id=%s session_id=%s intent=%s source=%s generated_chars=%s api_chars=%s router_ms=%s db_ms=%s rag_ms=%s vertex_ms=%s vertex_called=%s total_ms=%s exercise_intent=%s routine_found=%s technical_guide_found=%s",
        request_id, user.id, session.id, effective_intent, source,
        len(result.message), len(answer),
        metrics["router_ms"], metrics["db_ms"], metrics["rag_ms"], metrics["vertex_ms"], metrics["vertex_called"], total_ms,
        result.metadata.get("exercise_intent"), result.metadata.get("routine_found"), result.metadata.get("technical_guide_found"),
    )
    return {"request_id": request_id, "session_id": session.id, "intent": effective_intent, "source": source, "metadata": result.metadata, "message": answer, "response": answer, "message_length": len(answer)}


@app.get("/api/v1/chat/{session_id}")
def chat_history(session_id: str, user: Annotated[User, Depends(current_user)], db: Annotated[Session, Depends(db_session)]):
    """Return only the authenticated owner's persisted conversation."""
    session = db.get(ChatSession, session_id)
    if not session or session.user_id != user.id:
        raise HTTPException(status_code=404, detail="La sesión no existe.")
    messages = list(db.scalars(select(ChatMessage).where(ChatMessage.session_id == session.id).order_by(ChatMessage.created_at)))
    return {"session_id": session.id, "messages": [{"id": message.id, "role": message.role, "content": message.content, "intent": message.intent} for message in messages]}
