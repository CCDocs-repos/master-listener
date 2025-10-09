from dotenv import load_dotenv
load_dotenv()

import os
import sys
import logging
import json
from datetime import datetime, timedelta
import pytz
import threading
import time
import subprocess
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

# Add src directory to Python path for imports to work
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

# Import multi-bot architecture components
from config.multi_bot_config import MultiBotConfigManager
from config.channel_discovery import ChannelDiscoveryManager

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize multi-bot configuration
# NOTE: This is initialized AFTER BOT_ID environment variable is set by multi_bot_launcher
multi_bot_manager = MultiBotConfigManager()
current_bot_config = multi_bot_manager.get_current_bot_config()

# Initialize Slack clients with current bot's tokens
# Use the tokens from the environment variables set by multi_bot_launcher
client = WebClient(token=os.environ.get("SLACK_BOT_TOKEN", current_bot_config.bot_token))
app = App(token=os.environ.get("SLACK_BOT_TOKEN", current_bot_config.bot_token))

logger.info(f"🤖 Multi-bot configuration:")
logger.info(f"   • Total bots: {len(multi_bot_manager.bot_configs)}")
logger.info(f"   • This bot ID: {current_bot_config.bot_id}")
logger.info(f"   • Bot name: {current_bot_config.name}")
logger.info(f"   • Bot Token (from env): {os.environ.get('SLACK_BOT_TOKEN', 'NOT SET')[:12]}...")
logger.info(f"   • App Token (from env): {os.environ.get('SLACK_APP_TOKEN', 'NOT SET')[:12]}...")
logger.info(f"   • Assigned channels: {len(multi_bot_manager.get_current_bot_channels())}")

# Master channel IDs
AGENT_MASTER_CHANNEL_ID = os.environ.get("AGENT_MASTER_CHANNEL_ID")
APPTBK_MASTER_CHANNEL_ID = os.environ.get("APPTBK_MASTER_CHANNEL_ID", "C0953PV5Z2T")

# New separate master channels for managed vs storm clients
MANAGED_ADMIN_MASTER_CHANNEL_ID = os.environ.get("MANAGED_ADMIN_MASTER_CHANNEL_ID")
STORM_ADMIN_MASTER_CHANNEL_ID = os.environ.get("STORM_ADMIN_MASTER_CHANNEL_ID")

# Load channel categorizations
def load_channel_categorizations():
    """Load channel categorizations from JSON file"""
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

# Load channel categorizations
CHANNEL_CATEGORIZATIONS = load_channel_categorizations()

# Channels to ignore - these are the channel names to ignore completely
IGNORED_CHANNEL_NAMES = [
    "ccdocs-agents", 
    "ccdocs-admin", 
    "ccdocs-apptbk",
    "ccdocs-dialer",
    "building-universal-agents",
    "master-agent", 
    "master-admin-storm"
]

# Duplicate detection cache (stores message keys: "msg_id:channel_id")
# Uses client_msg_id (unique per message) with channel_id
# Messages are kept for 5 minutes to prevent duplicate processing
processed_messages_cache = {}
cache_lock = threading.Lock()

def update_client_lists():
    """Update client lists, channel mappings, and bot assignments"""
    try:
        logger.info("🔄 Starting comprehensive channel mapping and bot assignment update...")
        
        # Step 1: Run channel discovery and assignment (only Bot 1 does this)
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
            logger.info(f"⏭️ Skipping channel discovery (Bot {current_bot_config.bot_id} - only Bot 1 handles discovery)")
        
        # Step 2: Run channel mapping (only Bot 1 does this)
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
                
                # Fallback to basic client list update
                logger.info("🔄 Falling back to basic client list update...")
                try:
                    from utils.clickup_client_fetcher import ClientListGenerator
                    
                    generator = ClientListGenerator()
                    client_lists = generator.fetch_client_lists()
                    
                    if client_lists:
                        generator.save_client_lists(client_lists)
                        logger.info("✅ Basic client lists updated as fallback")
                    else:
                        logger.warning("⚠️ No client data found in fallback")
                        
                except Exception as fallback_error:
                    logger.error(f"❌ Fallback client update also failed: {fallback_error}")
        else:
            logger.info(f"⏭️ Skipping channel mapping (Bot {current_bot_config.bot_id} - only Bot 1 handles mapping)")
        
        # Step 3: All bots reload their channel categorizations
        logger.info("🔄 Reloading channel categorizations...")
        global CHANNEL_CATEGORIZATIONS
        CHANNEL_CATEGORIZATIONS = load_channel_categorizations()
        
        # Step 4: All bots reload their channel assignments
        multi_bot_manager._load_channel_assignments()
        assigned_channels = multi_bot_manager.get_current_bot_channels()
        
        # Log the updated counts for this bot
        logger.info(f"📊 Updated counts for {current_bot_config.name}:")
        logger.info(f"   • Total managed channels: {len(CHANNEL_CATEGORIZATIONS['managed_channels'])}")
        logger.info(f"   • Total storm channels: {len(CHANNEL_CATEGORIZATIONS['storm_channels'])}")
        logger.info(f"   • Channels assigned to this bot: {len(assigned_channels)}")
        logger.info(f"   • Ignored channels: {len(CHANNEL_CATEGORIZATIONS['ignored_channels'])}")
            
    except Exception as e:
        logger.error(f"❌ Exception during channel mapping update: {str(e)}")

