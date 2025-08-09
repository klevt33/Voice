# test_topic_storage.py
import unittest
import tempfile
import shutil
import os
from datetime import datetime
from unittest.mock import patch, MagicMock
from dataclasses import dataclass

from topic_storage import TopicStorageManager

@dataclass
class MockTopic:
    """Mock Topic class for testing."""
    text: str
    timestamp: datetime
    source: str

class TestTopicStorageManager(unittest.TestCase):
    """Unit tests for TopicStorageManager class."""
    
    def setUp(self):
        """Set up test fixtures before each test method."""
        # Create temporary directory for testing
        self.test_dir = tempfile.mkdtemp()
        self.storage_manager = TopicStorageManager(self.test_dir)
        
        # Create mock topic
        self.mock_topic = MockTopic(
            text="Test topic content",
            timestamp=datetime(2024, 1, 15, 14, 30, 25),
            source="ME"
        )
    
    def tearDown(self):
        """Clean up after each test method."""
        # Ensure any active session is properly closed
        if hasattr(self, 'storage_manager') and self.storage_manager.current_session:
            self.storage_manager.end_session()
        
        # Clean up temporary directory
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)
    
    def test_init(self):
        """Test TopicStorageManager initialization."""
        manager = TopicStorageManager("/test/path")
        self.assertEqual(manager.storage_folder, "/test/path")
        self.assertIsNone(manager.current_session)
    
    def test_ensure_storage_directory_creates_directory(self):
        """Test that _ensure_storage_directory creates missing directory."""
        # Remove the test directory
        shutil.rmtree(self.test_dir)
        self.assertFalse(os.path.exists(self.test_dir))
        
        # Method should create the directory
        result = self.storage_manager._ensure_storage_directory()
        self.assertTrue(result)
        self.assertTrue(os.path.exists(self.test_dir))
    
    def test_ensure_storage_directory_existing_directory(self):
        """Test that _ensure_storage_directory works with existing directory."""
        # Directory already exists from setUp
        result = self.storage_manager._ensure_storage_directory()
        self.assertTrue(result)
        self.assertTrue(os.path.exists(self.test_dir))
    
    def test_ensure_storage_directory_empty_path(self):
        """Test that _ensure_storage_directory handles empty path."""
        manager = TopicStorageManager("")
        result = manager._ensure_storage_directory()
        self.assertFalse(result)
    
    @patch('topic_storage.datetime')
    def test_generate_filename_basic(self, mock_datetime):
        """Test basic filename generation."""
        # Mock datetime to return predictable timestamp
        mock_datetime.now.return_value = datetime(2024, 1, 15, 14, 30, 25)
        
        filename = self.storage_manager._generate_filename()
        self.assertEqual(filename, "topics_20240115_143025.txt")
    
    @patch('topic_storage.datetime')
    def test_generate_filename_collision_handling(self, mock_datetime):
        """Test filename collision handling."""
        # Mock datetime to return predictable timestamp
        mock_datetime.now.return_value = datetime(2024, 1, 15, 14, 30, 25)
        
        # Create a file with the expected name to force collision
        collision_file = os.path.join(self.test_dir, "topics_20240115_143025.txt")
        with open(collision_file, 'w') as f:
            f.write("existing file")
        
        filename = self.storage_manager._generate_filename()
        self.assertEqual(filename, "topics_20240115_143025_001.txt")
    
    def test_start_session_success(self):
        """Test successful session start."""
        result = self.storage_manager.start_session()
        self.assertTrue(result)
        self.assertIsNotNone(self.storage_manager.current_session)
        self.assertIsNotNone(self.storage_manager.current_session.file_handle)
        
        # Check that file was created
        self.assertTrue(os.path.exists(self.storage_manager.current_session.file_path))
        
        # Check that header was written
        with open(self.storage_manager.current_session.file_path, 'r') as f:
            content = f.read()
            self.assertIn("=== AUDIO SESSION STARTED:", content)
    
    def test_start_session_ends_existing_session(self):
        """Test that starting new session ends existing one."""
        # Start first session
        self.storage_manager.start_session()
        first_session_path = self.storage_manager.current_session.file_path
        
        # Start second session
        self.storage_manager.start_session()
        second_session_path = self.storage_manager.current_session.file_path
        
        # Should be different files
        self.assertNotEqual(first_session_path, second_session_path)
        
        # First file should have footer (session ended)
        with open(first_session_path, 'r') as f:
            content = f.read()
            self.assertIn("=== AUDIO SESSION ENDED:", content)
    
    def test_end_session_success(self):
        """Test successful session end."""
        # Start session first
        self.storage_manager.start_session()
        session_path = self.storage_manager.current_session.file_path
        
        # End session
        self.storage_manager.end_session()
        self.assertIsNone(self.storage_manager.current_session)
        
        # Check that footer was written
        with open(session_path, 'r') as f:
            content = f.read()
            self.assertIn("=== AUDIO SESSION ENDED:", content)
            self.assertIn("=== SESSION DURATION:", content)
            self.assertIn("=== TOPICS CAPTURED:", content)
    
    def test_end_session_no_active_session(self):
        """Test ending session when none is active."""
        # Should not raise exception
        self.storage_manager.end_session()
        self.assertIsNone(self.storage_manager.current_session)
    
    def test_store_topic_success(self):
        """Test successful topic storage."""
        # Start session first
        self.storage_manager.start_session()
        
        # Store topic
        result = self.storage_manager.store_topic(self.mock_topic)
        self.assertTrue(result)
        self.assertEqual(self.storage_manager.current_session.topic_count, 1)
        
        # Check file content
        with open(self.storage_manager.current_session.file_path, 'r') as f:
            content = f.read()
            self.assertIn("[14:30] [ME] Test topic content", content)
    
    def test_store_topic_no_active_session(self):
        """Test storing topic when no session is active."""
        result = self.storage_manager.store_topic(self.mock_topic)
        self.assertFalse(result)
    
    def test_store_topic_multiple_topics(self):
        """Test storing multiple topics."""
        # Start session
        self.storage_manager.start_session()
        
        # Store multiple topics
        topic1 = MockTopic("First topic", datetime(2024, 1, 15, 14, 30, 25), "ME")
        topic2 = MockTopic("Second topic", datetime(2024, 1, 15, 14, 31, 10), "OTHERS")
        
        self.assertTrue(self.storage_manager.store_topic(topic1))
        self.assertTrue(self.storage_manager.store_topic(topic2))
        
        self.assertEqual(self.storage_manager.current_session.topic_count, 2)
        
        # Check file content
        with open(self.storage_manager.current_session.file_path, 'r') as f:
            content = f.read()
            self.assertIn("[14:30] [ME] First topic", content)
            self.assertIn("[14:31] [OTHERS] Second topic", content)

if __name__ == '__main__':
    unittest.main()