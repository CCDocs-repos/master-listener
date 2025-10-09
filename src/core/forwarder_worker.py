#!/usr/bin/env python3
"""
Forwarder Worker
================

Consumes jobs from Redis Streams (forwarding:jobs) and forwards messages
to Slack master channels. This pairs with listener_redis.py which enqueues
jobs after FCFS idempotent claim.

Key features (minimal viable):
- Uses the correct bot token per job (payload.bot_id) to preserve channel access
- Handles new posts and updates
- Handles thread replies by ensuring parent is posted first
- Stores mapping of source message ts -> master ts in Redis for edits
- Basic rate-limit handling (429 Retry-After) and exponential backoff retries
"""

from dotenv import load_dotenv
load_dotenv()

import os
import sys
import time
import json
import logging
from datetime import datetime
import pytz
from typing import Dict, Any, Optional

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

# Add src directory to Python path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

from config.multi_bot_config import MultiBotConfigManager


# ----------------------------------------------------------------------------
# Redis connection
# ----------------------------------------------------------------------------
import importlib.util


def get_redis_connection():
    root_dir = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
    # Try redis_client
    try:
        import redis_client  # type: ignore
        if hasattr(redis_client, 'r'):
            return redis_client.r
    except Exception:
        pass
    # Try redis-client.py
    try:
        client_path = os.path.join(root_dir, 'redis-client.py')
        if os.path.exists(client_path):
            spec = importlib.util.spec_from_file_location('redis_client_hyphen', client_path)
            module = importlib.util.module_from_spec(spec)
            assert spec and spec.loader
            spec.loader.exec_module(module)  # type: ignore
            if hasattr(module, 'r'):
                return module.r
    except Exception as e:
        print(f"Failed to load redis-client.py: {e}")
    raise RuntimeError("Could not import Redis connection `r`. Ensure redis_client.py or redis-client.py exposes `r`.")


r = get_redis_connection()


# ----------------------------------------------------------------------------
# Logging
# ----------------------------------------------------------------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ----------------------------------------------------------------------------
# Slack clients per bot
# ----------------------------------------------------------------------------
multi_bot_manager = MultiBotConfigManager()

bot_clients: Dict[int, WebClient] = {}
for bot_id, cfg in multi_bot_manager.bot_configs.items():
    token = os.environ.get("SLACK_BOT_TOKEN") if str(bot_id) == os.environ.get("BOT_ID", "") else cfg.bot_token
    bot_clients[bot_id] = WebClient(token=token)


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------
STREAM_JOBS = "forwarding:jobs"
GROUP_NAME = "workers"
CONSUMER_NAME = f"worker-{os.getpid()}"
MAP_MSG_KEY = "map:msg:{channel_id}:{ts}"
MAP_PARENT_KEY = "map:parent:{channel_id}:{parent_ts}"
MAP_TTL_SEC = 7 * 24 * 3600  # 7 days


def convert_to_est(ts: str) -> str:
    utc_time = datetime.fromtimestamp(float(ts))
    est = pytz.timezone('US/Eastern')
    est_time = utc_time.astimezone(est)
    return est_time.strftime('%Y-%m-%d %I:%M:%S %p %Z')


def ensure_group():
    try:
        r.xgroup_create(name=STREAM_JOBS, groupname=GROUP_NAME, id='$', mkstream=True)
        logger.info(f"Created consumer group {GROUP_NAME} on stream {STREAM_JOBS}")
    except Exception as e:
        # Group exists or other benign errors
        pass


def get_client_for_bot(bot_id: int) -> WebClient:
    if bot_id in bot_clients:
        return bot_clients[bot_id]
    # Fallback to any available client
    return next(iter(bot_clients.values()))


def get_master_ts_for_message(channel_id: str, ts: str) -> Optional[str]:
    try:
        key = MAP_MSG_KEY.format(channel_id=channel_id, ts=ts)
        return r.get(key)
    except Exception:
        return None