def client_list_scheduler():
    """Background scheduler to update client lists and channel mappings every 12 hours"""
    logger.info("🕐 Channel mapping scheduler started - will update every 12 hours")
    
    # Run initial update
    update_client_lists()
    
    while True:
        try:
            # Calculate next update time
            next_update = datetime.now() + timedelta(hours=12)
            logger.info(f"⏰ Next channel mapping update scheduled for: {next_update.strftime('%Y-%m-%d %I:%M:%S %p')}")
            
            # Wait 12 hours (43200 seconds)
            time.sleep(43200)
            update_client_lists()
        except Exception as e:
            logger.error(f"❌ Error in client list scheduler: {str(e)}")
            # Wait 1 hour before retrying if there's an error
            logger.info("⏰ Retrying in 1 hour due to error...")
            time.sleep(3600)

# Store message IDs to track edits and thread relationships
message_tracker = {}
thread_tracker = {}

def validate_master_channels():
    """Validate that master channel IDs are set and accessible"""
    if not AGENT_MASTER_CHANNEL_ID or not APPTBK_MASTER_CHANNEL_ID:
        raise ValueError("AGENT_MASTER_CHANNEL_ID and APPTBK_MASTER_CHANNEL_ID must be set in environment variables")

    if not MANAGED_ADMIN_MASTER_CHANNEL_ID or not STORM_ADMIN_MASTER_CHANNEL_ID:
        raise ValueError("MANAGED_ADMIN_MASTER_CHANNEL_ID and STORM_ADMIN_MASTER_CHANNEL_ID must be set in environment variables")

    try:
        # Validate agent master channel
        agent_info = client.conversations_info(channel=AGENT_MASTER_CHANNEL_ID)
        logger.info(f"Agent master channel validated: {agent_info['channel']['name']}")

        # Validate apptbk master channel
        apptbk_info = client.conversations_info(channel=APPTBK_MASTER_CHANNEL_ID)
        logger.info(f"Apptbk master channel validated: {apptbk_info['channel']['name']}")

        # Validate managed admin master channel
        managed_info = client.conversations_info(channel=MANAGED_ADMIN_MASTER_CHANNEL_ID)
        logger.info(f"Managed admin master channel validated: {managed_info['channel']['name']}")

        # Validate storm admin master channel
        storm_info = client.conversations_info(channel=STORM_ADMIN_MASTER_CHANNEL_ID)
        logger.info(f"Storm admin master channel validated: {storm_info['channel']['name']}")

    except SlackApiError as e:
        logger.error(f"Error validating master channels: {e.response['error']}")
        raise

def convert_to_est(timestamp):
    """Convert Unix timestamp to EST time string"""
    utc_time = datetime.fromtimestamp(float(timestamp))
    est = pytz.timezone('US/Eastern')
    est_time = utc_time.astimezone(est)
    return est_time.strftime('%Y-%m-%d %I:%M:%S %p %Z')

def fetch_private_channels():
    """Fetch all private channels and filter those ending with -admin or -agents"""
    try:
        # Fetch all private channels
        response = client.conversations_list(
            types="private_channel",
            limit=1000
        )
        channels = response["channels"]
        filtered_channels = []
        # Filter channels ending with -admin or -agent
        for channel in channels:
            if (channel["name"].endswith("-admin") or
                channel["name"].endswith("-agents") or
                channel["name"].endswith("-agent") or
                channel["name"].endswith("-admins") or
                channel["name"].endswith("-apptbk")):
                filtered_channels.append(channel)
                logger.info(f"Found target channel: {channel['name']} ({channel['id']})")
            else:
                logger.debug(f"Skipping non-target channel: {channel['name']}")
        return filtered_channels
    except SlackApiError as e:
        logger.error(f"Error fetching channels: {e.response['error']}")
        return []
def invite_bot_to_channels(channels):
    """Invite the bot to the specified channels"""
    bot_user_id = client.auth_test()["user_id"]
    for channel in channels:
        try:
            # Check if bot is already in the channel
            members = client.conversations_members(channel=channel["id"])["members"]
            if bot_user_id not in members:
                client.conversations_invite(
                    channel=channel["id"],
                    users=bot_user_id
                )
                logger.info(f"Invited bot to channel: {channel['name']}")
            else:
                logger.info(f"Bot already in channel: {channel['name']}")
        except SlackApiError as e:
            logger.error(f"Error inviting bot to channel {channel['name']}: {e.response['error']}")

