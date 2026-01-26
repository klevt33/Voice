# topic_router.py
import logging
import queue
from typing import Dict

from TopicsUI import Topic
from managers import StateManager, ServiceManager

logger = logging.getLogger(__name__)

class TopicRouter:
    """
    Routes transcribed topics to the UI or the browser based on the auto-submit mode.
    """
    def __init__(self, state_manager: StateManager, service_manager: ServiceManager, ui_controller):
        self.state_manager = state_manager
        self.service_manager = service_manager
        self.ui_controller = ui_controller

    def route_topic(self, topic: Topic):
        should_auto_submit = (
            self.state_manager.auto_submit_mode == "All" or
            (self.state_manager.auto_submit_mode == "Others" and topic.source == "OTHERS")
        )

        if should_auto_submit:
            self._route_to_browser(topic)
        else:
            self._route_to_ui(topic)

    def _route_to_browser(self, topic: Topic):
        # First add the topic to the UI so it's visible and recoverable
        self._route_to_ui(topic)
        
        # Mark the topic as auto-submitted (will appear grayed out)
        # We need to do this after a short delay to ensure the topic is processed by the UI queue
        import threading
        def mark_submitted():
            import time
            time.sleep(0.1)  # Small delay to ensure topic is added to UI
            self.ui_controller.mark_topic_as_auto_submitted(topic)
        
        threading.Thread(target=mark_submitted, daemon=True).start()
        
        if self.service_manager.browser_manager:
            submission_content = f"[{topic.source}] {topic.text}"
            browser_payload = {
                'content': submission_content,
                'topic_objects': [topic]  # Include the topic object for recovery and UI updates
            }
            self.service_manager.browser_manager.browser_queue.put(browser_payload)
            logger.info(f"AUTO-SUBMIT to browser: {submission_content[:50]}...")
        else:
            logger.warning("Cannot auto-submit, browser_manager not available.")

    def _route_to_ui(self, topic: Topic):
        self.ui_controller.add_topic_to_queue(topic)
        logger.info(f"ROUTED to UI: [{topic.source}] {topic.text[:50]}...")
