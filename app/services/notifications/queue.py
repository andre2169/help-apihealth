import redis

from app.core import security_policy as policy
from app.core.config import settings


def build_notification_redis_client() -> redis.Redis:
    if not settings.REDIS_URL:
        raise RuntimeError("redis_not_configured")

    return redis.Redis.from_url(
        settings.REDIS_URL,
        decode_responses=True,
        socket_connect_timeout=policy.REDIS_CONNECT_TIMEOUT_SECONDS,
        socket_timeout=policy.REDIS_OPERATION_TIMEOUT_SECONDS,
    )


def ensure_notification_consumer_group(client: redis.Redis) -> None:
    try:
        client.xgroup_create(
            name=policy.REDIS_NOTIFICATION_STREAM,
            groupname=policy.REDIS_NOTIFICATION_GROUP,
            id="0-0",
            mkstream=True,
        )
    except redis.exceptions.ResponseError as exc:
        if "BUSYGROUP" not in str(exc):
            raise


def enqueue_delivery(client: redis.Redis, delivery_id: int) -> str:
    return client.xadd(
        policy.REDIS_NOTIFICATION_STREAM,
        {"delivery_id": str(delivery_id)},
        maxlen=policy.WHATSAPP_STREAM_MAXLEN,
        approximate=True,
    )
