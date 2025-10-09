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
import io
import time
import logging
import threading
import multiprocessing
from datetime import datetime
from dotenv import load_dotenv

# Set UTF-8 encoding for Windows console
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

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

def run_bot_process(bot_id, bot_token, app_token, bot_name):
    """Run a bot instance in a separate process"""
    try:
        # Set the BOT_ID environment variable for this process
        os.environ["BOT_ID"] = str(bot_id)
        os.environ["SLACK_BOT_TOKEN"] = bot_token
        os.environ["SLACK_APP_TOKEN"] = app_token
        
        # Configure logging for this process
        logging.basicConfig(
            level=logging.INFO,
            format=f'%(asctime)s - %(name)s - [{bot_name}] - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        logger = logging.getLogger(__name__)
        
        logger.info(f"Starting {bot_name} (PID: {os.getpid()})")

        # Import and run the Redis-based listener (enqueue-only)
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
        from core import listener_redis as listener

        # Run the main function
        listener.main()

    except KeyboardInterrupt:
        pass  # Clean shutdown on Ctrl+C
    except Exception as e:
        logger.error(f"[ERROR] Error in {bot_name}: {e}")
        import traceback
        traceback.print_exc()
    finally:
        pass


def run_worker_process():
    """Run a single forwarder worker that consumes Redis jobs and posts to Slack"""
    try:
        # Configure logging for worker process
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - [ForwarderWorker] - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        logger = logging.getLogger(__name__)

        logger.info(f"Starting Forwarder Worker (PID: {os.getpid()})")

        # Import and run the forwarder worker
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
        from core import forwarder_worker

        forwarder_worker.main()

    except KeyboardInterrupt:
        pass  # Clean shutdown on Ctrl+C
    except Exception as e:
        logger.error(f"[ERROR] Error in Forwarder Worker: {e}")
        import traceback
        traceback.print_exc()
    finally:
        pass


class BotRunner:
    """Runs a single bot instance in a separate process"""
    
    def __init__(self, bot_id: int, bot_config):
        self.bot_id = bot_id
        self.bot_config = bot_config
        self.process = None
        self.running = False
        
    def start(self):
        """Start the bot in a separate process"""
        if self.running and self.process and self.process.is_alive():
            logger.warning(f"{self.bot_config.name} is already running")
            return

        self.running = True
        self.process = multiprocessing.Process(
            target=run_bot_process,
            args=(self.bot_id, self.bot_config.bot_token, self.bot_config.app_token, self.bot_config.name),
            name=f"Bot-{self.bot_id}",
            daemon=False  # Don't make daemon so we can wait for clean shutdown
        )
        self.process.start()
    
    def is_alive(self):
        """Check if the bot process is still running"""
        return self.process and self.process.is_alive()
    
    def join(self, timeout=None):
        """Wait for the bot process to finish"""
        if self.process:
            self.process.join(timeout)
    
    def terminate(self):
        """Terminate the bot process"""
        if self.process and self.process.is_alive():
            self.process.terminate()
            self.process.join(timeout=5)

class MultiBotLauncher:
    """Manages multiple bot instances"""
    
    def __init__(self):
        self.multi_bot_manager = MultiBotConfigManager()
        self.bot_runners = {}
        self.running = False
        self.worker_process = None
        
        logger.info(f"Multi-Bot Launcher initialized ({len(self.multi_bot_manager.bot_configs)} bots)")

        # Create bot runners for each configured bot
        for bot_id, bot_config in self.multi_bot_manager.bot_configs.items():
            self.bot_runners[bot_id] = BotRunner(bot_id, bot_config)
    
    def check_missing_channels(self):
        """Check for missing/inaccessible channels at startup"""
        print("\n" + "=" * 80)
        print("CHECKING FOR MISSING/INACCESSIBLE CHANNELS")
        print("=" * 80)
        
        try:
            # Get all the channel IDs that have been causing errors
            problem_channels = {
                'C086XJBA1MG': 'Unknown',
                'C0774AP1R5M': 'Unknown', 
                'C09K7TJ2K39': 'Unknown',
                'C0875D2QHMJ': 'Unknown',
                'C07BEB1RANB': 'Unknown',
                'C09B32K3JGN': 'Unknown',
                'C093RUL2N3C': 'Unknown',
                'C07HY03NX4N': 'Unknown',
                'C08PNJCKDV1': 'Unknown'
            }
            
            # Check each problematic channel with Bot 1's token
            bot_token = os.environ.get("SLACK_BOT_TOKEN")
            if bot_token:
                headers = {
                    "Authorization": f"Bearer {bot_token}",
                    "Content-Type": "application/json"
                }
                
                import requests
                for channel_id in problem_channels.keys():
                    try:
                        response = requests.get(
                            "https://slack.com/api/conversations.info",
                            headers=headers,
                            params={"channel": channel_id}
                        )
                        data = response.json()
                        
                        if not data.get("ok"):
                            error = data.get("error", "unknown_error")
                            logger.warning(f"MISSING CHANNEL: {channel_id} - Error: {error}")
                            print(f"  ❌ {channel_id}: {error}")
                        else:
                            channel = data.get("channel", {})
                            if channel.get("is_archived"):
                                logger.warning(f"ARCHIVED CHANNEL: {channel_id} - #{channel.get('name', 'unknown')}")
                                print(f"  📦 {channel_id}: #{channel.get('name', 'unknown')} (archived)")
                    except Exception as e:
                        logger.warning(f"Could not check {channel_id}: {e}")
                        
            # Now check all assigned channels
            logger.info("Running comprehensive channel check...")
            
            # Set environment variable for auto-cleanup
            os.environ["AUTO_CLEANUP"] = "true"
            
            # Import and run the checker
            sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'scripts'))
            from check_missing_channels import MissingChannelChecker
            
            checker = MissingChannelChecker()
            results = checker.check_missing_channels()
            
            if results:
                summary = results["summary"]
                if summary["missing_count"] > 0:
                    logger.warning(f"Found {summary['missing_count']} total missing/inaccessible channels")
                    print(f"\n📊 SUMMARY: {summary['missing_count']} channels not found")
                    
                    # Log ALL missing channel IDs clearly
                    print("\nMISSING CHANNELS LIST:")
                    for channel_id, info in results["missing"].items():
                        name = info.get("historical_name", "Unknown")
                        error = info['error']
                        print(f"  {channel_id} - #{name} - {error}")
                        logger.warning(f"Missing channel will be removed: {channel_id} (#{name})")
                    
                    # Auto-remove missing channels
                    checker.remove_missing_channels(results)
                    
                    # Reload channel assignments
                    self.multi_bot_manager.load_channel_assignments()
                    logger.info("Channel assignments updated - removed missing channels")
                    
                if summary["archived_count"] > 0:
                    logger.warning(f"Found {summary['archived_count']} archived channels (removed)")
                    
                logger.info(f"Active channels: {summary['active_count']}/{summary['total_assigned']}")
                
            print("=" * 80 + "\n")
                
        except Exception as e:
            logger.error(f"Error checking missing channels: {e}")
            import traceback
            traceback.print_exc()
            # Continue anyway - this is not critical

    def start_worker(self, worker_count: int = 1):
        """Start the forwarder worker(s) in separate process(es)"""
        if self.worker_process and self.worker_process.is_alive():
            return
        # For now, start a single worker; can be extended to multiple if needed
        self.worker_process = multiprocessing.Process(
            target=run_worker_process,
            name="ForwarderWorker",
            daemon=False
        )
        self.worker_process.start()

    def start_all_bots(self):
        """Start forwarder worker then all configured bots"""
        logger.info("Starting forwarder worker and bots...")
        
        # Check for missing channels first
        self.check_missing_channels()

        self.running = True

        # Start the worker first so it can consume jobs immediately
        try:
            worker_count = int(os.environ.get("FORWARDER_WORKER_COUNT", "1"))
        except Exception:
            worker_count = 1
        self.start_worker(worker_count=worker_count)

        # Start each bot in its own process
        for bot_id, bot_runner in self.bot_runners.items():
            try:
                bot_runner.start()
                time.sleep(2)  # Small delay between bot starts
            except Exception as e:
                logger.error(f"[ERROR] Failed to start Bot-{bot_id}: {e}")

        
        # Log the assignment distribution
        self.multi_bot_manager.log_assignment_stats()
        
        return True
    
    def monitor_bots(self):
        """Monitor bot health and restart if needed"""

        while self.running:
            try:
                # Check each bot's health
                for bot_id, bot_runner in self.bot_runners.items():
                    if not bot_runner.is_alive() and self.running:
                        logger.warning(f"Bot-{bot_id} stopped. Restarting...")
                        try:
                            bot_runner.start()
                            time.sleep(5)  # Give it time to start
                        except Exception as e:
                            logger.error(f"[ERROR] Failed to restart Bot-{bot_id}: {e}")

                # Check worker health
                if self.worker_process and not self.worker_process.is_alive() and self.running:
                    logger.warning("Forwarder Worker stopped. Restarting...")
                    try:
                        self.start_worker()
                        time.sleep(5)
                    except Exception as e:
                        logger.error(f"[ERROR] Failed to restart Forwarder Worker: {e}")

                # Sleep for 30 seconds before next health check
                time.sleep(30)

            except KeyboardInterrupt:
                break
            except Exception as e:
                logger.error(f"[ERROR] Error in bot monitoring: {e}")
                time.sleep(10)  # Wait before retrying
    
    def stop_all_bots(self):
        """Stop all bots gracefully"""
        logger.info("Stopping all bots...")

        self.running = False

        # Terminate all bot processes
        for bot_id, bot_runner in self.bot_runners.items():
            if bot_runner.is_alive():
                bot_runner.terminate()

        # Terminate worker
        if self.worker_process and self.worker_process.is_alive():
            self.worker_process.terminate()
            self.worker_process.join(timeout=5)

        # Wait for all bots to finish (with timeout)
        for bot_id, bot_runner in self.bot_runners.items():
            bot_runner.join(timeout=5)  # 5 second timeout per bot

            if bot_runner.is_alive():
                logger.warning(f"Bot-{bot_id} did not stop gracefully")
            else:
                pass  # Bot stopped gracefully

        # Confirm worker stop
        if self.worker_process and self.worker_process.is_alive():
            logger.warning("Forwarder Worker did not stop gracefully")
        else:
            pass  # Worker stopped gracefully

    
    def run(self):
        """Run the multi-bot system"""
        try:
            # Start all bots
            if not self.start_all_bots():
                logger.error("[ERROR] Failed to start bots")
                return False

            # Start monitoring in a separate thread
            monitor_thread = threading.Thread(
                target=self.monitor_bots,
                name="BotMonitor",
                daemon=True
            )
            monitor_thread.start()

            # Main loop - just wait and handle interrupts
            logger.info("Multi-bot system running. Press Ctrl+C to stop.")

            while self.running:
                # Show status every 60 seconds
                alive_count = sum(1 for runner in self.bot_runners.values() if runner.is_alive())
                total_count = len(self.bot_runners)

                if alive_count < total_count:
                    logger.info(f"Status: {alive_count}/{total_count} bots running")

                # List running bots
                for bot_id, bot_runner in self.bot_runners.items():
                    status = "[RUNNING]" if bot_runner.is_alive() else "[STOPPED]"
                    if status == "[STOPPED]":
                        logger.warning(f"Bot-{bot_id}: {status}")

                time.sleep(60)  # Status update every minute

        except KeyboardInterrupt:
            pass  # Clean shutdown on Ctrl+C
        except Exception as e:
            logger.error(f"[ERROR] Error in multi-bot system: {e}")
            logger.exception("Full error details:")
        finally:
            self.stop_all_bots()
        
        return True

def print_startup_banner():
    """Print a nice startup banner"""
    print("=" * 80)
    print("[BOT] MULTI-BOT SLACK FORWARDING SYSTEM")
    print("=" * 80)
    print(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("Features:")
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
            print("[ERROR] No bot configurations found!")
            print("[INFO] Please check your environment variables:")
            print("   • SLACK_BOT_TOKEN and SLACK_APP_TOKEN")
            print("   • SLACK_BOT_TOKEN_2 and SLACK_APP_TOKEN_2")
            print("   • etc.")
            return False

        success = launcher.run()

        if success:
            print("\n[OK] Multi-bot system completed successfully!")
        else:
            print("\n[ERROR] Multi-bot system failed!")

        return success

    except Exception as e:
        logger.error(f"[ERROR] Fatal error: {e}")
        logger.exception("Full error details:")
        return False

if __name__ == "__main__":
    # Required for multiprocessing on Windows
    multiprocessing.freeze_support()
    success = main()
    sys.exit(0 if success else 1)
