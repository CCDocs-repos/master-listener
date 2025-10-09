# 🤖 Master Listener - Slack Bot Multi-Instance Manager

A sophisticated Slack bot system that forwards messages from client channels to master channels with intelligent routing and multi-bot load balancing.

## ✨ Features

- **🔄 Multi-Bot Architecture**: Distributes workload across multiple bot instances to handle rate limits
- **🎯 Intelligent Channel Discovery**: Automatically discovers and categorizes Slack channels
- **📋 ClickUp Integration**: Fetches client lists and maps them to Slack channels
- **⚡ Real-Time Message Forwarding**: Forwards messages with thread support and file attachments
- **🐳 Docker Support**: Containerized deployment with docker-compose
- **📊 Load Balancing**: Consistent hashing for even channel distribution
- **🔍 Smart Channel Mapping**: Maps ClickUp clients to Slack channels using intelligent matching

## 🏗️ Architecture

```
master-listener/
├── src/
│   ├── core/           # Core bot functionality
│   │   ├── listener.py           # Legacy inline-forward listener
│   │   ├── listener_redis.py     # Redis-backed listener (enqueue-only)
│   │   ├── forwarder_worker.py   # Worker that posts to Slack from Redis queue
│   │   └── multi_bot_launcher.py # Multi-bot orchestrator (spawns worker + bots)
│   ├── config/         # Configuration and discovery
│   │   ├── multi_bot_config.py   # Bot configuration manager
│   │   ├── channel_discovery.py  # Channel discovery system
│   │   └── channel_mapper.py     # ClickUp-Slack mapping
│   └── utils/          # Utility modules
│       ├── clickup_client_fetcher.py  # ClickUp API client
│       └── slack_channel_fetcher.py   # Slack API utilities
├── scripts/            # Deployment and utility scripts
├── data/              # JSON configuration files
├── docs/              # Documentation
├── tests/             # Test files
├── logs/              # Log files (created at runtime)
├── main.py            # Main entry point
├── requirements.txt   # Python dependencies
├── Dockerfile         # Container configuration
└── docker-compose.yml # Multi-container setup
```

## 🚀 Quick Start

### Prerequisites

- Python 3.9+
- Slack workspace with admin access
- ClickUp workspace access
- Multiple Slack bot tokens (for load balancing)

### Installation

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd master-listener
   ```

2. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

3. **Configure environment variables**
   ```bash
   cp .env.example .env
   # Edit .env with your tokens
   ```

4. **Run the system**
   ```bash
   python main.py
   ```

### Docker Deployment

```bash
# Build and run with docker-compose
docker-compose up -d

# View logs
docker-compose logs -f
```

## ⚙️ Configuration

### Environment Variables

#### Required Slack Tokens
```env
# Primary bot (Bot 1)
SLACK_BOT_TOKEN=xoxb-your-bot-token
SLACK_APP_TOKEN=xapp-your-app-token

# Additional bots for load balancing
SLACK_BOT_TOKEN_2=xoxb-your-second-bot-token
SLACK_APP_TOKEN_2=xapp-your-second-app-token
SLACK_BOT_TOKEN_3=xoxb-your-third-bot-token
SLACK_APP_TOKEN_3=xapp-your-third-app-token
```

#### Master Channel IDs
```env
AGENT_MASTER_CHANNEL_ID=C1234567890
APPTBK_MASTER_CHANNEL_ID=C0987654321
MANAGED_ADMIN_MASTER_CHANNEL_ID=C1111111111
STORM_ADMIN_MASTER_CHANNEL_ID=C2222222222
```

#### ClickUp Integration
```env
CLICKUP_API_TOKEN=pk_your_clickup_token
```

### Channel Types

The bot handles four types of channels:

1. **Agent Channels** (`*-agent`, `*-agents`) → Forward to Agent Master
2. **Admin Channels** (`*-admin`, `*-admins`) → Forward to appropriate master based on client type
3. **Appointment Booking** (`*-apptbk`) → Forward to Appointment Master
4. **Ignored Channels** → Specified in configuration, not processed

## 🔧 Usage

### Starting the Multi-Bot System (Redis-backed)

```bash
# Start forwarder worker + all configured bots
python main.py
```

The system will:
1. Launch a Redis-backed forwarder worker (consumes `forwarding:jobs`).
2. Start one process per bot running `listener_redis.py` (FCFS idempotency + enqueue only).
3. Discover and assign channels (Bot-1 responsibility), reload categorizations for all bots.
4. Monitor worker and bots and restart if needed.

### Manual Channel Discovery

```bash
# Run channel discovery manually
python -m src.config.channel_discovery
```

### Update Client Mappings

```bash
# Refresh ClickUp client mappings
python -m src.config.channel_mapper
```

## 📊 Monitoring

### Bot Status

The system provides real-time status updates:

```
🤖 Multi-bot configuration:
   • Total bots: 3
   • This bot ID: 1
   • Bot name: Bot-1
   • Assigned channels: 45

