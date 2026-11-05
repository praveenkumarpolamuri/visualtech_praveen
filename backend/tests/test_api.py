import hashlib
import io
import secrets
import wave
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient
from app.main import app
from app.integrations.providers import consume_oauth_state, upsert_video_analytics
from app.integrations.media_generation import combine_wav_chunks, split_text_chunks
from app.modules.agent import sanitize_citation_markers, topic_prompt
from app.modules.domain import OAuthState, VideoAnalytics
from app.modules.publishing_worker import retry_delay_minutes
from app.modules.storage import get_limited_upload_size

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
    assert isinstance(data["schedule"], list)


def test_integration_status_exposes_provider_configuration():
    response = client.get("/api/integrations/status")
    assert response.status_code == 200
    providers = response.json()["providers"]
    assert {"openai", "image_generation", "voice", "youtube", "storage"}.issubset(providers)
    assert isinstance(providers["youtube"]["connected"], bool)


def test_youtube_authorization_requires_authentication():
    response = client.get("/api/integrations/youtube/authorize")
    assert response.status_code == 401


def test_image_generation_requires_authentication():
    response = client.post("/api/integrations/openai/images", json={"prompt": "A documentary scene"})
    assert response.status_code == 401


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


def test_analytics_are_upserted_per_youtube_video():
    engine = create_engine("sqlite:///:memory:")
    VideoAnalytics.__table__.create(engine)
    session = sessionmaker(bind=engine)()
    try:
        first_upload = type("Upload", (), {"id": "upload-one", "project_id": "same-project"})()
        second_upload = type("Upload", (), {"id": "upload-two", "project_id": "same-project"})()
        legacy_row = VideoAnalytics(project_id="same-project", views=999)
        session.add(legacy_row)
        session.commit()
        upsert_video_analytics(session, first_upload, [10, 20, 30, 1])
        upsert_video_analytics(session, second_upload, [40, 50, 60, 2])
        upsert_video_analytics(session, first_upload, [12, 22, 32, 3])
        session.commit()
        rows = session.query(VideoAnalytics).order_by(VideoAnalytics.youtube_upload_id).all()
        assert [(row.youtube_upload_id, row.views) for row in rows] == [("upload-one", 12), ("upload-two", 40)]
    finally:
        session.close()
        engine.dispose()


def test_oauth_state_can_only_be_consumed_once():
    engine = create_engine("sqlite:///:memory:")
    OAuthState.__table__.create(engine)
    session = sessionmaker(bind=engine)()
    state = secrets.token_urlsafe(32)
    try:
        session.add(OAuthState(
            state_hash=hashlib.sha256(state.encode()).hexdigest(),
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        ))
        session.commit()
        assert consume_oauth_state(session, state)
        assert not consume_oauth_state(session, state)
    finally:
        session.close()
        engine.dispose()


def test_upload_reader_rejects_data_over_limit():
    assert get_limited_upload_size(io.BytesIO(b"1234"), 4) == 4
    with pytest.raises(HTTPException) as error:
        get_limited_upload_size(io.BytesIO(b"12345"), 4)
    assert error.value.status_code == 413


def test_retry_delay_uses_bounded_exponential_backoff():
    assert [retry_delay_minutes(attempt) for attempt in (1, 2, 3, 10)] == [5, 10, 20, 360]


def test_topic_prompt_requests_distinct_audience_and_research_fields():
    prompt = topic_prompt("AI chips", 3, {"audience": "students", "tone": "curious"}, ["Inside a modern chip factory"])
    assert "students" in prompt
    assert "novelty_score" in prompt
    assert "source_queries" in prompt
    assert "Inside a modern chip factory" in prompt


def test_script_citations_reject_unknown_source_keys():
    text = "Evidence from [S1] is supported, while [S8] needs review."
    assert sanitize_citation_markers(text, {"S1": object()}) == "Evidence from [S1] is supported, while [VERIFY] needs review."


def test_long_voiceover_chunks_respect_provider_limit():
    text = "Sentence with useful narration. " * 200
    chunks = split_text_chunks(text)
    assert len(chunks) > 1
    assert all(len(chunk) <= 3500 for chunk in chunks)
    assert " ".join(chunks) == text.strip()


def test_wav_voiceover_chunks_join_into_one_stream():
    chunks = []
    for sample in (100, 200):
        output = io.BytesIO()
        with wave.open(output, "wb") as writer:
            writer.setparams((1, 2, 16000, 4, "NONE", "not compressed"))
            writer.writeframes(sample.to_bytes(2, "little", signed=True) * 4)
        chunks.append(output.getvalue())
    combined = combine_wav_chunks(chunks)
    with wave.open(io.BytesIO(combined), "rb") as reader:
        assert reader.getnframes() == 8
        assert reader.getframerate() == 16000
