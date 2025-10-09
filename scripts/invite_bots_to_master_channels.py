#!/usr/bin/env python3
"""
Invite All Bots to Master Channels
===================================

This script invites Bot-2 and Bot-3 to all master channels so they can start properly.
Run this before starting the multi-bot launcher.

Usage:
    python invite_bots_to_master_channels.py
"""

import os
import sys
import logging
import time
import random
from typing import Set
from dotenv import load_dotenv
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

# Add src directory to path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def get_bot_user_id(bot_token):
    """Get the user ID for a bot token"""
    try:
        client = WebClient(token=bot_token)
        response = client.auth_test()
        return response["user_id"]
    except SlackApiError as e:
        logger.error(f"Error getting bot user ID: {e.response['error']}")
        return None

def get_user_channels(client, user_id: str) -> Set[str]:
    """
    Bulk fetch all channels a user is already a member of.
    This is MUCH faster than checking each channel individually.
    """
    user_channels = set()
    cursor = None
    
    try:
        while True:
            response = client.users_conversations(
                user=user_id,
                limit=1000,
                cursor=cursor,
                types="public_channel,private_channel"
            )
            
            for channel in response["channels"]:
                user_channels.add(channel["id"])
            
            cursor = response.get("response_metadata", {}).get("next_cursor")
            if not cursor:
                break
            
            time.sleep(0.5)  # Small delay between pagination
        
        return user_channels
        
    except SlackApiError as e:
        logger.error(f"Error fetching user channels: {e.response['error']}")
        return set()
    except Exception as e:
        logger.error(f"Exception fetching user channels: {e}")
        return set()

def invite_bot_to_channel(client, channel_id, user_id, channel_name=""):
    """Invite a bot to a channel with proper rate limit handling"""
    try:
        # Invite the bot
        client.conversations_invite(
            channel=channel_id,
            users=user_id
        )
        return True
        
    except SlackApiError as e:
        error_code = e.response['error']
        
        if error_code == 'already_in_channel':
            return True
            
        elif e.response.status_code == 429:  # Rate limited
            # Respect Slack's Retry-After header
            retry_after = int(e.response.headers.get("Retry-After", 30))
            logger.warning(f"Rate limited. Waiting {retry_after}s...")
            time.sleep(retry_after)
            # Retry once
            try:
                client.conversations_invite(channel=channel_id, users=user_id)
                return True
            except SlackApiError:
                return False
        else:
            logger.error(f"   ❌ Error inviting bot to {channel_name}: {error_code}")
            return False

def main():
    """Main function to invite all bots to master channels"""
    logger.info("Starting bot invitation to master channels...")
    
    # Master channel IDs
    master_channels = {
        "master-agent": os.environ.get("AGENT_MASTER_CHANNEL_ID"),
        "master-apptbk": os.environ.get("APPTBK_MASTER_CHANNEL_ID"), 
        "master-admin-managed": os.environ.get("MANAGED_ADMIN_MASTER_CHANNEL_ID"),
        "master-admin-storm": os.environ.get("STORM_ADMIN_MASTER_CHANNEL_ID")
    }
    
    # Check if all master channels are configured
    missing_channels = [name for name, channel_id in master_channels.items() if not channel_id]
    if missing_channels:
        logger.error(f"❌ Missing master channel IDs: {', '.join(missing_channels)}")
        logger.error("Please configure all master channel environment variables")
        return False
    
    # Get bot tokens
    bot_tokens = {
        "Bot-1": os.environ.get("SLACK_BOT_TOKEN"),
        "Bot-2": os.environ.get("SLACK_BOT_TOKEN_2"),
        "Bot-3": os.environ.get("SLACK_BOT_TOKEN_3")
    }
    
    # Check if all bot tokens are configured
    missing_tokens = [name for name, token in bot_tokens.items() if not token]
    if missing_tokens:
        logger.error(f"❌ Missing bot tokens: {', '.join(missing_tokens)}")
        logger.error("Please configure all bot token environment variables")
        return False
    
    # Use Bot-1 as the inviter (it already has access to all channels)
    inviter_client = WebClient(token=bot_tokens["Bot-1"])
    
    # Get user IDs for Bot-2 and Bot-3
    bot_user_ids = {}
    for bot_name in ["Bot-2", "Bot-3"]:
        user_id = get_bot_user_id(bot_tokens[bot_name])
        if user_id:
            bot_user_ids[bot_name] = user_id
        else:
            logger.error(f"   ❌ Failed to get user ID for {bot_name}")
            return False
    
    for channel_name, channel_id in master_channels.items():
    
    
    # Invite each bot to each master channel
    for bot_name, user_id in bot_user_ids.items():
        
        # OPTIMIZATION: Bulk fetch existing memberships
        existing_channels = get_user_channels(inviter_client, user_id)
        
        for channel_name, channel_id in master_channels.items():
            # Skip if already a member
            if channel_id in existing_channels:
                continue
            
            success = invite_bot_to_channel(inviter_client, channel_id, user_id, channel_name)
            # Add randomized jitter
            delay = 1.5 + random.uniform(0, 0.5)
            time.sleep(delay)
    
    logger.info("Bot invitation to master channels completed")
    
    return True

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
