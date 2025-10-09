# Docker Deployment Guide

This guide explains how to deploy the Master Listener bot system using Docker.

## Prerequisites

- Docker and Docker Compose installed
- Slack Bot tokens and App tokens configured
- ClickUp API token (optional)

## Quick Start

### 1. Environment Configuration

Copy the example environment file and configure your tokens:

```bash
cp env.example .env
```

Edit `.env` and set your values:
- Slack bot tokens (SLACK_BOT_TOKEN, SLACK_BOT_TOKEN_2, etc.)
- Slack app tokens (SLACK_APP_TOKEN, SLACK_APP_TOKEN_2, etc.)
- Master channel IDs
- ClickUp API token
- Redis configuration (defaults work for Docker)

### 2. Build and Run

```bash
# Build and start all services
docker-compose up -d

# View logs
docker-compose logs -f slack-bot

# View Redis logs
docker-compose logs -f redis

# Stop all services
docker-compose down
```

## Architecture

The Docker setup includes:

### Services

1. **slack-bot** - Main multi-bot listener system
   - Runs multiple Slack bot instances
   - Forwards messages from client channels to master channels
   - Handles message deduplication and rate limiting

2. **redis** - Redis server for job queuing
   - Used for message deduplication across bots
   - Stores forwarding jobs for async processing
   - Data persisted in Docker volume

### Volumes

- `./logs` - Application logs (mounted to host)
- `./data` - Channel assignments and discovered channels (mounted to host)
- `redis-data` - Redis persistence (Docker volume)

### Network

All services run on `bot-network` bridge network for inter-service communication.

## Configuration

### Redis Connection

The bot connects to Redis using environment variables:

```bash
REDIS_HOST=redis          # Docker service name
REDIS_PORT=6379
REDIS_USERNAME=           # Leave empty for no auth
REDIS_PASSWORD=           # Leave empty for no auth
```

### Multiple Bots

Add additional bots by setting numbered environment variables:

```bash
SLACK_BOT_TOKEN_2=xoxb-...
SLACK_APP_TOKEN_2=xapp-...

SLACK_BOT_TOKEN_3=xoxb-...
SLACK_APP_TOKEN_3=xapp-...
```

The system automatically detects and configures all available bots.

## Data Persistence

### Channel Assignments

Channel-to-bot assignments are stored in `./data/channel_assignment.json` and mounted into the container. This ensures assignments persist across container restarts.

### Redis Data

Redis data is stored in a Docker volume (`redis-data`) and persists across container restarts.

### Logs

Application logs are written to `./logs/` which is mounted from the host.

## Monitoring

### View Logs

```bash
# All logs
docker-compose logs -f

# Only bot logs
docker-compose logs -f slack-bot

# Only Redis logs
docker-compose logs -f redis

# Last 100 lines
docker-compose logs --tail=100 slack-bot
```

### Check Status

```bash
# List running containers
docker-compose ps

# Check Redis connection
docker-compose exec redis redis-cli ping
```

### Redis Statistics

```bash
# Connect to Redis CLI
docker-compose exec redis redis-cli

# Check stream length
> XLEN forwarding:jobs

# Check memory usage
> INFO memory

# Monitor commands in real-time
> MONITOR
```

## Troubleshooting

### Container Won't Start

```bash
# Check logs for errors
docker-compose logs slack-bot

# Verify environment variables
docker-compose config

# Rebuild container
docker-compose up -d --build
```

### Redis Connection Issues

```bash
# Check Redis is running
docker-compose ps redis

# Test Redis connection
docker-compose exec redis redis-cli ping

# Check Redis logs
docker-compose logs redis
```

### Missing Channel Assignments

```bash
# Run channel discovery
docker-compose exec slack-bot python -m src.config.channel_discovery

# Check data volume
docker-compose exec slack-bot ls -la /app/data/
```

## Updates and Maintenance

### Update Code

```bash
# Pull latest code
git pull

# Rebuild and restart
docker-compose up -d --build
```

### Clear Redis Data

```bash
# Clear all Redis data
docker-compose exec redis redis-cli FLUSHALL

# Or restart Redis
docker-compose restart redis
```

### Backup Data

```bash
# Backup channel assignments
cp data/channel_assignment.json data/channel_assignment.json.backup

# Backup Redis data
docker-compose exec redis redis-cli SAVE
docker cp master-listener-redis:/data/dump.rdb ./redis-backup.rdb
```

## Production Recommendations

1. **Resource Limits**: Add resource constraints to docker-compose.yml
2. **Health Checks**: Implement health check endpoints
3. **Monitoring**: Use Prometheus/Grafana for metrics
4. **Logging**: Configure log rotation and centralized logging
5. **Secrets**: Use Docker secrets for sensitive data
6. **Backup**: Automate daily backups of data/ and Redis
7. **Updates**: Use semantic versioning and test updates in staging

## Environment Variables Reference

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| SLACK_BOT_TOKEN | Yes | - | Primary bot token |
| SLACK_APP_TOKEN | Yes | - | Primary app token |
| SLACK_BOT_TOKEN_N | No | - | Additional bot tokens (N=2,3,4...) |
| SLACK_APP_TOKEN_N | No | - | Additional app tokens (N=2,3,4...) |
| AGENT_MASTER_CHANNEL_ID | Yes | - | Agent master channel |
| APPTBK_MASTER_CHANNEL_ID | Yes | - | Appointment booking master channel |
| MANAGED_ADMIN_MASTER_CHANNEL_ID | Yes | - | Managed admin master channel |
| STORM_ADMIN_MASTER_CHANNEL_ID | Yes | - | Storm admin master channel |
| CLICKUP_API_TOKEN | No | - | ClickUp API token |
| REDIS_HOST | No | redis | Redis hostname |
| REDIS_PORT | No | 6379 | Redis port |
| REDIS_USERNAME | No | - | Redis username |
| REDIS_PASSWORD | No | - | Redis password |
| FORWARDER_WORKER_COUNT | No | 1 | Number of forwarder workers |
| LOG_LEVEL | No | INFO | Logging level |

## Support

For issues and questions:
1. Check logs: `docker-compose logs -f`
2. Review documentation in `/docs`
3. Check Redis status: `docker-compose exec redis redis-cli INFO`

