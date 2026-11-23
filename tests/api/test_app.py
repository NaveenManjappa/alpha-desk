"""Tests for serving the built web app from the API.

A tiny fake build stands in for the Angular one, so these need no Node.js. The app's real
startup runs, with fake services in place of the real ones.
"""

from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from alphadesk.api import app as app_module
from alphadesk.api.app import create_app
from alphadesk.api.dependencies import AppServices
from alphadesk.config.settings import Settings
from alphadesk.domain.chat_events import FinalEvent, ProgressEvent
from alphadesk.services.chat import ChatService

# What a browser sends when it asks for a page, rather than for a script or an image.
PAGE_REQUEST = {"accept": "text/html"}


async def _no_answer(message: str, thread_id: str) -> AsyncIterator[ProgressEvent | FinalEvent]:
    raise NotImplementedError("these tests never chat")
    yield  # makes this an async generator


@asynccontextmanager
async def _fake_services(settings: Settings) -> AsyncGenerator[AppServices]:
    yield AppServices(chat=ChatService(_no_answer), check_postgres=None)


@pytest.fixture
def web_dist(tmp_path: Path) -> Path:
    """A folder shaped like a built web app."""
    (tmp_path / "index.html").write_text("<title>AlphaDesk</title>")
    (tmp_path / "main.js").write_text("// the app")
    return tmp_path


@pytest.fixture
def patch_startup(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    """Replace the services and tracing that startup would set up for real."""
    monkeypatch.setattr(app_module, "open_app_services", _fake_services)
    monkeypatch.setattr(app_module, "configure_tracing", lambda settings: None)
    monkeypatch.setattr(app_module, "wait_for_all_tracers", lambda: None)
    return monkeypatch


def _client(patch_startup: pytest.MonkeyPatch, web_dist_dir: Path | None) -> TestClient:
    """A client for an app with this setting. Use it in a `with`, which runs startup."""
    settings = Settings(
        _env_file=None,  # pyright: ignore[reportCallIssue]
        openai_api_key="test-key",  # pyright: ignore[reportArgumentType]
        web_dist_dir=web_dist_dir,
    )
    patch_startup.setattr(app_module, "get_settings", lambda: settings)
    return TestClient(create_app())


@pytest.mark.unit
def test_serves_the_web_app(patch_startup: pytest.MonkeyPatch, web_dist: Path) -> None:
    with _client(patch_startup, web_dist) as client:
        assert "AlphaDesk" in client.get("/", headers=PAGE_REQUEST).text
        assert client.get("/main.js").text == "// the app"


@pytest.mark.unit
def test_api_routes_win_over_the_web_app(patch_startup: pytest.MonkeyPatch, web_dist: Path) -> None:
    with _client(patch_startup, web_dist) as client:
        response = client.get("/health", headers=PAGE_REQUEST)

    assert response.json() == {"status": "ok", "postgres": "not_configured"}


@pytest.mark.unit
def test_an_unknown_page_gets_the_app_but_a_missing_file_is_404(
    patch_startup: pytest.MonkeyPatch, web_dist: Path
) -> None:
    with _client(patch_startup, web_dist) as client:
        page = client.get("/some/page", headers=PAGE_REQUEST)
        script = client.get("/missing.js", headers={"accept": "*/*"})

    assert page.status_code == 200
    assert "AlphaDesk" in page.text
    assert script.status_code == 404


@pytest.mark.unit
def test_no_web_app_is_served_by_default(patch_startup: pytest.MonkeyPatch) -> None:
    with _client(patch_startup, None) as client:
        assert client.get("/", headers=PAGE_REQUEST).status_code == 404
        assert client.get("/health").status_code == 200


@pytest.mark.unit
def test_a_folder_without_a_build_stops_startup_and_names_the_setting(
    patch_startup: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _client(patch_startup, tmp_path)

    with pytest.raises(RuntimeError, match="ALPHADESK_WEB_DIST_DIR"), client:
        pass
