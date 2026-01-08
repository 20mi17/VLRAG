from __future__ import annotations

import documents_service


def test_supabase_ping_returns_true_when_query_succeeds(monkeypatch):
    class DummyTable:
        def select(self, *_args, **_kwargs):
            return self

        def limit(self, *_args, **_kwargs):
            return self

        def execute(self):
            return object()

    class DummyClient:
        def table(self, *_args, **_kwargs):
            return DummyTable()

    monkeypatch.setattr(documents_service, "get_supabase_client", lambda: DummyClient())
    assert documents_service.supabase_ping() is True


def test_supabase_ping_returns_false_on_exception(monkeypatch):
    def boom():
        raise RuntimeError("nope")

    monkeypatch.setattr(documents_service, "get_supabase_client", boom)
    assert documents_service.supabase_ping() is False


def test_get_document_returns_none_when_not_found(monkeypatch):
    class DummyRes:
        data = []

    class DummyTable:
        def select(self, *_args, **_kwargs):
            return self

        def eq(self, *_args, **_kwargs):
            return self

        def limit(self, *_args, **_kwargs):
            return self

        def execute(self):
            return DummyRes()

    class DummyClient:
        def table(self, *_args, **_kwargs):
            return DummyTable()

    monkeypatch.setattr(documents_service, "get_supabase_client", lambda: DummyClient())
    assert documents_service.get_document("missing") is None


def test_get_document_returns_first_row_when_found(monkeypatch):
    class DummyRes:
        data = [{"id": "abc", "title": "t"}]

    class DummyTable:
        def select(self, *_args, **_kwargs):
            return self

        def eq(self, *_args, **_kwargs):
            return self

        def limit(self, *_args, **_kwargs):
            return self

        def execute(self):
            return DummyRes()

    class DummyClient:
        def table(self, *_args, **_kwargs):
            return DummyTable()

    monkeypatch.setattr(documents_service, "get_supabase_client", lambda: DummyClient())
    assert documents_service.get_document("abc") == {"id": "abc", "title": "t"}
