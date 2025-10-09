#!/usr/bin/env python3
"""
Redis-Backed Listener
=====================

Purpose:
- Decouple Slack event ingestion from message forwarding using Redis.
- Enqueue normalized jobs to Redis Streams with idempotency.
- Remove inline chat_postMessage calls from event handlers to avoid burst limits.

This file mirrors the original listener's filters and routing decisions but
does NOT post to Slack directly. A separate worker should consume jobs,
apply token buckets and retries, and perform chat_postMessage/chat_update.
"""

from dotenv import load_dotenv
load_dotenv()

import os
import sys
import json
import hashlib
import logging
import time
import threading
import importlib.util
from typing import Dict, Any, Optional

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

# Add src directory to Python path for imports to work
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

from config.multi_bot_config import MultiBotConfigManager
from config.channel_discovery import ChannelDiscoveryManager


# ----------------------------------------------------------------------------
# Logging
# ----------------------------------------------------------------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ----------------------------------------------------------------------------
# Redis connection adapter
# ----------------------------------------------------------------------------
def get_redis_connection():
    """Attempt to import a global Redis connection `r`.

    Supports either `redis_client.py` (preferred) or `redis-client.py` at repo root.
    Returns a Redis client instance or raises if not found.
    """
    root_dir = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))

    # 1) Try module style import: redis_client
    try:
        import redis_client  # type: ignore
        if hasattr(redis_client, 'r'):
            return redis_client.r
    except Exception:
        pass

    # 2) Try loading from file path: redis-client.py
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
        logger.error(f"Failed to load redis-client.py: {e}")

    raise RuntimeError("Could not import Redis connection `r`. Ensure redis_client.py or redis-client.py exposes `r`.")


r = get_redis_connection()


# ----------------------------------------------------------------------------
# Multi-bot and Slack clients
# ----------------------------------------------------------------------------
multi_bot_manager = MultiBotConfigManager()
current_bot_config = multi_bot_manager.get_current_bot_config()

# Use env-provided tokens when set (multi-bot launcher sets these per thread)
client = WebClient(token=os.environ.get("SLACK_BOT_TOKEN", current_bot_config.bot_token))
app = App(token=os.environ.get("SLACK_BOT_TOKEN", current_bot_config.bot_token))


# ----------------------------------------------------------------------------
# Env and categorization
# ----------------------------------------------------------------------------
AGENT_MASTER_CHANNEL_ID = os.environ.get("AGENT_MASTER_CHANNEL_ID")
APPTBK_MASTER_CHANNEL_ID = os.environ.get("APPTBK_MASTER_CHANNEL_ID")
MANAGED_ADMIN_MASTER_CHANNEL_ID = os.environ.get("MANAGED_ADMIN_MASTER_CHANNEL_ID")
STORM_ADMIN_MASTER_CHANNEL_ID = os.environ.get("STORM_ADMIN_MASTER_CHANNEL_ID")


def load_channel_categorizations():
    try:
        with open('data/channel_lists.json', 'r') as f:
            data = json.load(f)
            return {
                'managed_channels': set(data.get('managed_channels', [])),
                'storm_channels': set(data.get('storm_channels', [])),
                'ignored_channels': set(data.get('ignored_channels', []))
            }
    except FileNotFoundError:
        logger.warning("channel_lists.json not found, using default categorizations")
        return {
            'managed_channels': set(),
            'storm_channels': set(),
            'ignored_channels': set(["ccdocs-admin", "test-admins"])
        }


CHANNEL_CATEGORIZATIONS = load_channel_categorizations()
IGNORED_CHANNEL_NAMES = [
    "ccdocs-agents",
    "ccdocs-admin",
    "ccdocs-apptbk",
    "ccdocs-dialer",
    "building-universal-agents",
    "master-agent",
    "master-admin-storm",
]


# ----------------------------------------------------------------------------
# Master channel validation (copied from listener.py)
# ----------------------------------------------------------------------------
def validate_master_channels():
    if not AGENT_MASTER_CHANNEL_ID or not APPTBK_MASTER_CHANNEL_ID:
        raise ValueError("AGENT_MASTER_CHANNEL_ID and APPTBK_MASTER_CHANNEL_ID must be set in environment variables")

    if not MANAGED_ADMIN_MASTER_CHANNEL_ID or not STORM_ADMIN_MASTER_CHANNEL_ID:
        raise ValueError("MANAGED_ADMIN_MASTER_CHANNEL_ID and STORM_ADMIN_MASTER_CHANNEL_ID must be set in environment variables")

    try:
        agent_info = client.conversations_info(channel=AGENT_MASTER_CHANNEL_ID)
        logger.info(f"Agent master channel validated: {agent_info['channel']['name']}")

        apptbk_info = client.conversations_info(channel=APPTBK_MASTER_CHANNEL_ID)
        logger.info(f"Apptbk master channel validated: {apptbk_info['channel']['name']}")

        managed_info = client.conversations_info(channel=MANAGED_ADMIN_MASTER_CHANNEL_ID)
        logger.info(f"Managed admin master channel validated: {managed_info['channel']['name']}")

        storm_info = client.conversations_info(channel=STORM_ADMIN_MASTER_CHANNEL_ID)
        logger.info(f"Storm admin master channel validated: {storm_info['channel']['name']}")
    except SlackApiError as e:
        logger.error(f"Error validating master channels: {e.response['error']}")
        raise


