#!/usr/bin/env python3
"""
Channel Discovery and Assignment System
=======================================

Discovers all Slack channels and assigns them to bots for distributed processing.
Integrates with the existing channel mapping system.
"""

import os
import json
import logging
import requests
from typing import List, Dict, Any
from dotenv import load_dotenv
from .multi_bot_config import MultiBotConfigManager

# Load environment variables
load_dotenv()

logger = logging.getLogger(__name__)

class ChannelDiscoveryManager:
    """Manages channel discovery and bot assignment"""
    
    def __init__(self, multi_bot_manager: MultiBotConfigManager):
        self.multi_bot_manager = multi_bot_manager
        self.slack_base_url = "https://slack.com/api"
        
        # Use the first bot's token for discovery (any bot can discover channels)
        first_bot = list(multi_bot_manager.bot_configs.values())[0]
        self.headers = {
            "Authorization": f"Bearer {first_bot.bot_token}",
            "Content-Type": "application/json"
        }
    
    def discover_all_channels(self) -> List[Dict[str, Any]]:
        """
        Discover all channels using pagination
        
        Returns:
            List of channel dictionaries with metadata
        """
        logger.info("🔍 Discovering all Slack channels...")
        
        all_channels = []
        cursor = None
        
        try:
            while True:
                # Prepare request parameters
                params = {
                    "types": "public_channel,private_channel",
                    "limit": 1000
                }
                
                if cursor:
                    params["cursor"] = cursor
                
                # Make API request
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
                
                # Add channels to our list
                channels = data["channels"]
                all_channels.extend(channels)
                logger.info(f"   📋 Discovered {len(channels)} channels (total: {len(all_channels)})")
                
                # Check for more pages
                cursor = data.get("response_metadata", {}).get("next_cursor")
                if not cursor:
                    break
            
            logger.info(f"✅ Channel discovery complete: {len(all_channels)} total channels")
            return all_channels
            
        except Exception as e:
            logger.error(f"❌ Error discovering channels: {e}")
            return []
    
    def filter_admin_channels(self, channels: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Filter channels to only admin channels (ending with -admin or -admins)
        
        Args:
            channels: List of all channels
            
        Returns:
            List of admin channels only
        """
        logger.info("🎯 Filtering for admin channels...")
        
        admin_channels = []
        
        for channel in channels:
            channel_name = channel.get("name", "")
            
            # Check if channel name ends with -admin or -admins
            if channel_name.endswith("-admin") or channel_name.endswith("-admins"):
                admin_channels.append({
                    "id": channel["id"],
                    "name": channel_name,
                    "is_private": channel.get("is_private", False),
                    "num_members": channel.get("num_members", 0),
                    "is_archived": channel.get("is_archived", False)
                })
        
        # Filter out archived channels
        active_admin_channels = [ch for ch in admin_channels if not ch["is_archived"]]
        
        logger.info(f"✅ Found {len(active_admin_channels)} active admin channels")
        logger.info(f"   (Filtered out {len(admin_channels) - len(active_admin_channels)} archived channels)")
        
        return active_admin_channels
    
    def assign_channels_to_bots(self, admin_channels: List[Dict[str, Any]]) -> Dict[int, List[str]]:
        """
        Assign admin channels to bots
        
        Args:
            admin_channels: List of admin channel dictionaries
            
        Returns:
            Dictionary mapping bot_id -> list of channel_ids
        """
        logger.info("🎯 Assigning admin channels to bots...")
        
        # Extract channel IDs
        channel_ids = [channel["id"] for channel in admin_channels]
        
        # Use multi-bot manager to assign channels
        assignments = self.multi_bot_manager.assign_channels_to_bots(channel_ids)
        
        # Save detailed channel info for reference
        self._save_channel_details(admin_channels)
        
        return assignments
    
    def _save_channel_details(self, admin_channels: List[Dict[str, Any]]):
        """Save detailed channel information for reference"""
        try:
            channel_details = {
                "metadata": {
                    "total_channels": len(admin_channels),
                    "discovery_timestamp": "2024-01-01T00:00:00Z"  # You might want to add actual timestamp
                },
                "channels": admin_channels
            }
            
            with open("data/discovered_channels.json", "w") as f:
                json.dump(channel_details, f, indent=2)
            
            logger.info(f"💾 Saved details for {len(admin_channels)} channels to discovered_channels.json")
            
        except Exception as e:
            logger.error(f"❌ Error saving channel details: {e}")
    
    def run_full_discovery(self) -> Dict[int, List[str]]:
        """
        Run complete channel discovery and assignment process
        
        Returns:
            Dictionary mapping bot_id -> list of assigned channel_ids
        """
        logger.info("🚀 Starting full channel discovery and assignment...")
        logger.info("=" * 60)
        
        try:
            # Step 1: Discover all channels
            all_channels = self.discover_all_channels()
            if not all_channels:
                logger.error("❌ No channels discovered")
                return {}
            
            # Step 2: Filter for admin channels
            admin_channels = self.filter_admin_channels(all_channels)
            if not admin_channels:
                logger.error("❌ No admin channels found")
                return {}
            
            # Step 3: Assign channels to bots
            assignments = self.assign_channels_to_bots(admin_channels)
            
            # Step 4: Log results
            logger.info("=" * 60)
            logger.info("🎉 Channel discovery and assignment complete!")
            self.multi_bot_manager.log_assignment_stats()
            
            return assignments
            
        except Exception as e:
            logger.error(f"❌ Error in channel discovery: {e}")
            return {}

def main():
    """Test the channel discovery system"""
    logging.basicConfig(level=logging.INFO)
    
    try:
        # Initialize multi-bot manager
        multi_bot_manager = MultiBotConfigManager()
        
        # Initialize discovery manager
        discovery_manager = ChannelDiscoveryManager(multi_bot_manager)
        
        # Run discovery
        assignments = discovery_manager.run_full_discovery()
        
        if assignments:
            print("\n📊 Final Assignment Summary:")
            for bot_id, channel_ids in assignments.items():
                print(f"Bot-{bot_id}: {len(channel_ids)} channels")
        
    except Exception as e:
        logger.error(f"❌ Error: {e}")

if __name__ == "__main__":
    main()
