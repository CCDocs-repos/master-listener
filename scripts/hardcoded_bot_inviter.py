#!/usr/bin/env python3
"""
Hardcoded Bot Channel Inviter
=============================

Simple script with hardcoded credentials to invite bots to their assigned channels.
Modify the HARDCODED_BOTS section with your actual bot tokens.

Usage:
    python hardcoded_bot_inviter.py
"""

import json
import time
import logging
import requests
import hashlib

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 🔧 HARDCODED BOT CONFIGURATIONS
# Replace these with your actual bot tokens
# Load bot tokens from environment variables
# WARNING: Do not hardcode tokens in source code
HARDCODED_BOTS = {
    1: {
        "name": "Bot-1",
        "bot_token": os.getenv("SLACK_BOT_TOKEN_1", "xoxb-REDACTED"),
        "app_token": os.getenv("SLACK_APP_TOKEN_1", "xapp-REDACTED")
    },
    2: {
        "name": "Bot-2", 
        "bot_token": os.getenv("SLACK_BOT_TOKEN_2", "xoxb-REDACTED"),
        "app_token": os.getenv("SLACK_APP_TOKEN_2", "xapp-REDACTED")
    },
    3: {
        "name": "Bot-3",
        "bot_token": os.getenv("SLACK_BOT_TOKEN_3", "xoxb-REDACTED"), 
        "app_token": os.getenv("SLACK_APP_TOKEN_3", "xapp-REDACTED")
    },
}

# Use Bot 1 as the base bot for invitations
BASE_BOT_TOKEN = HARDCODED_BOTS[1]["bot_token"]

