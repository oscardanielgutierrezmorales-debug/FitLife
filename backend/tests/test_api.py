import os
from concurrent.futures import ThreadPoolExecutor

os.environ["DATABASE_URL"] = "sqlite:////tmp/fitlife-api-test.db"
os.environ["VECTOR_DB_PATH"] = "/tmp/fitlife-api-vectors"
os.environ["JWT_SECRET"] = "test-secret"

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402
from app.llm import LLMUnavailable  # noqa: E402


def signup(client, username):
    response = client.post("/api/v1/auth/signup", json={"username": username, "password": "strong-password-123"})
    assert response.status_code == 201, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def profile():
    return {"language": "es", "sex": "male", "age": 32, "height_cm": 167, "weight_kg": 72, "workout_hours_per_week": 4, "goal": "general_fitness", "dietary_restrictions": [], "available_days": [0, 2, 4]}


def observed_profile(**changes):
    value = {"language": "es", "sex": "male", "age": 50, "height_cm": 190, "weight_kg": 70, "workout_hours_per_week": 18, "goal": "general_fitness", "dietary_restrictions": ["sin lactosa"], "available_days": [0, 1, 2, 3, 6]}
    value.update(changes)
    return value


def test_auth_isolation_plan_and_blocked_chat():
    with TestClient(app) as client:
        first, second = signup(client, "fitlife-user-a"), signup(client, "fitlife-user-b")
        assert client.put("/api/v1/profile", headers=first, json=profile()).status_code == 200
        generated = client.post("/api/v1/plan/generate", headers=first)
        assert generated.status_code == 201
        assert len(generated.json()["days"]) == 28
        assert client.get("/api/v1/plan", headers=second).status_code == 404
        blocked = client.post("/api/v1/chat", headers=first, json={"message": "Dime las leyes de Newton"})
        assert blocked.status_code == 200
        assert blocked.json()["intent"] == "OFF_TOPIC"
        assert "FitLife" in blocked.json()["response"]
        logged_in = client.post("/api/v1/auth/login", json={"username": "fitlife-user-a", "password": "strong-password-123"})
        assert logged_in.status_code == 200
        exercise = client.post("/api/v1/chat", headers=first, json={"message": "¿Cómo hago el press de pecho con mancuernas?"})
        assert exercise.status_code == 200 and "Press de pecho" in exercise.json()["response"]
        follow_up = client.post("/api/v1/chat", headers=first, json={"message": "¿Cuántas series hago?", "session_id": exercise.json()["session_id"]})
        assert follow_up.status_code == 200 and "series" in follow_up.json()["response"]
        history = client.get(f"/api/v1/chat/{exercise.json()['session_id']}", headers=first)
        assert history.status_code == 200 and len(history.json()["messages"]) == 4
        assert client.get(f"/api/v1/chat/{exercise.json()['session_id']}", headers=second).status_code == 404


def test_unavailable_local_llm_is_explicit_not_a_generic_error(monkeypatch):
    async def unavailable(**_):
        raise LLMUnavailable("model is still downloading")

    monkeypatch.setattr("app.main.llm.answer", unavailable)
    with TestClient(app) as client:
        headers = signup(client, "fitlife-user-c")
        assert client.put("/api/v1/profile", headers=headers, json=profile()).status_code == 200
        assert client.post("/api/v1/plan/generate", headers=headers).status_code == 201
        response = client.post("/api/v1/chat", headers=headers, json={"message": "¿Qué proteína recomiendas después de entrenar?"})
        assert response.status_code == 503
        assert response.json()["detail"]["message"] == "No pude completar la respuesta en este momento. Intenta nuevamente."

        recovered = client.post("/api/v1/chat", headers=headers, json={"message": "¿Qué me toca hoy?"})
        assert recovered.status_code == 200
        assert recovered.json()["metadata"]["vertex_called"] is False


