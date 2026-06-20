"""The SPA entry point must be served with revalidation forced so a new
frontend build is picked up immediately instead of being served stale from
the browser cache until a manual hard-refresh."""

from app.main import _spa_index_response


def test_index_html_sets_no_cache():
    resp = _spa_index_response()
    assert resp.headers["cache-control"] == "no-cache"


def test_index_html_points_at_static_index():
    resp = _spa_index_response()
    assert resp.path.endswith("index.html")
