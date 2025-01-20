import os
import asyncio
from datetime import datetime, timedelta
import pytz
from viam.robot.client import RobotClient
from viam.services.generic import Generic
from viam.components.sensor import Sensor
from gpiozero import Button
import tkinter as tk
from tkinter import Label, font
import cv2
from PIL import Image, ImageTk
import threading
import queue
import sys

# Set the DISPLAY environment variable to HDMI 0
os.environ["DISPLAY"] = ":0"

# Define the GPIO pin connected to the push button
BUTTON_PIN = 17  # Replace with your GPIO pin number
button = Button(BUTTON_PIN, pull_up=False)

# Create thread-safe queues to share data between threads
video_queue = queue.Queue()
message_queue = queue.Queue()
button_queue = queue.Queue()

# Global list to store upcoming events
upcoming_events = []

# Global variable to track the notification window
notification_window = None

# Global variable to store the VideoApp instance
app = None

class VideoApp:
    def __init__(self, root):
        self.root = root
        self.video_source = None
        self.timer_running = False
        self.video_playing = True

        # Configure the root window
        self.root.attributes('-fullscreen', True)
        self.root.bind('<Escape>', lambda e: self.root.withdraw())

        # Create a label for video display
        self.video_label = Label(self.root, text="", font=("Arial", 24))
        self.video_label.pack(fill=tk.BOTH, expand=True)

        # Get the screen width and height for fullscreen
        self.screen_width = self.root.winfo_screenwidth()
        self.screen_height = self.root.winfo_screenheight()

        # Start the video loop
        self.update_video()

    def set_video_source(self, video_source):
        """Set the video source and restart the video."""
        if video_source != self.video_source:
            print(f"Changing video to: {video_source}")
            self.video_source = video_source
            if hasattr(self, 'cap') and self.cap.isOpened():
                self.cap.release()
            if video_source is not None:
                self.cap = cv2.VideoCapture(self.video_source)
                self.video_playing = True
            else:
                self.video_playing = False

    def update_video(self):
        """Update the video frame or display messages."""
        if not self.video_playing:
            # If video is paused, skip updates
            self.root.after(100, self.update_video)
            return

        # Check if the video_label widget still exists
        if not self.video_label.winfo_exists():
            return  # Stop the video loop if the widget is destroyed

        if hasattr(self, 'cap') and self.cap.isOpened():
            ret, frame = self.cap.read()
            if ret:
                # Convert the frame to RGB
                frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

                # Resize the frame to fit the screen
                frame = cv2.resize(frame, (self.screen_width, self.screen_height))

                # Convert the frame to a PhotoImage
                img = ImageTk.PhotoImage(image=Image.fromarray(frame))

                # Display the frame
                self.video_label.config(image=img)
                self.video_label.image = img
            else:
                # Reset the video to the beginning if it reaches the end
                self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)

        # Schedule the next frame update
        self.root.after(30, self.update_video)

    def display_message(self, message):
        """Display a message in the Tkinter window."""
        self.video_label.config(image=None)
        self.video_label.config(text=message)

    def start_pomodoro_timer(self, duration):
        """Start a Pomodoro timer and display the countdown."""
        self.timer_running = True
        self.video_playing = False
        self.display_message(f"Pomodoro Timer: {duration} minutes")

        def countdown(remaining):
            if remaining > 0:
                self.display_message(f"Pomodoro Timer: {remaining} minutes")
                self.root.after(60000, countdown, remaining - 1)  # Update every minute
            else:
                self.timer_running = False
                self.display_message("Timer ended. Resuming video playback.")
                self.video_playing = True
                self.root.after(3000, self.update_video)  # Resume video after 3 seconds

        countdown(duration)

    def __del__(self):
        # Release the video capture when done
        if hasattr(self, 'cap') and self.cap.isOpened():
            self.cap.release()

def clear_window(root):
    """Clear all widgets from the Tkinter window."""
    for widget in root.winfo_children():
        widget.destroy()

def create_meeting_notification(meeting_name, start_time, app):
    """
    Creates a full-screen meeting notification window using Toplevel.
    """
    global notification_window

    # Destroy the existing notification window if it is open
    if notification_window is not None and notification_window.winfo_exists():
        notification_window.destroy()

    # Create a new notification window as a Toplevel window
    notification_window = tk.Toplevel()
    notification_window.title("Upcoming Meeting")
    notification_window.configure(bg="black")
    notification_window.attributes('-fullscreen', True)  # Make the window full-screen

    # Create Orbitron font
    orbitron_font = font.Font(family="Orbitron", size=40, weight="bold")
    orbitron_font_small = font.Font(family="Orbitron", size=35, weight="normal")

    # Center elements vertically and horizontally using grid
    notification_window.rowconfigure(0, weight=1)  # Make the first row expand to fill available space
    notification_window.columnconfigure(0, weight=1)  # Create labels
    headline_label = Label(notification_window, text="Meeting Upcoming", font=orbitron_font, fg="white", bg="black")
    meeting_name_label = Label(notification_window, text=meeting_name, font=orbitron_font_small, fg="white", bg="black")
    start_time_label = Label(notification_window, text=start_time, font=orbitron_font_small, fg="white", bg="black")

    # Create dismiss button using tkinter.Button
    dismiss_button = tk.Button(notification_window, text="Dismiss", font=orbitron_font_small, fg="white", bg="black", command=lambda: close_notification(notification_window, app))

    # Center elements horizontally using grid and columnspan
    headline_label.grid(row=0, column=0, columnspan=2, padx=20, pady=20)
    meeting_name_label.grid(row=1, column=0, columnspan=2, padx=20, pady=10)
    start_time_label.grid(row=2, column=0, columnspan=2, padx=20, pady=10)
    dismiss_button.grid(row=3, column=0, columnspan=2, padx=20, pady=80)

