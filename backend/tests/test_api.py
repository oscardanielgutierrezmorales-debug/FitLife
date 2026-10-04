import os

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
        assert "asistente local" in response.json()["detail"]["message"]


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
        assert routine.json()["intent"] == "FITNESS"
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
        assert unknown.json()["intent"] == "FITNESS"
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