def test_recipe_requests_resolve_the_exact_plan_meal_and_current_meal_type():
    with TestClient(app) as client:
        headers = signup(client, "fitlife-recipes")
        assert client.put("/api/v1/profile", headers=headers, json=profile()).status_code == 200
        plan = client.post("/api/v1/plan/generate", headers=headers).json()

        exact = client.post("/api/v1/chat", headers=headers, json={"message": "Dame la receta de la ensalada de garbanzos"})
        assert exact.status_code == 200, exact.text
        assert "Ensalada de garbanzo" in exact.json()["message"]
        assert "Sopa de lentejas" not in exact.json()["message"]
        assert exact.json()["metadata"]["meal"].startswith("Ensalada de garbanzo")

        current_lunch = next(meal for meal in plan["days"][0]["nutrition"]["meals"] if meal["meal_type"] == "Comida")
        generic = client.post("/api/v1/chat", headers=headers, json={"message": "Dame una receta para cocinar mi comida"})
        assert generic.status_code == 200, generic.text
        assert current_lunch["name"] in generic.json()["message"]
        assert generic.json()["metadata"]["meal"] == current_lunch["name"]

        for meal_type, question in [("Desayuno", "¿Cómo preparo mi desayuno?"), ("Cena", "¿Cómo preparo mi cena?")]:
            expected = next(meal for meal in plan["days"][0]["nutrition"]["meals"] if meal["meal_type"] == meal_type)
            response = client.post("/api/v1/chat", headers=headers, json={"message": question})
            assert response.status_code == 200, response.text
            assert expected["name"] in response.json()["message"]


def test_profile_context_is_authoritative_and_lactose_plan_is_validated(monkeypatch):
    async def llm_must_not_run(**_):
        raise AssertionError("profile and audit queries must remain deterministic")

    monkeypatch.setattr("app.main.llm.answer", llm_must_not_run)
    with TestClient(app) as client:
        headers = signup(client, "fitlife-profile-context")
        saved = client.put("/api/v1/profile", headers=headers, json=observed_profile())
        assert saved.status_code == 200
        assert saved.json()["dietary_restrictions"] == ["lactose_free"]
        plan = client.post("/api/v1/plan/generate", headers=headers)
        assert plan.status_code == 201, plan.text
        assert all(
            not meal["dietary_properties"]["contains_lactose"]
            for day in plan.json()["days"] for meal in day["nutrition"]["meals"]
        )

        restrictions = client.post("/api/v1/chat", headers=headers, json={"message": "¿Qué restricciones alimentarias tengo?"})
        assert restrictions.json()["intent"] == "PROFILE_QUERY"
        assert "Sin lactosa" in restrictions.json()["message"]
        review = client.post("/api/v1/chat", headers=headers, json={"message": "Revisa mi perfil"})
        assert review.json()["intent"] == "PROFILE_REVIEW"
        assert "18 horas" in review.json()["message"]
        assert "no tengo acceso" not in review.json()["message"].casefold()
        audit = client.post("/api/v1/chat", headers=headers, json={"message": "¿Mi plan respeta que soy sin lactosa?"})
        assert audit.json()["source"] == "profile_audit"
        assert audit.json()["metadata"]["plan_valid"] is True
        conflict = client.post("/api/v1/chat", headers=headers, json={"message": "Me estás poniendo en el desayuno un producto con lácteo"})
        assert "Sin lactosa" in conflict.json()["message"]
        assert "sin lácteos" in conflict.json()["message"]
        assert "no tengo acceso" not in conflict.json()["message"].casefold()

        nutrition = client.post("/api/v1/chat", headers=headers, json={"message": "¿Cómo preparo mi desayuno?"})
        assert nutrition.status_code == 200
        assert nutrition.json()["metadata"]["dietary_restrictions"] == ["lactose_free"]


def test_profile_change_marks_plan_for_review_and_invalid_generation_is_not_persisted(monkeypatch):
    with TestClient(app) as client:
        headers = signup(client, "fitlife-profile-review")
        assert client.put("/api/v1/profile", headers=headers, json=observed_profile(dietary_restrictions=[])).status_code == 200
        original = client.post("/api/v1/plan/generate", headers=headers).json()
        changed = client.put("/api/v1/profile", headers=headers, json=observed_profile(dietary_restrictions=["lactose_free"]))
        assert changed.json()["plan_needs_regeneration"] is True
        assert client.get("/api/v1/plan", headers=headers).json()["needs_review"] is True

        regenerated = client.post("/api/v1/plan/generate", headers=headers)
        assert regenerated.status_code == 201
        assert regenerated.json()["needs_review"] is False
        valid_id = regenerated.json()["id"]
        unchanged = client.put("/api/v1/profile", headers=headers, json=observed_profile(dietary_restrictions=["lactose_free"]))
        assert unchanged.json()["plan_needs_regeneration"] is False
        assert client.get("/api/v1/plan", headers=headers).json()["needs_review"] is False

        monkeypatch.setattr("app.main.validate_plan_against_profile", lambda *_: {"valid": False, "violations": [{"type": "dietary_restriction"}]})
        rejected = client.post("/api/v1/plan/generate", headers=headers)
        assert rejected.status_code == 422
        assert client.get("/api/v1/plan", headers=headers).json()["id"] == valid_id


