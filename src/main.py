import logging
import random
from src.config import Config
from src.scheduler import SMSScheduler
from src.models import Message
from src.api import SchedulerAPI

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def send(message: Message) -> bool:
    """
    Mock SMS send function for testing (provided and thread-safe).

    Returns True with 30% probability to amplify chance of failure over six tries (~11%).
    """
    success_rate = 0.3
    success = random.random() < success_rate

    if success:
        logger.info(f"✓ SMS sent successfully! id: {message.message_id}")
    else:
        logger.warning(f"✗ SMS send failed! id: {message.message_id}")

    return success


def main():
    """Main application entry point"""
    logger.info("Starting SMS Retry Scheduler...")

    # Load configuration
    config = Config.from_env()

    # Create scheduler with mock send function
    scheduler = SMSScheduler(config, send)

    # Create API
    api = SchedulerAPI(scheduler, config)

    # Start scheduler
    scheduler.start()

    logger.info(f"API server starting on {config.API_HOST}:{config.API_PORT}")
    logger.info(f"Web UI available at http://localhost:{config.API_PORT}")

    # Run API server (blocking)
    api.run()


if __name__ == '__main__':
    main()