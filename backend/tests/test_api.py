from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_health():
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


def test_dashboard_is_database_backed():
    response = client.get("/api/dashboard")
    assert response.status_code == 200
    data = response.json()
    assert data["source"] == "database"
    assert len(data["metrics"] == 5 if False else data["metrics"]) == 5
    assert len(data["pipeline"]) == 7


def test_mutation_requires_authentication():
    response = client.post("/api/topics", json={"title": "A topic", "pillar": "Technology"})
    assert response.status_code == 401


def test_bootstrap_login_and_authenticated_topic_create():
    login = client.post("/api/auth/login", json={"email": "admin@visualtech.local", "password": "change-me"})
    assert login.status_code == 200
    token = login.json()["access_token"]
    response = client.post(
        "/api/topics",
        headers={"Authorization": f"Bearer {token}"},
        json={"title": "Production-ready topic", "pillar": "Technology", "priority": "high"},
    )
    assert response.status_code == 201
    assert response.json()["title"] == "Production-ready topic"


def test_invalid_login_is_rejected():
    response = client.post("/api/auth/login", json={"email": "admin@visualtech.local", "password": "wrong"})
    assert response.status_code == 401
