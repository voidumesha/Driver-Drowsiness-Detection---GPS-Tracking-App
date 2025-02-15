import cv2
import time
import imutils
from datetime import datetime
from scipy.spatial import distance as dist
from imutils import face_utils
import dlib
import numpy as np
import RPi.GPIO as GPIO
from RPLCD.i2c import CharLCD


# ===== GPIO Setup =====
GPIO.setwarnings(False)
GPIO.setmode(GPIO.BCM)

BUZZER_PIN = 17
BUTTON_PIN = 19
LED_PIN = 21


GPIO.setup(BUZZER_PIN, GPIO.OUT)
GPIO.setup(BUTTON_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
GPIO.setup(LED_PIN, GPIO.OUT)



# ===== LCD Setup =====
lcd = CharLCD(i2c_expander='PCF8574', address=0x27, port=1,
              cols=20, rows=4, dotsize=8)

lcd.clear()
lcd.write_string("Initializing...")
time.sleep(2)
lcd.clear()

# ===== System State Variables =====
system_active = False
last_button_state = GPIO.input(BUTTON_PIN)
last_toggle_time = time.time()
last_lcd_message = ""
rest_start_time = None
rest_duration = 0
first_activation = True  # To ignore first activation for rest tracking

def buzzer_on():
    GPIO.output(BUZZER_PIN, GPIO.HIGH)

def buzzer_off():
    GPIO.output(BUZZER_PIN, GPIO.LOW)

def led_on():
    GPIO.output(LED_PIN, GPIO.HIGH)

def led_off():
    GPIO.output(LED_PIN, GPIO.LOW)



def lcd_message(line1, line2="", line3="", line4=""):
    """Updates the LCD only if the message is different to reduce processing lag."""
    global last_lcd_message
    message = f"{line1} | {line2} | {line3} | {line4}"
    
    if message != last_lcd_message:
        lcd.clear()
        lcd.write_string(line1)
        lcd.cursor_pos = (1, 0)
        lcd.write_string(line2)
        lcd.cursor_pos = (2, 0)
        lcd.write_string(line3)
        lcd.cursor_pos = (3, 0)
        lcd.write_string(line4)
        print(f"LCD: {line1} | {line2} | {line3} | {line4}")
        last_lcd_message = message

def toggle_system():
    """Toggles the system on/off when the button is pressed"""
    global system_active, rest_start_time, first_activation
    system_active = not system_active
    print(f"System {'Activated' if system_active else 'Paused'}")
    
    if system_active:
        buzzer_on()
        led_on()
        lcd_message("System Activated", "Monitoring ON", "", "")
        time.sleep(1)
        buzzer_off()
        led_off()
        
        if first_activation:
            first_activation = False  # Ignore first activation for rest tracking
        else:
            rest_start_time = None  # Reset rest time when system is activated
    else:
        buzzer_on()
        led_on()
        press_time = datetime.now().strftime("%H:%M:%S")
        lcd_message("System Paused", "Resting", "Start Time:", press_time)
        time.sleep(1)
        buzzer_off()
        led_off()
        rest_start_time = time.time()  # Start tracking rest time

# ===== Dlib Face Detector Setup =====
print("[INFO] Loading facial landmark predictor...")
lcd_message("Loading Model", "Please Wait...", "", "")
face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
eye_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_eye.xml")

#detector = dlib.get_frontal_face_detector()
#predictor = dlib.shape_predictor('shape_predictor_68_face_landmarks.dat')

# Initialize USB webcam
print("[INFO] Initializing USB webcam...")
lcd_message("Detecting Camera", "Please Wait...", "", "")
cap = None
for i in [0, 1]:  # Try both video0 and video1
    cap = cv2.VideoCapture(i, cv2.CAP_V4L2)  # Use V4L2 backend
    if cap.isOpened():
        print(f"✅ Camera found at index {i}")
        lcd_message("Camera Found", f"Using index {i}", "", "")
        break
else:
    print("❌ ERROR: No available camera!")
    lcd_message("ERROR:", "No Camera Found", "", "")
    exit()

cap.set(cv2.CAP_PROP_FPS, 30)

# ===== Constants =====
EYE_AR_THRESH = 0.25
EYE_CLOSED_TIME = 4  # seconds
FACE_MISSING_TIME = 2  # seconds before alert
COUNTER = 0
buzzer_active = False
face_missing_since = None
timer_start = None
frame_counter = 0
start_time = time.time()

# Landmark indices
(lStart, lEnd) = face_utils.FACIAL_LANDMARKS_IDXS["left_eye"]
(rStart, rEnd) = face_utils.FACIAL_LANDMARKS_IDXS["right_eye"]

def eye_aspect_ratio(eye):
    """Computes Eye Aspect Ratio (EAR) to detect eye closure"""
    A = dist.euclidean(eye[1], eye[5])
    B = dist.euclidean(eye[2], eye[4])
    C = dist.euclidean(eye[0], eye[3])
    return (A + B) / (2.0 * C)

while True:
    # ======= Handle Button Press =======
    current_button_state = GPIO.input(BUTTON_PIN)
    if current_button_state == GPIO.LOW and last_button_state == GPIO.HIGH:
        if time.time() - last_toggle_time > 0.3:
            toggle_system()
            last_toggle_time = time.time()
    last_button_state = current_button_state

    # ======= If system is paused, show rest time and date/time =======
    if not system_active:
        buzzer_off()
        
        if rest_start_time is not None:
            rest_duration = time.time() - rest_start_time
        
        rest_minutes = int(rest_duration // 60)
        rest_seconds = int(rest_duration % 60)
        rest_time_message = f"Rest: {rest_minutes}m {rest_seconds}s"
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        if int(time.time()) % 2 == 0:
            lcd_message(rest_time_message, "", "Time:", current_time)
        
        continue

    # ======= Capture Frame =======
    ret, frame = cap.read()
    if not ret:
        print("❌ ERROR: Failed to grab frame!")
        lcd_message("Camera Error!", "Check Connection", "", "")
        break

    frame = imutils.resize(frame, width=640)
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    faces = face_cascade.detectMultiScale(gray, scaleFactor=1.2, minNeighbors=5, minSize=(30, 30))

    # ======= Handle missing face case =======
    if len(faces) == 0:
        if face_missing_since is None:
            face_missing_since = time.time()
        elif time.time() - face_missing_since >= FACE_MISSING_TIME:
            if not buzzer_active:
                buzzer_on()
                led_on()
                buzzer_active = True
                    
                
            print("⚠ WARNING: No Face Detected!")
            lcd_message("No Face Found!", "Wake Up!", "", "")
            lcd_message(" WARNING: Please Stop the vehicle Now!", "Get Rest Now!", "", "")
            
    else:
        face_missing_since = None
        if buzzer_active:
            buzzer_off()
            led_off()
            buzzer_active = False
            lcd_message("Monitoring", "Face Detected", "", "")

    

        # ======= Drowsiness Detection =======
        for (x, y, w, h) in faces:
            roi_gray = gray[y:y + h, x:x + w]  # Extract face region
            roi_color = frame[y:y + h, x:x + w]

            eyes = eye_cascade.detectMultiScale(roi_gray, scaleFactor=1.1, minNeighbors=5, minSize=(20, 20))

            if len(eyes) == 0:
                if timer_start is None:
                    timer_start = time.time()  # Start the timer only if it hasn't started yet
                elif time.time() - timer_start >= EYE_CLOSED_TIME:  # Only check if timer_start is valid
                    if not buzzer_active:
                        buzzer_on()
                        led_on()
                        buzzer_active = True
                        print("⚠ DROWSINESS ALERT: Eyes Closed!")
                        lcd_message("Drowsiness!", "Wake Up!", "", "")
                        lcd_message(" WARNING: Please Stop the vehicle Now!", "Get Rest Now!", "", "")
        else:
            timer_start = None  # Reset timer when eyes are detected again
            if buzzer_active:
                buzzer_off()
                led_off()
                buzzer_active = False
                lcd_message("Monitoring", "Normal", "", "")


    
        frame_counter += 1
        if frame_counter % 10 == 0:
            elapsed_time = time.time() - start_time
            fps = frame_counter / elapsed_time
            print(f"FPS: {fps:.2f}")


    cv2.imshow("Driver Monitoring", frame)

    if cv2.waitKey(1) & 0xFF == ord("q"):
        break

cap.release()
cv2.destroyAllWindows()
GPIO.cleanup()