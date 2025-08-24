import pyaudiowpatch as pyaudio
import wave

def capture_system_audio():
    CHUNK = 1024
    FORMAT = pyaudio.paInt16
    RECORD_SECONDS = 10

    p = pyaudio.PyAudio()

    try:
        # Get default output device info
        default_speakers = p.get_device_info_by_index(
            p.get_default_output_device_info()['index']
        )
        
        # Find the corresponding loopback device
        if not default_speakers["isLoopbackDevice"]:
            for loopback in p.get_loopback_device_info_generator():
                if default_speakers["name"] in loopback["name"]:
                    default_speakers = loopback
                    break
            else:
                print("Default loopback output device not found.")
                return

        # Use device's native settings
        channels = int(default_speakers["maxInputChannels"])
        sample_rate = int(default_speakers["defaultSampleRate"])

        print(f"Recording from: {default_speakers['name']}")
        print(f"Channels: {channels}, Sample Rate: {sample_rate} Hz")

        stream = p.open(
            format=FORMAT,
            channels=channels,
            rate=sample_rate,
            frames_per_buffer=CHUNK,
            input=True,
            input_device_index=default_speakers["index"]
        )

        print(f"Recording for {RECORD_SECONDS} seconds...")
        frames = []

        total_frames = int(sample_rate / CHUNK * RECORD_SECONDS)
        for i in range(total_frames):
            data = stream.read(CHUNK)
            frames.append(data)

        print("Finished recording.")

        stream.stop_stream()
        stream.close()

        # Save the audio file
        with wave.open("system_audio.wav", 'wb') as wf:
            wf.setnchannels(channels)
            wf.setsampwidth(p.get_sample_size(FORMAT))
            wf.setframerate(sample_rate)
            wf.writeframes(b''.join(frames))
        
        print("Audio saved to system_audio.wav")

    finally:
        p.terminate()

if __name__ == "__main__":
    capture_system_audio()