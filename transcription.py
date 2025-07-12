# transcription.py
import io
import time
import torch
import gc
import queue
import logging
from typing import Dict
from faster_whisper import WhisperModel
import os
from datetime import datetime
from TopicsUI import Topic
from config import WHISPER_MODEL, COMPUTE_TYPE, MODELS_FOLDER, LANGUAGE, BEAM_SIZE

# Configure logger for this module
logger = logging.getLogger(__name__)

# Cache for models to avoid reloading
_model_cache = {}

def get_whisper_model(model_name: str, device: str, compute_type: str) -> WhisperModel:
    """Get a cached whisper model or create a new one"""
    cache_key = f"{model_name}_{device}_{compute_type}"
    if cache_key not in _model_cache:
        logger.info(f"Creating new WhisperModel instance: {model_name} on {device}")
        _model_cache[cache_key] = WhisperModel(
            model_name,
            device=device,
            compute_type=compute_type,
            download_root=MODELS_FOLDER
        )
    else:
        logger.info(f"Using cached WhisperModel instance: {model_name}")
    return _model_cache[cache_key]

def transcription_thread(app_controller,
                         audio_queue: queue.Queue, 
                         run_threads_ref: Dict[str, bool], 
                         ui_queue: queue.Queue) -> None:
    """Thread that processes audio segments and converts speech to text using faster_whisper"""
    logger.info(f"Initializing faster_whisper ({WHISPER_MODEL} model)...")
    
    # Determine device type
    device = "cuda" if torch.cuda.is_available() else "cpu"
    logger.info(f"Using device: {device}")
        
    # Create models folder if it doesn't exist
    if not os.path.exists(MODELS_FOLDER):
        os.makedirs(MODELS_FOLDER)
        logger.info(f"Created models folder: {MODELS_FOLDER}")
    
    # Initialize the model using the cache function
    try:
        model = get_whisper_model(
            model_name=WHISPER_MODEL,
            device=device,
            compute_type=COMPUTE_TYPE if device == "cuda" else "int8"
        )
        logger.info("faster_whisper model loaded successfully")
    except Exception as e:
        logger.error(f"Error initializing faster_whisper: {e}")
        logger.error(f"Detailed error: {str(e)}")
        run_threads_ref["active"] = False
        return
    
    logger.info("Speech recognition thread ready.")
    
    # Stats for monitoring performance
    stats = {
        "segments_processed": 0,
        "empty_segments": 0,
        "errors": 0,
        "total_processing_time": 0
    }
    
    # Main processing loop
    while run_threads_ref["active"]:
        try:
            # Get the next audio segment with a timeout to allow checking run_threads
            try:
                audio_segment = audio_queue.get(timeout=1)
            except queue.Empty:
                continue
                
            # Process the audio segment
            source_prefix = f"[{audio_segment.source}]"
            start_time = time.time()
            
            try:
                # Get audio data as WAV bytes
                audio_data = audio_segment.get_wav_bytes()
                if not audio_data:
                    logger.warning(f"{source_prefix} Could not get WAV data")
                    audio_queue.task_done()
                    stats["errors"] += 1
                    continue
                
                # Transcribe with faster_whisper in a managed context
                with io.BytesIO(audio_data) as audio_io:
                    segments, info = model.transcribe(
                        audio_io,
                        language=LANGUAGE,
                        beam_size=BEAM_SIZE,
                        word_timestamps=False
                    )
                    
                    # Process the transcript without timestamps
                    segment_list = list(segments)  # Convert generator to list
                    stats["segments_processed"] += 1
                    
                    if not segment_list:
                        logger.info(f"{source_prefix} No speech detected.")
                        stats["empty_segments"] += 1
                    else:
                        # Combine all segments into one continuous text
                        transcript_text = " ".join(segment.text for segment in segment_list)
                        cleaned_text = transcript_text.strip()

                        # Check if the text should be sent to the queue
                        if ("thank" in cleaned_text.lower() and len(cleaned_text) <= 40) or len(cleaned_text) <= 10: # Likely faster_whisper hallucination...
                            logger.info(f"TRANSCRIBED (Not Sent): {cleaned_text}")
                        else:
                            # Create a Topic object
                            topic = Topic(text=cleaned_text, timestamp=datetime.now(), source=audio_segment.source)
                            
                            # Get current auto-submit mode
                            auto_submit_mode = app_controller.auto_submit_mode
                            
                            # Determine destination based on auto-submit mode
                            should_auto_submit = (
                                auto_submit_mode == "All" or
                                (auto_submit_mode == "Others" and topic.source == "OTHERS")
                            )
                            
                            if should_auto_submit:
                                # Route to browser
                                submission_content = f"[{topic.source}] {topic.text}"
                                browser_payload = {
                                    'content': submission_content,
                                    'topic_objects': [topic]
                                }
                                if app_controller.browser_manager:
                                    app_controller.browser_manager.browser_queue.put(browser_payload)
                                    logger.info(f"AUTO-SUBMIT to browser: {submission_content[:50]}...")
                                else:
                                    logger.warning("Cannot auto-submit, browser_manager not available.")
                            else:
                                # Route to UI
                                full_transcript = f"[{topic.source}] {cleaned_text}"
                                logger.info(f"TRANSCRIBED (Sent to UI): {full_transcript[:48]}...")
                                ui_queue.put(full_transcript)
                
                audio_queue.task_done()
                processing_time = time.time() - start_time
                stats["total_processing_time"] += processing_time
                logger.debug(f"Processed segment in {processing_time:.2f}s")
                    
            except Exception as e:
                logger.error(f"Error transcribing {source_prefix} audio: {e}")
                # Put it back in the queue to try again later
                audio_queue.put(audio_segment)
                stats["errors"] += 1
                time.sleep(1)
                
        except Exception as e:
            logger.error(f"Error in transcription thread: {e}")
            stats["errors"] += 1
            time.sleep(1)
            
        # Check if we should exit
        if not run_threads_ref["active"]:
            break
    
    # Print stats before exiting
    if stats["segments_processed"] > 0:
        logger.info(f"Transcription stats: processed {stats['segments_processed']} segments, "
                   f"{stats['empty_segments']} empty, {stats['errors']} errors, "
                   f"avg time: {stats['total_processing_time']/stats['segments_processed']:.2f}s per segment")
    
    # Clean up resources
    logger.info("Cleaning up transcription resources")
    del model
    gc.collect()
    if device == "cuda":
        torch.cuda.empty_cache()
    
    logger.info("Transcription thread shutting down.")