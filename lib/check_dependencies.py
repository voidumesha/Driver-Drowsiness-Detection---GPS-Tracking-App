def check_dependencies():
    missing_libs = []
    errors = []
    
    # Check each library
    try:
        import os
        print("✅ os: OK")
    except ImportError as e:
        missing_libs.append("os")
        errors.append(str(e))

    try:
        import cv2
        print("✅ cv2 (OpenCV):", cv2.__version__)
    except ImportError as e:
        missing_libs.append("opencv-python")
        errors.append(str(e))

    try:
        import numpy as np
        print("✅ numpy:", np.__version__)
    except ImportError as e:
        missing_libs.append("numpy")
        errors.append(str(e))

    try:
        import RPi.GPIO as GPIO
        print("✅ RPi.GPIO: OK")
    except ImportError as e:
        missing_libs.append("RPi.GPIO")
        errors.append(str(e))

    try:
        from picamera2 import Picamera2
        print("✅ picamera2: OK")
    except ImportError as e:
        missing_libs.append("picamera2")
        errors.append(str(e))

    try:
        from RPLCD.i2c import CharLCD
        print("✅ RPLCD: OK")
    except ImportError as e:
        missing_libs.append("RPLCD")
        errors.append(str(e))

    try:
        from collections import deque
        print("✅ collections.deque: OK")
    except ImportError as e:
        missing_libs.append("collections")
        errors.append(str(e))

    # Print results
    if missing_libs:
        print("\n❌ Missing libraries:")
        for lib, error in zip(missing_libs, errors):
            print(f"- {lib}: {error}")
        print("\nTo install missing libraries, run:")
        print("pip install " + " ".join(missing_libs))
    else:
        print("\n✅ All dependencies are installed!")

if __name__ == "__main__":
    check_dependencies() 