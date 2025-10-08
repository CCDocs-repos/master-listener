# Setup Guide

## Prerequisites

### Slack Workspace Setup

1. **Create Slack Apps**
   - Go to https://api.slack.com/apps
   - Create multiple apps (recommended: 3-5 for load balancing)
   - For each app:
     - Enable Socket Mode
     - Add Bot Token Scopes:
       - `channels:read`
       - `groups:read`
       - `chat:write`
       - `files:read`
       - `users:read`
     - Install app to workspace

2. **Create Master Channels**
   - Create dedicated channels for message aggregation:
     - `#master-agents` (for agent messages)
     - `#master-apptbk` (for appointment booking)
     - `#master-managed-admin` (for managed client admin messages)
     - `#master-storm-admin` (for storm client admin messages)

3. **Invite Bots to Channels**
   - The system will automatically invite bots to relevant channels
   - Ensure bots have access to master channels

### ClickUp Setup

1. **Get API Token**
   - Go to ClickUp Settings → Apps
   - Generate API token
   - Ensure access to Technology space and Data Department list

2. **Verify Structure**
   - Technology Space
     - Data Department List
       - "Managed Clients - Fractionals" task
       - "Managed Clients - Full Clients" task
       - "Storm Master Client List - Internal CC Docs" task

## Installation Steps

### 1. Environment Setup

```bash
# Clone repository
git clone <repo-url>
cd master-listener

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Configuration

Create `.env` file with your tokens:

```env
# Primary Bot
SLACK_BOT_TOKEN=xoxb-your-token
SLACK_APP_TOKEN=xapp-your-token

# Additional Bots
SLACK_BOT_TOKEN_2=xoxb-second-token
SLACK_APP_TOKEN_2=xapp-second-token

# Master Channels
AGENT_MASTER_CHANNEL_ID=C1234567890
APPTBK_MASTER_CHANNEL_ID=C0987654321
MANAGED_ADMIN_MASTER_CHANNEL_ID=C1111111111
STORM_ADMIN_MASTER_CHANNEL_ID=C2222222222

# ClickUp
CLICKUP_API_TOKEN=pk_your_token
```

### 3. Initial Setup

```bash
# Test configuration
python -m src.config.multi_bot_config

# Run channel discovery
python -m src.config.channel_discovery

# Update client mappings
python -m src.config.channel_mapper
```

### 4. Start the System

```bash
# Start all bots
python main.py
```

## Docker Deployment

### 1. Build Image

```bash
docker build -t master-listener .
```

### 2. Run with Docker Compose

```bash
# Create .env file first
docker-compose up -d
```

### 3. Monitor Logs

```bash
docker-compose logs -f
```

## Troubleshooting

### Common Issues

1. **Bot Not Responding**
   - Check bot tokens are valid
   - Verify Socket Mode is enabled
   - Ensure bot is invited to channels

2. **Channel Discovery Fails**
   - Verify bot has `channels:read` and `groups:read` scopes
   - Check if bot can access private channels

3. **ClickUp Integration Issues**
   - Verify API token has correct permissions
   - Check workspace structure matches expected format

4. **Import Errors**
   - Ensure you're running from the project root
   - Check Python path includes src directory

### Debug Mode

Enable debug logging:

```bash
export LOG_LEVEL=DEBUG
python main.py
```

### Health Checks

The system provides built-in health monitoring:
- Bot status every 60 seconds
- Automatic restart of failed bots
- Channel assignment validation

## Performance Tuning

### Bot Count

- Start with 3 bots for most workloads
- Add more bots if hitting rate limits
- Monitor bot distribution in logs

### Channel Assignment

- System uses consistent hashing for even distribution
- Assignments persist across restarts
- Manual reassignment available if needed

## Security Considerations

- Store tokens in environment variables only
- Use non-root user in Docker
- Regularly rotate API tokens
- Monitor bot access logs in Slack