def set_master_ts_for_message(channel_id: str, ts: str, master_ts: str) -> None:
    try:
        key = MAP_MSG_KEY.format(channel_id=channel_id, ts=ts)
        r.set(key, master_ts, ex=MAP_TTL_SEC)
    except Exception:
        pass


def get_master_ts_for_parent(channel_id: str, parent_ts: str) -> Optional[str]:
    try:
        key = MAP_PARENT_KEY.format(channel_id=channel_id, parent_ts=parent_ts)
        return r.get(key)
    except Exception:
        return None


def set_master_ts_for_parent(channel_id: str, parent_ts: str, master_ts: str) -> None:
    try:
        key = MAP_PARENT_KEY.format(channel_id=channel_id, parent_ts=parent_ts)
        r.set(key, master_ts, ex=MAP_TTL_SEC)
    except Exception:
        pass


def ensure_parent_posted(client: WebClient, payload: Dict[str, Any]) -> Optional[str]:
    """Ensure the parent message is posted in the master channel, return parent master ts."""
    source_channel_id = payload.get("source_channel_id", "")
    source_channel_name = payload.get("source_channel_name", "")
    target_channel_id = payload.get("target_channel_id", "")
    thread_ts = payload.get("thread_ts")
    user = payload.get("user", "unknown")

    if not thread_ts:
        return None

    # Check cache
    master_parent_ts = get_master_ts_for_parent(source_channel_id, thread_ts)
    if master_parent_ts:
        return master_parent_ts

    # Fetch original parent message
    try:
        hist = client.conversations_history(channel=source_channel_id, latest=thread_ts, limit=1, inclusive=True)
        if not hist.get("messages"):
            return None
        original_msg = hist["messages"][0]
        parent_ts = original_msg["ts"]
        parent_text = original_msg.get("text", "")
        parent_message = f"*From #{source_channel_name}*\n{parent_text}\n_Posted by <@{original_msg.get('user','unknown')}> at {convert_to_est(parent_ts)}_"
        parent_resp = client.chat_postMessage(channel=target_channel_id, text=parent_message)
        master_parent_ts = parent_resp["ts"]
        set_master_ts_for_parent(source_channel_id, parent_ts, master_parent_ts)
        return master_parent_ts
    except SlackApiError as e:
        logger.error(f"Error ensuring parent posted: {e.response['error']}")
        return None


def handle_post_job(client: WebClient, payload: Dict[str, Any]) -> None:
    target_channel_id = payload.get("target_channel_id", "")
    source_channel_id = payload.get("source_channel_id", "")
    source_channel_name = payload.get("source_channel_name", "")
    text = payload.get("text", "")
    user = payload.get("user", "unknown")
    ts = payload.get("ts", "")
    is_thread_reply = bool(payload.get("is_thread_reply"))
    thread_ts = payload.get("thread_ts")
    attachments = payload.get("attachments") or []
    files = payload.get("files") or []

    # Build message
    est_time_str = convert_to_est(ts) if ts else ""
    message = f"*From #{source_channel_name}*\n{text}\n_Posted by <@{user}> at {est_time_str}_"
    params: Dict[str, Any] = {"channel": target_channel_id, "text": message}

    # Try to append attachments (if already normalized)
    if attachments:
        params["attachments"] = attachments

    # Handle thread linkage
    if is_thread_reply and thread_ts:
        master_parent_ts = ensure_parent_posted(client, payload)
        if master_parent_ts:
            params["thread_ts"] = master_parent_ts

    # Post with retries
    backoff = 1.0
    for attempt in range(4):
        try:
            resp = client.chat_postMessage(**params)
            master_ts = resp["ts"]
            if ts:
                set_master_ts_for_message(source_channel_id, ts, master_ts)
            logger.info(f"Posted message to {target_channel_id} from #{source_channel_name}")
            return
        except SlackApiError as e:
            err = e.response.get('error') if hasattr(e, 'response') and e.response is not None else str(e)
            retry_after = None
            try:
                retry_after = int(e.response.headers.get('Retry-After', '0')) if hasattr(e, 'response') and e.response is not None else 0
            except Exception:
                retry_after = 0
            if retry_after and retry_after > 0:
                time.sleep(retry_after)
                continue
            if err in ("ratelimited", "rate_limited", "internal_error", "unknown_error") and attempt < 3:
                time.sleep(backoff)
                backoff *= 2
                continue
            logger.error(f"chat_postMessage failed (no retry): {err}")
            return