def forward_managed_admin_message(channel_id, text, user, timestamp, message_ts=None, thread_ts=None, is_thread_reply=False, attachments=None, files=None):
    """Forward messages from managed client admin channels to managed master channel"""
    try:
        # Get channel info
        channel_info = client.conversations_info(channel=channel_id)["channel"]
        channel_name = channel_info["name"]
        
        # Ensure this is a managed admin channel
        if not (channel_name.endswith("-admin") or channel_name.endswith("-admins")):
            logger.error(f"forward_managed_admin_message called for non-admin channel: {channel_name}")
            return
            
        if channel_name not in CHANNEL_CATEGORIZATIONS['managed_channels']:
            logger.error(f"forward_managed_admin_message called for non-managed channel: {channel_name}")
            return
            
        # Check if channel should be ignored
        if channel_name in IGNORED_CHANNEL_NAMES:
            logger.info(f"Ignoring message from explicitly ignored channel: {channel_name}")
            return
            
        if channel_name in CHANNEL_CATEGORIZATIONS['ignored_channels']:
            logger.info(f"Ignoring message from ignored managed admin channel: {channel_name}")
            return
            
        if not MANAGED_ADMIN_MASTER_CHANNEL_ID:
            logger.error(f"MANAGED_ADMIN_MASTER_CHANNEL_ID not set, cannot forward message from {channel_name}")
            return
            
        target_channel = MANAGED_ADMIN_MASTER_CHANNEL_ID

        
        # Format the forwarded message
        est_time = convert_to_est(timestamp)
        message = f"*From #{channel_name}*\n{text}\n_Posted by <@{user}> at {est_time}_"

        # Prepare message parameters
        message_params = {
            "channel": target_channel,
            "text": message
        }

        # Add thread_ts if this is a thread reply
        if is_thread_reply:
            parent_key = f"{channel_id}_{thread_ts}"
            logger.info(f"Looking for parent message with key: {parent_key}")

            if parent_key in message_tracker:
                message_params["thread_ts"] = message_tracker[parent_key]
            else:
                # Try to fetch the original message and its thread
                try:
                    result = client.conversations_history(
                        channel=channel_id,
                        latest=thread_ts,
                        limit=1,
                        inclusive=True
                    )

                    if result["messages"]:
                        original_msg = result["messages"][0]
                        original_ts = original_msg["ts"]

                        thread_result = client.conversations_replies(
                            channel=channel_id,
                            ts=original_ts
                        )

                        if thread_result["messages"]:
                            parent_msg = thread_result["messages"][0]
                            parent_ts = parent_msg["ts"]

                            if f"{channel_id}_{parent_ts}" not in message_tracker:
                                parent_message = f"*From #{channel_name}*\n{parent_msg['text']}\n_Posted by <@{parent_msg['user']}> at {convert_to_est(parent_ts)}_"
                                parent_response = client.chat_postMessage(
                                    channel=target_channel,
                                    text=parent_message
                                )
                                message_tracker[f"{channel_id}_{parent_ts}"] = parent_response["ts"]

                            message_params["thread_ts"] = message_tracker[f"{channel_id}_{parent_ts}"]

                except SlackApiError as e:
                    logger.error(f"Error fetching thread messages: {e.response['error']}")
                    return

        # Handle files if present
        if files:
            for file in files:
                try:
                    # Get file info
                    file_info = client.files_info(file=file["id"])

                    # Add file to message
                    if "attachments" not in message_params:
                        message_params["attachments"] = []

                    # Create a file attachment
                    file_attachment = {
                        "fallback": f"File: {file_info['file']['name']}",
                        "title": file_info["file"]["name"],
                        "title_link": file_info["file"]["url_private"],
                        "text": f"File shared by <@{user}>",
                        "ts": timestamp
                    }

                    # Add image_url for image files
                    if file_info["file"]["mimetype"].startswith("image/"):
                        file_attachment["image_url"] = file_info["file"]["url_private"]

                    message_params["attachments"].append(file_attachment)
                    logger.info(f"Added file attachment: {file_info['file']['name']}")

                except SlackApiError as e:
                    logger.error(f"Error handling file: {e.response['error']}")

        # Add regular attachments if present
        if attachments:
            if "attachments" not in message_params:
                message_params["attachments"] = []
            message_params["attachments"].extend(attachments)

        if message_ts:
            # This is an edit, update the existing message
            message_params["ts"] = message_ts
            client.chat_update(**message_params)
            logger.info(f"Updated managed admin message in master channel {target_channel} from {channel_name}")
        else:
            # This is a new message
            response = client.chat_postMessage(**message_params)
            # Store the message ID for future edits and thread tracking
            message_tracker[f"{channel_id}_{timestamp}"] = response["ts"]
            logger.info(f"SUCCESSFULLY FORWARDED managed admin message from {channel_name} to master channel {target_channel}")

    except SlackApiError as e:
        logger.error(f"Error forwarding managed admin message: {e.response['error']}")

