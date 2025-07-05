# check_cuda_v2.py
import os
import torch
import ctranslate2
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

DLL_PATHS = [
    r"C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.9\bin",
    r"C:\Program Files\NVIDIA\CUDNN\v9.10\bin\12.9"
]

logging.info("Attempting to add DLL directories to path...")
for path in DLL_PATHS:
    if os.path.exists(path):
        try:
            os.add_dll_directory(path)
            logging.info(f"SUCCESS: Added DLL directory: {path}")
        except Exception as e:
            logging.error(f"FAILED to add DLL directory: {path} - {e}")
    else:
        logging.warning(f"SKIPPED: DLL path does not exist: {path}")

print("-" * 50)

logging.info("Checking PyTorch CUDA availability...")
pytorch_cuda_available = torch.cuda.is_available()
logging.info(f"torch.cuda.is_available(): {pytorch_cuda_available}")
if pytorch_cuda_available:
    logging.info(f"PyTorch found {torch.cuda.device_count()} CUDA device(s).")
    logging.info(f"Current device name: {torch.cuda.get_device_name(0)}")
else:
    logging.error("PyTorch cannot find CUDA. This is the root cause.")

print("-" * 50)

logging.info("Checking ctranslate2 compute device...")
try:
    # Corrected function call
    cuda_info = ctranslate2.get_compute_device_info('cuda')
    logging.info(f"SUCCESS: ctranslate2 found CUDA device: {cuda_info['name']}")
    logging.info("Your application should be able to use the 'cuda' device.")
except RuntimeError as e:
    logging.error(f"FAILURE: ctranslate2 raised a RuntimeError: {e}")
    logging.info("This confirms it cannot access the CUDA libraries correctly.")
except Exception as e:
    logging.error(f"FAILURE: An unexpected exception occurred while checking ctranslate2: {e}")

print("-" * 50)
logging.info("Resolution Checklist:")
logging.info("1. Reinstall PyTorch to match your CUDA version (see steps below).")
logging.info("2. Simplify the cuDNN path by copying DLLs (see steps below).")
logging.info("3. Consider a clean reinstall of your NVIDIA driver if issues persist.")