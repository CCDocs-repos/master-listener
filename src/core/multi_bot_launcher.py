#!/usr/bin/env python3
"""
Multi-Bot Launcher
==================

Runs all configured bots in a single process using separate threads.
Each bot runs independently with its own tokens and assigned channels.

Usage:
    python multi_bot_launcher.py
"""

import os
import sys
import time
import logging
import threading
from datetime import datetime
from dotenv import load_dotenv

# Add src directory to Python path for imports to work
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

# Load environment variables
load_dotenv()

# Import our multi-bot components
from config.multi_bot_config import MultiBotConfigManager

# Configure logging with thread names
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - [%(threadName)s] - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

class BotRunner:
    """Runs a single bot instance in a thread"""
    
    def __init__(self, bot_id: int, bot_config):
        self.bot_id = bot_id
        self.bot_config = bot_config
        self.thread = None
        self.running = False
        
    def run_bot(self):
        """Run the bot instance"""
        try:
            # Set the BOT_ID environment variable for this thread
            os.environ["BOT_ID"] = str(self.bot_id)
            
            logger.info(f"🚀 Starting {self.bot_config.name}...")
            logger.info(f"   • Bot ID: {self.bot_id}")
            logger.info(f"   • Bot Token: {self.bot_config.bot_token[:12]}...")
            logger.info(f"   • App Token: {self.bot_config.app_token[:12]}...")
            
            # Import and run the listener
            # We need to import here to avoid conflicts between bot instances
            import importlib
            from core import listener
            
            # Reload the listener module to pick up the new BOT_ID
            importlib.reload(listener)
            
            # Run the main function
            listener.main()
            
        except KeyboardInterrupt:
            logger.info(f"🛑 {self.bot_config.name} interrupted by user")
        except Exception as e:
            logger.error(f"❌ Error in {self.bot_config.name}: {e}")
            logger.exception("Full error details:")
        finally:
            self.running = False
            logger.info(f"🔚 {self.bot_config.name} stopped")
    
    def start(self):
        """Start the bot in a separate thread"""
        if self.running:
            logger.warning(f"⚠️ {self.bot_config.name} is already running")
            return
        
        self.running = True
        self.thread = threading.Thread(
            target=self.run_bot,
            name=f"Bot-{self.bot_id}",
            daemon=False  # Don't make daemon so we can wait for clean shutdown
        )
        self.thread.start()
        logger.info(f"✅ {self.bot_config.name} thread started")
    
    def is_alive(self):
        """Check if the bot thread is still running"""
        return self.thread and self.thread.is_alive()
    
    def join(self, timeout=None):
        """Wait for the bot thread to finish"""
        if self.thread:
            self.thread.join(timeout)

