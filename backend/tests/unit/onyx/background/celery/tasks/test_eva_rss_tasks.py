from __future__ import annotations

import pytest

from onyx.background.celery.tasks.eva_rss import tasks


class _FakeRssDB:
    pass


def test_check_eva_rss_fetch_accepts_tenant_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen_db: list[_FakeRssDB] = []

    def fake_fetch_due_subscriptions(db: _FakeRssDB) -> list[object]:
        seen_db.append(db)
        return []

    monkeypatch.setattr(tasks, "EvaRssDB", _FakeRssDB)
    monkeypatch.setattr(tasks, "fetch_due_subscriptions", fake_fetch_due_subscriptions)

    tasks.check_eva_rss_fetch.run(tenant_id="public")

    assert len(seen_db) == 1
