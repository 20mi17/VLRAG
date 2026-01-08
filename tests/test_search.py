from fastapi.testclient import TestClient
import routers.search as search_router_module
from main import app

client = TestClient(app)


def test_search_returns_empty_results_for_no_matches(monkeypatch):
    # mock the search function used by the router
    monkeypatch.setattr(search_router_module, "search_chunks", lambda q, top_k, document_id: [])
    res = client.post("/search", json={"query": "thiswillnotmatchanything", "top_k": 3})
    assert res.status_code == 200
    body = res.json()
    assert body["query"] == "thiswillnotmatchanything"
    assert body["results"] == []


def test_search_requires_query():
    res = client.post("/search", json={"query": ""})
    assert res.status_code == 422