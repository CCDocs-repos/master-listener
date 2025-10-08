import os
import requests
from dotenv import load_dotenv
import json

# Load environment variables
load_dotenv()

class SlackChannelFetcher:
    def __init__(self):
        self.bot_token = os.environ.get("SLACK_BOT_TOKEN")
        self.base_url = "https://slack.com/api"
        self.headers = {
            "Authorization": f"Bearer {self.bot_token}",
            "Content-Type": "application/json"
        }
    
    def get_all_channels(self):
        """Get all channels (public and private)"""
        print("Fetching all channels from Slack...")
        all_channels = []
        
        try:
            # Get public channels
            response = requests.get(f"{self.base_url}/conversations.list", 
                                 headers=self.headers,
                                 params={"types": "public_channel,private_channel", "limit": 1000})
            response.raise_for_status()
            data = response.json()
            
            if data["ok"]:
                channels = data["channels"]
                all_channels.extend(channels)
                print(f"Found {len(channels)} channels")
                
                # Handle pagination if needed
                while data.get("response_metadata", {}).get("next_cursor"):
                    cursor = data["response_metadata"]["next_cursor"]
                    response = requests.get(f"{self.base_url}/conversations.list", 
                                         headers=self.headers,
                                         params={"types": "public_channel,private_channel", 
                                                "limit": 1000, 
                                                "cursor": cursor})
                    response.raise_for_status()
                    data = response.json()
                    
                    if data["ok"]:
                        channels = data["channels"]
                        all_channels.extend(channels)
                        print(f"Found {len(channels)} more channels")
                    else:
                        break
            else:
                print(f"Error getting channels: {data.get('error')}")
                
        except Exception as e:
            print(f"Error fetching channels: {e}")
        
        return all_channels
    
    def filter_admin_channels(self, channels):
        """Filter channels to only admin channels"""
        admin_channels = []
        
        for channel in channels:
            channel_name = channel.get("name", "")
            
            # Check if channel name ends with -admin or -admins
            if channel_name.endswith("-admin") or channel_name.endswith("-admins"):
                admin_channels.append({
                    "id": channel["id"],
                    "name": channel_name,
                    "is_private": channel.get("is_private", False),
                    "num_members": channel.get("num_members", 0)
                })
                print(f"Found admin channel: {channel_name}")
        
        return admin_channels
    
    def save_to_file(self, admin_channels):
        """Save admin channels to a JSON file"""
        data = {
            "admin_channels": admin_channels,
            "total_count": len(admin_channels),
            "last_updated": "2024-01-01"  # You might want to add actual timestamp
        }
        
        with open("data/admin_channels.json", "w") as f:
            json.dump(data, f, indent=2)
        
        print(f"\nSaved to admin_channels.json:")
        print(f"Total admin channels: {len(admin_channels)}")
    
    def analyze_channel_patterns(self, admin_channels):
        """Analyze patterns in admin channel names"""
        print("\n=== CHANNEL NAME ANALYSIS ===")
        
        # Extract client names from channel names
        client_names = []
        for channel in admin_channels:
            channel_name = channel["name"]
            # Remove -admin or -admins suffix
            client_name = channel_name.replace("-admin", "").replace("-admins", "")
            client_names.append(client_name)
        
        print(f"Unique client names found: {len(set(client_names))}")
        print("\nFirst 20 client names:")
        for i, name in enumerate(sorted(set(client_names))[:20]):
            print(f"  {i+1}. {name}")
        
        if len(set(client_names)) > 20:
            print(f"  ... and {len(set(client_names)) - 20} more")
        
        return client_names

def main():
    if not os.environ.get("SLACK_BOT_TOKEN"):
        print("Error: SLACK_BOT_TOKEN environment variable not set")
        print("Please add your Slack bot token to your .env file")
        return
    
    fetcher = SlackChannelFetcher()
    
    # Get all channels
    all_channels = fetcher.get_all_channels()
    print(f"\nTotal channels found: {len(all_channels)}")
    
    # Filter for admin channels
    admin_channels = fetcher.filter_admin_channels(all_channels)
    
    # Save to file
    fetcher.save_to_file(admin_channels)
    
    # Analyze patterns
    client_names = fetcher.analyze_channel_patterns(admin_channels)
    
    print("\nSummary:")
    print(f"Total channels: {len(all_channels)}")
    print(f"Admin channels: {len(admin_channels)}")
    print(f"Unique clients: {len(set(client_names))}")

if __name__ == "__main__":
    main() 