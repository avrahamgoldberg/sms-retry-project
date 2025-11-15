import threading
import time
import logging
import heapq
from typing import Dict, List, Callable
from src.models import Message, MessageState, MessageStatus
from src.persistence import S3PersistenceLayer
from src.config import Config

logger = logging.getLogger(__name__)


class SMSScheduler:
    """
    Thread-safe SMS retry scheduler with S3 persistence.

    Architecture:
    - Priority queue (min-heap) for efficient time-based scheduling
    - ReentrantLock for thread safety between newMessage() and wakeup()
    - Bounded work per wakeup() tick (only process due messages)
    """

    def __init__(self, config: Config, send_function: Callable[[Message], bool]):
        self.config = config
        self.send_function = send_function
        self.persistence = S3PersistenceLayer(config)

        # Priority queue: (next_retry_at, message_id)
        self.retry_heap: List[tuple] = []

        # Fast lookup: message_id -> MessageState
        self.message_map: Dict[str, MessageState] = {}

        # Thread synchronization
        self.lock = threading.RLock()

        # Control flags
        self.running = False
        self.wakeup_thread = None

        # Statistics
        self.stats = {
            'total_messages': 0,
            'total_success': 0,
            'total_failed': 0,
            'in_progress': 0
        }

        logger.info("SMS Scheduler initialized")

    def start(self):
        """Start the scheduler and wakeup timer"""
        with self.lock:
            if self.running:
                logger.warning("Scheduler already running")
                return

            # Recover state from S3
            self._recover_from_s3()

            self.running = True
            self.wakeup_thread = threading.Thread(target=self._wakeup_loop, daemon=True)
            self.wakeup_thread.start()
            logger.info("Scheduler started")

    def stop(self):
        """Stop the scheduler"""
        with self.lock:
            self.running = False
            if self.wakeup_thread:
                self.wakeup_thread.join(timeout=2)
            logger.info("Scheduler stopped")

    def _recover_from_s3(self):
        """Recover pending messages from S3 on startup"""
        logger.info("Recovering state from S3...")
        pending_states = self.persistence.load_all_pending_states()

        current_time = time.time()
        for state in pending_states:
            # Adjust the next retry time if it's in the past
            if state.next_retry_at < current_time:
                state.next_retry_at = current_time

            self.message_map[state.message_id] = state
            heapq.heappush(self.retry_heap, (state.next_retry_at, state.message_id))

        self.stats['in_progress'] = len(pending_states)
        logger.info(f"Recovered {len(pending_states)} pending messages")

    def newMessage(self, message: Message):
        """
        Handle new message arrival (called by external system).
        Thread-safe, can be called concurrently with wakeup().
        """
        with self.lock:
            current_time = time.time()

            # Create initial state
            state = MessageState(
                message_id=message.message_id,
                message=message,
                attempt_count=0,
                next_retry_at=current_time,  # Immediate first attempt
                status=MessageStatus.PENDING,
                created_at=current_time,
                updated_at=current_time
            )

            self.message_map[message.message_id] = state
            self.stats['total_messages'] += 1
            self.stats['in_progress'] += 1

            logger.info(f"New message received: {message.message_id}")

            # Attempt immediate send (attempt 0)
            success = self._attempt_send(state)

            if success:
                self._handle_success(state)
            else:
                # Schedule first retry (0.5s from now)
                self._schedule_next_retry(state)

    def wakeup(self):
        """
        Process messages due for retry (called every 500ms).
        Thread-safe, bounded work per tick.
        """
        with self.lock:
            if not self.running:
                return

            current_time = time.time()
            processed_count = 0

            # Process all messages due now (bounded by heap top)
            while self.retry_heap:
                next_time, message_id = self.retry_heap[0]

                # Stop if the next message is not due yet
                if next_time > current_time:
                    break

                # Pop from heap
                heapq.heappop(self.retry_heap)

                # Check if the message still exists (might have been completed)
                if message_id not in self.message_map:
                    continue

                state = self.message_map[message_id]

                # Double-check it's still pending
                if state.status != MessageStatus.PENDING:
                    continue

                # Attempt send
                success = self._attempt_send(state)

                if success:
                    self._handle_success(state)
                else:
                    # Check if max attempts reached
                    if state.attempt_count >= MessageState.MAX_ATTEMPTS:
                        self._handle_failure(state)
                    else:
                        self._schedule_next_retry(state)

                processed_count += 1

            if processed_count > 0:
                logger.debug(f"Wakeup processed {processed_count} messages")

    def _wakeup_loop(self):
        """Background thread that calls wakeup() every 500ms"""
        logger.info("Wakeup loop started")
        while self.running:
            try:
                self.wakeup()
                time.sleep(0.5)  # 500ms tick
            except Exception as e:
                logger.error(f"Error in wakeup loop: {e}", exc_info=True)
        logger.info("Wakeup loop stopped")

    def _attempt_send(self, state: MessageState) -> bool:
        """
        Attempt to send message using provided send function.
        Returns True if successful, False otherwise.
        """
        try:
            logger.info(
                f"Attempting send for {state.message_id} (attempt {state.attempt_count + 1}/{MessageState.MAX_ATTEMPTS})")

            success = self.send_function(state.message)

            state.attempt_count += 1
            state.updated_at = time.time()

            return success
        except Exception as e:
            logger.error(f"Error sending message {state.message_id}: {e}")
            state.attempt_count += 1
            state.updated_at = time.time()
            return False

    def _schedule_next_retry(self, state: MessageState):
        """Schedule next retry attempt"""
        if state.attempt_count >= len(MessageState.RETRY_SCHEDULE):
            logger.error(f"No more retries for {state.message_id}")
            return

        delay = MessageState.RETRY_SCHEDULE[state.attempt_count]
        state.next_retry_at = state.created_at + delay

        # Add to heap
        heapq.heappush(self.retry_heap, (state.next_retry_at, state.message_id))

        # Persist to S3
        try:
            self.persistence.save_message_state(state)
        except Exception as e:
            logger.error(f"Failed to persist state for {state.message_id}: {e}")

        logger.debug(f"Scheduled retry for {state.message_id} at {state.next_retry_at} (delay: {delay}s)")

    def _handle_success(self, state: MessageState):
        """Handle successful message delivery"""
        state.status = MessageStatus.SUCCESS
        state.updated_at = time.time()

        # Remove from tracking
        del self.message_map[state.message_id]

        # Update stats
        self.stats['total_success'] += 1
        self.stats['in_progress'] -= 1

        # Persist to S3
        try:
            self.persistence.mark_success(state.message_id, state)
        except Exception as e:
            logger.error(f"Failed to persist success for {state.message_id}: {e}")

        logger.info(f"✓ Message {state.message_id} sent successfully after {state.attempt_count} attempts")

    def _handle_failure(self, state: MessageState):
        """Handle message failure after max retries"""
        state.status = MessageStatus.FAILED_MAX_RETRIES
        state.updated_at = time.time()

        # Remove from tracking
        del self.message_map[state.message_id]

        # Update stats
        self.stats['total_failed'] += 1
        self.stats['in_progress'] -= 1

        # Persist to S3
        try:
            self.persistence.mark_failed(state.message_id, state)
        except Exception as e:
            logger.error(f"Failed to persist failure for {state.message_id}: {e}")

        logger.warning(f"✗ Message {state.message_id} failed after {MessageState.MAX_ATTEMPTS} attempts")

    def get_stats(self) -> dict:
        """Get current statistics"""
        with self.lock:
            return self.stats.copy()

    def get_recent_success(self, limit: int = 100) -> List[dict]:
        """Get recent successful messages"""
        return self.persistence.get_recent_success(limit)

    def get_recent_failed(self, limit: int = 100) -> List[dict]:
        """Get recent failed messages"""
        return self.persistence.get_recent_failed(limit)