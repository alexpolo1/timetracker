#!/usr/bin/env python3

import json
import os
import sys
import threading
import time
from datetime import datetime, timedelta
import csv
import termios
import tty
import signal

# Constants
TIME_ENTRIES_FILE = os.path.expanduser('~/scripts/time_entries.json')
LOG_FILE = os.path.expanduser('~/scripts/logs/time_tracker.log')
EXPORT_DIR = os.path.expanduser('~/scripts/export')
MASTER_CSV_FILE = os.path.join(EXPORT_DIR, 'time_tracker_log.csv')
WEEKLY_CSV_DAY = 'Friday'
WEEKLY_CSV_TIME = '16:00'
MAX_DURATION = timedelta(hours=7, minutes=40)

# Ensure necessary directories exist
os.makedirs(EXPORT_DIR, exist_ok=True)
os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)

# Initialize global variables
is_tracking = False
start_time = None
stop_event = threading.Event()
auto_stop_timer = None
csv_lock = threading.Lock()

def log(message):
    """Append a message to the log file with a timestamp."""
    timestamp = datetime.now().strftime('%d-%m-%Y %H:%M:%S')
    with open(LOG_FILE, 'a') as f:
        f.write(f"[{timestamp}] {message}\n")

def load_time_entries():
    """Load time entries from the JSON file."""
    if not os.path.exists(TIME_ENTRIES_FILE):
        return []
    with open(TIME_ENTRIES_FILE, 'r') as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return []

def save_time_entries(entries):
    """Save time entries to the JSON file."""
    with open(TIME_ENTRIES_FILE, 'w') as f:
        json.dump(entries, f, indent=4)

def append_time_entry(entry):
    """Append a single time entry to the JSON and CSV files."""
    entries = load_time_entries()
    entries.append(entry)
    save_time_entries(entries)
    append_to_csv(entry)

def append_to_csv(entry):
    """Append a single time entry to the master CSV file."""
    with csv_lock:
        file_exists = os.path.isfile(MASTER_CSV_FILE)
        try:
            with open(MASTER_CSV_FILE, 'a', newline='', encoding='utf-8') as csvfile:
                writer = csv.writer(csvfile)
                if not file_exists:
                    # Write headers if CSV doesn't exist
                    writer.writerow(['Dato', 'Starttid', 'Sluttid', 'Varighed'])
                writer.writerow([
                    entry["date"],
                    entry["start_time"],
                    entry["end_time"],
                    entry["duration"]
                ])
        except Exception as e:
            log(f"Error appending to CSV: {e}")
            print(f"\nFejl ved opdatering af CSV: {e}")

def get_key_press():
    """Capture a single key press without waiting for Enter."""
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setraw(sys.stdin.fileno())
        ch = sys.stdin.read(1)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
    return ch

def start_tracking():
    """Start tracking time."""
    global is_tracking, start_time, auto_stop_timer
    if is_tracking:
        print("Tidsregistrering er allerede startet.")
        return
    is_tracking = True
    start_time = datetime.now()
    print(f"Intern arbejde registrering startet kl. {start_time.strftime('%H:%M:%S')}.")
    log("Intern arbejde registrering startet.")

    # Start the auto-stop timer as a daemon thread
    auto_stop_timer = threading.Timer(MAX_DURATION.total_seconds(), auto_stop)
    auto_stop_timer.daemon = True
    auto_stop_timer.start()

    # Start the timer display thread as a daemon
    threading.Thread(target=display_timer, daemon=True).start()

    # Start the key listening thread as a daemon
    threading.Thread(target=listen_for_stop, daemon=True).start()

def stop_tracking(manual=False):
    """Stop tracking time."""
    global is_tracking, start_time, auto_stop_timer
    if not is_tracking:
        print("Ingen aktiv tidsregistrering at stoppe.")
        return
    end_time = datetime.now()
    duration = end_time - start_time
    hours, remainder = divmod(int(duration.total_seconds()), 3600)
    minutes, seconds = divmod(remainder, 60)

    # Cancel the auto-stop timer if still running
    if auto_stop_timer and auto_stop_timer.is_alive():
        auto_stop_timer.cancel()

    # Log and display the stop event
    if manual:
        print(f"\nIntern arbejde registrering stoppet manuelt kl. {end_time.strftime('%H:%M:%S')}. Varighed: {hours}h {minutes}m.")
        log(f"Intern arbejde registrering stoppet manuelt. Varighed: {hours}h{minutes}m.")
    else:
        print(f"\nIntern arbejde registrering stoppet automatisk kl. {end_time.strftime('%H:%M:%S')}. Varighed: {hours}h {minutes}m.")
        log(f"Intern arbejde registrering stoppet automatisk. Varighed: {hours}h{minutes}m.")

    # Append the entry to the JSON and CSV files
    entry = {
        "date": start_time.strftime('%d-%m-%Y'),
        "start_time": start_time.strftime('%H:%M:%S'),
        "end_time": end_time.strftime('%H:%M:%S'),
        "duration": f"{hours}h{minutes}m"
    }
    append_time_entry(entry)

    is_tracking = False
    stop_event.set()

    # Notify user about the CSV entry
    csv_path = os.path.abspath(MASTER_CSV_FILE)
    print(f"Data er tilføjet til CSV: {csv_path}")
    log(f"Data er tilføjet til CSV: {csv_path}")

