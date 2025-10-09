#!/usr/bin/env python3
"""
Comprehensive Channel Mapping System
====================================

This script:
1. Fetches client lists from ClickUp
2. Fetches admin channels from Slack  
3. Maps ClickUp clients to Slack channels using intelligent matching
4. Updates channel_lists.json with proper categorizations
5. Maintains final_client_mapping.json for reference

Usage:
    python channel_mapper.py
"""

import os
import json
import requests
import re
from datetime import datetime
from difflib import SequenceMatcher
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

class ChannelMapper:
    def __init__(self):
        # ClickUp setup
        self.clickup_token = os.environ.get("CLICKUP_API_TOKEN")
        if not self.clickup_token:
            raise ValueError("CLICKUP_API_TOKEN environment variable not set")
        
        # Slack setup
        self.slack_token = os.environ.get("SLACK_BOT_TOKEN")
        if not self.slack_token:
            raise ValueError("SLACK_BOT_TOKEN environment variable not set")
        
        self.clickup_headers = {
            "Authorization": self.clickup_token,
            "Content-Type": "application/json"
        }
        
        self.slack_headers = {
            "Authorization": f"Bearer {self.slack_token}",
            "Content-Type": "application/json"
        }
        
        self.clickup_base_url = "https://api.clickup.com/api/v2"
        self.slack_base_url = "https://slack.com/api"
        
        print("🚀 Channel Mapper initialized")

    def clean_client_name(self, client_name):
        """Clean up client names by removing fractional indicators and other patterns"""
        if not client_name:
            return client_name
            
        # Define patterns to remove (case insensitive)
        patterns_to_remove = [
            r'\s*\(\s*solar\s+fractional\s*\)',
            r'\s*\(\s*fractional\s+solar\s*\)',
            r'\s*\(\s*roofing\s+fractional\s*\)',
            r'\s*\(\s*fractional\s+roofing\s*\)',
            r'\s*\(\s*fractional\s*\)',
        ]
        
        cleaned_name = client_name.strip()
        
        # Apply each pattern removal
        for pattern in patterns_to_remove:
            cleaned_name = re.sub(pattern, '', cleaned_name, flags=re.IGNORECASE)
        
        # Clean up any extra whitespace
        cleaned_name = re.sub(r'\s+', ' ', cleaned_name).strip()
        
        return cleaned_name

    def fetch_clickup_clients(self):
        """Fetch client lists from ClickUp"""
        print("📋 Fetching client lists from ClickUp...")
        
        try:
            # Get workspace
            response = requests.get(f"{self.clickup_base_url}/team", headers=self.clickup_headers)
            response.raise_for_status()
            teams = response.json()["teams"]
            workspace_id = teams[0]["id"] if teams else None
            
            if not workspace_id:
                print("❌ No workspace found")
                return {}

            # Find Technology space
            response = requests.get(f"{self.clickup_base_url}/team/{workspace_id}/space", headers=self.clickup_headers)
            response.raise_for_status()
            spaces = response.json()["spaces"]
            
            tech_space = None
            for space in spaces:
                if space['name'].lower() == 'technology':
                    tech_space = space
                    break

            if not tech_space:
                print("❌ Technology space not found")
                return {}

            # Find Data Department list
            response = requests.get(f"{self.clickup_base_url}/space/{tech_space['id']}/list", headers=self.clickup_headers)
            response.raise_for_status()
            lists = response.json()["lists"]
            
            data_dept_list = None
            for list_item in lists:
                if list_item["name"] == "Data Department":
                    data_dept_list = list_item
                    break

            if not data_dept_list:
                print("❌ Data Department list not found")
                return {}

            # Get tasks from Data Department
            response = requests.get(f"{self.clickup_base_url}/list/{data_dept_list['id']}/task", headers=self.clickup_headers)
            response.raise_for_status()
            tasks = response.json()["tasks"]
            
            # Initialize client categories
            client_lists = {
                "managed_clients_fractionals": [],
                "managed_clients_full": [],
                "storm_clients": []
            }
            
            # Process each target task
            target_tasks = {
                "Managed Clients - Fractionals": "managed_clients_fractionals",
                "Managed Clients - Full Clients": "managed_clients_full",
                "Storm Master Client List - Internal CC Docs": "storm_clients"
            }
            
            for task in tasks:
                task_name = task.get("name", "")
                if task_name in target_tasks:
                    category = target_tasks[task_name]
                    task_id = task["id"]
                    print(f"  📋 Processing: {task_name}")
                    
                    # Get subtasks (client names)
                    try:
                        # First try the subtask endpoint
                        response = requests.get(f"{self.clickup_base_url}/task/{task_id}/subtask", headers=self.clickup_headers)
                        if response.status_code == 200:
                            subtasks = response.json()["tasks"]
                        else:
                            # If that fails, try getting task details with subtasks
                            response = requests.get(f"{self.clickup_base_url}/task/{task_id}?include_subtasks=true", headers=self.clickup_headers)
                            response.raise_for_status()
                            task_details = response.json()
                            subtasks = task_details.get("subtasks", [])
                    except Exception as e:
                        print(f"Error getting subtasks for {task_name}: {e}")
                        subtasks = []
                    
                    for subtask in subtasks:
                        client_name = subtask.get("name", "").strip()
                        if client_name and not client_name.startswith("Template"):
                            # Clean up the client name
                            cleaned_name = self.clean_client_name(client_name)
                            if cleaned_name:  # Only add if name isn't empty after cleaning
                                client_lists[category].append(cleaned_name)
                    
                    print(f"Found {len(client_lists[category])} clients")
            
            total_clients = sum(len(clients) for clients in client_lists.values())
            print(f"Total ClickUp clients fetched: {total_clients}")
            print(f"Fractional: {len(client_lists['managed_clients_fractionals'])}")
            print(f"Full: {len(client_lists['managed_clients_full'])}")
            print(f"Storm: {len(client_lists['storm_clients'])}")
            
            return client_lists
            
        except Exception as e:
            print(f"Error fetching ClickUp clients: {e}")
            return {}

    def fetch_slack_channels(self):
        """Fetch admin channels from Slack"""
        print("💬 Fetching admin channels from Slack...")
        
        try:
            all_channels = []
            
            # Get all channels with pagination
            response = requests.get(
                f"{self.slack_base_url}/conversations.list", 
                headers=self.slack_headers,
                params={"types": "public_channel,private_channel", "limit": 1000}
            )
            response.raise_for_status()
            data = response.json()
            
            if data["ok"]:
                channels = data["channels"]
                all_channels.extend(channels)
                
                # Handle pagination
                while data.get("response_metadata", {}).get("next_cursor"):
                    cursor = data["response_metadata"]["next_cursor"]
                    response = requests.get(
                        f"{self.slack_base_url}/conversations.list", 
                        headers=self.slack_headers,
                        params={
                            "types": "public_channel,private_channel", 
                            "limit": 1000, 
                            "cursor": cursor
                        }
                    )
                    response.raise_for_status()
                    data = response.json()
                    
                    if data["ok"]:
                        channels = data["channels"]
                        all_channels.extend(channels)
                    else:
                        break
            
            # Filter for admin channels
            admin_channels = []
            for channel in all_channels:
                channel_name = channel.get("name", "")
                
                # Check if channel name ends with -admin or -admins
                if channel_name.endswith("-admin") or channel_name.endswith("-admins"):
                    admin_channels.append({
                        "id": channel["id"],
                        "name": channel_name,
                        "is_private": channel.get("is_private", False),
                        "num_members": channel.get("num_members", 0)
                    })
            
            print(f"Total Slack admin channels found: {len(admin_channels)}")
            return admin_channels
            
        except Exception as e:
            print(f"Error fetching Slack channels: {e}")
            return []

    def normalize_name_for_matching(self, name):
        """Normalize names for better matching"""
        if not name:
            return ""
        
        # Convert to lowercase
        normalized = name.lower()
        
        # Remove common business suffixes/prefixes
        suffixes_to_remove = [
            'llc', 'inc', 'corp', 'corporation', 'company', 'co', 'ltd',
            'roofing', 'construction', 'contractors', 'contracting', 'restoration',
            'exteriors', 'solutions', 'services', 'group', 'enterprises'
        ]
        
        # Remove punctuation and extra spaces
        normalized = re.sub(r'[^\w\s]', ' ', normalized)
        normalized = re.sub(r'\s+', ' ', normalized).strip()
        
        # Split into words and remove common suffixes
        words = normalized.split()
        filtered_words = []
        
        for word in words:
            if word not in suffixes_to_remove:
                filtered_words.append(word)
        
        return ' '.join(filtered_words)

    def calculate_similarity(self, name1, name2):
        """Calculate similarity between two names"""
        norm1 = self.normalize_name_for_matching(name1)
        norm2 = self.normalize_name_for_matching(name2)
        
        # Use SequenceMatcher for similarity
        similarity = SequenceMatcher(None, norm1, norm2).ratio()
        
        # Boost score if one name contains the other
        if norm1 in norm2 or norm2 in norm1:
            similarity = max(similarity, 0.8)
        
        # Check for word overlap
        words1 = set(norm1.split())
        words2 = set(norm2.split())
        
        if words1 and words2:
            word_overlap = len(words1.intersection(words2)) / len(words1.union(words2))
            similarity = max(similarity, word_overlap)
        
        return similarity

    def map_clients_to_channels(self, clickup_clients, slack_channels):
        """Map managed clients to Slack channels, all others go to storm"""
        print("Mapping managed clients to Slack channels...")
        print("All other admin channels will be categorized as storm")
        
        mappings = {
            "managed_channels": [],
            "storm_channels": [],
            "unmapped_clickup_clients": [],
            "unmapped_slack_channels": []
        }
        
        # Combine managed clients (full + fractionals)
        all_managed_clients = (
            clickup_clients.get("managed_clients_fractionals", []) + 
            clickup_clients.get("managed_clients_full", [])
        )
        
        used_channels = set()
        
        # Map managed clients only
        print("Mapping managed clients (full + fractionals)...")
        for client_name in all_managed_clients:
            best_match = None
            best_score = 0.0
            
            for channel in slack_channels:
                if channel["name"] in used_channels:
                    continue
                
                # Extract client name from channel (remove -admin suffix)
                channel_client_name = channel["name"].replace("-admin", "").replace("-admins", "")
                channel_client_name = channel_client_name.replace("-", " ")
                
                similarity = self.calculate_similarity(client_name, channel_client_name)
                
                if similarity > best_score and similarity > 0.6:  # Minimum threshold
                    best_score = similarity
                    best_match = channel
            
            if best_match:
                mappings["managed_channels"].append({
                    "slack_channel": best_match,
                    "clickup_name": client_name,
                    "confidence": best_score
                })
                used_channels.add(best_match["name"])
                print(f"{client_name} → {best_match['name']} (confidence: {best_score:.2f})")
            else:
                mappings["unmapped_clickup_clients"].append({
                    "name": client_name,
                    "type": "managed"
                })
                print(f" No match found for managed client: {client_name}")
        
        # All remaining channels go to storm (much simpler!)
        print("Assigning all remaining admin channels to storm...")
        storm_count = 0
        for channel in slack_channels:
            if channel["name"] not in used_channels:
                mappings["storm_channels"].append({
                    "slack_channel": channel,
                    "clickup_name": "Auto-assigned (Storm)",
                    "confidence": 1.0
                })
                storm_count += 1
        
        print(f"{storm_count} channels auto-assigned to storm")
        
        print(f"Mapping complete:")
        print(f"Managed mappings: {len(mappings['managed_channels'])}")
        print(f"Storm channels: {len(mappings['storm_channels'])}")
        print(f"Unmapped managed clients: {len(mappings['unmapped_clickup_clients'])}")
        print(f"Total channels processed: {len(slack_channels)}")
        
        return mappings

    def update_channel_lists(self, mappings):
        """Update channel_lists.json with new mappings"""
        print("Updating channel_lists.json...")
        
        channel_lists = {
            "managed_channels": [mapping["slack_channel"]["name"] for mapping in mappings["managed_channels"]],
            "storm_channels": [mapping["slack_channel"]["name"] for mapping in mappings["storm_channels"]],
            "ignored_channels": ["ccdocs-admin"]  # Keep existing ignored channels
        }
        
        # Load existing ignored channels if they exist
        try:
            with open('data/channel_lists.json', 'r') as f:
                existing_data = json.load(f)
                existing_ignored = existing_data.get('ignored_channels', [])
                # Merge with existing ignored channels
                channel_lists["ignored_channels"] = list(set(channel_lists["ignored_channels"] + existing_ignored))
        except FileNotFoundError:
            pass
        
        # Save updated channel lists
        with open('data/channel_lists.json', 'w') as f:
            json.dump(channel_lists, f, indent=2)
        
        print(f"channel_lists.json updated:")
        print(f"Managed channels: {len(channel_lists['managed_channels'])}")
        print(f"Storm channels: {len(channel_lists['storm_channels'])}")
        print(f"Ignored channels: {len(channel_lists['ignored_channels'])}")

    def save_detailed_mapping(self, mappings, clickup_clients):
        """Save detailed mapping to final_client_mapping.json"""
        print("Saving detailed mapping...")
        
        # Calculate managed clients total
        managed_total = (
            len(clickup_clients.get("managed_clients_fractionals", [])) + 
            len(clickup_clients.get("managed_clients_full", []))
        )
        
        detailed_mapping = {
            "metadata": {
                "last_updated": datetime.now().isoformat(),
                "mapping_strategy": "Managed clients mapped individually, all others auto-assigned to storm",
                "clickup_totals": {
                    "managed_fractionals": len(clickup_clients.get("managed_clients_fractionals", [])),
                    "managed_full": len(clickup_clients.get("managed_clients_full", [])),
                    "managed_total": managed_total,
                    "storm_clients": len(clickup_clients.get("storm_clients", []))
                },
                "mapping_results": {
                    "managed_mapped": len(mappings["managed_channels"]),
                    "storm_channels": len(mappings["storm_channels"]),
                    "unmapped_managed": len(mappings["unmapped_clickup_clients"]),
                    "total_channels_processed": len(mappings["managed_channels"]) + len(mappings["storm_channels"])
                }
            },
            "managed_channels": mappings["managed_channels"],
            "storm_channels": mappings["storm_channels"],
            "unmapped_managed_clients": mappings["unmapped_clickup_clients"]
        }
        
        with open('data/final_client_mapping.json', 'w') as f:
            json.dump(detailed_mapping, f, indent=2)
        
        print("Detailed mapping saved to final_client_mapping.json")

    def run_full_mapping(self):
        """Run the complete mapping process"""
        print("Starting complete channel mapping process...")
        print("=" * 60)
        
        try:
            # Step 1: Fetch ClickUp clients
            clickup_clients = self.fetch_clickup_clients()
            if not clickup_clients:
                print("Failed to fetch ClickUp clients")
                return False
            
            print()
            
            # Step 2: Fetch Slack channels
            slack_channels = self.fetch_slack_channels()
            if not slack_channels:
                print("Failed to fetch Slack channels")
                return False
            
            print()
            
            # Step 3: Map clients to channels
            mappings = self.map_clients_to_channels(clickup_clients, slack_channels)
            
            print()
            
            # Step 4: Update channel lists
            self.update_channel_lists(mappings)
            
            print()
            
            # Step 5: Save detailed mapping
            self.save_detailed_mapping(mappings, clickup_clients)
            
            print()
            print("=" * 60)
            print("🎉 Channel mapping process completed successfully!")
            
            return True
            
        except Exception as e:
            print(f"Error in mapping process: {e}")
            return False

def main():
    """Main execution"""
    if not os.environ.get("CLICKUP_API_TOKEN"):
        print("Error: CLICKUP_API_TOKEN environment variable not set")
        return
    
    if not os.environ.get("SLACK_BOT_TOKEN"):
        print("Error: SLACK_BOT_TOKEN environment variable not set")
        return
    
    try:
        mapper = ChannelMapper()
        success = mapper.run_full_mapping()
        
        if success:
            print("\n All systems updated! The listener will automatically reload the new channel categorizations.")
        else:
            print("\n Mapping process failed. Please check the errors above.")
            
    except Exception as e:
        print(f"Fatal error: {e}")

if __name__ == "__main__":
    main()