def forward_storm_admin_message(channel_id, text, user, timestamp, message_ts=None, thread_ts=None, is_thread_reply=False, attachments=None, files=None):
    """Forward messages from storm client admin channels to storm master channel"""
    try:
        # Get channel info
        channel_info = client.conversations_info(channel=channel_id)["channel"]
        channel_name = channel_info["name"]
        
        # Ensure this is a storm admin channel
        if not (channel_name.endswith("-admin") or channel_name.endswith("-admins")):
            logger.error(f"forward_storm_admin_message called for non-admin channel: {channel_name}")
            return
            
        if channel_name not in CHANNEL_CATEGORIZATIONS['storm_channels']:
            logger.error(f"forward_storm_admin_message called for non-storm channel: {channel_name}")
            return
            
        # Check if channel should be ignored
        if channel_name in IGNORED_CHANNEL_NAMES:
            logger.info(f"Ignoring message from explicitly ignored channel: {channel_name}")
            return
            
        if channel_name in CHANNEL_CATEGORIZATIONS['ignored_channels']:
            logger.info(f"Ignoring message from ignored storm admin channel: {channel_name}")
            return
            
        if not STORM_ADMIN_MASTER_CHANNEL_ID:
            logger.error(f"STORM_ADMIN_MASTER_CHANNEL_ID not set, cannot forward message from {channel_name}")
            return
            
        target_channel = STORM_ADMIN_MASTER_CHANNEL_ID


        # Format the forwarded message
        est_time = convert_to_est(timestamp)
        message = f"*From #{channel_name}*\n{text}\n_Posted by <@{user}> at {est_time}_"

        # Prepare message parameters
        message_params = {
            "channel": target_channel,
            "text": message
        }

        # Add thread_ts if this is a thread reply
        if is_thread_reply:
            parent_key = f"{channel_id}_{thread_ts}"
            logger.info(f"Looking for parent message with key: {parent_key}")

            if parent_key in message_tracker:
                message_params["thread_ts"] = message_tracker[parent_key]
            else:
                # Try to fetch the original message and its thread
                try:
                    result = client.conversations_history(
                        channel=channel_id,
                        latest=thread_ts,
                        limit=1,
                        inclusive=True
                    )

                    if result["messages"]:
                        original_msg = result["messages"][0]
                        original_ts = original_msg["ts"]

                        thread_result = client.conversations_replies(
                            channel=channel_id,
                            ts=original_ts
                        )

                        if thread_result["messages"]:
                            parent_msg = thread_result["messages"][0]
                            parent_ts = parent_msg["ts"]

                            if f"{channel_id}_{parent_ts}" not in message_tracker:
                                parent_message = f"*From #{channel_name}*\n{parent_msg['text']}\n_Posted by <@{parent_msg['user']}> at {convert_to_est(parent_ts)}_"
                                parent_response = client.chat_postMessage(
                                    channel=target_channel,
                                    text=parent_message
                                )
                                message_tracker[f"{channel_id}_{parent_ts}"] = parent_response["ts"]

                            message_params["thread_ts"] = message_tracker[f"{channel_id}_{parent_ts}"]

                except SlackApiError as e:
                    logger.error(f"Error fetching thread messages: {e.response['error']}")
                    return

        # Handle files if present
        if files:
            for file in files:
                try:
                    # Get file info
                    file_info = client.files_info(file=file["id"])

                    # Add file to message
                    if "attachments" not in message_params:
                        message_params["attachments"] = []

                    # Create a file attachment
                    file_attachment = {
                        "fallback": f"File: {file_info['file']['name']}",
                        "title": file_info["file"]["name"],
                        "title_link": file_info["file"]["url_private"],
                        "text": f"File shared by <@{user}>",
                        "ts": timestamp
                    }

                    # Add image_url for image files
                    if file_info["file"]["mimetype"].startswith("image/"):
                        file_attachment["image_url"] = file_info["file"]["url_private"]

                    message_params["attachments"].append(file_attachment)
                    logger.info(f"Added file attachment: {file_info['file']['name']}")

                except SlackApiError as e:
                    logger.error(f"Error handling file: {e.response['error']}")

        # Add regular attachments if present
        if attachments:
            if "attachments" not in message_params:
                message_params["attachments"] = []
            message_params["attachments"].extend(attachments)

        if message_ts:
            # This is an edit, update the existing message
            message_params["ts"] = message_ts
            client.chat_update(**message_params)
            logger.info(f"Updated storm admin message in master channel {target_channel} from {channel_name}")
        else:
            # This is a new message
            response = client.chat_postMessage(**message_params)
            # Store the message ID for future edits and thread tracking
            message_tracker[f"{channel_id}_{timestamp}"] = response["ts"]
            logger.info(f"SUCCESSFULLY FORWARDED storm admin message from {channel_name} to master channel {target_channel}")

    except SlackApiError as e:
        logger.error(f"Error forwarding storm admin message: {e.response['error']}")