def auto_stop():
    """Automatically stop tracking after MAX_DURATION."""
    stop_tracking(manual=False)

def display_timer():
    """Continuously display the elapsed time."""
    while is_tracking and not stop_event.is_set():
        elapsed = datetime.now() - start_time
        hours, remainder = divmod(int(elapsed.total_seconds()), 3600)
        minutes, seconds = divmod(remainder, 60)
        print(f"\rTid registreret: {hours:02d}:{minutes:02d}:{seconds:02d}. Tryk 'd' for at stoppe.", end='', flush=True)
        time.sleep(1)

def listen_for_stop():
    """Listen for 'd' key press to stop tracking."""
    while is_tracking and not stop_event.is_set():
        key = get_key_press()
        if key.lower() == 'd':
            stop_tracking(manual=True)
            break

def schedule_weekly_csv():
    """Schedule weekly CSV generation every Friday at WEEKLY_CSV_TIME."""
    now = datetime.now()
    target_time = datetime.strptime(WEEKLY_CSV_TIME, '%H:%M').time()
    days_ahead = (datetime.strptime(WEEKLY_CSV_DAY, '%A').weekday() - now.weekday()) % 7
    if days_ahead == 0 and now.time() > target_time:
        days_ahead = 7
    next_run = now + timedelta(days=days_ahead)
    next_run = next_run.replace(hour=target_time.hour, minute=target_time.minute, second=0, microsecond=0)
    delay = (next_run - now).total_seconds()

    # Create and start the Timer as a daemon thread
    t = threading.Timer(delay, generate_weekly_csv)
    t.daemon = True
    t.start()

    log(f"Weekly CSV scheduled to run at {next_run.strftime('%A %H:%M:%S')}.")
    print(f"\nWeekly CSV scheduled to run at {next_run.strftime('%A %H:%M:%S')}.")
    
def generate_weekly_csv():
    """Generate a weekly CSV summarizing time entries."""
    now = datetime.now()
    start_of_week = now - timedelta(days=now.weekday())  # Monday
    end_of_week = start_of_week + timedelta(days=6)     # Sunday

    # Load entries
    entries = load_time_entries()

    # Filter entries for the current week
    weekly_entries = [
        entry for entry in entries
        if start_of_week.strftime('%d-%m-%Y') <= entry["date"] <= end_of_week.strftime('%d-%m-%Y')
    ]

    if not weekly_entries:
        log("Ingen tidsregistreringer fundet for denne uge.")
        print("\nIngen tidsregistreringer fundet for denne uge.")
    else:
        # Define CSV headers
        headers = ['Dato', 'Starttid', 'Sluttid', 'Varighed']

        # Define CSV file path
        csv_filename = f"time_tracker_weekly_{end_of_week.strftime('%Y-%m-%d')}.csv"
        csv_filepath = os.path.join(EXPORT_DIR, csv_filename)

        # Write to CSV
        try:
            with open(csv_filepath, 'w', newline='', encoding='utf-8') as csvfile:
                writer = csv.writer(csvfile)
                writer.writerow(headers)
                for entry in weekly_entries:
                    writer.writerow([
                        entry["date"],
                        entry["start_time"],
                        entry["end_time"],
                        entry["duration"]
                    ])
            log(f"Weekly CSV generated: {csv_filename}")
            print(f"\nUge CSV fil genereret: {csv_filename} - Sti: {os.path.abspath(csv_filepath)}")
        except Exception as e:
            log(f"Error generating weekly CSV: {e}")
            print(f"\nFejl ved generering af CSV: {e}")

    # Schedule the next weekly CSV
    schedule_weekly_csv()

def handle_exit(signum, frame):
    """Handle script exit gracefully."""
    if is_tracking:
        stop_tracking(manual=False)
    else:
        stop_event.set()
    print("\nTime Tracker script afsluttet.")
    log("Time Tracker script afsluttet.")
    # Do NOT call sys.exit(0) here to allow main thread to handle the exit

def main():
    """Main function to run the Time Registration Tracker."""
    # Handle exit signals
    signal.signal(signal.SIGINT, handle_exit)
    signal.signal(signal.SIGTERM, handle_exit)

    # Schedule the first weekly CSV
    schedule_weekly_csv()

    # Prompt to start tracking
    print("Vil du starte med at registrere intern arbejde for i dag? (y/N): ", end='', flush=True)
    while True:
        key = get_key_press()
        if key.lower() == 'y':
            start_tracking()
            break
        elif key.lower() == 'n':
            print("\nTidsregistrering afbrudt.")
            log("Tidsregistrering afbrudt af bruger.")
            sys.exit(0)
        else:
            print("\nUgyldigt input. Tryk 'y' for at starte eller 'n' for at afbryde: ", end='', flush=True)

    # Wait for tracking to stop
    stop_event.wait()

    # Exit the script
    print("Script afsluttes...")
    log("Script afsluttes...")
    sys.exit(0)

if __name__ == "__main__":
    main()

