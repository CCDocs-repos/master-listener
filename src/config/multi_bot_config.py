#!/usr/bin/env python3
"""
Multi-Bot Configuration Manager
===============================

Manages multiple Slack bot configurations and channel assignments.
Supports loading multiple bot tokens from environment variables and
distributing channels evenly across bots.
"""

import os
import json
import hashlib
import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

logger = logging.getLogger(__name__)

@dataclass
class BotConfig:
    """Configuration for a single bot"""
    bot_id: int
    bot_token: str
    app_token: str
    name: str

class MultiBotConfigManager:
    """Manages multiple bot configurations and channel assignments"""
    
    def __init__(self):
        self.bot_configs: Dict[int, BotConfig] = {}
        self.current_bot_id: Optional[int] = None
        self.channel_assignments: Dict[str, int] = {}
        
        # Get absolute path to project root (src/config -> ../..)
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
        self.assignment_file = os.path.join(project_root, "data", "channel_assignment.json")
        
        self._load_bot_configs()
        self._load_channel_assignments()
    
    def _load_bot_configs(self):
        """Load all bot configurations from environment variables"""
        # Get current bot ID from environment
        self.current_bot_id = int(os.environ.get("BOT_ID", "1"))
        
        # Load bot configurations
        bot_id = 1
        while True:
            # Try to load bot token and app token for this bot ID
            if bot_id == 1:
                # Bot 1 uses the original environment variable names
                bot_token = os.environ.get("SLACK_BOT_TOKEN")
                app_token = os.environ.get("SLACK_APP_TOKEN")
            else:
                # Bot 2+ use numbered environment variables
                bot_token = os.environ.get(f"SLACK_BOT_TOKEN_{bot_id}")
                app_token = os.environ.get(f"SLACK_APP_TOKEN_{bot_id}")
            
            # If we can't find tokens for this bot ID, we're done
            if not bot_token or not app_token:
                break
            
            # Create bot configuration
            bot_config = BotConfig(
                bot_id=bot_id,
                bot_token=bot_token,
                app_token=app_token,
                name=f"Bot-{bot_id}"
            )
            
            self.bot_configs[bot_id] = bot_config
            bot_id += 1
        
        if not self.bot_configs:
            raise ValueError("No bot configurations found! Please set SLACK_BOT_TOKEN and SLACK_APP_TOKEN")
        
        logger.info(f"Bot-{self.current_bot_id} initialized ({len(self.bot_configs)} bots total)")
        
        # Validate current bot ID
        if self.current_bot_id not in self.bot_configs:
            raise ValueError(f"BOT_ID {self.current_bot_id} not found in configured bots: {list(self.bot_configs.keys())}")
    
    def _load_channel_assignments(self):
        """Load channel assignments from file"""
        try:
            with open(self.assignment_file, 'r') as f:
                data = json.load(f)
                self.channel_assignments = data.get('assignments', {})
        except FileNotFoundError:
            self.channel_assignments = {}
        except Exception as e:
            logger.error(f"❌ Error loading channel assignments: {e}")
            self.channel_assignments = {}
    
    def save_channel_assignments(self):
        """Save channel assignments to file"""
        try:
            data = {
                "metadata": {
                    "total_bots": len(self.bot_configs),
                    "total_channels": len(self.channel_assignments),
                    "bot_ids": list(self.bot_configs.keys())
                },
                "assignments": self.channel_assignments
            }
            
            with open(self.assignment_file, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving channel assignments: {e}")
    
    def assign_channels_to_bots(self, channel_ids: List[str]) -> Dict[int, List[str]]:
        """
        Assign channels to bots using consistent hashing.
        Only assigns NEW channels - existing assignments are preserved.
        
        Args:
            channel_ids: List of channel IDs to assign
            
        Returns:
            Dictionary mapping bot_id -> list of assigned channel_ids (includes both new and existing)
        """
        # Separate new channels from already-assigned channels
        new_channels = [ch_id for ch_id in channel_ids if ch_id not in self.channel_assignments]
        existing_channels = [ch_id for ch_id in channel_ids if ch_id in self.channel_assignments]
        
        if new_channels:
            logger.info(f"Assigning {len(new_channels)} new channels ({len(existing_channels)} existing)")
        
        # Initialize bot assignments with empty lists
        bot_assignments = {bot_id: [] for bot_id in self.bot_configs.keys()}
        
        # Only assign NEW channels using consistent hashing
        if new_channels:
            for channel_id in new_channels:
                # Use hash of channel_id to determine bot assignment
                hash_value = int(hashlib.md5(channel_id.encode()).hexdigest(), 16)
                assigned_bot_id = (hash_value % len(self.bot_configs)) + 1
                
                # Store assignment
                self.channel_assignments[channel_id] = assigned_bot_id
                bot_assignments[assigned_bot_id].append(channel_id)
        
        # Add existing assignments to the result
        for channel_id in existing_channels:
            assigned_bot_id = self.channel_assignments[channel_id]
            bot_assignments[assigned_bot_id].append(channel_id)
        
        # Save assignments
        self.save_channel_assignments()
        
        return bot_assignments
    
    def is_channel_assigned_to_current_bot(self, channel_id: str) -> bool:
        """Check if a channel is assigned to the current bot"""
        assigned_bot_id = self.channel_assignments.get(channel_id)
        return assigned_bot_id == self.current_bot_id
    
    def get_current_bot_config(self) -> BotConfig:
        """Get configuration for the current bot"""
        if self.current_bot_id not in self.bot_configs:
            raise ValueError(f"Current bot ID {self.current_bot_id} not found in configurations")
        return self.bot_configs[self.current_bot_id]
    
    def get_current_bot_channels(self) -> List[str]:
        """Get list of channels assigned to the current bot"""
        return [
            channel_id for channel_id, bot_id in self.channel_assignments.items()
            if bot_id == self.current_bot_id
        ]
    
    def get_assignment_stats(self) -> Dict:
        """Get statistics about channel assignments"""
        stats = {
            "total_bots": len(self.bot_configs),
            "total_channels": len(self.channel_assignments),
            "current_bot_id": self.current_bot_id,
            "current_bot_channels": len(self.get_current_bot_channels()),
            "bot_distribution": {}
        }
        
        # Calculate distribution per bot
        for bot_id in self.bot_configs.keys():
            bot_channels = [
                channel_id for channel_id, assigned_bot_id in self.channel_assignments.items()
                if assigned_bot_id == bot_id
            ]
            stats["bot_distribution"][f"bot_{bot_id}"] = len(bot_channels)
        
        return stats
    
    def log_assignment_stats(self):
        """Log current assignment statistics"""
        stats = self.get_assignment_stats()
        logger.info(f"Bot-{stats['current_bot_id']}: {stats['current_bot_channels']}/{stats['total_channels']} channels")

def main():
    """Test the multi-bot configuration manager"""
    logging.basicConfig(level=logging.INFO)
    
    try:
        manager = MultiBotConfigManager()
        manager.log_assignment_stats()
        
        # Test channel assignment
        test_channels = [f"test-channel-{i}" for i in range(10)]
        assignments = manager.assign_channels_to_bots(test_channels)
        
        print("\nTest channel assignments:")
        for bot_id, channels in assignments.items():
            print(f"Bot-{bot_id}: {channels}")
        
    except Exception as e:
        logger.error(f"❌ Error: {e}")

if __name__ == "__main__":
    main()
