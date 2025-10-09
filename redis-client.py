"""Redis client for cross-process message deduplication.
"""

import os
import redis
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Initialize Redis client with credentials from .env
r = redis.Redis(
    host=os.environ.get('REDIS_HOST'),
    port=int(os.environ.get('REDIS_PORT')),
    username=os.environ.get('REDIS_USERNAME', 'default'),
    password=os.environ.get('REDIS_PASSWORD'),
    decode_responses=True
)

# Test connection
try:
    r.ping()
    print("Redis connection successful!")
    print(f"Connected to: {os.environ.get('REDIS_HOST')}:{os.environ.get('REDIS_PORT')}")
except redis.ConnectionError as e:
    print(f"Redis connection failed: {e}")
except Exception as e:
    print(f"Unexpected error: {e}")