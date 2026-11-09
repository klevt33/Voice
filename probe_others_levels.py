"""Probe ALL loopback devices — shows which one actually carries your audio.
Play audio on the machine while this runs (YouTube/video/meeting)."""
import pyaudiowpatch as pyaudio
import numpy as np
from config import FORMAT, CHUNK_SIZE

pa = pyaudio.PyAudio()
try:
    default_out = pa.get_default_output_device_info()
    print(f"Windows default output: {default_out['name']}\n")
    loopbacks = list(pa.get_loopback_device_info_generator())
    for lb in loopbacks:
        try:
            stream = pa.open(format=FORMAT, channels=int(lb["maxInputChannels"]),
                             rate=int(lb["defaultSampleRate"]), input=True,
                             input_device_index=lb["index"], frames_per_buffer=CHUNK_SIZE)
            chunks = []
            for _ in range(30):  # ~0.7s of audio
                chunks.append(stream.read(CHUNK_SIZE, exception_on_overflow=False))
            stream.close()
            data = np.abs(np.frombuffer(b"".join(chunks), dtype=np.int16))
            mean_lvl, peak = float(np.mean(data)), int(np.max(data))
            bar = "#" * min(int(mean_lvl / 20), 40)
            status = "SOUND!" if mean_lvl > 100 else ("some" if mean_lvl > 20 else "quiet")
            print(f"[{lb['index']:2d}] mean={mean_lvl:8.1f} peak={peak:6d} {status:6s} {bar}  {lb['name']}")
        except Exception as e:
            print(f"[{lb['index']:2d}] open failed: {e}  {lb['name']}")
finally:
    pa.terminate()
