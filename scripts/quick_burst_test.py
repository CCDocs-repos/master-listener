#!/usr/bin/env python3
"""
Quick Burst Test
================
Simple script to quickly send numbered test messages.
Defaults: 25 messages per bot, 3 messages per second.
"""

import os
import sys
import time
import random
import requests
from datetime import datetime
from dotenv import load_dotenv

# Add parent directory to path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

from src.config.multi_bot_config import MultiBotConfigManager

# Load environment variables
load_dotenv()

def run_burst_test():
    """Run a quick burst test with default settings"""
    
    # Configuration
    MESSAGES_PER_BOT = 25
    MESSAGES_PER_SECOND = 3
    DELAY = 1.0 / MESSAGES_PER_SECOND  # ~0.33 seconds
    
    print("\n" + "🚀 " * 20)
    print("QUICK BURST TEST - SENDING NUMBERED TEST MESSAGES")
    print("🚀 " * 20)
    print(f"\nSettings: {MESSAGES_PER_BOT} msgs/bot @ {MESSAGES_PER_SECOND} msgs/sec")
    
    # Initialize
    manager = MultiBotConfigManager()
    slack_url = "https://slack.com/api/chat.postMessage"
    
    # Counters
    global_counter = 0
    total_sent = 0
    total_failed = 0
    start = datetime.now()
    
    # Process each bot
    for bot_id, bot_config in manager.bot_configs.items():
        print(f"\n{'='*60}")
        print(f"Bot-{bot_id}: {bot_config.name}")
        print(f"{'='*60}")
        
        # Get bot's channels
        channels = manager.channel_assignments.get(bot_id, [])
        if not channels:
            print("  ⚠️ No channels assigned")
            continue
        
        # Random selection
        selected = random.sample(channels, min(MESSAGES_PER_BOT, len(channels)))
        print(f"  📋 Selected {len(selected)} random channels")
        
        # Send messages
        headers = {
            "Authorization": f"Bearer {bot_config.bot_token}",
            "Content-Type": "application/json"
        }
        
        for i, channel_id in enumerate(selected, 1):
            global_counter += 1
            
            # Create message
            msg = f"🧪 Listener test msg - channel {global_counter}"
            
            # Send
            try:
                response = requests.post(
                    slack_url,
                    headers=headers,
                    json={"channel": channel_id, "text": msg}
                )
                
                if response.json().get("ok"):
                    total_sent += 1
                    print(f"  ✅ [{i:2d}] Sent msg #{global_counter} to {channel_id}")
                else:
                    total_failed += 1
                    error = response.json().get("error", "unknown")
                    print(f"  ❌ [{i:2d}] Failed msg #{global_counter} to {channel_id}: {error}")
                    
            except Exception as e:
                total_failed += 1
                print(f"  ❌ [{i:2d}] Error msg #{global_counter}: {str(e)[:50]}")
            
            # Rate limit (skip on last message)
            if i < len(selected):
                time.sleep(DELAY)
    
    # Summary
    duration = (datetime.now() - start).total_seconds()
    
    print(f"\n{'='*60}")
    print("📊 TEST COMPLETE")
    print(f"{'='*60}")
    print(f"✅ Sent: {total_sent} messages")
    print(f"❌ Failed: {total_failed} messages")
    print(f"⏱️ Duration: {duration:.1f} seconds")
    print(f"📈 Actual rate: {total_sent/duration:.2f} msgs/sec")
    print(f"{'='*60}\n")

if __name__ == "__main__":
    # Simple confirmation
    print("\n⚠️  WARNING: This will send test messages to real Slack channels!")
    confirm = input("Type 'yes' to continue: ")
    
    if confirm.lower() == 'yes':
        run_burst_test()
    else:
        print("❌ Test cancelled")