class MultiBotLauncher:
    """Manages multiple bot instances"""
    
    def __init__(self):
        self.multi_bot_manager = MultiBotConfigManager()
        self.bot_runners = {}
        self.running = False
        
        logger.info("🤖 Multi-Bot Launcher initialized")
        logger.info(f"   • Total bots configured: {len(self.multi_bot_manager.bot_configs)}")
        
        # Create bot runners for each configured bot
        for bot_id, bot_config in self.multi_bot_manager.bot_configs.items():
            self.bot_runners[bot_id] = BotRunner(bot_id, bot_config)
    
    def start_all_bots(self):
        """Start all configured bots"""
        logger.info("🚀 Starting all bots...")
        logger.info("=" * 60)
        
        self.running = True
        
        # Start each bot in its own thread
        for bot_id, bot_runner in self.bot_runners.items():
            try:
                bot_runner.start()
                time.sleep(2)  # Small delay between bot starts
            except Exception as e:
                logger.error(f"❌ Failed to start Bot-{bot_id}: {e}")
        
        logger.info("=" * 60)
        logger.info("✅ All bots started!")
        
        # Log the assignment distribution
        self.multi_bot_manager.log_assignment_stats()
        
        return True
    
    def monitor_bots(self):
        """Monitor bot health and restart if needed"""
        logger.info("👁️ Starting bot monitoring...")
        
        while self.running:
            try:
                # Check each bot's health
                for bot_id, bot_runner in self.bot_runners.items():
                    if not bot_runner.is_alive() and self.running:
                        logger.warning(f"⚠️ Bot-{bot_id} appears to have stopped. Attempting restart...")
                        try:
                            bot_runner.start()
                            time.sleep(5)  # Give it time to start
                        except Exception as e:
                            logger.error(f"❌ Failed to restart Bot-{bot_id}: {e}")
                
                # Sleep for 30 seconds before next health check
                time.sleep(30)
                
            except KeyboardInterrupt:
                logger.info("🛑 Bot monitoring interrupted")
                break
            except Exception as e:
                logger.error(f"❌ Error in bot monitoring: {e}")
                time.sleep(10)  # Wait before retrying
    
    def stop_all_bots(self):
        """Stop all bots gracefully"""
        logger.info("🛑 Stopping all bots...")
        
        self.running = False
        
        # Wait for all bots to finish (with timeout)
        for bot_id, bot_runner in self.bot_runners.items():
            logger.info(f"⏳ Waiting for Bot-{bot_id} to stop...")
            bot_runner.join(timeout=10)  # 10 second timeout per bot
            
            if bot_runner.is_alive():
                logger.warning(f"⚠️ Bot-{bot_id} did not stop gracefully")
            else:
                logger.info(f"✅ Bot-{bot_id} stopped")
        
        logger.info("🔚 All bots stopped")
    
    def run(self):
        """Run the multi-bot system"""
        try:
            # Start all bots
            if not self.start_all_bots():
                logger.error("❌ Failed to start bots")
                return False
            
            # Start monitoring in a separate thread
            monitor_thread = threading.Thread(
                target=self.monitor_bots,
                name="BotMonitor",
                daemon=True
            )
            monitor_thread.start()
            
            # Main loop - just wait and handle interrupts
            logger.info("🎯 Multi-bot system running. Press Ctrl+C to stop.")
            logger.info("📊 Bot Status:")
            
            while self.running:
                # Show status every 60 seconds
                alive_count = sum(1 for runner in self.bot_runners.values() if runner.is_alive())
                total_count = len(self.bot_runners)
                
                logger.info(f"💓 Heartbeat: {alive_count}/{total_count} bots running")
                
                # List running bots
                for bot_id, bot_runner in self.bot_runners.items():
                    status = "🟢 Running" if bot_runner.is_alive() else "🔴 Stopped"
                    logger.info(f"   • Bot-{bot_id}: {status}")
                
                time.sleep(60)  # Status update every minute
            
        except KeyboardInterrupt:
            logger.info("🛑 Received interrupt signal")
        except Exception as e:
            logger.error(f"❌ Error in multi-bot system: {e}")
            logger.exception("Full error details:")
        finally:
            self.stop_all_bots()
        
        return True

def print_startup_banner():
    """Print a nice startup banner"""
    print("=" * 80)
    print("🤖 MULTI-BOT SLACK FORWARDING SYSTEM")
    print("=" * 80)
    print(f"⏰ Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("🎯 Features:")
    print("   • Distributed channel processing")
    print("   • Automatic rate limit management") 
    print("   • Real-time message forwarding")
    print("   • Thread-based bot management")
    print("   • Health monitoring and auto-restart")
    print("=" * 80)

def main():
    """Main execution"""
    print_startup_banner()
    
    try:
        # Create and run the multi-bot launcher
        launcher = MultiBotLauncher()
        
        if not launcher.multi_bot_manager.bot_configs:
            print("❌ ERROR: No bot configurations found!")
            print("💡 Please check your environment variables:")
            print("   • SLACK_BOT_TOKEN and SLACK_APP_TOKEN")
            print("   • SLACK_BOT_TOKEN_2 and SLACK_APP_TOKEN_2")
            print("   • etc.")
            return False
        
        success = launcher.run()
        
        if success:
            print("\n✅ Multi-bot system completed successfully!")
        else:
            print("\n❌ Multi-bot system failed!")
            
        return success
        
    except Exception as e:
        logger.error(f"❌ Fatal error: {e}")
        logger.exception("Full error details:")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