def handle_update_job(client: WebClient, payload: Dict[str, Any]) -> None:
    target_channel_id = payload.get("target_channel_id", "")
    source_channel_id = payload.get("source_channel_id", "")
    text = payload.get("text", "")
    ts = payload.get("ts", "")  # original message ts

    master_ts = get_master_ts_for_message(source_channel_id, ts)
    if not master_ts:
        logger.warning(f"No master ts mapping for update {source_channel_id}:{ts}")
        return

    params: Dict[str, Any] = {"channel": target_channel_id, "ts": master_ts, "text": text}

    backoff = 1.0
    for attempt in range(4):
        try:
            client.chat_update(**params)
            logger.info(f"Updated message in {target_channel_id}")
            return
        except SlackApiError as e:
            err = e.response.get('error') if hasattr(e, 'response') and e.response is not None else str(e)
            retry_after = None
            try:
                retry_after = int(e.response.headers.get('Retry-After', '0')) if hasattr(e, 'response') and e.response is not None else 0
            except Exception:
                retry_after = 0
            if retry_after and retry_after > 0:
                time.sleep(retry_after)
                continue
            if err in ("ratelimited", "rate_limited", "internal_error", "unknown_error") and attempt < 3:
                time.sleep(backoff)
                backoff *= 2
                continue
            logger.error(f"chat_update failed (no retry): {err}")
            return


def parse_stream_message(data: Dict[str, Any]) -> Dict[str, Any]:
    """Stream fields are flat strings. Parse JSON fields back to structures."""
    parsed: Dict[str, Any] = {}
    for k, v in data.items():
        if k in ("attachments", "files"):
            try:
                parsed[k] = json.loads(v)
            except Exception:
                parsed[k] = []
        elif k in ("is_thread_reply",):
            parsed[k] = v in ("1", "true", "True")
        elif k in ("bot_id",):
            try:
                parsed[k] = int(v)
            except Exception:
                parsed[k] = 1
        else:
            parsed[k] = v
    return parsed


def main():
    ensure_group()
    logger.info(f"Worker started. Group={GROUP_NAME} Consumer={CONSUMER_NAME}")
    while True:
        try:
            resp = r.xreadgroup(groupname=GROUP_NAME, consumername=CONSUMER_NAME, streams={STREAM_JOBS: '>'}, count=10, block=5000)
            if not resp:
                continue
            for stream_key, messages in resp:
                for msg_id, fields in messages:
                    payload = parse_stream_message(fields)
                    bot_id = payload.get("bot_id", 1)
                    client = get_client_for_bot(bot_id)
                    job_type = payload.get("type", "post")
                    try:
                        if job_type == "update":
                            handle_update_job(client, payload)
                        else:
                            handle_post_job(client, payload)
                        r.xack(STREAM_JOBS, GROUP_NAME, msg_id)
                    except Exception as e:
                        logger.error(f"Unhandled worker error: {e}")
                        # Acknowledge to prevent blocking the PEL; alternatively, move to DLQ
                        r.xack(STREAM_JOBS, GROUP_NAME, msg_id)
        except Exception as loop_err:
            logger.error(f"Worker loop error: {loop_err}")
            time.sleep(1)


if __name__ == "__main__":
    main()


