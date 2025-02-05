import os
import cv2
import numpy as np
import RPi.GPIO as GPIO
import time
from picamera2 import Picamera2, Preview
import tflite_runtime.interpreter as tflite
from collections import deque
from RPLCD.i2c import CharLCD
import firebase_admin
from firebase_admin import credentials, firestore
import datetime

# ------------------- Suppress TensorFlow & OpenCV Warnings -------------------
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'
os.environ['DISPLAY'] = ':0'  # Ensure OpenCV GUI works on Raspberry Pi

# ------------------- GPIO SETUP -------------------
BUZZER_PIN = 17  
GPIO.setwarnings(False)  
GPIO.setmode(GPIO.BCM)
GPIO.setup(BUZZER_PIN, GPIO.OUT)

# ------------------- LCD DISPLAY SETUP -------------------
try:
    lcd = CharLCD(i2c_expander='PCF8574', address=0x27, port=1,
                  cols=16, rows=2, dotsize=8)
    lcd.clear()
    print("✅ LCD Display Connected Successfully!")
except Exception as e:
    print(f"❌ LCD Error: {str(e)}")
    print("⚠ Continuing without LCD display...")
    lcd = None

def display_message(text, line=0):
    try:
        if lcd is not None:
            clean_text = text.replace('🚨', '').replace('⚠', '').strip()
            lcd.cursor_pos = (line, 0)
            lcd.write_string(' ' * 16)  # Clear line
            lcd.cursor_pos = (line, 0)
            lcd.write_string(clean_text[:16])  # Truncate if needed
    except Exception as e:
        print(f"LCD Display Error: {str(e)}")

def update_lcd_status(status_line1, status_line2=None):
    display_message(status_line1, 0)
    if status_line2:
        display_message(status_line2, 1)

# ------------------- BUZZER ALERT FUNCTION -------------------
def buzzer_alert(message="⚠ ALERT!"):
    print(f"🔊 {message}")
    display_message(message.replace('⚠', ''), 0)
    GPIO.output(BUZZER_PIN, GPIO.HIGH)
    time.sleep(0.5)
    GPIO.output(BUZZER_PIN, GPIO.LOW)

# ------------------- TFLITE MODEL SETUP -------------------
interpreter = tflite.Interpreter(model_path="model_unquant.tflite")
interpreter.allocate_tensors()
input_details = interpreter.get_input_details()
output_details = interpreter.get_output_details()

def predict_tflite(image):
    if image is None or image.size == 0:  
        return None  

    image = cv2.resize(image, (224, 224))
    image = image.astype("float32") / 255.0
    image = np.expand_dims(image, axis=0)
    
    interpreter.set_tensor(input_details[0]['index'], image)
    interpreter.invoke()
    output = interpreter.get_tensor(output_details[0]['index'])

    confidence = np.max(output)
    prediction = np.argmax(output)

    return prediction if confidence > 0.8 else None

# ------------------- FACE & EYE DETECTION SETUP -------------------
face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
eye_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_eye.xml")

# ------------------- CSI CAMERA SETUP -------------------
try:
    from picamera2 import Picamera2
    picam2 = Picamera2()
    
    # Simple configuration without format specification
    config = picam2.create_preview_configuration(
        main={"size": (640, 480)}
    )
    picam2.configure(config)
    picam2.start()
    print("✅ CSI Camera Connected Successfully!")
except Exception as e:
    print(f"❌ CSI Camera Error: {str(e)}")
    print("Make sure the CSI camera is properly connected!")
    print(f"Error details: {str(e)}")
    exit(1)

# ------------------- DROWSINESS DETECTION VARIABLES -------------------
eye_closed_start_time = None  
face_missing_start_time = None
paused = False  
nap_alert_triggered = False  

EYE_CLOSED_DURATION = 4.0  # Seconds
EYE_CONSECUTIVE_FRAMES = 3  
FACE_MISSING_THRESHOLD = 3  # Seconds before triggering continuous buzzer

yawning_timestamps = deque(maxlen=3)

# Firebase initialization
cred = credentials.Certificate("path/to/your/serviceAccountKey.json")
firebase_admin.initialize_app(cred)
db = firestore.client()