def test_complete_fitlife_conversation_and_profile_isolation(monkeypatch):
    async def llm_must_not_run(**_):
        raise AssertionError("the tested conversation is deterministic or RAG-backed")

    monkeypatch.setattr("app.main.llm.answer", llm_must_not_run)
    with TestClient(app) as client:
        first = signup(client, "fitlife-conversation-a")
        second = signup(client, "fitlife-conversation-b")
        assert client.put("/api/v1/profile", headers=first, json=observed_profile()).status_code == 200
        assert client.put("/api/v1/profile", headers=second, json=observed_profile(dietary_restrictions=[])).status_code == 200
        plan = client.post("/api/v1/plan/generate", headers=first).json()
        assert client.post("/api/v1/plan/generate", headers=second).status_code == 201
        selected = next(day for day in plan["days"] if day["workout"]["exercises"])

        session_id = None
        turns = [
            ("Hola", "SMALL_TALK", {}),
            ("Dame un resumen de mi perfil", "PROFILE_SUMMARY", {}),
            ("¿Y de mi plan?", "PLAN_SUMMARY", {}),
            ("¿Cómo voy?", "PROGRESS_SUMMARY", {}),
            ("¿Qué ejercicio tengo este día?", "plan_question", {"selected_plan_date": selected["date"]}),
            ("¿Cómo hago ese ejercicio?", "EXERCISE_INSTRUCTION", {}),
            ("Gracias", "SMALL_TALK", {}),
        ]
        technique = None
        for question, expected_intent, extra in turns:
            response = client.post("/api/v1/chat", headers=first, json={"message": question, "session_id": session_id, **extra})
            assert response.status_code == 200, response.text
            assert response.json()["intent"] == expected_intent
            assert response.json()["intent"] != "OFF_TOPIC"
            session_id = response.json()["session_id"]
            if question == "¿Cómo hago ese ejercicio?":
                technique = response.json()
        assert technique is not None
        assert technique["source"] in {"routine_rag", "routine"}
        assert selected["workout"]["exercises"][0]["name"] in technique["message"]

        first_profile = client.post("/api/v1/chat", headers=first, json={"message": "¿Qué restricciones alimentarias tengo?"})
        second_profile = client.post("/api/v1/chat", headers=second, json={"message": "¿Qué restricciones alimentarias tengo?"})
        assert "Sin lactosa" in first_profile.json()["message"]
        assert "ninguna restricción" in second_profile.json()["message"].casefold()


def test_general_fitness_nutrition_and_contextual_followup_use_profile_without_promises(monkeypatch):
    async def llm_must_not_run(**_):
        raise AssertionError("general guidance is deterministic")

    monkeypatch.setattr("app.main.llm.answer", llm_must_not_run)
    with TestClient(app) as client:
        headers = signup(client, "fitlife-general-guidance")
        assert client.put("/api/v1/profile", headers=headers, json=profile()).status_code == 200
        assert client.post("/api/v1/plan/generate", headers=headers).status_code == 201

        fitness = client.post("/api/v1/chat", headers=headers, json={"message": "¿En cuánto tiempo genero resistencia?"})
        assert fitness.status_code == 200, fitness.text
        assert fitness.json()["intent"] == "GENERAL_FITNESS_QUERY"
        assert "no existe un plazo exacto" in fitness.json()["message"]
        assert "Condición general" in fitness.json()["message"]

        followup = client.post("/api/v1/chat", headers=headers, json={
            "message": "Es parte del perfil",
            "session_id": fitness.json()["session_id"],
        })
        assert followup.status_code == 200, followup.text
        assert followup.json()["intent"] == "contextual_followup"
        assert "contexto de tu perfil" in followup.json()["message"]
        assert "fuera" not in followup.json()["message"].casefold()

        nutrition = client.post("/api/v1/chat", headers=headers, json={"message": "¿Para qué sirve la proteína?"})
        assert nutrition.status_code == 200, nutrition.text
        assert nutrition.json()["intent"] == "GENERAL_NUTRITION_QUERY"
        assert "reparar tejidos" in nutrition.json()["message"]

        blocked = client.post("/api/v1/chat", headers=headers, json={"message": "Escribe código Python"})
        assert blocked.status_code == 200
        assert blocked.json()["intent"] == "OFF_TOPIC"