def forward_agent_message(channel_id, text, user, timestamp, message_ts=None, thread_ts=None, is_thread_reply=False, attachments=None, files=None):
    """Forward messages from agent channels to agent master channel"""
    try:
        # Get channel info
        channel_info = client.conversations_info(channel=channel_id)["channel"]
        channel_name = channel_info["name"]
        
        # Ensure this is an agent channel
        if not (channel_name.endswith("-agent") or channel_name.endswith("-agents")):
            logger.error(f"forward_agent_message called for non-agent channel: {channel_name}")
            return
            
        # Check if channel should be ignored
        if channel_name in IGNORED_CHANNEL_NAMES:
            logger.info(f"Ignoring message from explicitly ignored channel: {channel_name}")
            return
            
        if channel_name in CHANNEL_CATEGORIZATIONS['ignored_channels']:
            logger.info(f"Ignoring message from ignored agent channel: {channel_name}")
            return
            
        if not AGENT_MASTER_CHANNEL_ID:
            logger.error(f"AGENT_MASTER_CHANNEL_ID not set, cannot forward message from {channel_name}")
            return
            
        target_channel = AGENT_MASTER_CHANNEL_ID

        
        # Format the forwarded message
        est_time = convert_to_est(timestamp)
        message = f"*From #{channel_name}*\n{text}\n_Posted by <@{user}> at {est_time}_"

        # Prepare message parameters
        message_params = {
            "channel": target_channel,
            "text": message
        }

        # Add thread_ts if this is a thread reply
        if is_thread_reply:
            parent_key = f"{channel_id}_{thread_ts}"
            logger.info(f"Looking for parent message with key: {parent_key}")

            if parent_key in message_tracker:
                message_params["thread_ts"] = message_tracker[parent_key]
            else:
                # Try to fetch the original message and its thread
                try:
                    result = client.conversations_history(
                        channel=channel_id,
                        latest=thread_ts,
                        limit=1,
                        inclusive=True
                    )

                    if result["messages"]:
                        original_msg = result["messages"][0]
                        original_ts = original_msg["ts"]

                        thread_result = client.conversations_replies(
                            channel=channel_id,
                            ts=original_ts
                        )

                        if thread_result["messages"]:
                            parent_msg = thread_result["messages"][0]
                            parent_ts = parent_msg["ts"]

                            if f"{channel_id}_{parent_ts}" not in message_tracker:
                                parent_message = f"*From #{channel_name}*\n{parent_msg['text']}\n_Posted by <@{parent_msg['user']}> at {convert_to_est(parent_ts)}_"
                                parent_response = client.chat_postMessage(
                                    channel=target_channel,
                                    text=parent_message
                                )
                                message_tracker[f"{channel_id}_{parent_ts}"] = parent_response["ts"]

                            message_params["thread_ts"] = message_tracker[f"{channel_id}_{parent_ts}"]

                except SlackApiError as e:
                    logger.error(f"Error fetching thread messages: {e.response['error']}")
                    return

        # Handle files if present
        if files:
            for file in files:
                try:
                    # Get file info
                    file_info = client.files_info(file=file["id"])

                    # Add file to message
                    if "attachments" not in message_params:
                        message_params["attachments"] = []

                    # Create a file attachment
                    file_attachment = {
                        "fallback": f"File: {file_info['file']['name']}",
                        "title": file_info["file"]["name"],
                        "title_link": file_info["file"]["url_private"],
                        "text": f"File shared by <@{user}>",
                        "ts": timestamp
                    }

                    # Add image_url for image files
                    if file_info["file"]["mimetype"].startswith("image/"):
                        file_attachment["image_url"] = file_info["file"]["url_private"]

                    message_params["attachments"].append(file_attachment)
                    logger.info(f"Added file attachment: {file_info['file']['name']}")

                except SlackApiError as e:
                    logger.error(f"Error handling file: {e.response['error']}")

        # Add regular attachments if present
        if attachments:
            if "attachments" not in message_params:
                message_params["attachments"] = []
            message_params["attachments"].extend(attachments)

        if message_ts:
            # This is an edit, update the existing message
            message_params["ts"] = message_ts
            client.chat_update(**message_params)
            logger.info(f"Updated agent message in master channel {target_channel} from {channel_name}")
        else:
            # This is a new message
            response = client.chat_postMessage(**message_params)
            # Store the message ID for future edits and thread tracking
            message_tracker[f"{channel_id}_{timestamp}"] = response["ts"]
            logger.info(f"SUCCESSFULLY FORWARDED agent message from {channel_name} to master channel {target_channel}")

    except SlackApiError as e:
        logger.error(f"Error forwarding agent message: {e.response['error']}")

