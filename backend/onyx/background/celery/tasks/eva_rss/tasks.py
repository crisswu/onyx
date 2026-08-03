from __future__ import annotations

from celery import shared_task

from onyx.configs.constants import OnyxCeleryTask
from onyx.db.eva_rss import EvaRssDB
from onyx.rss.fetcher import fetch_due_subscriptions
from onyx.rss.fetcher import fetch_subscription_now
from onyx.utils.logger import setup_logger

logger = setup_logger()


@shared_task(name=OnyxCeleryTask.CHECK_EVA_RSS_FETCH, ignore_result=True)
def check_eva_rss_fetch(*, tenant_id: str | None = None) -> None:
    """Fetch due RSS subscriptions for the owner/default EVA local store."""
    _ = tenant_id
    db = EvaRssDB()
    results = fetch_due_subscriptions(db)
    logger.info("EVA RSS due fetch complete: subscriptions=%s", len(results))


@shared_task(name=OnyxCeleryTask.EVA_RSS_FETCH_SUBSCRIPTION, ignore_result=True)
def eva_rss_fetch_subscription(
    subscription_id: int,
    *,
    tenant_id: str | None = None,
) -> None:
    """Fetch a single RSS subscription from the owner/default EVA local store."""
    _ = tenant_id
    db = EvaRssDB()
    subscription = db.get_subscription(subscription_id)
    if subscription is None:
        logger.warning("Skipping missing EVA RSS subscription id=%s", subscription_id)
        return
    result = fetch_subscription_now(db, subscription)
    if result.error:
        logger.warning(
            "EVA RSS subscription fetch failed: subscription_id=%s error=%s",
            subscription_id,
            result.error,
        )
