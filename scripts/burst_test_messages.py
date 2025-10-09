#!/usr/bin/env python3
"""
Burst Test Messages Script
==========================
Posts numbered test messages to random channels for each bot.
- 25 messages per bot (1 per channel)
- Messages numbered sequentially
- Burst rate: 3 messages per second
"""

import os
import sys
import json
import time
import random
import requests
from typing import List, Dict
from datetime import datetime
from dotenv import load_dotenv

# Add parent directory to path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

from src.config.multi_bot_config import MultiBotConfigManager

# Load environment variables
load_dotenv()

class BurstMessageTester:
    def __init__(self):
        """Initialize with all bot tokens"""
        self.multi_bot_manager = MultiBotConfigManager()
        self.slack_base_url = "https://slack.com/api"
        
        # Get bot tokens
        self.bot_tokens = {}
        for bot_id, bot_config in self.multi_bot_manager.bot_configs.items():
            self.bot_tokens[bot_id] = bot_config.bot_token
            print(f"Loaded Bot-{bot_id}: {bot_config.name}")
        
        # Load channel assignments
        self.channel_assignments = self.multi_bot_manager.channel_assignments
        
    def get_channel_name(self, channel_id: str, bot_token: str) -> str:
        """Get channel name from ID"""
        try:
            headers = {
                "Authorization": f"Bearer {bot_token}",
                "Content-Type": "application/json"
            }
            
            response = requests.get(
                f"{self.slack_base_url}/conversations.info",
                headers=headers,
                params={"channel": channel_id}
            )
            data = response.json()
            
            if data.get("ok"):
                return data.get("channel", {}).get("name", "unknown")
            return "unknown"
        except:
            return "unknown"
    
    def post_message(self, channel_id: str, text: str, bot_token: str) -> bool:
        """Post a message to a channel"""
        try:
            headers = {
                "Authorization": f"Bearer {bot_token}",
                "Content-Type": "application/json"
            }
            
            payload = {
                "channel": channel_id,
                "text": text
            }
            
            response = requests.post(
                f"{self.slack_base_url}/chat.postMessage",
                headers=headers,
                json=payload
            )
            
            data = response.json()
            return data.get("ok", False)
            
        except Exception as e:
            print(f"Error posting message: {e}")
            return False
    
    def burst_test_messages(self, messages_per_bot: int = 25, messages_per_second: float = 3):
        """Send burst test messages across random channels"""
        print("\n" + "=" * 80)
        print("BURST TEST MESSAGE SENDER")
        print(f"Configuration: {messages_per_bot} messages per bot, {messages_per_second} msgs/sec")
        print("=" * 80)
        
        # Calculate delay between messages
        delay = 1.0 / messages_per_second
        
        # Track overall statistics
        total_sent = 0
        total_failed = 0
        start_time = datetime.now()
        
        # Process each bot
        for bot_id, bot_token in self.bot_tokens.items():
            print(f"\n[Bot-{bot_id}] Starting message burst...")
            
            # Get channels assigned to this bot
            assigned_channels = self.channel_assignments.get(bot_id, [])
            
            if not assigned_channels:
                print(f"[Bot-{bot_id}] No channels assigned, skipping...")
                continue
            
            # Randomly select channels (up to messages_per_bot)
            num_channels = min(messages_per_bot, len(assigned_channels))
            selected_channels = random.sample(assigned_channels, num_channels)
            
            print(f"[Bot-{bot_id}] Selected {num_channels} random channels from {len(assigned_channels)} assigned")
            
            # Send messages
            bot_sent = 0
            bot_failed = 0
            
            for i, channel_id in enumerate(selected_channels, 1):
                # Create numbered message
                message_text = f"🧪 Listener test msg - channel {i}"
                
                # Get channel name for logging
                channel_name = self.get_channel_name(channel_id, bot_token)
                
                # Send message
                success = self.post_message(channel_id, message_text, bot_token)
                
                if success:
                    bot_sent += 1
                    total_sent += 1
                    print(f"  [{i:2d}/{num_channels}] ✅ Sent to #{channel_name} ({channel_id})")
                else:
                    bot_failed += 1
                    total_failed += 1
                    print(f"  [{i:2d}/{num_channels}] ❌ Failed to send to #{channel_name} ({channel_id})")
                
                # Rate limiting - except for last message
                if i < num_channels:
                    time.sleep(delay)
            
            print(f"[Bot-{bot_id}] Complete: {bot_sent} sent, {bot_failed} failed")
        
        # Summary
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()
        
        print("\n" + "=" * 80)
        print("BURST TEST COMPLETE")
        print("=" * 80)
        print(f"Total messages sent: {total_sent}")
        print(f"Total messages failed: {total_failed}")
        print(f"Duration: {duration:.1f} seconds")
        print(f"Actual rate: {total_sent/duration:.1f} msgs/sec")
        print("=" * 80)
        
        return {
            "sent": total_sent,
            "failed": total_failed,
            "duration": duration
        }

def main():
    """Main execution"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Send burst test messages to Slack channels')
    parser.add_argument(
        '--messages-per-bot',
        type=int,
        default=25,
        help='Number of messages to send per bot (default: 25)'
    )
    parser.add_argument(
        '--rate',
        type=float,
        default=3.0,
        help='Messages per second (default: 3.0)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be sent without actually sending'
    )
    
    args = parser.parse_args()
    
    try:
        tester = BurstMessageTester()
        
        if args.dry_run:
            print("\n🔍 DRY RUN MODE - No messages will be sent")
            
            for bot_id, channels in tester.channel_assignments.items():
                print(f"\nBot-{bot_id}:")
                num_channels = min(args.messages_per_bot, len(channels))
                selected = random.sample(channels, num_channels)
                
                for i, channel_id in enumerate(selected[:5], 1):  # Show first 5 as sample
                    print(f"  Would send 'Listener test msg - channel {i}' to {channel_id}")
                if num_channels > 5:
                    print(f"  ... and {num_channels - 5} more channels")
        else:
            # Confirmation prompt
            total_messages = args.messages_per_bot * len(tester.bot_tokens)
            print(f"\n⚠️  This will send {total_messages} test messages across all bots!")
            response = input("Are you sure you want to continue? (y/n): ")
            
            if response.lower() != 'y':
                print("Aborted.")
                return
            
            # Run the burst test
            results = tester.burst_test_messages(
                messages_per_bot=args.messages_per_bot,
                messages_per_second=args.rate
            )
            
            # Save results
            results_file = f"data/burst_test_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            with open(results_file, 'w') as f:
                json.dump(results, f, indent=2)
            print(f"\nResults saved to: {results_file}")
    
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    return True

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
