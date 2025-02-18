import cv2
import time
import imutils
from datetime import datetime
import numpy as np
import RPi.GPIO as GPIO
from RPLCD.i2c import CharLCD
import dlib
import firebase_admin
from firebase_admin import credentials, firestore
import requests
import threading


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
lcd = CharLCD(i2c_expander='PCF8574', address=0x27, port=1, cols=20, rows=4, dotsize=8)

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
first_activation = True  # Ignore first activation for rest tracking

# ===== Buzzer & LED Control =====
def buzzer_on():
    GPIO.output(BUZZER_PIN, GPIO.HIGH)

def buzzer_off():
    GPIO.output(BUZZER_PIN, GPIO.LOW)

def led_on():
    GPIO.output(LED_PIN, GPIO.HIGH)

def led_off():
    GPIO.output(LED_PIN, GPIO.LOW)

# ===== LCD Message Function =====
def lcd_message(line1="", line2="", line3="", line4=""):
    """Updates the LCD only if the message is different to reduce processing lag."""
    global last_lcd_message
    message = f"{line1} | {line2} | {line3} | {line4}"
    
    if message != last_lcd_message:
        lcd.clear()
        
        lcd.cursor_pos = (0, 0)  # First row
        lcd.write_string(line1[:20])  # Max 20 characters
        
        lcd.cursor_pos = (1, 0)  # Second row
        lcd.write_string(line2[:20]) 
        
        lcd.cursor_pos = (2, 0)  # Third row (Date)
        lcd.write_string(line3[:20])  
        
        lcd.cursor_pos = (3, 0)  # Fourth row (Rest message)
        lcd.write_string(line4[:20])  
        
        print(f"LCD:\n{line1}\n{line2}\n{line3}\n{line4}")  
        last_lcd_message = message


# ===== System Toggle Function =====
def toggle_system():
    """Toggles the system on/off when the button is pressed"""
    global system_active, rest_start_time, first_activation
    system_active = not system_active
    print(f"System {'Activated' if system_active else 'Paused'}")
    
    if system_active:
        # When system is activated
        buzzer_on()
        led_on()
        lcd_message("System Activated", "Monitoring ON", "", "")
        time.sleep(1)
        buzzer_off()
        led_off()
        
        # Update break status to false when system is activated
        update_break_status(False)
        
        if first_activation:
            first_activation = False
        else:
            rest_start_time = None
    else:
        # When system is paused
        buzzer_on()
        led_on()
        press_time = datetime.now().strftime("%H:%M:%S")
        lcd_message("System Paused", "Resting", "Start Time:", press_time)
        time.sleep(1)
        buzzer_off()
        led_off()
        rest_start_time = time.time()
        
        # Set break status to true when system is paused
        update_break_status(True)

# ===== OpenCV Face & Dlib Eye Detection Model Load =====
print("[INFO] Loading OpenCV Haarcascades and Dlib Model...")
lcd_message("Loading Model", "Please Wait...", "", "")

# Load Haarcascades for face detection
face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")

# Load Dlib's shape predictor for facial landmarks (for eye detection)
detector = dlib.get_frontal_face_detector()
predictor = dlib.shape_predictor('shape_predictor_68_face_landmarks.dat')

# ===== Camera Initialization =====
print("[INFO] Initializing USB webcam...")
lcd_message("Detecting Camera", "Please Wait...", "", "")

cap = None
for i in [0, 1]:  # Try both video0 and video1
    cap = cv2.VideoCapture(i)
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
EYE_CLOSED_TIME = 3  # Seconds before buzzer triggers
FACE_MISSING_TIME = 2  # Seconds before buzzer triggers
face_missing_since = None
timer_start = None
buzzer_active = False
face_alert_triggered = False

# Firebase initialization
cred = credentials.Certificate("/home/dasun/Downloads/serviceAccountKey.json")  # Update path
firebase_admin.initialize_app(cred)
db = firestore.client()