# Add this function to send alerts
def send_drowsiness_alert(alert_type, message):
    try:
        if not message or not alert_type:
            print("Invalid alert data")
            return

        # Get current journey
        journeys_ref = db.collection('journeys')
        active_journeys = journeys_ref.where('isActive', '==', True).get()
        
        for journey in active_journeys:
            if not journey.exists:
                continue
                
            try:
                # Add alert location to journey
                journey.reference.update({
                    'alertLocations': firestore.ArrayUnion([{
                        'latitude': YOUR_CURRENT_LAT,  # You need to implement getting current GPS coordinates
                        'longitude': YOUR_CURRENT_LONG,
                        'timestamp': datetime.datetime.now(),
                        'type': alert_type
                    }])
                })
            except Exception as e:
                print(f"Error updating journey: {e}")

        # Send alert
        alert_data = {
            'type': alert_type,
            'message': message,
            'timestamp': datetime.datetime.now(),
            'isActive': True
        }
        
        db.collection('alerts').add(alert_data)
        
    except Exception as e:
        print(f"Firebase Error: {str(e)}")

# ------------------- MAIN LOOP -------------------
try:
    consecutive_closed = 0
    alert_active = False
    
    while True:
        if paused:
            time.sleep(1)
            continue

        # Capture frame from CSI Camera
        frame = picam2.capture_array()
        
        # Add a small delay to prevent high CPU usage
        time.sleep(0.1)  # 100ms delay
        
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = face_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=4)

        # ------------------- FACE MISSING DETECTION -------------------
        if len(faces) == 0:
            if face_missing_start_time is None:
                face_missing_start_time = time.time()
                update_lcd_status("No Face Detected")
            elif time.time() - face_missing_start_time >= FACE_MISSING_THRESHOLD:
                update_lcd_status("DRIVER MISSING!", "ALERT!")
                buzzer_alert("DRIVER MISSING!")
            continue  
        else:
            face_missing_start_time = None
            GPIO.output(BUZZER_PIN, GPIO.LOW)
            update_lcd_status("Driver Detected", "System Normal")

        for (x, y, w, h) in faces:
            roi_color = frame[y:y+h, x:x+w]

            # ------------------- DROWSINESS DETECTION -------------------
            labels = ["Eye open", "Eye close", "Open mouth"]
            predicted_class = predict_tflite(roi_color)
            
            if predicted_class is None:
                continue  

            detected_label = labels[predicted_class]

            if predicted_class == 1:  # "Eye close"
                consecutive_closed += 1
                if consecutive_closed >= EYE_CONSECUTIVE_FRAMES:
                    if eye_closed_start_time is None:
                        eye_closed_start_time = time.time()
                        update_lcd_status("Eyes Closed", "Monitoring...")
                    elif time.time() - eye_closed_start_time >= EYE_CLOSED_DURATION:
                        if not alert_active:
                            update_lcd_status("WAKE UP!", "Eyes Closed 4s")
                            alert_active = True
                            send_drowsiness_alert('drowsy', 'Driver drowsiness detected - Eyes closed for too long!')
                        buzzer_alert("WAKE UP!")
            elif predicted_class == 0:  # "Eye open"
                consecutive_closed = 0
                eye_closed_start_time = None
                if alert_active:
                    GPIO.output(BUZZER_PIN, GPIO.LOW)
                    alert_active = False
                    update_lcd_status("Eyes Open", "System Normal")

            # ------------------- YAWNING DETECTION -------------------
            if predicted_class == 2:  # "Open mouth"
                yawning_timestamps.append(time.time())

                while yawning_timestamps and time.time() - yawning_timestamps[0] > 60:
                    yawning_timestamps.popleft()

                yawn_count = len(yawning_timestamps)
                update_lcd_status(f"Yawning Detected", f"Count: {yawn_count}/3")

                if yawn_count >= 3 and not nap_alert_triggered:
                    update_lcd_status("Take a Break!", "Too Many Yawns")
                    nap_alert_triggered = True
                    send_drowsiness_alert('fatigue', 'Driver fatigue detected - Multiple yawns!')
                    yawning_timestamps.clear()

        cv2.imshow("Driver Monitoring", frame)
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

except KeyboardInterrupt:
    print("\n🛑 Program manually stopped. Cleaning up...")
    update_lcd_status("System Stopped", "Cleaning up...")
    GPIO.output(BUZZER_PIN, GPIO.LOW)

finally:
    cv2.destroyAllWindows()
    if lcd is not None:
        try:
            lcd.clear()
            lcd.write_string("System Off")
            time.sleep(1)
            lcd.clear()
            lcd.close(clear=True)
        except:
            pass
    GPIO.cleanup()
    print("✅ Resources released. Safe exit!")