# Bot Invitation System

## Overview

Automated system for inviting bots to their assigned Slack channels with optimized performance and rate limiting.

## Key Features

### 1. **Automatic Bot Invitation**
- Runs automatically after channel discovery (on startup and every 12 hours)
- Can also be run manually using `scripts/bot_channel_inviter.py`

### 2. **Preserves Existing Assignments**
- **New channels only**: Only newly discovered channels are assigned to bots
- **Existing assignments preserved**: Channels already assigned to bots keep their assignments
- Uses consistent hashing to ensure stable assignments across restarts

### 3. **Highly Optimized Performance**

#### Before Optimization
- Checked each channel membership individually (~300+ API calls)
- Time: 10-15 minutes with rate limits
- Prone to hitting Slack's burst rate limits

#### After Optimization
- **Bulk caching**: Uses `users_conversations()` to fetch all memberships at once (1-2 API calls)
- **Skips existing members**: Only invites to new channels
- **Retry-After headers**: Respects Slack's rate limit timing
- **Randomized jitter**: 1.2-2.0 second delays prevent burst detection
- Time: **30-40 seconds** for ~300 channels
- **Saves 95%+ of API calls**

## Architecture

### Channel Discovery Flow

```
┌─────────────────────────────────────────────────┐
│ 1. Discover All Channels                        │
│    - Fetch all Slack channels with pagination   │
│    - Filter for -admin/-admins channels          │
└─────────────────────┬───────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────┐
│ 2. Assign Channels to Bots                      │
│    - Check existing assignments                  │
│    - Only assign NEW channels (preserve old)     │
│    - Use consistent hashing for distribution     │
└─────────────────────┬───────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────┐
│ 3. Auto-Invite Bots to Channels                 │
│    - Bulk fetch existing memberships             │
│    - Skip channels bot is already in             │
│    - Invite to new channels only                 │
│    - Respect rate limits with jitter             │
└──────────────────────────────────────────────────┘
```

### Bot Invitation Optimizations

1. **Bulk Membership Caching**
   ```python
   # Fetch all channels user is in with one API call
   existing_channels = get_user_channels(user_id)
   
   # Skip channels already a member of
   channels_to_invite = [ch for ch in assigned 
                        if ch not in existing_channels]
   ```

2. **Rate Limit Handling**
   ```python
   # Respect Slack's Retry-After header
   if e.response.status_code == 429:
       retry_after = int(e.response.headers.get("Retry-After", 30))
       time.sleep(retry_after)
   ```

3. **Randomized Jitter**
   ```python
   # Avoid burst detection
   delay = 1.2 + random.uniform(0, 0.8)
   time.sleep(delay)
   ```

## Usage

### Automatic Invitations
Invitations happen automatically:
- ✅ On system startup (after first channel discovery)
- ✅ Every 12 hours (after scheduled channel discovery)

### Manual Invitations

#### Invite to All Assigned Channels
```bash
python scripts/bot_channel_inviter.py
```

#### Invite to Master Channels Only
```bash
python scripts/invite_bots_to_master_channels.py
```

## Configuration Files

### Channel Assignments
`data/channel_assignment.json`
```json
{
  "metadata": {
    "total_bots": 3,
    "total_channels": 479,
    "bot_ids": [1, 2, 3]
  },
  "assignments": {
    "C07KXUAJUEB": 2,
    "C083U35KLSE": 1,
    ...
  }
}
```

### Invitation Results
`data/bot_invitation_results.json`
```json
{
  "metadata": {
    "base_bot": "Bot-1",
    "total_bots_processed": 2
  },
  "results": {
    "Bot-2": {
      "total_channels": 141,
      "successful_invitations": 9,
      "already_in_channel": 132,
      "failed_invitations": 0
    },
    ...
  }
}
```

## Performance Metrics

### Real-World Example
**Bot-2:**
- Total assigned channels: 141
- Already in: 132 channels (skipped)
- New invitations: 9 channels
- Time: ~20 seconds

**Bot-3:**
- Total assigned channels: 169
- Already in: 156 channels (skipped)
- New invitations: 13 channels
- Time: ~25 seconds

**Total:**
- Only 22 invitations instead of 310
- Saved ~290 API calls (94% reduction)
- Completed in 45 seconds instead of 10-15 minutes

## Error Handling

- **Rate Limits**: Automatically waits for Slack's specified retry time
- **Channel Not Found**: Skips non-existent channels (e.g., test channels)
- **Already Member**: Silently skips channels bot is already in
- **API Errors**: Logs errors but continues with remaining channels

## Integration Points

### In `listener.py`
```python
# Runs on startup
update_client_lists()  # Triggers channel discovery + bot invitation
```

### In `channel_discovery.py`
```python
def run_full_discovery(auto_invite=True):
    # 1. Discover channels
    # 2. Assign to bots (preserve existing)
    # 3. Auto-invite bots (if auto_invite=True)
```

### In `multi_bot_config.py`
```python
def assign_channels_to_bots(channel_ids):
    # Only assign NEW channels
    # Preserve existing assignments
    # Use consistent hashing
```

## Best Practices

1. **Let it run automatically**: Don't manually invite unless needed
2. **Check logs**: Monitor `data/bot_invitation_results.json` for issues
3. **New bot added**: Run `python scripts/bot_channel_inviter.py` once
4. **Master channels**: Run `python scripts/invite_bots_to_master_channels.py` for master channel setup

## Troubleshooting

### Bot not receiving messages
1. Check if bot is in the channel: Look at invitation results
2. Check channel assignment: Verify in `data/channel_assignment.json`
3. Check bot process: Ensure all 3 processes are running

### Rate limit errors
- Script automatically handles rate limits
- If persistent, increase jitter: Edit `base_delay` in `bot_channel_inviter.py`

### Channel not assigned
- Wait for next discovery cycle (12 hours)
- Or manually run: `python scripts/bot_channel_inviter.py`

## Future Enhancements

- [ ] Async/parallel invitations using `AsyncWebClient`
- [ ] Batch invitations (add multiple users per call when possible)
- [ ] Webhook notifications when new channels are discovered
- [ ] Dashboard showing invitation status per bot