# ----------------------------------------------------------------------------
# Background scheduler (unchanged; Bot-1 refreshes mappings/assignments)
# ----------------------------------------------------------------------------
def update_client_lists():
    try:
        logger.info("🔄 Starting comprehensive channel mapping and bot assignment update...")

        if current_bot_config.bot_id == 1:
            logger.info("🔍 Running channel discovery and assignment (Bot 1 responsibility)...")
            try:
                discovery_manager = ChannelDiscoveryManager(multi_bot_manager)
                assignments = discovery_manager.run_full_discovery()
                if assignments:
                    logger.info("✅ Channel discovery and assignment completed")
                else:
                    logger.warning("⚠️ Channel discovery failed")
            except Exception as discovery_error:
                logger.error(f"❌ Channel discovery failed: {discovery_error}")
        else:
            logger.info(f"⏭️ Skipping channel discovery (Bot {current_bot_config.bot_id})")

        if current_bot_config.bot_id == 1:
            logger.info("🗺️ Running channel mapping (Bot 1 responsibility)...")
            try:
                from config.channel_mapper import ChannelMapper
                mapper = ChannelMapper()
                success = mapper.run_full_mapping()
                if success:
                    logger.info("✅ Channel mapping completed successfully")
                else:
                    logger.warning("⚠️ Channel mapping failed")
            except Exception as mapping_error:
                logger.warning(f"⚠️ Channel mapping failed: {mapping_error}")
        else:
            logger.info(f"⏭️ Skipping channel mapping (Bot {current_bot_config.bot_id})")

        # All bots reload categorizations and assignments
        logger.info("🔄 Reloading channel categorizations and assignments...")
        global CHANNEL_CATEGORIZATIONS
        CHANNEL_CATEGORIZATIONS = load_channel_categorizations()
        multi_bot_manager._load_channel_assignments()

        assigned_channels = multi_bot_manager.get_current_bot_channels()
        logger.info(f"📊 Updated counts for {current_bot_config.name}:")
        logger.info(f"   • Total managed channels: {len(CHANNEL_CATEGORIZATIONS['managed_channels'])}")
        logger.info(f"   • Total storm channels: {len(CHANNEL_CATEGORIZATIONS['storm_channels'])}")
        logger.info(f"   • Channels assigned to this bot: {len(assigned_channels)}")
        logger.info(f"   • Ignored channels: {len(CHANNEL_CATEGORIZATIONS['ignored_channels'])}")
    except Exception as e:
        logger.error(f"❌ Exception during channel mapping update: {str(e)}")


def client_list_scheduler():
    logger.info("🕐 Channel mapping scheduler started - will update every 12 hours")
    update_client_lists()
    while True:
        try:
            time.sleep(43200)  # 12h
            update_client_lists()
        except Exception as e:
            logger.error(f"❌ Error in client list scheduler: {str(e)}")
            logger.info("⏰ Retrying in 1 hour due to error...")
            time.sleep(3600)


# ----------------------------------------------------------------------------
# Redis idempotency and queueing utilities
# ----------------------------------------------------------------------------
STREAM_JOBS = "forwarding:jobs"
FCFS_TTL_SEC = 300  # 5 minutes for cross-bot FCFS claim


def build_fcfs_key(event_type: str, channel_id: str, identifier: str) -> str:
    if event_type == "message_changed":
        return f"fcfs:edit:{channel_id}:{identifier}"
    return f"fcfs:msg:{channel_id}:{identifier}"


def try_fcfs_claim(key: str, value: str) -> bool:
    """First-come-first-serve claim across all bots, TTL 5 minutes.

    Stores the message identifier as the value for traceability/debugging.
    """
    try:
        return bool(r.set(key, value, nx=True, ex=FCFS_TTL_SEC))
    except Exception as e:
        logger.error(f"Redis SET NX failed for {key}: {e}")
        # If Redis is unavailable, we cannot guarantee dedup; best effort: allow one bot to proceed
        return True


