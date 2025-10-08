#!/usr/bin/env python3
"""
Simple script to generate client_lists.json with proper categorization.
Only fetches client names from subtasks - nothing else.
"""

import os
import json
import requests
import re
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

class ClientListGenerator:
    def __init__(self):
        self.api_token = os.environ.get("CLICKUP_API_TOKEN")
        if not self.api_token:
            raise ValueError("CLICKUP_API_TOKEN environment variable not set")
        
        self.headers = {
            "Authorization": self.api_token,
            "Content-Type": "application/json"
        }
        self.base_url = "https://api.clickup.com/api/v2"

    def clean_client_name(self, client_name):
        """Clean up client names by removing fractional indicators and other patterns"""
        if not client_name:
            return client_name
            
        # Define patterns to remove (case insensitive)
        patterns_to_remove = [
            r'\s*\(solar\s+fractional\)',
            r'\s*\(fractional\s+solar\)',
            r'\s*\(roofing\s+fractional\)',
            r'\s*\(fractional\s+roofing\)',
            r'\s*\(fractional\)',
        ]
        
        cleaned_name = client_name.strip()
        
        # Apply each pattern removal
        for pattern in patterns_to_remove:
            cleaned_name = re.sub(pattern, '', cleaned_name, flags=re.IGNORECASE)
        
        # Clean up any extra whitespace
        cleaned_name = re.sub(r'\s+', ' ', cleaned_name).strip()
        
        return cleaned_name

    def get_workspace_id(self):
        """Get the first workspace ID"""
        response = requests.get(f"{self.base_url}/team", headers=self.headers)
        response.raise_for_status()
        teams = response.json()["teams"]
        return teams[0]["id"] if teams else None

    def get_spaces(self, workspace_id):
        """Get all spaces in workspace"""
        response = requests.get(f"{self.base_url}/team/{workspace_id}/space", headers=self.headers)
        response.raise_for_status()
        return response.json()["spaces"]

    def get_lists(self, space_id):
        """Get all lists in a space"""
        response = requests.get(f"{self.base_url}/space/{space_id}/list", headers=self.headers)
        response.raise_for_status()
        return response.json()["lists"]

    def get_list_items(self, list_id):
        """Get all tasks in a list"""
        response = requests.get(f"{self.base_url}/list/{list_id}/task", headers=self.headers)
        response.raise_for_status()
        return response.json()["tasks"]

    def get_task_details(self, task_id):
        """Get task details including subtasks"""
        try:
            response = requests.get(f"{self.base_url}/task/{task_id}?include_subtasks=true", headers=self.headers)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            print(f"Error getting task details for {task_id}: {e}")
            return None

    def get_task_subtasks(self, task_id):
        """Get all subtasks of a task"""
        try:
            # First try the subtask endpoint
            response = requests.get(f"{self.base_url}/task/{task_id}/subtask", headers=self.headers)
            if response.status_code == 200:
                return response.json()["tasks"]
            
            # If that fails, try getting task details with subtasks
            task_details = self.get_task_details(task_id)
            if task_details and "subtasks" in task_details:
                return task_details["subtasks"]
            
            return []
        except Exception as e:
            print(f"Error getting subtasks for {task_id}: {e}")
            return []

    def fetch_client_lists(self):
        """Fetch and categorize all client lists"""
        print("🎯 Generating client lists from Technology > Data Department...")
        
        workspace_id = self.get_workspace_id()
        if not workspace_id:
            print("❌ No workspace found")
            return {}

        # Find Technology space
        spaces = self.get_spaces(workspace_id)
        tech_space = None
        for space in spaces:
            if space['name'].lower() == 'technology':
                tech_space = space
                break

        if not tech_space:
            print("❌ Technology space not found")
            return {}

        print(f"✅ Found Technology space: {tech_space['name']}")

        # Find Data Department list
        lists = self.get_lists(tech_space["id"])
        data_dept_list = None
        for list_item in lists:
            if list_item["name"] == "Data Department":
                data_dept_list = list_item
                break

        if not data_dept_list:
            print("❌ Data Department list not found")
            return {}

        print(f"✅ Found Data Department list: {data_dept_list['name']}")
        
        # Get tasks from Data Department
        tasks = self.get_list_items(data_dept_list["id"])
        
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
                print(f"📋 Processing: {task_name}")
                
                # Get subtasks (client names)
                subtasks = self.get_task_subtasks(task_id)
                
                for subtask in subtasks:
                    client_name = subtask.get("name", "").strip()
                    if client_name and not client_name.startswith("Template"):
                        # Clean up the client name
                        cleaned_name = self.clean_client_name(client_name)
                        if cleaned_name:  # Only add if name isn't empty after cleaning
                            client_lists[category].append(cleaned_name)
                
                print(f"  ✅ Found {len(client_lists[category])} clients")
        
        return client_lists

    def save_client_lists(self, client_lists):
        """Save client lists to JSON file"""
        output_file = "data/client_lists.json"
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(client_lists, f, indent=2, ensure_ascii=False)
        
        print(f"\n✅ Client lists saved to: {output_file}")
        print(f"📊 Summary:")
        print(f"   • Fractional clients: {len(client_lists['managed_clients_fractionals'])}")
        print(f"   • Full clients: {len(client_lists['managed_clients_full'])}")
        print(f"   • Storm clients: {len(client_lists['storm_clients'])}")
        print(f"   • Total clients: {sum(len(clients) for clients in client_lists.values())}")

def main():
    """Main execution"""
    if not os.environ.get("CLICKUP_API_TOKEN"):
        print("❌ Error: CLICKUP_API_TOKEN environment variable not set")
        print("Please add your ClickUp API token to your .env file")
        return
    
    try:
        generator = ClientListGenerator()
        client_lists = generator.fetch_client_lists()
        
        if client_lists:
            generator.save_client_lists(client_lists)
        else:
            print("❌ No client data found")
            
    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    main()
