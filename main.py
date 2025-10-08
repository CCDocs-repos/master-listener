#!/usr/bin/env python3
"""
Master Listener - Slack Bot Multi-Instance Manager
==================================================

A sophisticated Slack bot system that forwards messages from client channels
to master channels with intelligent routing and multi-bot load balancing.

Features:
- Multi-bot architecture for rate limit management
- Intelligent channel discovery and assignment
- ClickUp integration for client management
- Real-time message forwarding with thread support
- Docker containerization support

Usage:
    python main.py

Environment Variables Required:
    SLACK_BOT_TOKEN - Primary bot token
    SLACK_APP_TOKEN - Primary app token
    SLACK_BOT_TOKEN_2, SLACK_BOT_TOKEN_3, etc. - Additional bot tokens
    SLACK_APP_TOKEN_2, SLACK_APP_TOKEN_3, etc. - Additional app tokens
    CLICKUP_API_TOKEN - ClickUp API token for client management
    AGENT_MASTER_CHANNEL_ID - Master channel for agent messages
    APPTBK_MASTER_CHANNEL_ID - Master channel for appointment booking
    MANAGED_ADMIN_MASTER_CHANNEL_ID - Master channel for managed clients
    STORM_ADMIN_MASTER_CHANNEL_ID - Master channel for storm clients
"""

import sys
import os

# Add src directory to Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from core.multi_bot_launcher import main as launcher_main

if __name__ == "__main__":
    launcher_main()