def get_message_identifier_from_event(event: Dict[str, Any]) -> str:
    """Prefer Slack's client_msg_id when available; fallback to ts.

    Note: client_msg_id is present for user-originated messages from Slack clients,
    not guaranteed for bot/system messages. ts is always present and acts as message id.
    """
    return event.get("client_msg_id") or event.get("ts", "")


def enqueue_forward_job(payload: Dict[str, Any]) -> Optional[str]:
    """Push a normalized job to Redis Streams for the worker."""
    try:
        # Serialize nested fields as JSON strings (Streams only accept flat fields)
        flat_payload: Dict[str, str] = {}
        for k, v in payload.items():
            if isinstance(v, (dict, list)):
                flat_payload[k] = json.dumps(v)
            elif v is None:
                continue
            else:
                flat_payload[k] = str(v)

        # Stream cap to avoid unbounded growth
        msg_id = r.xadd(STREAM_JOBS, flat_payload, maxlen=10000, approximate=True)
        return msg_id
    except Exception as e:
        logger.error(f"Redis XADD failed: {e}")
        return None


# ----------------------------------------------------------------------------
# Routing helpers (decide category and target channel)
# ----------------------------------------------------------------------------
def classify_channel(channel_name: str) -> Optional[str]:
    if channel_name.endswith("-apptbk"):
        return "apptbk"
    if channel_name.endswith("-admin") or channel_name.endswith("-admins"):
        if channel_name in CHANNEL_CATEGORIZATIONS['managed_channels']:
            return "managed_admin"
        if channel_name in CHANNEL_CATEGORIZATIONS['storm_channels']:
            return "storm_admin"
        # Unknown admin channel: skip (optional: default to storm)
        return None
    if channel_name.endswith("-agent") or channel_name.endswith("-agents"):
        return "agent"
    return None


def resolve_target_channel(category: str) -> Optional[str]:
    if category == "managed_admin":
        return MANAGED_ADMIN_MASTER_CHANNEL_ID
    if category == "storm_admin":
        return STORM_ADMIN_MASTER_CHANNEL_ID
    if category == "agent":
        return AGENT_MASTER_CHANNEL_ID
    if category == "apptbk":
        return APPTBK_MASTER_CHANNEL_ID
    return None


# ----------------------------------------------------------------------------
# Event handlers (enqueue-only)
# ----------------------------------------------------------------------------
@app.event("message")
def handle_message(event, body, say):
    try:
        channel_id = event["channel"]

        # FCFS cross-bot claim using Redis to avoid duplicate processing
        # Priority: client_msg_id (unique) > fallback to content hash (never use timestamp)
        message_identifier = event.get("client_msg_id")
        if not message_identifier:
            # Fallback: Create deterministic hash from event content
            event_signature = f"{channel_id}:{event.get('user', 'bot')}:{event.get('text', '')[:50]}"
            message_identifier = hashlib.md5(event_signature.encode()).hexdigest()[:16]
        
        message_key = build_fcfs_key("message", channel_id, message_identifier)
        if not try_fcfs_claim(message_key, message_identifier):
            return  # Duplicate - already claimed by another bot

        try:
            channel_info = client.conversations_info(channel=channel_id)["channel"]
            channel_name = channel_info["name"]

            # Skip ignored channels
            if channel_name in IGNORED_CHANNEL_NAMES or channel_name in CHANNEL_CATEGORIZATIONS['ignored_channels']:
                return

            # For apptbk: forward all (including bots). Else: ignore bot messages.
            if "bot_id" in event and not channel_name.endswith("-apptbk"):
                return

            category = classify_channel(channel_name)
            if not category:
                return  # Non-target or unknown admin channel

            target_channel = resolve_target_channel(category)
            if not target_channel:
                logger.error(f"Target channel not set for category {category}")
                return

        except SlackApiError as e:
            logger.error(f"Channel error [{channel_id}]: {e.response['error']}")
            return

        text = event.get("text", "")
        user = event.get("user") or event.get("bot_id", "unknown")
        timestamp = event["ts"]
        thread_ts = event.get("thread_ts")
        attachments = event.get("attachments", [])
        files = event.get("files", [])

        is_thread_reply = thread_ts is not None and thread_ts != timestamp

        job_payload = {
            "type": "post",  # worker distinguishes post vs update
            "category": category,
            "source_channel_id": channel_id,
            "source_channel_name": channel_name,
            "target_channel_id": target_channel,
            "user": user,
            "ts": timestamp,
            "thread_ts": thread_ts,
            "is_thread_reply": is_thread_reply,
            "text": text,
            "attachments": attachments,
            "files": files,
            "bot_id": current_bot_config.bot_id,
        }

        msg_id = enqueue_forward_job(job_payload)
        if msg_id:
            logger.info(f"ENQUEUED message -> stream={STREAM_JOBS} id={msg_id} cat={category} src=#{channel_name}")
        else:
            logger.error(f"Failed to enqueue message from #{channel_name}")
    except Exception as e:
        logger.error(f"Error handling message: {str(e)}")


