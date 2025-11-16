from src.main import main
from src.api import SchedulerAPI
from src.config import Config
from src.scheduler import SMSScheduler
from src.main import send

# Build the full application exactly like main(), but WITHOUT calling app.run()
config = Config.from_env()
scheduler = SMSScheduler(config, send)
api = SchedulerAPI(scheduler, config)

# Start scheduler thread
scheduler.start()

# Gunicorn needs 'app'
app = api.app
