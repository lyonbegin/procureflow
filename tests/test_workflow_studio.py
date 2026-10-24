"""React Flow is the homepage; legacy workbench and G2B API stay in place.

These checks do not touch Railway or a live DB, and require a prior Vite build
staged in static/studio/ by the GitHub workflow.
"""
from pathlib import Path

from fastapi.testclient import TestClient
from main import app, STUDIO_DIST


def test_react_flow_is_primary_homepage_when_built():
    assert (STUDIO_DIST / "index.html").is_file(), "CI must build the frontend"
    assert (STUDIO_DIST / "assets").is_dir()


def test_homepage_and_assets_are_served_without_db_connection():
    client = TestClient(app)
    result = client.get("/")
    assert result.status_code == 200
    assert "text/html" in result.headers.get("content-type", "")
    assert '<div id="root"></div>' in result.text
    assert '/studio/assets/' in result.text
    assert result.headers["cache-control"] == "no-cache"
    filename = next((STUDIO_DIST / "assets").glob("*.js"))
    asset = client.get("/studio/assets/" + filename.name)
    assert asset.status_code == 200
    assert len(asset.content) > 1000


def test_legacy_workbench_survives_and_separate_pages_stay_registered():
    client = TestClient(app)
    old = client.get("/legacy/workbench")
    assert old.status_code == 200
    assert "입찰 통합 작업관리" in old.text
    paths = {getattr(route, "path", "") for route in app.routes}
    for required in ("/operations", "/bids", "/prepare", "/agents", "/g2b-104",
                     "/g2b-104-api", "/api/g2b/full/case"):
        assert required in paths


def test_standalone_flow_has_independent_route_and_same_compiled_app():
    client = TestClient(app)
    result = client.get("/flow")
    assert result.status_code == 200
    assert "text/html" in result.headers["content-type"]
    assert '<div id="root"></div>' in result.text
    assert "/studio/assets/" in result.text
    assert result.headers["cache-control"] == "no-cache"
    assert result.text == client.get("/").text


def test_fullscreen_flow_preserves_existing_main_and_legacy():
    client = TestClient(app)
    assert client.get("/").status_code == 200
    assert client.get("/legacy/workbench").status_code == 200
    source = (Path(__file__).resolve().parents[1] / "frontend/src/FlowWorkspace.jsx").read_text()
    assert "flow-workspace-stage" in source
    assert "flow-workspace-inspector-frame" in source
    assert "flow-workspace-library" in source
    assert "flow-workspace-console" in source
    assert "renderCanvas" in source and "renderInspector" in source


def test_104_per_feature_get_and_post_routes_preserved():
    urls = {getattr(route, "path", "") for route in app.routes}
    for number in range(1, 105):
        root = f"/api/g2b/cases/{{bid_no}}/features/{number}"
        assert root in urls
        assert root + "/run" in urls
    assert len([path for path in urls if path.endswith("/run") and "/features/" in path]) == 104


def test_frontend_flow_has_single_selected_case_and_no_submission_endpoint():
    root = Path(__file__).resolve().parents[1] / "frontend" / "src"
    text = (root / "api.js").read_text(encoding="utf-8")
    assert "R26BK01787028" in text
    assert "'/api/g2b/cases/'" in text
    assert "submitBid" not in text
    assert "bid_participation" not in text