class HardcodedBotInviter:
    """Simple bot inviter with hardcoded credentials"""
    
    def __init__(self):
        self.slack_base_url = "https://slack.com/api"
        self.headers = {
            "Authorization": f"Bearer {BASE_BOT_TOKEN}",
            "Content-Type": "application/json"
        }
        self.invitation_delay = 1.0  # 1 second between invitations
        
        logger.info(f"Hardcoded Bot Inviter initialized ({len(HARDCODED_BOTS)} bots)")
    
    def get_bot_user_id(self, bot_token: str) -> str:
        """Get the user ID for a bot token"""
        try:
            headers = {
                "Authorization": f"Bearer {bot_token}",
                "Content-Type": "application/json"
            }
            
            response = requests.get(
                f"{self.slack_base_url}/auth.test",
                headers=headers
            )
            response.raise_for_status()
            data = response.json()
            
            if data["ok"]:
                return data["user_id"]
            else:
                logger.error(f"❌ Error getting bot user ID: {data.get('error')}")
                return None
                
        except Exception as e:
            logger.error(f"❌ Exception getting bot user ID: {e}")
            return None
    
    def discover_admin_channels(self):
        """Discover all admin channels"""
        
        all_channels = []
        cursor = None
        
        try:
            while True:
                params = {
                    "types": "public_channel,private_channel",
                    "limit": 1000
                }
                
                if cursor:
                    params["cursor"] = cursor
                
                response = requests.get(
                    f"{self.slack_base_url}/conversations.list",
                    headers=self.headers,
                    params=params
                )
                response.raise_for_status()
                data = response.json()
                
                if not data["ok"]:
                    logger.error(f"❌ Slack API error: {data.get('error')}")
                    break
                
                channels = data["channels"]
                all_channels.extend(channels)
                
                cursor = data.get("response_metadata", {}).get("next_cursor")
                if not cursor:
                    break
            
            # Filter for admin channels
            admin_channels = []
            for channel in all_channels:
                channel_name = channel.get("name", "")
                if (channel_name.endswith("-admin") or channel_name.endswith("-admins")) and not channel.get("is_archived", False):
                    admin_channels.append({
                        "id": channel["id"],
                        "name": channel_name
                    })
            
            logger.info(f"Found {len(admin_channels)} admin channels")
            return admin_channels
            
        except Exception as e:
            logger.error(f"❌ Error discovering channels: {e}")
            return []
    
    def assign_channels_to_bots(self, admin_channels):
        """Assign channels to bots using consistent hashing"""
        
        assignments = {}
        bot_channels = {bot_id: [] for bot_id in HARDCODED_BOTS.keys()}
        
        for channel in admin_channels:
            channel_id = channel["id"]
            
            # Use hash of channel_id to determine bot assignment
            hash_value = int(hashlib.md5(channel_id.encode()).hexdigest(), 16)
            assigned_bot_id = (hash_value % len(HARDCODED_BOTS)) + 1
            
            assignments[channel_id] = assigned_bot_id
            bot_channels[assigned_bot_id].append(channel)
        
        # Log distribution
        for bot_id, channels in bot_channels.items():
        
        return assignments, bot_channels
    
    def invite_bot_to_channel(self, channel_id: str, user_id: str, bot_name: str, channel_name: str) -> bool:
        """Invite a bot to a specific channel"""
        try:
            response = requests.post(
                f"{self.slack_base_url}/conversations.invite",
                headers=self.headers,
                json={
                    "channel": channel_id,
                    "users": user_id
                }
            )
            response.raise_for_status()
            data = response.json()
            
            if data["ok"]:
                return True
            else:
                error = data.get('error', 'unknown')
                if error == 'already_in_channel':
                    return True
                elif error == 'ratelimited':
                    logger.warning(f"Rate limited inviting {bot_name} to {channel_name}")
                    time.sleep(5)
                    return False
                else:
                    logger.error(f"   ❌ Error inviting {bot_name} to {channel_name}: {error}")
                    return False
                    
        except Exception as e:
            logger.error(f"   ❌ Exception inviting {bot_name} to {channel_name}: {e}")
            return False
    
    def run_invitation_process(self):
        """Run the complete invitation process"""
        logger.info("Starting hardcoded bot invitations...")
        
        try:
            # Step 1: Discover admin channels
            admin_channels = self.discover_admin_channels()
            if not admin_channels:
                logger.error("❌ No admin channels found")
                return False
            
            # Step 2: Assign channels to bots
            assignments, bot_channels = self.assign_channels_to_bots(admin_channels)
            
            # Step 3: Get bot user IDs
            bot_user_ids = {}
            for bot_id, bot_config in HARDCODED_BOTS.items():
                if bot_id == 1:
                    continue  # Skip base bot
                
                user_id = self.get_bot_user_id(bot_config["bot_token"])
                if user_id:
                    bot_user_ids[bot_id] = user_id
                else:
                    logger.error(f"   ❌ Failed to get user ID for {bot_config['name']}")
            
            if not bot_user_ids:
                logger.error("❌ No bot user IDs found")
                return False
            
            # Step 4: Invite bots to their assigned channels
            results = {}
            
            for bot_id, user_id in bot_user_ids.items():
                bot_name = HARDCODED_BOTS[bot_id]["name"]
                assigned_channels = bot_channels.get(bot_id, [])
                
                if not assigned_channels:
                    continue
                
                
                successful = 0
                failed = 0
                
                for i, channel in enumerate(assigned_channels, 1):
                    
                    success = self.invite_bot_to_channel(
                        channel["id"], 
                        user_id, 
                        bot_name, 
                        channel["name"]
                    )
                    
                    if success:
                        successful += 1
                    else:
                        failed += 1
                    
                    time.sleep(self.invitation_delay)
                
                results[bot_id] = {
                    "bot_name": bot_name,
                    "total_channels": len(assigned_channels),
                    "successful": successful,
                    "failed": failed
                }
                
                if successful > 0 or failed > 0:
                    logger.info(f"{bot_name}: {successful} invited, {failed} failed")
            
            # Step 5: Save assignments and results
            self.save_results(assignments, results)
            
            # Summary
            
            total_successful = sum(r["successful"] for r in results.values())
            total_failed = sum(r["failed"] for r in results.values())
            total_channels = sum(r["total_channels"] for r in results.values())
            
            if total_successful > 0:
                logger.info(f"Summary: {total_successful}/{total_channels} successful ({(total_successful/total_channels*100):.1f}% success rate)")
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Error in invitation process: {e}")
            return False
    
    def save_results(self, assignments, results):
        """Save channel assignments and invitation results"""
        try:
            # Save channel assignments
            assignment_data = {
                "metadata": {
                    "total_bots": len(HARDCODED_BOTS),
                    "total_channels": len(assignments),
                    "bot_ids": list(HARDCODED_BOTS.keys())
                },
                "assignments": assignments
            }
            
            with open("channel_assignment.json", "w") as f:
                json.dump(assignment_data, f, indent=2)
            
            # Save invitation results
            results_data = {
                "metadata": {
                    "timestamp": "2024-01-01T00:00:00Z",
                    "total_bots_processed": len(results)
                },
                "results": results
            }
            
            with open("bot_invitation_results.json", "w") as f:
                json.dump(results_data, f, indent=2)
            
            
        except Exception as e:
            logger.error(f"❌ Error saving results: {e}")

def main():
    """Main execution"""
    print("🤖 Hardcoded Bot Channel Inviter")
    print("=" * 40)
    print("⚠️  IMPORTANT: Update HARDCODED_BOTS with your actual bot tokens!")
    print("=" * 40)
    
    # Check if tokens look like placeholders
    if "your-bot-1-token-here" in HARDCODED_BOTS[1]["bot_token"]:
        print("❌ ERROR: Please update HARDCODED_BOTS with your actual bot tokens")
        print("   Edit the HARDCODED_BOTS section at the top of this file")
        return
    
    try:
        inviter = HardcodedBotInviter()
        success = inviter.run_invitation_process()
        
        if success:
            print("\n✅ Bot invitation process completed successfully!")
            print("🚀 Your bots should now have access to their assigned channels.")
        else:
            print("\n❌ Bot invitation process failed. Check the logs above.")
            
    except Exception as e:
        logger.error(f"❌ Fatal error: {e}")

if __name__ == "__main__":
    main()