def test_selected_calendar_day_is_authoritative_for_deterministic_plan_questions(monkeypatch):
    async def vertex_must_not_run(**_):
        raise AssertionError("deterministic plan questions must not call the LLM")

    monkeypatch.setattr("app.main.llm.answer", vertex_must_not_run)
    with TestClient(app) as client:
        headers = signup(client, "fitlife-selected-day")
        assert client.put("/api/v1/profile", headers=headers, json=profile()).status_code == 200
        plan = client.post("/api/v1/plan/generate", headers=headers).json()
        workout_days = [day for day in plan["days"] if day["workout"]["exercises"]]
        assert len(workout_days) >= 3

        for selected in [workout_days[0], workout_days[1], workout_days[2], workout_days[1]]:
            response = client.post(
                "/api/v1/chat",
                headers=headers,
                json={"message": "¿Qué ejercicio tengo que hacer?", "selected_plan_date": selected["date"]},
            )
            assert response.status_code == 200, response.text
            assert response.json()["intent"] == "plan_question"
            assert response.json()["metadata"]["plan_day"] == selected["date"]
            assert response.json()["metadata"]["context_source"] == "selected_plan_date"
            assert selected["workout"]["type"] in response.json()["message"]
            for exercise in selected["workout"]["exercises"]:
                assert exercise["name"] in response.json()["message"]
            assert response.json()["metadata"]["vertex_called"] is False

        progress = client.post(
            "/api/v1/chat",
            headers=headers,
            json={"message": "¿Qué día de mi rutina voy?", "selected_plan_date": workout_days[1]["date"]},
        )
        assert progress.status_code == 200, progress.text
        assert progress.json()["intent"] == "progress_question"
        assert progress.json()["metadata"]["plan_day"] == workout_days[1]["date"]
        assert "día voy" not in progress.json()["message"].casefold()

        # An explicit date wins over a conflicting calendar selection.
        explicit = client.post(
            "/api/v1/chat",
            headers=headers,
            json={"message": f"¿Qué ejercicio tengo el {workout_days[2]['date']}?", "selected_plan_date": workout_days[0]["date"]},
        )
        assert explicit.status_code == 200, explicit.text
        assert explicit.json()["metadata"]["plan_day"] == workout_days[2]["date"]
        assert explicit.json()["metadata"]["context_source"] == "explicit_date"

        invalid = client.post(
            "/api/v1/chat",
            headers=headers,
            json={"message": "¿Qué ejercicio tengo que hacer?", "selected_plan_date": "1999-01-01"},
        )
        assert invalid.status_code == 422


def test_simultaneous_selected_dates_do_not_leak_between_requests_or_users(monkeypatch):
    async def vertex_must_not_run(**_):
        raise AssertionError("selected-day lookups must stay deterministic")

    monkeypatch.setattr("app.main.llm.answer", vertex_must_not_run)
    with TestClient(app) as client:
        first, second = signup(client, "fitlife-concurrent-a"), signup(client, "fitlife-concurrent-b")
        for headers in (first, second):
            assert client.put("/api/v1/profile", headers=headers, json=profile()).status_code == 200
        first_plan = client.post("/api/v1/plan/generate", headers=first).json()
        second_plan = client.post("/api/v1/plan/generate", headers=second).json()
        first_day = next(day for day in first_plan["days"] if day["workout"]["exercises"])
        second_day = [day for day in second_plan["days"] if day["workout"]["exercises"]][1]

        def ask(headers, selected):
            return client.post("/api/v1/chat", headers=headers, json={"message": "¿Qué ejercicio tengo que hacer?", "selected_plan_date": selected["date"]})

        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(lambda args: ask(*args), [(first, first_day), (second, second_day)]))
        for response, expected in zip(responses, (first_day, second_day)):
            assert response.status_code == 200, response.text
            assert response.json()["metadata"]["plan_day"] == expected["date"]
            assert expected["workout"]["type"] in response.json()["message"]
            assert response.headers["x-request-id"] == response.json()["request_id"]