@app.event("message_changed")
def handle_message_edit(event, body, say):
    try:
        edited_message = event["message"]
        channel_id = event["channel"]
        timestamp = edited_message["ts"]

        # FCFS claim for edits
        # Priority: client_msg_id (unique) > fallback to content hash (never use timestamp)
        edit_identifier = edited_message.get("client_msg_id")
        if not edit_identifier:
            # Fallback: Create deterministic hash from event content
            event_signature = f"{channel_id}:{edited_message.get('user', 'bot')}:{edited_message.get('text', '')[:50]}"
            edit_identifier = hashlib.md5(event_signature.encode()).hexdigest()[:16]
        
        edit_key = build_fcfs_key("message_changed", channel_id, edit_identifier)
        if not try_fcfs_claim(edit_key, edit_identifier):
            return  # Duplicate edit - already claimed

        try:
            channel_info = client.conversations_info(channel=channel_id)["channel"]
            channel_name = channel_info["name"]

            # Skip ignored channels
            if channel_name in IGNORED_CHANNEL_NAMES or channel_name in CHANNEL_CATEGORIZATIONS['ignored_channels']:
                return

            if "bot_id" in edited_message and not channel_name.endswith("-apptbk"):
                return

            category = classify_channel(channel_name)
            if not category:
                return  # Non-target or unknown admin channel

            target_channel = resolve_target_channel(category)
            if not target_channel:
                logger.error(f"Target channel not set for category {category}")
                return
        except SlackApiError as e:
            logger.error(f"Channel error [{channel_id}]: {e.response['error']}")
            return

        user = edited_message.get("user") or edited_message.get("bot_id", "unknown")
        text = edited_message.get("text", "")

        job_payload = {
            "type": "update",
            "category": category,
            "source_channel_id": channel_id,
            "source_channel_name": channel_name,
            "target_channel_id": target_channel,
            "user": user,
            "ts": timestamp,
            "text": text,
            "bot_id": current_bot_config.bot_id,
        }

        msg_id = enqueue_forward_job(job_payload)
        if msg_id:
            logger.info(f"ENQUEUED edit -> stream={STREAM_JOBS} id={msg_id} cat={category} src=#{channel_name}")
        else:
            logger.error(f"Failed to enqueue edit from #{channel_name}")
    except Exception as e:
        logger.error(f"Error handling message edit: {str(e)}")


# ----------------------------------------------------------------------------
# Main bootstrap
# ----------------------------------------------------------------------------
def main():
    try:
        # Debug: Log environment variables and state
        logger.info(f"AGENT_MASTER_CHANNEL_ID: {AGENT_MASTER_CHANNEL_ID}")
        logger.info(f"APPTBK_MASTER_CHANNEL_ID: {APPTBK_MASTER_CHANNEL_ID}")
        logger.info(f"MANAGED_ADMIN_MASTER_CHANNEL_ID: {MANAGED_ADMIN_MASTER_CHANNEL_ID}")
        logger.info(f"STORM_ADMIN_MASTER_CHANNEL_ID: {STORM_ADMIN_MASTER_CHANNEL_ID}")

        logger.info(f"Managed channels: {len(CHANNEL_CATEGORIZATIONS['managed_channels'])}")
        logger.info(f"Storm channels: {len(CHANNEL_CATEGORIZATIONS['storm_channels'])}")
        logger.info(f"Ignored channels: {len(CHANNEL_CATEGORIZATIONS['ignored_channels'])}")

        # Start channel mapping scheduler (unchanged)
        scheduler_thread = threading.Thread(target=client_list_scheduler, daemon=True)
        scheduler_thread.start()
        logger.info("🚀 Channel mapping scheduler thread started")

        # Validate master channels before starting
        validate_master_channels()

        # Start the app with current bot's app token (env override)
        app_token = os.environ.get("SLACK_APP_TOKEN", current_bot_config.app_token)
        logger.info(f"🔌 Connecting to Slack with app token: {app_token[:12]}...")
        handler = SocketModeHandler(app_token=app_token, app=app)

        if threading.current_thread() is threading.main_thread():
            handler.start()
        else:
            handler.connect()
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                logger.info("🛑 Bot thread interrupted")
                handler.disconnect()

    except Exception as e:
        logger.error(f"Error in main: {str(e)}")


if __name__ == "__main__":
    main()