def close_notification(window, app):
    """
    Closes the notification window and resumes normal video playback.
    """
    global notification_window
    if window and window.winfo_exists():
        window.destroy()
    notification_window = None

    # Reset the main application to play the default video
    if hasattr(app, 'set_video_source'):
        app.set_video_source("animations/blink.mp4")

async def monitor_sensors(machine, app):
    """Monitor sensor data and update the video source dynamically."""
    previous_video_path = None
    while True:
        ens_160 = Sensor.from_robot(machine, "ENS160")
        ens_160_return_value = await ens_160.get_readings()

        temt_6000 = Sensor.from_robot(machine, "TEMT6000")
        temt_6000_return_value = await temt_6000.get_readings()

        video_path = "animations/blink.mp4"  # Default video

        if 'eCO2' in ens_160_return_value:
            if ens_160_return_value['eCO2'] in range(500, 750):
                video_path = "animations/yellow.mp4"
            elif ens_160_return_value['eCO2'] in range(750, 1500):
                video_path = "animations/red.mp4"

        if 'light_intensity' in temt_6000_return_value:
            if temt_6000_return_value['light_intensity'] < 10:
                video_path = "animations/black.mp4"

        if video_path != previous_video_path:
            previous_video_path = video_path
            app.set_video_source(video_path)

        await asyncio.sleep(1)

def start_tkinter(machine, loop):
    """Start the Tkinter main loop and handle video updates."""
    global app
    root = tk.Tk()
    app = VideoApp(root)

    # Set the default video source
    app.set_video_source("animations/blink.mp4")

    # Schedule the monitor_sensors coroutine in the main event loop
    asyncio.run_coroutine_threadsafe(monitor_sensors(machine, app), loop)

    def process_queues():
        """Process video paths and messages from the queues."""
        try:
            while True:
                video_path = video_queue.get_nowait()
                app.set_video_source(video_path)
        except queue.Empty:
            pass

        try:
            while True:
                message = message_queue.get_nowait()
                app.display_message(message)
        except queue.Empty:
            pass

        try:
            while True:
                button_press = button_queue.get_nowait()
                if button_press == "Button Pressed!":
                    print("Button press detected! Fetching events...")
                    # Clear the current window and start the Pomodoro timer
                    clear_window(root)
                    handle_button_press(root, machine, loop)
        except queue.Empty:
            pass

        # Schedule the next queue check
        root.after(100, process_queues)

    # Start processing the queues
    root.after(100, process_queues)
    root.mainloop()

def handle_button_press(root, machine, loop):
    """Handle button press: show meeting notification or start Pomodoro timer."""
    global notification_window

    # Destroy the existing notification window if it is open
    if notification_window is not None and notification_window.winfo_exists():
        notification_window.destroy()
        notification_window = None

    # Clear the window contents
    clear_window(root)

    # Configure the root window
    root.configure(bg="#1e1e2e")  # Set background color

    # Load Google Font
    custom_font = font.Font(family="Orbitron", size=150)

    # Create and configure the timer label
    timer_label = tk.Label(root, text="00:00", font=custom_font, fg="#ffffff", bg="#1e1e2e")
    timer_label.pack(expand=True)

    # Set the duration for the countdown (e.g., 25 minutes = 1500 seconds)
    countdown_duration = 1500  # Change this for different durations

    def start_countdown(duration):
        """Start the countdown with the specified duration in seconds."""
        def update_timer():
            nonlocal duration
            if duration > 0:
                # Check if the label still exists
                if timer_label.winfo_exists():
                    minutes, seconds = divmod(duration, 60)
                    timer_label.config(text=f"{minutes:02}:{seconds:02}")
                    duration -= 1
                    root.after(1000, update_timer)  # Schedule the next update
            else:
                # Timer finished
                if timer_label.winfo_exists():
                    timer_label.config(text="00:00")
                # Clear the window and restart the video
                clear_window(root)
                app = VideoApp(root)
                app.set_video_source("animations/blink.mp4")
                asyncio.run_coroutine_threadsafe(monitor_sensors(machine, app), loop)

        update_timer()

    # Start the countdown
    start_countdown(countdown_duration)

    # Close the window with the Escape key
    def close(event):
        # Clear the window and restart the video
        clear_window(root)
        app = VideoApp(root)
        app.set_video_source("animations/blink.mp4")
        # Restart the sensor monitoring loop
        asyncio.run_coroutine_threadsafe(monitor_sensors(machine, app), loop)

    root.bind("<Escape>", close)

