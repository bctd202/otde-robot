from fastapi.testclient import TestClient

from app.main import app, frontend_dist


client = TestClient(app)


def test_frontend_build_path_is_verified() -> None:
    assert (frontend_dist / "index.html").is_file()
    assert (frontend_dist / "assets").is_dir()


def test_root_serves_frontend_html() -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert '<div id="root">' in response.text
    assert "/assets/app.js" in response.text


def test_static_javascript_and_css_assets_are_served() -> None:
    javascript = client.get("/assets/app.js")
    stylesheet = client.get("/assets/app.css")
    assert javascript.status_code == 200
    assert "javascript" in javascript.headers["content-type"]
    assert stylesheet.status_code == 200
    assert stylesheet.headers["content-type"].startswith("text/css")


def test_favicon_is_served() -> None:
    response = client.get("/favicon.svg")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/svg+xml")


def test_spa_fallback_and_reserved_routes() -> None:
    assert client.get("/command-center").status_code == 200
    assert client.get("/command-center").headers["content-type"].startswith("text/html")
    assert client.get("/api/not-a-route").status_code == 404
    assert client.get("/docs").status_code == 200
    assert client.get("/redoc").status_code == 200
    assert client.get("/openapi.json").status_code == 200


def test_backend_routes_remain_available() -> None:
    for path in ("/api/health", "/api/dashboard", "/api/candles/SPY"):
        assert client.get(path).status_code == 200
