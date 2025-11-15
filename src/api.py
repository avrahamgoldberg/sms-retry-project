from flask import Flask, request, jsonify, render_template
import logging
import uuid
from src.models import Message
from src.scheduler import SMSScheduler

logger = logging.getLogger(__name__)


class SchedulerAPI:
    """Web API and UI for SMS Scheduler"""

    def __init__(self, scheduler: SMSScheduler, config):
        self.scheduler = scheduler
        self.config = config
        self.app = Flask(__name__)
        self._setup_routes()

    def _setup_routes(self):
        """Setup Flask routes"""

        @self.app.route('/')
        def index():
            """Simple web UI"""
            # return render_template_string(HTML_TEMPLATE)
            return render_template('index.html')


        @self.app.route('/api/start', methods=['POST'])
        def start():
            """Start the scheduler"""
            try:
                self.scheduler.start()
                return jsonify({'status': 'success', 'message': 'Scheduler started'})
            except Exception as e:
                logger.error(f"Failed to start scheduler: {e}")
                return jsonify({'status': 'error', 'message': str(e)}), 500

        @self.app.route('/api/stop', methods=['POST'])
        def stop():
            """Stop the scheduler"""
            try:
                self.scheduler.stop()
                return jsonify({'status': 'success', 'message': 'Scheduler stopped'})
            except Exception as e:
                logger.error(f"Failed to stop scheduler: {e}")
                return jsonify({'status': 'error', 'message': str(e)}), 500

        @self.app.route('/api/send', methods=['POST'])
        def send_single():
            """Send a single message"""
            try:
                data = request.json
                message = Message(
                    message_id=str(uuid.uuid4()),
                    content=data['content'],
                    metadata=data.get('metadata')
                )
                self.scheduler.newMessage(message)
                return jsonify({
                    'status': 'success',
                    'message_id': message.message_id
                })
            except Exception as e:
                logger.error(f"Failed to send message: {e}")
                return jsonify({'status': 'error', 'message': str(e)}), 400

        @self.app.route('/api/send-bulk', methods=['POST'])
        def send_bulk():
            """Send N copies of the same message"""
            try:
                data = request.json
                count = data.get('count', 1)
                message_ids = []

                for i in range(count):
                    message = Message(
                        message_id=str(uuid.uuid4()),
                        content=data['content'],
                        metadata={'bulk_index': i, **(data.get('metadata', {}))}
                    )
                    self.scheduler.newMessage(message)
                    message_ids.append(message.message_id)

                return jsonify({
                    'status': 'success',
                    'count': count,
                    'message_ids': message_ids
                })
            except Exception as e:
                logger.error(f"Failed to send bulk messages: {e}")
                return jsonify({'status': 'error', 'message': str(e)}), 400

        @self.app.route('/api/stats', methods=['GET'])
        def get_stats():
            """Get scheduler statistics"""
            return jsonify(self.scheduler.get_stats())

        @self.app.route('/api/success', methods=['GET'])
        def get_success():
            """Get recent successful messages"""
            limit = request.args.get('limit', 100, type=int)
            messages = self.scheduler.get_recent_success(limit)
            return jsonify({'count': len(messages), 'messages': messages})

        @self.app.route('/api/failed', methods=['GET'])
        def get_failed():
            """Get recent failed messages"""
            limit = request.args.get('limit', 100, type=int)
            messages = self.scheduler.get_recent_failed(limit)
            return jsonify({'count': len(messages), 'messages': messages})

        @self.app.route('/api/config', methods=['GET', 'POST'])
        def manage_config():
            """Get or update S3 configuration"""
            if request.method == 'GET':
                return jsonify({
                    's3_bucket': self.config.S3_BUCKET,
                    's3_state_prefix': self.config.S3_STATE_PREFIX,
                    's3_success_prefix': self.config.S3_SUCCESS_PREFIX,
                    's3_failed_prefix': self.config.S3_FAILED_PREFIX
                })
            else:
                # Update config (Note: requires restart to take effect)
                data = request.json
                return jsonify({
                    'status': 'success',
                    'message': 'Config update requires restart'
                })

        @self.app.route('/health', methods=['GET'])
        def health():
            """Health check endpoint"""
            return jsonify({
                'status': 'healthy',
                'scheduler_running': self.scheduler.running
            })

    def run(self):
        """Run the Flask app"""
        self.app.run(
            host=self.config.API_HOST,
            port=self.config.API_PORT,
            debug=False,
            threaded=True
        )
