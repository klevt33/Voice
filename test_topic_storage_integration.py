# test_topic_storage_integration.py
import unittest
import tempfile
import shutil
import os
import time
from datetime import datetime
from unittest.mock import patch, MagicMock

# Import the classes we need to test
from topic_storage import TopicStorageManager
from TopicsUI import Topic

class TestTopicStorageIntegration(unittest.TestCase):
    """Integration tests for topic storage functionality."""
    
    def setUp(self):
        """Set up test fixtures before each test method."""
        # Create temporary directory for testing
        self.test_dir = tempfile.mkdtemp()
        self.storage_manager = TopicStorageManager(self.test_dir)
    
    def tearDown(self):
        """Clean up after each test method."""
        # Clean up temporary directory
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)
    
    def test_complete_session_workflow(self):
        """Test complete workflow from session start to end with topics."""
        # Start session
        self.assertTrue(self.storage_manager.start_session())
        
        # Create and store multiple topics
        topics = [
            Topic("Hello world", datetime(2024, 1, 15, 14, 30, 25), "ME"),
            Topic("How are you?", datetime(2024, 1, 15, 14, 30, 30), "OTHERS"),
            Topic("I'm doing well", datetime(2024, 1, 15, 14, 30, 35), "ME"),
        ]
        
        for topic in topics:
            self.assertTrue(self.storage_manager.store_topic(topic))
        
        # End session
        self.storage_manager.end_session()
        
        # Verify file exists and contains expected content
        files = os.listdir(self.test_dir)
        self.assertEqual(len(files), 1)
        
        file_path = os.path.join(self.test_dir, files[0])
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check session markers
        self.assertIn("=== AUDIO SESSION STARTED:", content)
        self.assertIn("=== AUDIO SESSION ENDED:", content)
        self.assertIn("=== TOPICS CAPTURED: 3 ===", content)
        
        # Check topic content
        self.assertIn("[14:30] [ME] Hello world", content)
        self.assertIn("[14:30] [OTHERS] How are you?", content)
        self.assertIn("[14:30] [ME] I'm doing well", content)
    
    def test_multiple_sessions_create_separate_files(self):
        """Test that multiple sessions create separate files."""
        # First session
        self.storage_manager.start_session()
        topic1 = Topic("First session topic", datetime.now(), "ME")
        self.storage_manager.store_topic(topic1)
        self.storage_manager.end_session()
        
        # Small delay to ensure different timestamps
        time.sleep(0.1)
        
        # Second session
        self.storage_manager.start_session()
        topic2 = Topic("Second session topic", datetime.now(), "OTHERS")
        self.storage_manager.store_topic(topic2)
        self.storage_manager.end_session()
        
        # Should have two files
        files = os.listdir(self.test_dir)
        self.assertEqual(len(files), 2)
        
        # Each file should contain only its respective topic
        for file_name in files:
            file_path = os.path.join(self.test_dir, file_name)
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Each file should have session markers
            self.assertIn("=== AUDIO SESSION STARTED:", content)
            self.assertIn("=== AUDIO SESSION ENDED:", content)
            
            # Check that each file contains only one topic
            if "First session topic" in content:
                self.assertNotIn("Second session topic", content)
                self.assertIn("=== TOPICS CAPTURED: 1 ===", content)
            else:
                self.assertIn("Second session topic", content)
                self.assertNotIn("First session topic", content)
                self.assertIn("=== TOPICS CAPTURED: 1 ===", content)
    
    def test_topics_independent_of_ui_interactions(self):
        """Test that stored topics are independent of UI interactions."""
        # Start session and store topics
        self.storage_manager.start_session()
        
        topics = [
            Topic("Topic to be submitted", datetime.now(), "ME"),
            Topic("Topic to be deleted", datetime.now(), "OTHERS"),
            Topic("Topic to be copied", datetime.now(), "ME"),
        ]
        
        for topic in topics:
            self.storage_manager.store_topic(topic)
        
        # Simulate UI interactions by modifying topic states
        topics[0].submitted = True  # Simulate submission
        topics[1].selected = True   # Simulate selection for deletion
        # Topic 2 remains unchanged (simulate copy operation)
        
        # End session
        self.storage_manager.end_session()
        
        # Verify all topics are still in the file regardless of UI state
        files = os.listdir(self.test_dir)
        file_path = os.path.join(self.test_dir, files[0])
        
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # All topics should be present regardless of their UI state
        self.assertIn("Topic to be submitted", content)
        self.assertIn("Topic to be deleted", content)
        self.assertIn("Topic to be copied", content)
        self.assertIn("=== TOPICS CAPTURED: 3 ===", content)
    
    def test_error_recovery_directory_creation(self):
        """Test error recovery when directory doesn't exist."""
        # Use non-existent directory
        non_existent_dir = os.path.join(self.test_dir, "nested", "path", "that", "does", "not", "exist")
        manager = TopicStorageManager(non_existent_dir)
        
        # Should create directory and start session successfully
        self.assertTrue(manager.start_session())
        self.assertTrue(os.path.exists(non_existent_dir))
        
        # Should be able to store topics
        topic = Topic("Test topic", datetime.now(), "ME")
        self.assertTrue(manager.store_topic(topic))
        
        manager.end_session()
    
    def test_graceful_degradation_on_storage_failure(self):
        """Test that storage failures don't interrupt normal operation."""
        # Start session normally
        self.storage_manager.start_session()
        
        # Simulate storage failure by closing the file handle
        if self.storage_manager.current_session:
            self.storage_manager.current_session.file_handle.close()
            self.storage_manager.current_session.file_handle = None
        
        # Storing topic should fail gracefully
        topic = Topic("Test topic", datetime.now(), "ME")
        result = self.storage_manager.store_topic(topic)
        self.assertFalse(result)  # Should return False but not crash
        
        # End session should also handle the error gracefully
        self.storage_manager.end_session()  # Should not raise exception
    
    def test_session_statistics_accuracy(self):
        """Test that session statistics are accurate."""
        self.storage_manager.start_session()
        
        # Store known number of topics
        num_topics = 5
        for i in range(num_topics):
            topic = Topic(f"Topic {i+1}", datetime.now(), "ME" if i % 2 == 0 else "OTHERS")
            self.storage_manager.store_topic(topic)
        
        self.storage_manager.end_session()
        
        # Check statistics in file
        files = os.listdir(self.test_dir)
        file_path = os.path.join(self.test_dir, files[0])
        
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        self.assertIn(f"=== TOPICS CAPTURED: {num_topics} ===", content)
    
    def test_filename_uniqueness_across_sessions(self):
        """Test that filenames are unique even with rapid session cycling."""
        file_names = set()
        
        # Create multiple sessions rapidly
        for i in range(3):
            self.storage_manager.start_session()
            topic = Topic(f"Topic {i}", datetime.now(), "ME")
            self.storage_manager.store_topic(topic)
            
            # Capture filename before ending session
            if self.storage_manager.current_session:
                file_names.add(os.path.basename(self.storage_manager.current_session.file_path))
            
            self.storage_manager.end_session()
            time.sleep(0.01)  # Small delay to ensure different timestamps
        
        # All filenames should be unique
        self.assertEqual(len(file_names), 3)
        
        # All files should exist
        actual_files = set(os.listdir(self.test_dir))
        self.assertEqual(file_names, actual_files)

if __name__ == '__main__':
    unittest.main()