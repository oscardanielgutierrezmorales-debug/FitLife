from datetime import date
from pathlib import Path

from app.agents.fitness import exercise_response, find_exercise
from app.agents.conversation import asks_last_completed_exercise, classify_conversation_intent
from app.guardrails.domain_classifier import classify_domain
from app.agents.planner import generate_plan
from app.agents.nutrition import plan_nutrition_response
from app.agents.router import route
from app.rag.retriever import LocalRetriever
from app.validation.plan_rules import validate_plan_against_profile


def profile():
    return {"age": 32, "height_cm": 167, "weight_kg": 72, "workout_hours_per_week": 4, "goal": "general_fitness", "available_days": [0, 2, 4], "dietary_restrictions": ["sin lactosa"]}


def test_structured_plan_has_28_varied_days_and_respects_days():
    days = generate_plan(profile(), date(2026, 10, 5))
    assert len(days) == 28
    assert all(day["kind"] != "workout" or date.fromisoformat(day["date"]).weekday() in {0, 2, 4} for day in days)
    assert len({tuple(meal["name"] for meal in day["nutrition"]["meals"]) for day in days}) > 20
    assert all(len(day["nutrition"]["meals"]) == 4 for day in days)


def test_exercise_matching_never_accepts_unknown_named_movement(tmp_path):
    retriever = LocalRetriever(str(tmp_path))
    seed = Path("/data/seed/knowledge_base.json")
    retriever.store.source_path = seed if seed.exists() else Path(__file__).parents[2] / "data/knowledge_base.json"
    retriever.initialize()
    days = [{"payload": item} for item in generate_plan(profile(), date(2026, 10, 5))]
    lookup = find_exercise("¿Cómo hago el ejercicio de pecho con mancuernas?", days, retriever, [])
    assert lookup.routine_match and lookup.routine_match["exercise"]["name"] == "Press de pecho con mancuernas"
    unknown = find_exercise("¿Cómo hago un salto de superman?", days, retriever, [])
    assert unknown.routine_match is None and unknown.knowledge is None


def test_exercise_matching_normalizes_accents_and_ignores_accidental_filler(tmp_path):
    retriever = LocalRetriever(str(tmp_path))
    seed = Path("/data/seed/knowledge_base.json")
    retriever.store.source_path = seed if seed.exists() else Path(__file__).parents[2] / "data/knowledge_base.json"
    retriever.initialize()
    days = [{"payload": item} for item in generate_plan(profile(), date(2026, 10, 5))]

    lookup = find_exercise("Como se hace elejercicio de flexion inclinada", days, retriever, [])
    assert lookup.entity.label == "flexion inclinada"
    assert lookup.intent == "exercise_instruction"
    assert lookup.routine_match is not None
    assert lookup.routine_match["exercise"]["name"] == "Flexión inclinada"
    assert lookup.knowledge is not None
    response = exercise_response(lookup)
    assert "Apoya las manos en una superficie estable" in response
    assert "3 series de 8–10 repeticiones" in response


def test_all_visible_current_routine_exercises_match_after_a_noisy_history_turn(tmp_path):
    retriever = LocalRetriever(str(tmp_path))
    seed = Path("/data/seed/knowledge_base.json")
    retriever.store.source_path = seed if seed.exists() else Path(__file__).parents[2] / "data/knowledge_base.json"
    retriever.initialize()
    days = [{"payload": item} for item in generate_plan(profile(), date(2026, 10, 5))]
    history = ["el salto de pokemon se encuentra en mi rutina, como lo hago?"]

    for question, expected in [
        ("como hacer la flexion inclinada", "Flexión inclinada"),
        ("¿Cómo hago la flexión inclinada?", "Flexión inclinada"),
        ("flexion inclinada", "Flexión inclinada"),
        ("¿Cómo hago la sentadilla con peso corporal?", "Sentadilla con peso corporal"),
        ("¿Cómo hago el remo con banda?", "Remo con banda"),
    ]:
        lookup = find_exercise(question, days, retriever, history)
        assert lookup.routine_match is not None
        assert lookup.routine_match["exercise"]["name"] == expected

    unknown = find_exercise("el salto de pokemon se encuentra en mi rutina, como lo hago?", days, retriever, history)
    assert unknown.routine_match is None and unknown.knowledge is None
    assert unknown.entity.label == "salto de pokemon"
    assert "salto de pokemon" in exercise_response(unknown)


