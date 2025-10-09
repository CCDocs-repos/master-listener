"""Basic connection example.
"""

import redis

r = redis.Redis(
    host='redis-14632.c251.east-us-mz.azure.redns.redis-cloud.com',
    port=14632,
    decode_responses=True,
    username="default",
    password="ME10MMhTAYrEgl4YCmSCWdKaCOdnZA9g",
)