💓 Heartbeat: 3/3 bots running
   • Bot-1: 🟢 Running
   • Bot-2: 🟢 Running
   • Bot-3: 🟢 Running
```

### Channel Assignment Stats

```
📊 Channel Assignment Statistics:
   • Total bots: 3
   • Total channels: 135
   • Current bot: 1 (45 channels)
   • Bot-1: 45 channels
   • Bot-2: 45 channels
   • Bot-3: 45 channels
```

## 🛠️ Development

### Project Structure

- **`src/core/`**: Main bot logic and multi-bot orchestration
- **`src/config/`**: Configuration management and channel discovery
- **`src/utils/`**: External API integrations (ClickUp, Slack)
- **`scripts/`**: Deployment and utility scripts
- **`data/`**: Runtime data files (JSON configurations)

### Adding New Bots

1. Add new environment variables:
   ```env
   SLACK_BOT_TOKEN_4=xoxb-new-bot-token
   SLACK_APP_TOKEN_4=xapp-new-app-token
   ```

2. Restart the system - new bots are automatically detected

### Custom Channel Types

To add support for new channel types:

1. Update the channel filtering logic in `src/core/listener.py`
2. Add new forwarding function following the existing pattern
3. Update the routing logic in `forward_message()`

## 🐳 Docker

### Building

```bash
# Build the image
docker build -t master-listener .

# Run with docker-compose
docker-compose up -d
```

### Environment (Redis-backed)

The Docker setup includes:
- Multi-stage build for optimization
- Non-root user for security
- Volume mounts for logs and data
- Automatic restart policies
- Redis Cloud connectivity via `redis-client.py`

## 📝 Logging & Flow

Logs are structured and include:
- Timestamp and log level
- Thread/bot identification
- Message processing details
- Error handling and recovery

Event flow (Redis-backed):
- Listener receives Slack event → FCFS claim via Redis (`client_msg_id` or `event_id`) → enqueue job to `forwarding:jobs`.
- Worker consumes jobs → rate limits and retries → posts to master channel → stores `source ts → master ts` mapping for edits.

Example log output:
```
2024-01-01 12:00:00 - listener - [Bot-1] - INFO - 🤖 Multi-bot configuration:
2024-01-01 12:00:01 - listener - [Bot-1] - INFO - PROCESSING message - Channel: client-admin (C123456789)
2024-01-01 12:00:02 - listener - [Bot-1] - INFO - ✅ SUCCESSFULLY FORWARDED managed admin message
```

## 🔒 Security & Reliability

- Bot tokens are stored as environment variables
- Non-root Docker user
- Rate limit handling in worker prevents API abuse (429 Retry-After honored)
- Channel access validation
- Secure file handling for attachments
 - FCFS idempotency via Redis prevents duplicate processing across bots

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests if applicable
5. Submit a pull request

## 📄 License

This project is licensed under the MIT License - see the LICENSE file for details.

## 🆘 Support

For issues and questions:
1. Check the logs for error messages
2. Verify environment variables are set correctly
3. Ensure bot tokens have proper permissions
4. Check Slack workspace settings

## 🔄 Changelog

### v3.0.0 (Current)
- Redis-backed architecture: `listener_redis` + `forwarder_worker`
- FCFS idempotency using `client_msg_id` → fallback `event_id` (never `ts`)
- Multi-bot launcher spawns worker first, then bots
- Basic retry/backoff and thread parent posting in worker

### v2.0.0
- Multi-bot architecture implementation
- Intelligent channel discovery
- ClickUp integration
- Docker containerization
- Improved error handling and logging

### v1.0.0
- Basic message forwarding
- Single bot operation
- Manual channel configuration