def test_long_answers_round_trip_without_truncation_and_twenty_turns_remain_ordered(monkeypatch):
    long_answer = "Respuesta extensa: " + ("contenido completo. " * 190)

    async def answer(**_):
        return long_answer

    monkeypatch.setattr("app.main.llm.answer", answer)
    with TestClient(app) as client:
        headers = signup(client, "fitlife-long-chat")
        assert client.put("/api/v1/profile", headers=headers, json=profile()).status_code == 200
        assert client.post("/api/v1/plan/generate", headers=headers).status_code == 201
        response = client.post("/api/v1/chat", headers=headers, json={"message": "¿Qué proteína recomiendas después de entrenar?"})
        assert response.status_code == 200, response.text
        assert response.json()["message"] == long_answer
        assert response.json()["message_length"] == len(long_answer)
        session_id = response.json()["session_id"]

        for index in range(19):
            turn = client.post("/api/v1/chat", headers=headers, json={"message": "¿Qué me toca hoy?", "session_id": session_id})
            assert turn.status_code == 200, f"turn {index + 2}: {turn.text}"

        history = client.get(f"/api/v1/chat/{session_id}", headers=headers)
        assert history.status_code == 200
        messages = history.json()["messages"]
        assert len(messages) == 40
        assert messages[1]["content"] == long_answer
        assert all(message["id"] for message in messages)
        assert [message["role"] for message in messages] == [role for _ in range(20) for role in ("user", "assistant")]


def test_chat_returns_stable_contract_and_combines_real_plan_with_technical_exercise_knowledge(monkeypatch):
    async def should_not_run(**_):
        raise AssertionError("an off-topic request must not reach the LLM")

    monkeypatch.setattr("app.main.llm.answer", should_not_run)
    with TestClient(app) as client:
        headers = signup(client, "fitlife-user-d")
        assert client.put("/api/v1/profile", headers=headers, json=profile()).status_code == 200
        assert client.post("/api/v1/plan/generate", headers=headers).status_code == 201

        routine = client.post("/api/v1/chat", headers=headers, json={"message": "Como se hace elejercicio de flexion inclinada"})
        assert routine.status_code == 200, routine.text
        assert routine.json()["intent"] == "EXERCISE_INSTRUCTION"
        assert routine.json()["source"] == "routine_rag"
        assert "Flexión inclinada" in routine.json()["message"]
        assert "Apoya las manos en una superficie estable" in routine.json()["message"]
        assert "3 series de 8–10 repeticiones" in routine.json()["message"]
        assert routine.json()["metadata"]["exercise_intent"] == "exercise_instruction"
        assert routine.json()["metadata"]["routine_found"] is True
        assert routine.json()["metadata"]["technical_guide_found"] is True
        assert routine.json()["message"] == routine.json()["response"]

        # A prior unmatched message in the same session must never contaminate
        # the entity that is looked up in the persisted user routine.
        noisy = client.post(
            "/api/v1/chat",
            headers=headers,
            json={"message": "¿Cómo hago el salto de pokemon?", "session_id": routine.json()["session_id"]},
        )
        assert noisy.status_code == 200
        recovered = client.post(
            "/api/v1/chat",
            headers=headers,
            json={"message": "como hacer la flexion inclinada", "session_id": routine.json()["session_id"]},
        )
        assert recovered.status_code == 200
        assert recovered.json()["source"] == "routine_rag"
        assert "Flexión inclinada" in recovered.json()["message"]

        programming = client.post("/api/v1/chat", headers=headers, json={"message": "¿Cuántas series hago de flexión inclinada?"})
        assert programming.status_code == 200
        assert programming.json()["source"] == "routine"
        assert programming.json()["metadata"]["exercise_intent"] == "exercise_programming"
        assert programming.json()["message"].startswith("En tu rutina")
        assert "3 series de 8–10 repeticiones" in programming.json()["message"]

        membership = client.post("/api/v1/chat", headers=headers, json={"message": "¿La flexión inclinada está en mi rutina?"})
        assert membership.status_code == 200
        assert membership.json()["metadata"]["exercise_intent"] == "routine_membership"
        assert membership.json()["message"].startswith("Sí, Flexión inclinada")

        unknown = client.post("/api/v1/chat", headers=headers, json={"message": "¿Cómo hago el salto de pokemon?"})
        assert unknown.status_code == 200
        assert unknown.json()["intent"] == "EXERCISE_INSTRUCTION"
        assert unknown.json()["source"] == "not_found"
        assert "salto de pokemon" in unknown.json()["message"]
        assert "No quiero inventarte" in unknown.json()["message"]

        superman = client.post("/api/v1/chat", headers=headers, json={"message": "¿El salto de superman está en mi rutina?"})
        assert superman.status_code == 200
        assert superman.json()["source"] == "not_found"
        assert "salto de superman" in superman.json()["message"]

        off_topic = client.post("/api/v1/chat", headers=headers, json={"message": "Explícame Python"})
        assert off_topic.status_code == 200
        assert off_topic.json()["source"] == "guardrail"
        assert "programación" in off_topic.json()["message"]
        for question, category in [
            ("¿Cómo cocinar un Pokémon?", "videojuegos"),
            ("¿Cuánto es 2+2?", "matemáticas"),
            ("¿Cómo hago un script en Python para SQL?", "programación"),
        ]:
            blocked = client.post("/api/v1/chat", headers=headers, json={"message": question})
            assert blocked.status_code == 200
            assert blocked.json()["source"] == "guardrail"
            assert category in blocked.json()["message"]