def forward_apptbk_message(channel_id, text, user, timestamp, message_ts=None, thread_ts=None, is_thread_reply=False, attachments=None, files=None):
    """Forward ALL messages (bots and non-bots) from apptbk channels to master-apptbk"""
    try:
        # Get channel info
        channel_info = client.conversations_info(channel=channel_id)["channel"]
        channel_name = channel_info["name"]
        
            # Ensure this is an apptbk channel
        if not channel_name.endswith("-apptbk"):
            logger.error(f"forward_apptbk_message called for non-apptbk channel: {channel_name}")
            return
            
        # Check if channel should be ignored
        if channel_name in IGNORED_CHANNEL_NAMES:
            logger.info(f"Ignoring message from explicitly ignored channel: {channel_name}")
            return
            
        if channel_name in CHANNEL_CATEGORIZATIONS['ignored_channels']:
            logger.info(f"Ignoring message from ignored apptbk channel: {channel_name}")
            return
            
        target_channel = APPTBK_MASTER_CHANNEL_ID


        # Format the forwarded message
        est_time = convert_to_est(timestamp)
        message = f"*From #{channel_name}*\n{text}\n_Posted by <@{user}> at {est_time}_"

        # Prepare message parameters
        message_params = {
            "channel": target_channel,
            "text": message
        }

        # Add thread_ts if this is a thread reply
        if is_thread_reply:
            parent_key = f"{channel_id}_{thread_ts}"
            logger.info(f"Looking for parent message with key: {parent_key}")

            if parent_key in message_tracker:
                message_params["thread_ts"] = message_tracker[parent_key]
            else:
                # Try to fetch the original message and its thread
                try:
                    result = client.conversations_history(
                        channel=channel_id,
                        latest=thread_ts,
                        limit=1,
                        inclusive=True
                    )

                    if result["messages"]:
                        original_msg = result["messages"][0]
                        original_ts = original_msg["ts"]

                        thread_result = client.conversations_replies(
                            channel=channel_id,
                            ts=original_ts
                        )

                        if thread_result["messages"]:
                            parent_msg = thread_result["messages"][0]
                            parent_ts = parent_msg["ts"]

                            if f"{channel_id}_{parent_ts}" not in message_tracker:
                                parent_message = f"*From #{channel_name}*\n{parent_msg['text']}\n_Posted by <@{parent_msg['user']}> at {convert_to_est(parent_ts)}_"
                                parent_response = client.chat_postMessage(
                                    channel=target_channel,
                                    text=parent_message
                                )
                                message_tracker[f"{channel_id}_{parent_ts}"] = parent_response["ts"]

                            message_params["thread_ts"] = message_tracker[f"{channel_id}_{parent_ts}"]

                except SlackApiError as e:
                    logger.error(f"Error fetching thread messages: {e.response['error']}")
                    return

        # Handle files if present
        if files:
            for file in files:
                try:
                    # Get file info
                    file_info = client.files_info(file=file["id"])

                    # Add file to message
                    if "attachments" not in message_params:
                        message_params["attachments"] = []

                    # Create a file attachment
                    file_attachment = {
                        "fallback": f"File: {file_info['file']['name']}",
                        "title": file_info["file"]["name"],
                        "title_link": file_info["file"]["url_private"],
                        "text": f"File shared by <@{user}>",
                        "ts": timestamp
                    }

                    # Add image_url for image files
                    if file_info["file"]["mimetype"].startswith("image/"):
                        file_attachment["image_url"] = file_info["file"]["url_private"]

                    message_params["attachments"].append(file_attachment)
                    logger.info(f"Added file attachment: {file_info['file']['name']}")

                except SlackApiError as e:
                    logger.error(f"Error handling file: {e.response['error']}")

        # Add regular attachments if present
        if attachments:
            if "attachments" not in message_params:
                message_params["attachments"] = []
            message_params["attachments"].extend(attachments)

        if message_ts:
            # This is an edit, update the existing message
            message_params["ts"] = message_ts
            client.chat_update(**message_params)
            logger.info(f"Updated apptbk message in master channel {target_channel} from {channel_name}")
        else:
            # This is a new message
            response = client.chat_postMessage(**message_params)
            # Store the message ID for future edits and thread tracking
            message_tracker[f"{channel_id}_{timestamp}"] = response["ts"]
            logger.info(f"SUCCESSFULLY FORWARDED apptbk message from {channel_name} to master channel {target_channel}")

    except SlackApiError as e:
        logger.error(f"Error forwarding apptbk message: {e.response['error']}")

def forward_message(channel_id, text, user, timestamp, message_ts=None, thread_ts=None, is_thread_reply=False, attachments=None, files=None):
    """Route messages to appropriate dedicated forwarding functions based on source channel"""
    try:
        # Get channel info to determine the type
        channel_info = client.conversations_info(channel=channel_id)["channel"]
        channel_name = channel_info["name"]

        # Check if channel should be ignored first
        if channel_name in CHANNEL_CATEGORIZATIONS['ignored_channels']:
            logger.info(f"Ignoring message from ignored channel: {channel_name}")
            return

        # Route to dedicated functions based on channel type
        if channel_name.endswith("-apptbk"):
            forward_apptbk_message(channel_id, text, user, timestamp, message_ts, thread_ts, is_thread_reply, attachments, files)
        elif channel_name.endswith("-admin") or channel_name.endswith("-admins"):
            # Check if it's a managed or storm client
            if channel_name in CHANNEL_CATEGORIZATIONS['managed_channels']:
                forward_managed_admin_message(channel_id, text, user, timestamp, message_ts, thread_ts, is_thread_reply, attachments, files)
            elif channel_name in CHANNEL_CATEGORIZATIONS['storm_channels']:
                forward_storm_admin_message(channel_id, text, user, timestamp, message_ts, thread_ts, is_thread_reply, attachments, files)
            else:
                # Unknown admin channel - don't forward
                logger.warning(f"Unknown admin channel {channel_name} - not forwarding")
        elif channel_name.endswith("-agent") or channel_name.endswith("-agents"):
            forward_agent_message(channel_id, text, user, timestamp, message_ts, thread_ts, is_thread_reply, attachments, files)

    except SlackApiError as e:
        logger.error(f"Error in forward_message router: {e.response['error']}")
        return