def test_rag_exercise_is_explicitly_distinguished_when_not_in_current_routine(tmp_path):
    retriever = LocalRetriever(str(tmp_path))
    seed = Path("/data/seed/knowledge_base.json")
    retriever.store.source_path = seed if seed.exists() else Path(__file__).parents[2] / "data/knowledge_base.json"
    retriever.initialize()
    other_routine = [{"payload": {"workout": {"exercises": [{"name": "Sentadilla a caja"}]}}}]

    lookup = find_exercise("¿Cómo hago remo con banda?", other_routine, retriever, [])
    assert lookup.routine_match is None
    assert lookup.knowledge is not None and "Ancla una banda" in lookup.knowledge["text"]
    response = exercise_response(lookup)
    assert "no aparece en tu rutina actual" in response
    assert "Ancla una banda" in response


def test_exercise_intents_answer_with_the_requested_information(tmp_path):
    retriever = LocalRetriever(str(tmp_path))
    seed = Path("/data/seed/knowledge_base.json")
    retriever.store.source_path = seed if seed.exists() else Path(__file__).parents[2] / "data/knowledge_base.json"
    retriever.initialize()
    days = [{"payload": item} for item in generate_plan(profile(), date(2026, 10, 5))]

    instruction = find_exercise("¿Cómo hago la flexión inclinada?", days, retriever, [])
    programming = find_exercise("¿Cuántas series hago de flexión inclinada?", days, retriever, [])
    membership = find_exercise("¿La flexión inclinada está en mi rutina?", days, retriever, [])
    unknown = find_exercise("¿El salto de superman está en mi rutina?", days, retriever, [])

    assert instruction.intent == "exercise_instruction"
    assert "Apoya las manos" in exercise_response(instruction)
    assert programming.intent == "exercise_programming"
    assert exercise_response(programming).startswith("En tu rutina")
    assert membership.intent == "routine_membership"
    assert exercise_response(membership).startswith("Sí, Flexión inclinada")
    assert unknown.entity.label == "salto de superman"
    assert "No encuentro un ejercicio identificado" in exercise_response(unknown)


def test_routine_exercise_without_a_verified_guide_does_not_invent_technique(tmp_path):
    retriever = LocalRetriever(str(tmp_path))
    seed = Path("/data/seed/knowledge_base.json")
    retriever.store.source_path = seed if seed.exists() else Path(__file__).parents[2] / "data/knowledge_base.json"
    retriever.initialize()
    days = [{"payload": item} for item in generate_plan(profile(), date(2026, 10, 5))]

    lookup = find_exercise("¿Cómo hago la sentadilla con peso corporal?", days, retriever, [])

    assert lookup.routine_match is not None
    assert lookup.knowledge is None
    assert "No tengo una guía técnica verificada" in exercise_response(lookup)


def test_contextual_and_plan_turns_are_routed_before_entity_extraction():
    assert classify_conversation_intent("¿En qué nos quedamos?") == "contextual_followup"
    assert classify_conversation_intent("¿Cuál fue el último ejercicio por el que te pregunté?") == "contextual_followup"
    assert classify_conversation_intent("¿Qué me toca hoy?") == "plan_question"
    assert classify_conversation_intent("¿Qué ejercicio tengo que hacer?") == "plan_question"
    assert classify_conversation_intent("¿Qué día estoy viendo?") == "plan_question"
    assert classify_conversation_intent("¿Qué tengo el 6 de octubre?") == "plan_question"
    assert classify_conversation_intent("¿En qué día voy?") == "progress_question"
    assert classify_conversation_intent("¿Qué día de mi rutina voy?") == "progress_question"
    assert classify_conversation_intent("¿Cuál fue el último ejercicio que hice?") == "progress_question"
    assert asks_last_completed_exercise("¿Cuál fue el último ejercicio que hice?")
    assert classify_conversation_intent("¿Cómo hago la flexión inclinada?") is None