def monitor_button():
    """Monitor the button press in a separate thread."""
    while True:
        if button.is_pressed:
            print("Button pressed! Adding to queue...")
            button_queue.put("Button Pressed!")
        threading.Event().wait(0.1)  # Poll every 100ms

async def get_events_and_check_alerts(machine):
    """Fetch events from the calendar service and check for upcoming events within 15 minutes."""
    try:
        calendar = Generic.from_robot(robot=machine, name="Calendar")
        command = {"get_events": {"max_results": 10}}
        result = await calendar.do_command(command)
        print("Calendar response:", result)  # Debugging output

        if not result or "events" not in result:
            print("No events found or invalid response format.")
            return []

        tz = pytz.timezone('Asia/Kolkata')
        current_time = datetime.now(tz)
        alert_time_threshold = current_time + timedelta(minutes=15)  # Change to 15 minutes

        events_within_threshold = []

        for event in result.get("events", []):
            start_time_str = event.get("start")
            end_time_str = event.get("end")

            if isinstance(start_time_str, str) and isinstance(end_time_str, str):
                try:
                    # Parse the start time and make it timezone-aware
                    event_start = datetime.fromisoformat(start_time_str)
                    event_start = event_start.astimezone(tz)

                    # Debugging: Print the event start time and current time
                    print(f"Event start: {event_start}, Current time: {current_time}, Threshold: {alert_time_threshold}")

                    # Check if the event is within the next 15 minutes
                    if current_time <= event_start <= alert_time_threshold:
                        events_within_threshold.append(event)
                except ValueError as e:
                    print(f"Skipping event with invalid times: {start_time_str}, {end_time_str}, Error: {e}")

        print("Parsed events:", events_within_threshold)  # Debugging output
        return events_within_threshold

    except Exception as e:
        print(f"Error fetching events: {e}")
        return []

async def check_for_upcoming_meetings(machine, app):
    """Check for upcoming meetings and display notifications if any event is within 15 minutes."""
    global upcoming_events
    while True:
        events = await get_events_and_check_alerts(machine)
        
        # Check for new events
        new_events = [event for event in events if event not in upcoming_events]
        if new_events:
            print("New events found:")
            for event in new_events:
                meeting_name = event.get('summary', 'No Summary')
                start_time = datetime.fromisoformat(event['start']).strftime('%H:%M')
                print(f"- {meeting_name} at {start_time}")
                # Display a notification for the upcoming event
                create_meeting_notification(meeting_name, start_time, app)
        
        # Update the global list of upcoming events
        upcoming_events = events
        
        await asyncio.sleep(60)  # Check every minute

async def connect():
    opts = RobotClient.Options.with_api_key( 
        api_key='3nlxs7c6qglbpxxxxxxx549gk9jzfwrv',
        api_key_id='c97bc8a1-xxxx-xxxx-a716-b4a5059b0a54'
    )
    return await RobotClient.at_address('pomodoro-main.xxxxxxxxxx.viam.cloud', opts)

async def main():
    """Main function to run the program."""
    machine = await connect()

    # Get the main event loop
    loop = asyncio.get_event_loop()

    # Start Tkinter in a separate thread
    tk_thread = threading.Thread(target=start_tkinter, args=(machine, loop), daemon=True)
    tk_thread.start()

    # Start button monitoring in a separate thread
    button_thread = threading.Thread(target=monitor_button, daemon=True)
    button_thread.start()

    # Wait for the Tkinter app to initialize
    while app is None:
        await asyncio.sleep(0.1)

    # Start meeting check in a separate task
    asyncio.create_task(check_for_upcoming_meetings(machine, app))

    # Main async loop to handle sensor data and video updates
    previous_video_path = None
    try:
        while True:
            ens_160 = Sensor.from_robot(machine, "ENS160")
            ens_160_return_value = await ens_160.get_readings()

            temt_6000 = Sensor.from_robot(machine, "TEMT6000")
            temt_6000_return_value = await temt_6000.get_readings()

            video_path = "animations/blink.mp4"  # Default video

            if 'eCO2' in ens_160_return_value:
                if ens_160_return_value['eCO2'] in range(500, 750):
                    video_path = "animations/yellow.mp4"
                elif ens_160_return_value['eCO2'] in range(750, 1500):
                    video_path = "animations/red.mp4"

            if 'light_intensity' in temt_6000_return_value:
                if temt_6000_return_value['light_intensity'] < 10:
                    video_path = "animations/black.mp4"

            if video_path != previous_video_path:
                previous_video_path = video_path
                video_queue.put(video_path)

            await asyncio.sleep(1)
    except KeyboardInterrupt:
        print("Keyboard interrupt received. Exiting gracefully...")
    finally:
        # Cleanup code
        if machine:
            await machine.close()
        if button:
            button.close()
        if notification_window and notification_window.winfo_exists():
            notification_window.destroy()
        sys.exit(0)

# Run the program
if __name__ == "__main__":
    asyncio.run(main())