# Add this function to update break status
def update_break_status(is_breaking):
    try:
        # Get current active journey
        journeys_ref = db.collection('journeys')
        active_journeys = journeys_ref.where('isActive', '==', True).get()
        
        # Get current location (assuming you have GPS coordinates)
        current_location = {
            'latitude': current_lat,  # Your current GPS latitude
            'longitude': current_lng  # Your current GPS longitude
        }
        
        # Update break status with location
        break_ref = db.collection('breaking').document('status')
        break_ref.set({
            'isBreaking': is_breaking,
            'timestamp': datetime.now(),
            'location': current_location,
            'breakCount': firestore.Increment(1) if is_breaking else None
        }, merge=True)

        # Update journey with break details
        for journey in active_journeys:
            if is_breaking:
                # Add break details to journey
                journey.reference.update({
                    'breaks': firestore.ArrayUnion([{
                        'time': datetime.now(),
                        'location': current_location,
                        'duration': 20,  # 20 minutes break
                        'breakNumber': (journey.get('totalBreaks') or 0) + 1
                    }]),
                    'totalBreaks': firestore.Increment(1)  # Increment break count
                })
                
                print(f"Break #{journey.get('totalBreaks') or 1} recorded at location: {current_location}")
                
                # Update LCD with break information
                lcd_message(
                    f"Break #{journey.get('totalBreaks') or 1}",
                    "Take 20min Rest",
                    f"Lat: {current_lat:.4f}",
                    f"Lng: {current_lng:.4f}"
                )

    except Exception as e:
        print(f"Firebase Error: {str(e)}")


def get_current_city(lat, lng):
    try:
        url = f"https://maps.googleapis.com/maps/api/geocode/json?latlng={lat},{lng}&key={GOOGLE_MAPS_API_KEY}"
        response = requests.get(url).json()
        
        if response['status'] == 'OK':
            for component in response['results'][0]['address_components']:
                if 'locality' in component['types']:
                    city_name = component['long_name']
                    # Update Firebase with current city
                    db.collection('cities').document('current').set({
                        'name': city_name,
                        'timestamp': datetime.now()
                    })
                    return city_name
    except Exception as e:
        print(f"Error getting city: {e}")
    return None

# Update LCD display with current city
def update_lcd_with_location():
    try:
        city_doc = db.collection('cities').document('current').get()
        if city_doc.exists:
            city_data = city_doc.to_dict()
            lcd_message(
                "Current Location:",
                city_data['name'],
                datetime.now().strftime("%H:%M:%S"),
                ""
            )
except Exception as e:
        print(f"Error updating LCD: {e}")

# Add these global variables at the top
is_drowsy_alert = False
is_no_face_alert = False

def handle_system_pause(channel):
    global is_drowsy_alert, is_no_face_alert, buzzer_active, system_active
    
    if buzzer_active:  # Only update break status if buzzer was active
        update_break_status(True)  # Set isBreaking to true
        buzzer_off()
        led_off()
        buzzer_active = False
        is_drowsy_alert = False
        is_no_face_alert = False
        system_active = False
        lcd_message("System Paused", "Take 20min Break", "", "")
    else:
        toggle_system()  # Normal system toggle if no alert

# Add at the top with other global variables
break_end_notified = False

def check_break_status():
    global break_end_notified, system_active
    try:
        break_doc = db.collection('breaking').document('status').get()
        if break_doc.exists:
            data = break_doc.to_dict()
            if data.get('isBreaking') and not system_active:  # Only check when system is paused
                break_start = data.get('timestamp').timestamp()
                current_time = time.time()
                break_duration = current_time - break_start
                
                # Check if break time is over
                if break_duration >= 20 * 60 and not break_end_notified:
                    buzzer_on()
                    led_on()
                    lcd_message("Break Over!", "Ready to Drive", "", "")
                    time.sleep(2)
                    buzzer_off()
                    led_off()
                    break_end_notified = True
                    
                    # Don't automatically update break status
                    # Let the system activation handle it
    except Exception as e:
        print(f"Error checking break status: {e}")

# Add this function to track position updates
def update_current_position(lat, lng):
    global _currentPosition
    _currentPosition = type('Position', (), {'latitude': lat, 'longitude': lng})()
    
    while True:
    # Handle button press for alerts
    current_button_state = GPIO.input(BUTTON_PIN)
    if current_button_state == GPIO.LOW and last_button_state == GPIO.HIGH:
        handle_system_pause(BUTTON_PIN)
    last_button_state = current_button_state

    
    