@app.event("message")
def handle_message(event, say):
    """Handle incoming messages"""
    try:
        channel_id = event["channel"]

        # FIRST-COME-FIRST-SERVE: Any bot can process, message ID-based deduplication
        # Extract message ID (client_msg_id is unique per message, ts as fallback)
        msg_id = event.get("client_msg_id") or event.get("ts", "")
        message_key = f"{msg_id}:{channel_id}"
        
        # Log the message ID for debugging
        logger.info(f"[{current_bot_config.name}] 📩 Received message - Channel: {channel_id}, Message ID: {msg_id}, Key: {message_key}")
        
        # Check for duplicate processing (prevents multiple bots from handling same message)
        with cache_lock:
            current_time = time.time()
            
            # Clean old entries (older than 5 minutes)
            expired_keys = [k for k, v in processed_messages_cache.items() if current_time - v > 300]
            for k in expired_keys:
                del processed_messages_cache[k]
            
            # Check if already processed
            if message_key in processed_messages_cache:
                logger.info(f"[{current_bot_config.name}] ⏭️ DUPLICATE - Message {message_key} already processed by another bot")
                return
            
            # Mark as processed IMMEDIATELY (claim ownership)
            processed_messages_cache[message_key] = current_time
        
        logger.info(f"[{current_bot_config.name}] 🏃 FIRST-RESPONDER - Processing message {message_key}")

        try:
            channel_info = client.conversations_info(channel=channel_id)["channel"]
            channel_name = channel_info["name"]

            # Ignore messages from explicitly ignored channels
            if channel_name in IGNORED_CHANNEL_NAMES:
                logger.info(f"IGNORING message from explicitly ignored channel: {channel_name}")
                return

            # Ignore messages from categorized ignored channels
            if channel_name in CHANNEL_CATEGORIZATIONS['ignored_channels']:
                logger.info(f"IGNORING message from categorized ignored channel: {channel_name}")
                return

            # Ignore bot messages in non-apptbk channels
            if "bot_id" in event and not channel_name.endswith("-apptbk"):
                return

            # Only process messages from channels ending with specific suffixes
            if not (channel_name.endswith("-admin") or
                   channel_name.endswith("-admins") or
                   channel_name.endswith("-agent") or
                   channel_name.endswith("-agents") or
                   channel_name.endswith("-apptbk")):
                logger.info(f"Ignoring message from non-target channel: {channel_name}")
                return

        except SlackApiError as e:
            logger.error(f"Error getting channel info: {e.response['error']}")
            return

        text = event.get("text", "")
        # Handle both user messages and bot messages
        user = event.get("user") or event.get("bot_id", "unknown")
        timestamp = event["ts"]
        thread_ts = event.get("thread_ts")
        attachments = event.get("attachments", [])
        files = event.get("files", [])

        # Check if this is a thread reply
        is_thread_reply = thread_ts is not None and thread_ts != timestamp

        logger.info(f"[{current_bot_config.name}] ✅ PROCESSING message - Channel: {channel_name} ({channel_id}), Timestamp: {timestamp}, Thread TS: {thread_ts}, Is Thread Reply: {is_thread_reply}, Has Attachments: {bool(attachments)}, Has Files: {bool(files)}")

        forward_message(
            channel_id=channel_id,
            text=text,
            user=user,
            timestamp=timestamp,
            thread_ts=thread_ts,
            is_thread_reply=is_thread_reply,
            attachments=attachments,
            files=files
        )
        
        logger.info(f"[{current_bot_config.name}] ✅ FORWARDED message from {channel_name}")
    except Exception as e:
        logger.error(f"[{current_bot_config.name}] Error handling message: {str(e)}")

