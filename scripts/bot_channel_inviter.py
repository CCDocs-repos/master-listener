#!/usr/bin/env python3
"""
Bot Channel Inviter
===================

This script uses Bot 1 (base bot) to invite all other bots to their assigned channels.
Run this after channel discovery and assignment to ensure all bots can access their channels.

Usage:
    python bot_channel_inviter.py
"""

import os
import sys
import json
import time
import random
import logging
from typing import Dict, List, Set
import requests
from dotenv import load_dotenv
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

# Add src directory to path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))

from config.multi_bot_config import MultiBotConfigManager

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class BotChannelInviter:
    """Manages inviting bots to their assigned channels"""
    
    def __init__(self):
        # Initialize multi-bot manager
        self.multi_bot_manager = MultiBotConfigManager()
        
        # Use Bot 1 (base bot) for invitations
        self.base_bot = self.multi_bot_manager.bot_configs[1]
        
        # Use Slack SDK WebClient instead of raw requests
        self.client = WebClient(token=self.base_bot.bot_token)
        
        # Rate limiting with jitter
        self.base_delay = 1.2  # Base delay between invitations
        self.max_jitter = 0.8  # Max random jitter to add
        
        logger.info(f"Bot Channel Inviter initialized (Base: {self.base_bot.name}, {len(self.multi_bot_manager.bot_configs) - 1} bots to invite)")
    
    def get_bot_user_id(self, bot_token: str) -> str:
        """Get the user ID for a bot token"""
        try:
            temp_client = WebClient(token=bot_token)
            response = temp_client.auth_test()
            return response["user_id"]
                
        except SlackApiError as e:
            logger.error(f"❌ Error getting bot user ID: {e.response['error']}")
            return None
        except Exception as e:
            logger.error(f"❌ Exception getting bot user ID: {e}")
            return None
    
    def get_user_channels(self, user_id: str) -> Set[str]:
        """
        Bulk fetch all channels a user is already a member of.
        This is MUCH faster than checking each channel individually.
        """
        user_channels = set()
        cursor = None
        
        try:
            while True:
                response = self.client.users_conversations(
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
                
                # Small delay between pagination calls
                time.sleep(0.5)
            
            return user_channels
            
        except SlackApiError as e:
            logger.error(f"❌ Error fetching user channels: {e.response['error']}")
            return set()
        except Exception as e:
            logger.error(f"❌ Exception fetching user channels: {e}")
            return set()
    
    def get_all_bot_user_ids(self) -> Dict[int, str]:
        """Get user IDs for all bots"""
        
        bot_user_ids = {}
        
        for bot_id, bot_config in self.multi_bot_manager.bot_configs.items():
            if bot_id == 1:
                # Skip base bot - it doesn't need to be invited to channels
                continue
            
            user_id = self.get_bot_user_id(bot_config.bot_token)
            if user_id:
                bot_user_ids[bot_id] = user_id
            else:
                logger.error(f"   ❌ Failed to get user ID for {bot_config.name}")
        
        return bot_user_ids
    
    
    def invite_bot_to_channel(self, channel_id: str, user_id: str, bot_name: str, channel_name: str = None) -> bool:
        """Invite a bot to a specific channel with proper rate limit handling"""
        try:
            # Invite the bot using WebClient
            self.client.conversations_invite(
                channel=channel_id,
                users=user_id
            )
            return True
            
        except SlackApiError as e:
            error_code = e.response['error']
            
            if error_code == 'already_in_channel':
                return True
                
            elif error_code == 'channel_not_found':
                return True  # Return True to not count as failure
                
            elif e.response.status_code == 429:  # Rate limited
                # Respect Slack's Retry-After header
                retry_after = int(e.response.headers.get("Retry-After", 30))
                logger.warning(f"Rate limited. Waiting {retry_after}s...")
                time.sleep(retry_after)
                # Retry once after waiting
                try:
                    self.client.conversations_invite(channel=channel_id, users=user_id)
                    return True
                except SlackApiError as retry_error:
                    logger.error(f"   ❌ Failed after retry for {channel_name or channel_id}: {retry_error.response['error']}")
                    return False
            else:
                logger.error(f"   ❌ Error inviting {bot_name} to {channel_name or channel_id}: {error_code}")
                return False
                
        except Exception as e:
            logger.error(f"   ❌ Exception inviting {bot_name} to {channel_name or channel_id}: {e}")
            return False
    
    def get_channel_name(self, channel_id: str) -> str:
        """Get channel name from channel ID"""
        try:
            response = self.client.conversations_info(channel=channel_id)
            return response["channel"]["name"]
        except SlackApiError:
            return channel_id
        except Exception:
            return channel_id
    
    def invite_bots_to_assigned_channels(self) -> Dict[int, Dict[str, int]]:
        """Invite all bots to their assigned channels with optimized bulk caching"""
        logger.info("Starting bot channel invitations...")
        
        # Get bot user IDs
        bot_user_ids = self.get_all_bot_user_ids()
        if not bot_user_ids:
            logger.error("❌ No bot user IDs found - cannot proceed")
            return {}
        
        # Get channel assignments
        channel_assignments = self.multi_bot_manager.channel_assignments
        if not channel_assignments:
            logger.error("❌ No channel assignments found - run channel discovery first")
            return {}
        
        # Group channels by bot
        bot_channels = {}
        for channel_id, bot_id in channel_assignments.items():
            if bot_id not in bot_channels:
                bot_channels[bot_id] = []
            bot_channels[bot_id].append(channel_id)
        
        # Invitation results
        results = {}
        
        # Invite each bot to its assigned channels
        for bot_id, user_id in bot_user_ids.items():
            bot_name = self.multi_bot_manager.bot_configs[bot_id].name
            assigned_channels = bot_channels.get(bot_id, [])
            
            if not assigned_channels:
                logger.warning(f"No channels assigned to {bot_name}")
                continue
            
            
            # OPTIMIZATION: Bulk fetch all channels the user is already in
            existing_channels = self.get_user_channels(user_id)
            
            # Filter out channels the bot is already in
            channels_to_invite = [ch for ch in assigned_channels if ch not in existing_channels]
            already_in = len(assigned_channels) - len(channels_to_invite)
            
            if len(channels_to_invite) > 0:
                logger.info(f"{bot_name}: Inviting to {len(channels_to_invite)} new channels")
            
            results[bot_id] = {
                "total_channels": len(assigned_channels),
                "successful_invitations": 0,
                "failed_invitations": 0,
                "already_in_channel": already_in,
                "skipped_not_found": 0
            }
            
            # Only invite to channels the bot is not already in
            for i, channel_id in enumerate(channels_to_invite, 1):
                # Get channel name for better logging
                channel_name = self.get_channel_name(channel_id)
                
                # Show progress every 20 channels
                if i % 20 == 0 or i == len(channels_to_invite):
                    pass  # Progress logging removed for cleaner output
                
                # Invite bot to channel
                success = self.invite_bot_to_channel(channel_id, user_id, bot_name, channel_name)
                
                if success:
                    results[bot_id]["successful_invitations"] += 1
                else:
                    results[bot_id]["failed_invitations"] += 1
                
                # Add randomized jitter to avoid burst rate limiting
                delay = self.base_delay + random.uniform(0, self.max_jitter)
                time.sleep(delay)
            
            # Log results for this bot
            bot_results = results[bot_id]
            if bot_results['successful_invitations'] > 0 or bot_results['failed_invitations'] > 0:
                logger.info(f"{bot_name}: {bot_results['successful_invitations']} invited, {bot_results['failed_invitations']} failed")
        
        return results
    
    def save_invitation_results(self, results: Dict[int, Dict[str, int]]):
        """Save invitation results to file"""
        try:
            invitation_data = {
                "metadata": {
                    "timestamp": "2024-01-01T00:00:00Z",  # You might want actual timestamp
                    "base_bot": self.base_bot.name,
                    "total_bots_processed": len(results)
                },
                "results": {}
            }
            
            # Convert results to include bot names
            for bot_id, bot_results in results.items():
                bot_name = self.multi_bot_manager.bot_configs[bot_id].name
                invitation_data["results"][bot_name] = bot_results
            
            with open("data/bot_invitation_results.json", "w") as f:
                json.dump(invitation_data, f, indent=2)
            
            
        except Exception as e:
            logger.error(f"❌ Error saving invitation results: {e}")
    
    def run_full_invitation_process(self):
        """Run the complete bot invitation process"""
        try:
            
            # Check if we have channel assignments
            if not self.multi_bot_manager.channel_assignments:
                logger.error("No channel assignments found! Run channel discovery first.")
                return False
            
            # Run invitations
            results = self.invite_bots_to_assigned_channels()
            
            if not results:
                logger.error("❌ No invitation results - process failed")
                return False
            
            # Save results
            self.save_invitation_results(results)
            
            # Summary
            
            total_successful = sum(r["successful_invitations"] for r in results.values())
            total_failed = sum(r["failed_invitations"] for r in results.values())
            total_channels = sum(r["total_channels"] for r in results.values())
            
            if total_successful > 0:
                logger.info(f"Summary: {total_successful}/{total_channels} successful ({(total_successful/total_channels*100):.1f}% success rate)")
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Error in invitation process: {e}")
            return False

def main():
    """Main execution"""
    try:
        inviter = BotChannelInviter()
        success = inviter.run_full_invitation_process()
        
        if success:
            print("\n✅ Bot invitation process completed successfully!")
            print("🚀 Your bots should now have access to their assigned channels.")
        else:
            print("\n❌ Bot invitation process failed. Check the logs above.")
            
    except Exception as e:
        logger.error(f"❌ Fatal error: {e}")

if __name__ == "__main__":
    main()
