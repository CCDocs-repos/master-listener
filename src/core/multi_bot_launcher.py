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
        
        logger.info(f"[START] Starting {bot_name} in separate process...")
        logger.info(f"   • Bot ID: {bot_id}")
        logger.info(f"   • Bot Token: {bot_token[:12]}...")
        logger.info(f"   • App Token: {app_token[:12]}...")
        logger.info(f"   • Process ID: {os.getpid()}")

        # Import and run the Redis-based listener (enqueue-only)
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
        from core import listener_redis as listener

        # Run the main function
        listener.main()

    except KeyboardInterrupt:
        logger.info(f"[STOP] {bot_name} interrupted by user")
    except Exception as e:
        logger.error(f"[ERROR] Error in {bot_name}: {e}")
        import traceback
        traceback.print_exc()
    finally:
        logger.info(f"[END] {bot_name} stopped")


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

        logger.info("[START] Starting Forwarder Worker process...")
        logger.info(f"   • Process ID: {os.getpid()}")

        # Import and run the forwarder worker
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
        from core import forwarder_worker

        forwarder_worker.main()

    except KeyboardInterrupt:
        logger.info("[STOP] Forwarder Worker interrupted by user")
    except Exception as e:
        logger.error(f"[ERROR] Error in Forwarder Worker: {e}")
        import traceback
        traceback.print_exc()
    finally:
        logger.info("[END] Forwarder Worker stopped")


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
            logger.warning(f"[WARN] {self.bot_config.name} is already running")
            return

        self.running = True
        self.process = multiprocessing.Process(
            target=run_bot_process,
            args=(self.bot_id, self.bot_config.bot_token, self.bot_config.app_token, self.bot_config.name),
            name=f"Bot-{self.bot_id}",
            daemon=False  # Don't make daemon so we can wait for clean shutdown
        )
        self.process.start()
        logger.info(f"[OK] {self.bot_config.name} process started (PID: {self.process.pid})")
    
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
        
        logger.info("[BOT] Multi-Bot Launcher initialized")
        logger.info(f"   • Total bots configured: {len(self.multi_bot_manager.bot_configs)}")

        # Create bot runners for each configured bot
        for bot_id, bot_config in self.multi_bot_manager.bot_configs.items():
            self.bot_runners[bot_id] = BotRunner(bot_id, bot_config)

    def start_worker(self, worker_count: int = 1):
        """Start the forwarder worker(s) in separate process(es)"""
        if self.worker_process and self.worker_process.is_alive():
            logger.info("[OK] Forwarder Worker already running")
            return
        # For now, start a single worker; can be extended to multiple if needed
        self.worker_process = multiprocessing.Process(
            target=run_worker_process,
            name="ForwarderWorker",
            daemon=False
        )
        self.worker_process.start()
        logger.info(f"[OK] Forwarder Worker process started (PID: {self.worker_process.pid})")

    def start_all_bots(self):
        """Start forwarder worker then all configured bots"""
        logger.info("[START] Starting forwarder worker and all bots...")
        logger.info("=" * 60)

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

        logger.info("=" * 60)
        logger.info("[OK] Forwarder worker and all bots started!")
        
        # Log the assignment distribution
        self.multi_bot_manager.log_assignment_stats()
        
        return True
    
    def monitor_bots(self):
        """Monitor bot health and restart if needed"""
        logger.info("[MONITOR] Starting bot monitoring...")

        while self.running:
            try:
                # Check each bot's health
                for bot_id, bot_runner in self.bot_runners.items():
                    if not bot_runner.is_alive() and self.running:
                        logger.warning(f"[WARN] Bot-{bot_id} appears to have stopped. Attempting restart...")
                        try:
                            bot_runner.start()
                            time.sleep(5)  # Give it time to start
                        except Exception as e:
                            logger.error(f"[ERROR] Failed to restart Bot-{bot_id}: {e}")

                # Check worker health
                if self.worker_process and not self.worker_process.is_alive() and self.running:
                    logger.warning("[WARN] Forwarder Worker appears to have stopped. Attempting restart...")
                    try:
                        self.start_worker()
                        time.sleep(5)
                    except Exception as e:
                        logger.error(f"[ERROR] Failed to restart Forwarder Worker: {e}")

                # Sleep for 30 seconds before next health check
                time.sleep(30)

            except KeyboardInterrupt:
                logger.info("[STOP] Bot monitoring interrupted")
                break
            except Exception as e:
                logger.error(f"[ERROR] Error in bot monitoring: {e}")
                time.sleep(10)  # Wait before retrying
    
    def stop_all_bots(self):
        """Stop all bots gracefully"""
        logger.info("[STOP] Stopping all bots...")

        self.running = False

        # Terminate all bot processes
        for bot_id, bot_runner in self.bot_runners.items():
            if bot_runner.is_alive():
                logger.info(f"[STOP] Terminating Bot-{bot_id}...")
                bot_runner.terminate()

        # Terminate worker
        if self.worker_process and self.worker_process.is_alive():
            logger.info("[STOP] Terminating Forwarder Worker...")
            self.worker_process.terminate()
            self.worker_process.join(timeout=5)

        # Wait for all bots to finish (with timeout)
        for bot_id, bot_runner in self.bot_runners.items():
            logger.info(f"[WAIT] Waiting for Bot-{bot_id} to stop...")
            bot_runner.join(timeout=5)  # 5 second timeout per bot

            if bot_runner.is_alive():
                logger.warning(f"[WARN] Bot-{bot_id} did not stop gracefully")
            else:
                logger.info(f"[OK] Bot-{bot_id} stopped")

        # Confirm worker stop
        if self.worker_process and self.worker_process.is_alive():
            logger.warning("[WARN] Forwarder Worker did not stop gracefully")
        else:
            logger.info("[OK] Forwarder Worker stopped")

        logger.info("[END] All bots and worker stopped")
    
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
            logger.info("[RUNNING] Multi-bot system running. Press Ctrl+C to stop.")
            logger.info("[STATUS] Bot Status:")

            while self.running:
                # Show status every 60 seconds
                alive_count = sum(1 for runner in self.bot_runners.values() if runner.is_alive())
                total_count = len(self.bot_runners)

                logger.info(f"[HEARTBEAT] {alive_count}/{total_count} bots running")

                # List running bots
                for bot_id, bot_runner in self.bot_runners.items():
                    status = "[RUNNING]" if bot_runner.is_alive() else "[STOPPED]"
                    logger.info(f"   • Bot-{bot_id}: {status}")

                time.sleep(60)  # Status update every minute

        except KeyboardInterrupt:
            logger.info("[STOP] Received interrupt signal")
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
