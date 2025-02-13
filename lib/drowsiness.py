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
LED_PIN = 21  # LED pin for the bulb

GPIO.setup(BUZZER_PIN, GPIO.OUT)
GPIO.setup(BUTTON_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)  # Internal pull-up resistor
GPIO.setup(LED_PIN, GPIO.OUT)  # Set LED pin as output

# ===== LCD Setup (Address 0x27 detected) =====
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

def buzzer_on():
    GPIO.output(BUZZER_PIN, GPIO.HIGH)

def buzzer_off():
    GPIO.output(BUZZER_PIN, GPIO.LOW)

def led_on():
    GPIO.output(LED_PIN, GPIO.HIGH)

def led_off():
    GPIO.output(LED_PIN, GPIO.LOW)

def lcd_message(line1, line2=""):
    """Updates the LCD only if the message is different."""
    global last_lcd_message
    message = f"{line1} | {line2}"
    
    if message != last_lcd_message:  # Prevent unnecessary updates
        lcd.clear()
        lcd.write_string(line1)
        lcd.cursor_pos = (1, 0)
        lcd.write_string(line2)
        print(f"LCD: {line1} | {line2}")
        last_lcd_message = message
        time.sleep(1)

def toggle_system():
    """Toggles the system on/off when the button is pressed"""
    global system_active, rest_start_time
    system_active = not system_active
    print(f"System {'Activated' if system_active else 'Paused'}")
    
    if system_active:
        buzzer_on()
        led_on()
        lcd_message("System Activated", "Monitoring ON")
        time.sleep(1)
        buzzer_off()
        led_off()
        rest_start_time = None  # Reset rest time when system is activated
    else:
        buzzer_on()
        led_on()
        lcd_message("System Paused", "Press to Start")
        time.sleep(1)
        buzzer_off()
        led_off()
        rest_start_time = time.time()  # Start tracking rest time

# ===== Dlib Face Detector Setup =====
print("[INFO] Loading facial landmark predictor...")
lcd_message("Loading Model", "Please Wait...")
detector = dlib.get_frontal_face_detector()
predictor = dlib.shape_predictor('shape_predictor_68_face_landmarks.dat')

# Initialize USB webcam
print("[INFO] Initializing USB webcam...")
lcd_message("Initializing", "Camera...")
cap = cv2.VideoCapture(0)

if not cap.isOpened():
    print("❌ ERROR: Cannot access webcam!")
    lcd_message("ERROR:", "No Camera Found")
    exit()

# ===== Constants =====
EYE_AR_THRESH = 0.25
EYE_CLOSED_TIME = 4  # seconds
FACE_MISSING_TIME = 2  # seconds before alert
NECK_FALL_TIME = 2  # seconds for neck fall detection
COUNTER = 0
buzzer_active = False
face_missing_since = None
neck_fallen_since = None
timer_start = None

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
        if time.time() - last_toggle_time > 0.3:  # Debounce time 300ms
            toggle_system()
            last_toggle_time = time.time()
    last_button_state = current_button_state

    # ======= If system is paused, show date/time and rest time =======
    if not system_active:
        buzzer_off()
        
        if rest_start_time is not None:
            rest_duration = time.time() - rest_start_time  # Calculate rest time
        
        # Display rest time
        rest_minutes = int(rest_duration // 60)
        rest_seconds = int(rest_duration % 60)
        rest_time_message = f"You Rested {rest_minutes}m {rest_seconds}s"
        
        # Display real-time date and time
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # Ensure the system isn't overloading the display with updates
        if int(time.time()) % 2 == 0:  # Update every 2 seconds
            lcd_message(rest_time_message, current_time)
        
        continue

    # ======= Capture Frame =======
    ret, frame = cap.read()
    if not ret:
        print("❌ ERROR: Failed to grab frame!")
        lcd_message("Camera Error!", "Check Connection")
        break

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    rects = detector(gray, 0)

    # ======= Handle missing face case =======
    if len(rects) == 0:
        if face_missing_since is None:
            face_missing_since = time.time()
        elif time.time() - face_missing_since >= FACE_MISSING_TIME:
            if not buzzer_active:
                buzzer_on()
                led_on()
                buzzer_active = True
            print("⚠ WARNING: No Face Detected!")
            lcd_message("No Face Found!", "Wake Up!")
    else:
        face_missing_since = None
        if buzzer_active:
            buzzer_off()
            led_off()
            buzzer_active = False
            lcd_message("Monitoring", "Face Detected")

    for rect in rects:
        shape = predictor(gray, rect)
        shape = face_utils.shape_to_np(shape)

        leftEye = shape[lStart:lEnd]
        rightEye = shape[rStart:rEnd]
        ear = (eye_aspect_ratio(leftEye) + eye_aspect_ratio(rightEye)) / 2.0

        # ======= Drowsiness Detection =======
        if ear < EYE_AR_THRESH:
            if timer_start is None:
                timer_start = time.time()
            elif time.time() - timer_start >= EYE_CLOSED_TIME:
                if not buzzer_active:
                    buzzer_on()
                    led_on()
                    buzzer_active = True
                    print("⚠ DROWSINESS ALERT: Eyes Closed!")
                    lcd_message("Drowsiness!", "Wake Up!")
        else:
            timer_start = None
            if buzzer_active:
                buzzer_off()
                led_off()
                buzzer_active = False
                lcd_message("Monitoring", "Normal")

    cv2.imshow("Driver Monitoring", frame)

    if cv2.waitKey(1) & 0xFF == ord("q"):
        break

cap.release()
cv2.destroyAllWindows()
GPIO.cleanup()