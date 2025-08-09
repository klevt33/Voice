# topic_storage.py
import os
import logging
from datetime import datetime
from typing import Optional, TextIO
from dataclasses import dataclass

logger = logging.getLogger(__name__)

@dataclass
class StorageSession:
    """Represents an active storage session with file handle and metadata."""
    file_path: str
    file_handle: Optional[TextIO]
    start_time: datetime
    topic_count: int = 0

class TopicStorageManager:
    """
    Manages persistent storage of captured topics to files.
    
    Creates session-based files when audio monitoring starts and closes them
    when monitoring stops. All captured topics are written immediately to
    ensure data preservation across application crashes.
    """
    
    def __init__(self, storage_folder_path: str):
        """
        Initialize the storage manager with the configured storage folder path.
        
        Args:
            storage_folder_path: Path to the folder where topic files will be stored
        """
        self.storage_folder = storage_folder_path
        self.current_session: Optional[StorageSession] = None
        logger.info(f"TopicStorageManager initialized with folder: {storage_folder_path}")
    
    def _generate_filename(self) -> str:
        """
        Generate a unique filename based on current timestamp.
        
        Uses format: topics_YYYYMMDD_HHMMSS.txt
        If filename already exists, appends a counter: topics_YYYYMMDD_HHMMSS_001.txt
        
        Returns:
            Unique filename for the storage file
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        base_filename = f"topics_{timestamp}.txt"
        full_path = os.path.join(self.storage_folder, base_filename)
        
        # Handle filename collisions by appending counter
        counter = 1
        while os.path.exists(full_path):
            collision_filename = f"topics_{timestamp}_{counter:03d}.txt"
            full_path = os.path.join(self.storage_folder, collision_filename)
            counter += 1
            
            # Safety check to prevent infinite loop
            if counter > 999:
                logger.error(f"Too many filename collisions for timestamp {timestamp}")
                break
        
        filename = os.path.basename(full_path)
        logger.debug(f"Generated filename: {filename}")
        return filename
    
    def _ensure_storage_directory(self) -> bool:
        """
        Ensure the storage directory exists, creating it if necessary.
        
        Returns:
            True if directory exists or was created successfully, False otherwise
        """
        if not self.storage_folder:
            logger.error("Storage folder path is empty")
            return False
            
        try:
            if not os.path.exists(self.storage_folder):
                os.makedirs(self.storage_folder, exist_ok=True)
                logger.info(f"Created storage directory: {self.storage_folder}")
            
            # Verify directory is writable
            if not os.access(self.storage_folder, os.W_OK):
                logger.error(f"Storage directory is not writable: {self.storage_folder}")
                return False
                
            return True
            
        except OSError as e:
            logger.error(f"Failed to create or access storage directory {self.storage_folder}: {e}")
            return False
    
    def start_session(self) -> bool:
        """
        Start a new storage session by creating a new file.
        
        Creates a new timestamped file and writes the session header.
        If a session is already active, it will be ended first.
        
        Returns:
            True if session started successfully, False otherwise
        """
        # End any existing session first
        if self.current_session is not None:
            logger.warning("Starting new session while previous session is active. Ending previous session.")
            self.end_session()
        
        # Ensure storage directory exists
        if not self._ensure_storage_directory():
            logger.error("Cannot start storage session: directory setup failed")
            return False
        
        try:
            # Generate unique filename and create file
            filename = self._generate_filename()
            file_path = os.path.join(self.storage_folder, filename)
            
            # Open file for writing
            file_handle = open(file_path, 'w', encoding='utf-8')
            
            # Create session object
            start_time = datetime.now()
            self.current_session = StorageSession(
                file_path=file_path,
                file_handle=file_handle,
                start_time=start_time,
                topic_count=0
            )
            
            # Write session header
            header = f"=== AUDIO SESSION STARTED: {start_time.strftime('%Y-%m-%d %H:%M:%S')} ===\n"
            file_handle.write(header)
            file_handle.flush()  # Ensure header is written immediately
            
            logger.info(f"Started storage session: {filename}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to start storage session: {e}")
            if self.current_session and self.current_session.file_handle:
                try:
                    self.current_session.file_handle.close()
                except:
                    pass
            self.current_session = None
            return False
    
    def end_session(self) -> None:
        """
        End the current storage session by writing footer and closing file.
        
        Writes session statistics and closes the file handle.
        Safe to call even if no session is active.
        """
        if self.current_session is None:
            logger.debug("No active storage session to end")
            return
        
        try:
            if self.current_session.file_handle:
                # Write session footer with statistics
                end_time = datetime.now()
                duration = end_time - self.current_session.start_time
                footer = f"=== AUDIO SESSION ENDED: {end_time.strftime('%Y-%m-%d %H:%M:%S')} ===\n"
                footer += f"=== SESSION DURATION: {duration} ===\n"
                footer += f"=== TOPICS CAPTURED: {self.current_session.topic_count} ===\n"
                
                self.current_session.file_handle.write(footer)
                self.current_session.file_handle.flush()
                self.current_session.file_handle.close()
                
                logger.info(f"Ended storage session: {os.path.basename(self.current_session.file_path)} "
                           f"({self.current_session.topic_count} topics, {duration})")
            
        except Exception as e:
            logger.error(f"Error ending storage session: {e}")
        
        finally:
            self.current_session = None
    
    def store_topic(self, topic) -> bool:
        """
        Store a topic to the current active storage file.
        
        Formats the topic with timestamp, source, and text, then writes it
        to the active file with immediate flush for crash protection.
        
        Args:
            topic: Topic object with text, timestamp, and source attributes
            
        Returns:
            True if topic was stored successfully, False otherwise
        """
        if self.current_session is None:
            logger.warning("Cannot store topic: no active storage session")
            return False
        
        if self.current_session.file_handle is None:
            logger.error("Cannot store topic: file handle is None")
            return False
        
        try:
            # Format topic data for storage
            timestamp_str = topic.timestamp.strftime('%H:%M')
            topic_line = f"[{timestamp_str}] [{topic.source}] {topic.text}\n"
            
            # Write to file and flush immediately for crash protection
            self.current_session.file_handle.write(topic_line)
            self.current_session.file_handle.flush()
            
            # Update session statistics
            self.current_session.topic_count += 1
            
            logger.debug(f"Stored topic from {topic.source}: {topic.text[:50]}...")
            return True
            
        except Exception as e:
            logger.error(f"Failed to store topic: {e}")
            return False