def test_persistent_context_survives_login_and_keeps_users_isolated():
    with TestClient(app) as client:
        first = signup(client, "fitlife-memory-a")
        second = signup(client, "fitlife-memory-b")
        assert client.put("/api/v1/profile", headers=first, json=profile()).status_code == 200
        plan = client.post("/api/v1/plan/generate", headers=first).json()

        exercise = client.post("/api/v1/chat", headers=first, json={"message": "¿Cómo hago la flexión inclinada?"})
        assert exercise.status_code == 200
        assert exercise.json()["source"] == "routine_rag"
        persisted = client.get("/api/v1/context", headers=first)
        assert persisted.status_code == 200
        assert persisted.json()["memory"]["last_exercise"] == "Flexión inclinada"
        assert persisted.json()["memory"]["last_topic"] == "la técnica del ejercicio"

        workout_day = next(day for day in plan["days"] if day["kind"] == "workout")
        completed = client.post("/api/v1/progress", headers=first, json={"date": workout_day["date"], "completed": True})
        assert completed.status_code == 200
        assert completed.json()["completed_at"] is not None
        performed = client.post("/api/v1/chat", headers=first, json={"message": "¿Cuál fue el último ejercicio que hice?"})
        assert performed.status_code == 200
        assert performed.json()["source"] == "plan"
        assert performed.json()["metadata"]["conversation_intent"] == "progress_question"
        assert workout_day["workout"]["exercises"][-1]["name"] in performed.json()["message"]

        # A fresh token models a new login; neither the visual session id nor
        # the original token is required to recover backend memory.
        relogin = client.post("/api/v1/auth/login", json={"username": "fitlife-memory-a", "password": "strong-password-123"})
        restored_headers = {"Authorization": f"Bearer {relogin.json()['access_token']}"}
        last_exercise = client.post("/api/v1/chat", headers=restored_headers, json={"message": "¿Cuál fue el último ejercicio por el que te pregunté?"})
        assert last_exercise.status_code == 200
        assert last_exercise.json()["source"] == "memory"
        assert "Flexión inclinada" in last_exercise.json()["message"]

        follow_up = client.post("/api/v1/chat", headers=restored_headers, json={"message": "¿En qué nos quedamos?"})
        assert follow_up.status_code == 200
        assert follow_up.json()["source"] == "memory"
        assert follow_up.json()["message"].startswith("Nos quedamos")
        assert "3 series de 8–10 repeticiones" in follow_up.json()["message"]

        today = client.post("/api/v1/chat", headers=restored_headers, json={"message": "¿Qué me toca hoy?"})
        assert today.status_code == 200
        assert today.json()["source"] == "plan"
        assert today.json()["metadata"]["conversation_intent"] == "plan_question"

        reloaded_plan = client.get("/api/v1/plan", headers=restored_headers)
        assert workout_day["date"] in reloaded_plan.json()["completed_days"]

        other_context = client.get("/api/v1/context", headers=second)
        assert other_context.status_code == 200
        assert other_context.json()["memory"] is None
        assert other_context.json()["plan"] is None