# ======= If system is paused, show rest time and date/time =======
    if not system_active:

        buzzer_off()

        if rest_start_time is None:
            rest_start_time = time.time()  # ✅ Ensure rest tracking starts

        rest_duration = time.time() - rest_start_time
        rest_minutes = int(rest_duration // 60)
        rest_seconds = int(rest_duration % 60)

        rest_time_message = f"Rest: {rest_minutes}m {rest_seconds}s"
        current_time = datetime.now().strftime("%H:%M:%S")  # ✅ Keep time format clean
        current_date = datetime.now().strftime("%Y-%m-%d")  # ✅ Show proper date

        # First Row: Rest time
        # Second Row: Current time
        # Third Row: Current date
        # Fourth Row: Alert message if rest time exceeds 20 minutes
        if rest_duration >= 20 * 60:  # 2 minutes (instead of 20 minutes for testing purposes)
            update_break_status(True)
            alert_message = "Rest over!"
        else:
            update_break_status(False)
            alert_message = ""

        lcd_message(
            rest_time_message,  # Line 1
            current_time,       # Line 2
            current_date,       # Line 3
            alert_message       # Line 4
)

        
        # Check if the rest time exceeds 20 minutes and turn on the buzzer if true
        if rest_duration >= 20 * 60:  # 20 minutes in seconds
            buzzer_on()
            led_on()
            print("⚠ Rest time exceeded 20 minutes! Buzzer activated.")

        time.sleep(1)  # ✅ Ensures display updates correctly
        continue  # ✅ Ensure loop continues smoothly
        buzzer_off()
        led_off()
        # ... rest of your pause logic ...
                continue  

    # Capture and process frame
    ret, frame = cap.read()
    if not ret:
        print("❌ ERROR: Failed to grab frame!")
        lcd_message("Camera Error!", "Check Connection", "", "")
        break

    frame = imutils.resize(frame, width=640)
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    
    # Detect faces using Haarcascade
    faces = face_cascade.detectMultiScale(gray, scaleFactor=1.2, minNeighbors=5, minSize=(30, 30))

    # Handle missing face case
    if len(faces) == 0:
        if face_missing_since is None:
            face_missing_since = time.time()
        elif time.time() - face_missing_since >= FACE_MISSING_TIME:
            is_no_face_alert = True
            buzzer_on()
            led_on()
            buzzer_active = True
            lcd_message("Stop vehicle!", "Take rest!", "", "")
            print("🚨 Face missing alert triggered! Buzzer ON.")
    else:
        face_missing_since = None

    # Handle eye closure detection
    for face in faces:
        (x, y, w, h) = face
        landmarks = predictor(gray, dlib.rectangle(x, y, x + w, y + h))

        # Define the indices for the left and right eye (using Dlib's shape predictor)
        left_eye = landmarks.parts()[36:42]  # Left eye landmarks (points 36 to 41)
        right_eye = landmarks.parts()[42:48]  # Right eye landmarks (points 42 to 47)

        # Check if the eyes are closed based on landmarks (for simplicity, you can compare the eye aspect ratio)
        def eye_aspect_ratio(eye):
            # Convert dlib points to NumPy arrays for easier calculation
            eye = np.array([(point.x, point.y) for point in eye])

            # Calculate the distances between vertical eye landmarks
            A = np.linalg.norm(eye[1] - eye[5])  # Vertical distance
            B = np.linalg.norm(eye[2] - eye[4])  # Vertical distance
            C = np.linalg.norm(eye[0] - eye[3])  # Horizontal distance
            ear = (A + B) / (2.0 * C)
            return ear

        # Calculate EAR for left and right eye
        left_eye_ear = eye_aspect_ratio(left_eye)
        right_eye_ear = eye_aspect_ratio(right_eye)

        # Average EAR to determine if eyes are closed (threshold is usually between 0.2 and 0.3)
        ear = (left_eye_ear + right_eye_ear) / 2.0

        # Debug print statements to check EAR values
        print(f"Left Eye EAR: {left_eye_ear:.2f}, Right Eye EAR: {right_eye_ear:.2f}, Avg EAR: {ear:.2f}")

        if ear < 0.25:  # Threshold value for closed eyes
            if timer_start is None:
                timer_start = time.time()
        elif ear >= 0.25:
            timer_start = None

        if timer_start is not None and time.time() - timer_start >= EYE_CLOSED_TIME:
            is_drowsy_alert = True
            buzzer_on()
            led_on()
            buzzer_active = True
            lcd_message("Take Rest!", "Press Button", "", "")
            print("🚨 Drowsiness detected! Buzzer ON.")
        elif not is_drowsy_alert and not is_no_face_alert:
            buzzer_off()
            led_off()
            buzzer_active = False
            lcd_message("Monitoring", "Normal", "", "")

    # Keep buzzer and LED on if any alert is active until button is pressed
    if is_drowsy_alert or is_no_face_alert:
        buzzer_on()
        led_on()
        buzzer_active = True

    # Check break status
    check_break_status()
    
    # Reset break_end_notified when a new break starts
    if not system_active:
        break_end_notified = False

    # Update current position (if you have GPS)
    if current_lat and current_lng:  # Your GPS variables
        update_current_position(current_lat, current_lng)

        cv2.imshow("Driver Monitoring", frame)
    if cv2.waitKey(1) & 0xFF == ord("q"):
            break

# Cleanup
cap.release()
    cv2.destroyAllWindows()
    GPIO.cleanup()