def test_conversational_fitlife_intent_family_and_off_topic_boundary():
    expected = {
        "Hola": "SMALL_TALK",
        "¿Cómo estás?": "SMALL_TALK",
        "Gracias": "SMALL_TALK",
        "¿Qué puedes hacer?": "APP_HELP",
        "Dame un resumen de mi perfil": "PROFILE_SUMMARY",
        "Revisa mi perfil": "PROFILE_REVIEW",
        "Dame un resumen de mi plan": "PLAN_SUMMARY",
        "Dame un resumen general de mi rutina": "ROUTINE_SUMMARY",
        "Resume mi alimentación": "NUTRITION_SUMMARY",
        "¿Cómo voy?": "PROGRESS_SUMMARY",
        "¿Cómo me llamo?": "USER_QUERY",
        "¿Qué ejercicio tengo este día?": "plan_question",
    }
    for question, intent in expected.items():
        assert classify_conversation_intent(question) == intent
        assert route(question) == intent
    assert classify_conversation_intent("¿Cómo hago la flexión inclinada?") is None
    assert route("¿Cómo hago la flexión inclinada?") == "EXERCISE_INSTRUCTION"
    for question in ("¿Cuánto es 2+2?", "Escribe un script en Python", "Háblame de Pokémon"):
        assert classify_conversation_intent(question) is None
        assert classify_domain(question) == "OFF_TOPIC"


def test_structured_constraint_validation_distinguishes_lactose_from_dairy():
    lactose_profile = profile() | {"dietary_restrictions": ["lactose_free"]}
    lactose_plan = generate_plan(lactose_profile, date(2026, 10, 5))
    assert validate_plan_against_profile(lactose_profile, lactose_plan) == {"valid": True, "violations": []}
    assert any(meal["dietary_properties"]["contains_dairy"] for day in lactose_plan for meal in day["nutrition"]["meals"])
    assert all(not meal["dietary_properties"]["contains_lactose"] for day in lactose_plan for meal in day["nutrition"]["meals"])

    dairy_profile = profile() | {"dietary_restrictions": ["dairy_free"]}
    dairy_plan = generate_plan(dairy_profile, date(2026, 10, 5))
    assert validate_plan_against_profile(dairy_profile, dairy_plan)["valid"] is True
    assert all(not meal["dietary_properties"]["contains_dairy"] for day in dairy_plan for meal in day["nutrition"]["meals"])


def test_off_topic_categories_override_misleading_fitlife_verbs():
    assert classify_domain("¿Cómo cocinar un Pokémon?") == "OFF_TOPIC"
    assert classify_domain("¿Cuánto es 2+2?") == "OFF_TOPIC"
    assert classify_domain("¿Cómo hago un script en Python para SQL?") == "OFF_TOPIC"
    assert classify_domain("¿Cómo preparo los tacos?") == "NUTRITION"


def test_recipe_lookup_uses_the_named_meal_from_any_real_plan_day():
    days = generate_plan(profile(), date(2026, 10, 5))
    response = plan_nutrition_response("¿Cómo cocinar los tacos de tortilla de maíz con pollo?", days[0], days)

    assert response is not None
    assert "Tacos de tortilla de maíz con pollo" in response
    assert "tortillas de maíz" in response
    assert "Verduras salteadas" not in response


def test_calories_are_retrieved_from_the_real_plan_day():
    day = generate_plan(profile(), date(2026, 10, 5))[0]
    breakfast = plan_nutrition_response("¿Cuántas calorías tiene mi desayuno?", day)
    dinner = plan_nutrition_response("¿Cuántas calorías tiene la cena?", day)
    assert "desayuno" in breakfast.casefold() and "kcal" in breakfast
    assert "cena" in dinner.casefold() and "Total del día" not in dinner
