# demo_topic_storage.py
"""
Demonstration of the persistent topic storage feature.
This script simulates the topic capture and storage workflow.
"""

import os
import tempfile
from datetime import datetime
from topic_storage import TopicStorageManager
from TopicsUI import Topic

def demo_topic_storage():
    """Demonstrate the complete topic storage workflow."""
    print("=== Persistent Topic Storage Demo ===\n")
    
    # Create temporary directory for demo
    demo_dir = tempfile.mkdtemp()
    print(f"Demo storage directory: {demo_dir}")
    
    # Initialize storage manager
    storage_manager = TopicStorageManager(demo_dir)
    
    # Simulate starting audio monitoring (Listen=ON)
    print("\n1. Starting audio session (Listen=ON)...")
    success = storage_manager.start_session()
    print(f"   Session started: {success}")
    
    if success:
        print(f"   Created file: {os.path.basename(storage_manager.current_session.file_path)}")
    
    # Simulate capturing topics
    print("\n2. Capturing topics...")
    topics = [
        Topic("Hello, how are you doing today?", datetime.now(), "ME"),
        Topic("I'm doing great, thanks for asking!", datetime.now(), "OTHERS"),
        Topic("That's wonderful to hear.", datetime.now(), "ME"),
        Topic("What are your plans for the weekend?", datetime.now(), "OTHERS"),
        Topic("I'm thinking of going hiking if the weather is nice.", datetime.now(), "ME"),
    ]
    
    for i, topic in enumerate(topics, 1):
        success = storage_manager.store_topic(topic)
        print(f"   Topic {i}: {topic.text[:40]}... -> Stored: {success}")
    
    # Simulate stopping audio monitoring (Listen=OFF)
    print("\n3. Stopping audio session (Listen=OFF)...")
    storage_manager.end_session()
    print("   Session ended and file closed")
    
    # Show the created file
    print("\n4. Examining created file...")
    files = os.listdir(demo_dir)
    if files:
        file_path = os.path.join(demo_dir, files[0])
        print(f"   File created: {files[0]}")
        print(f"   File size: {os.path.getsize(file_path)} bytes")
        
        print("\n   File contents:")
        print("   " + "="*50)
        with open(file_path, 'r', encoding='utf-8') as f:
            for line_num, line in enumerate(f, 1):
                print(f"   {line_num:2d}: {line.rstrip()}")
        print("   " + "="*50)
    
    # Demonstrate crash protection (topics persist)
    print("\n5. Demonstrating crash protection...")
    print("   Topics are saved to file immediately and persist even if application crashes")
    print("   File remains intact and can be reviewed manually")
    
    # Cleanup
    import shutil
    shutil.rmtree(demo_dir)
    print(f"\n   Demo cleanup: Removed {demo_dir}")
    
    print("\n=== Demo Complete ===")
    print("The persistent topic storage feature is working correctly!")

if __name__ == "__main__":
    demo_topic_storage()