@app.event("message_changed")
def handle_message_edit(event, say):
    """Handle edited messages"""
    try:
        # Get the edited message details
        edited_message = event["message"]
        channel_id = event["channel"]
        timestamp = edited_message["ts"]
        
        # FIRST-COME-FIRST-SERVE: Any bot can process, message ID-based deduplication
        # Extract message ID from edited message
        msg_id = edited_message.get("client_msg_id") or timestamp
        message_key = f"{msg_id}:{channel_id}:edit"
        
        # Log the edit message ID for debugging
        logger.info(f"[{current_bot_config.name}] 📝 Received edit - Channel: {channel_id}, Message ID: {msg_id}, Key: {message_key}")
        
        # Check for duplicate processing
        with cache_lock:
            current_time = time.time()
            
            # Check if already processed
            if message_key in processed_messages_cache:
                logger.info(f"[{current_bot_config.name}] ⏭️ DUPLICATE - Edit {message_key} already processed by another bot")
                return
            
            # Mark as processed IMMEDIATELY (claim ownership)
            processed_messages_cache[message_key] = current_time
        
        logger.info(f"[{current_bot_config.name}] 🏃 FIRST-RESPONDER - Processing edit {message_key}")

        try:
            channel_info = client.conversations_info(channel=channel_id)["channel"]
            channel_name = channel_info["name"]

            # Ignore edits from explicitly ignored channels
            if channel_name in IGNORED_CHANNEL_NAMES:
                logger.info(f"IGNORING edit from explicitly ignored channel: {channel_name}")
                return

            # Ignore edits from categorized ignored channels
            if channel_name in CHANNEL_CATEGORIZATIONS['ignored_channels']:
                logger.info(f"IGNORING edit from categorized ignored channel: {channel_name}")
                return

            # Ignore bot edits in non-apptbk channels
            if "bot_id" in edited_message and not channel_name.endswith("-apptbk"):
                logger.info(f"Ignoring bot edit in non-apptbk channel: {channel_name}")
                return

            logger.info(f"Channel name for edit: {channel_name}")

            # Ignore messages from master channels
            if channel_id in [AGENT_MASTER_CHANNEL_ID, APPTBK_MASTER_CHANNEL_ID, 
                            MANAGED_ADMIN_MASTER_CHANNEL_ID, STORM_ADMIN_MASTER_CHANNEL_ID]:
                logger.info(f"Ignoring message from master channel: {channel_name}")
                return

            # Only process messages from channels ending with specific suffixes
            if not (channel_name.endswith("-admin") or
                   channel_name.endswith("-admins") or
                   channel_name.endswith("-agent") or
                   channel_name.endswith("-agents") or
                   channel_name.endswith("-apptbk")):
                logger.info(f"Ignoring message from non-target channel: {channel_name}")
                return

        except SlackApiError as e:
            logger.error(f"Error getting channel info for edit: {e.response['error']}")
            return

        # Get the original message ID
        message_key = f"{channel_id}_{timestamp}"
        if message_key in message_tracker:
            # Forward the edited message
            forward_message(
                channel_id=channel_id,
                text=edited_message["text"],
                user=edited_message.get("user") or edited_message.get("bot_id", "unknown"),
                timestamp=timestamp,
                message_ts=message_tracker[message_key]
            )
            logger.info(f"Updated edited message in master channel")
        else:
            logger.warning(f"Could not find original message to update: {message_key}")
    except Exception as e:
        logger.error(f"Error handling message edit: {str(e)}")

def main():
    """Main function to initialize the bot"""
    try:
        # Debug: Log environment variables
        logger.info(f"AGENT_MASTER_CHANNEL_ID: {AGENT_MASTER_CHANNEL_ID}")
        logger.info(f"APPTBK_MASTER_CHANNEL_ID: {APPTBK_MASTER_CHANNEL_ID}")
        logger.info(f"MANAGED_ADMIN_MASTER_CHANNEL_ID: {MANAGED_ADMIN_MASTER_CHANNEL_ID}")
        logger.info(f"STORM_ADMIN_MASTER_CHANNEL_ID: {STORM_ADMIN_MASTER_CHANNEL_ID}")
        
        # Log channel categorizations
        logger.info(f"Managed channels: {len(CHANNEL_CATEGORIZATIONS['managed_channels'])}")
        logger.info(f"Storm channels: {len(CHANNEL_CATEGORIZATIONS['storm_channels'])}")
        logger.info(f"Ignored channels: {len(CHANNEL_CATEGORIZATIONS['ignored_channels'])}")

        # Validate master channels
        validate_master_channels()

        # Start the channel mapping scheduler in a background thread
        scheduler_thread = threading.Thread(target=client_list_scheduler, daemon=True)
        scheduler_thread.start()
        logger.info("🚀 Channel mapping scheduler thread started")

        # Note: Channel invitation removed - not needed for mapping functionality
        logger.info("🚀 Bot initialization complete - ready to listen for messages")
        # Start the app with current bot's app token (from environment variable set by multi_bot_launcher)
        app_token = os.environ.get("SLACK_APP_TOKEN", current_bot_config.app_token)
        logger.info(f"🔌 Connecting to Slack with app token: {app_token[:12]}...")
        handler = SocketModeHandler(app_token=app_token, app=app)
        
        # Check if we're running in the main thread (for signal handling)
        if threading.current_thread() is threading.main_thread():
            handler.start()
        else:
            # If running in a thread, use connect() instead of start()
            handler.connect()
            # Keep the thread alive
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
