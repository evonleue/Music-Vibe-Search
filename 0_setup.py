"""
Music Vibe Search - Main Menu

Single entry point for both first-time setup and daily use.

  * No configuration found: Setup mode.
  * Configuration intact:   Main Menu (search/playlist, rescan, exit).
"""

import os
import sys
import json
import sqlite3
import subprocess
from pathlib import Path

APP_NAME = "Music-Vibe-Search"

APP_DATA_DIR = (
    Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    / APP_NAME
)

CONFIG_PATH = APP_DATA_DIR / "config.json"
DB_PATH = APP_DATA_DIR / "music_fingerprints.db"
PLAYLIST_PATH = APP_DATA_DIR / "Latest_Vibe_Playlist.m3u"
LOG_DIR = APP_DATA_DIR / "logs"

SCRIPT_DIR = Path(__file__).resolve().parent
SCANNER_SCRIPT = SCRIPT_DIR / "1_scan_music.py"
SEARCH_SCRIPT = SCRIPT_DIR / "2_search_music.py"

SUPPORTED_EXTENSIONS = {".mp3", ".wav", ".flac", ".m4a", ".ogg"}

# Current observed scanner rate: approximately 0.7 seconds per audio file.
SECONDS_PER_FILE = 0.7

CONFIG_VERSION = 1


# ------------------------------------------------------------
# Basic configuration
# ------------------------------------------------------------

def ensure_app_data():
    APP_DATA_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)


def save_config(library_root):
    ensure_app_data()

    config = {
        "library_root": str(library_root),
        "db_path": str(DB_PATH),
        "playlist_path": str(PLAYLIST_PATH),
        "version": CONFIG_VERSION,
    }

    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=4)

    return config


def load_config():
    if not CONFIG_PATH.exists():
        return None

    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print()
        print("ERROR: Unable to read the configuration file.")
        print()
        print(e)
        return None


# ------------------------------------------------------------
# Library validation
# ------------------------------------------------------------

def count_audio_files(root):
    count = 0

    for path in root.rglob("*"):
        try:
            if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS:
                count += 1
        except OSError:
            # Skip unreadable entries (permissions, broken links, etc.)
            continue

    return count


def format_time_estimate(audio_count):
    total_seconds = audio_count * SECONDS_PER_FILE

    hours = int(total_seconds // 3600)
    minutes = int((total_seconds % 3600) // 60)

    if hours > 0:
        if minutes > 0:
            return f"approximately {hours} hr {minutes} min"
        return f"approximately {hours} hr"

    if minutes > 0:
        return f"approximately {minutes} min"

    seconds = max(1, int(total_seconds))
    return f"approximately {seconds} sec"


def show_scan_estimate(audio_count):
    print()
    print(f"Files to process: {audio_count:,}")
    print(f"Estimated scan time: {format_time_estimate(audio_count)}")
    print()


# ------------------------------------------------------------
# Folder selection
# ------------------------------------------------------------

def choose_folder():
    """Open a folder picker; fall back to typed input if Tk is unavailable."""
    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        selected = filedialog.askdirectory(title="Select your music library folder")
        root.destroy()

        if selected:
            return Path(selected)
        return None
    except Exception:
        typed = input("Enter the full path to your music folder: ").strip().strip('"')
        return Path(typed) if typed else None


def prompt_for_library():
    """Loop until the user picks a valid folder containing audio, or cancels."""
    while True:
        print("Choose the folder that contains your music...")
        folder = choose_folder()

        if folder is None:
            print("No folder selected.")
            if not confirm("Try again?"):
                return None, 0
            continue

        if not folder.is_dir():
            print(f"Not a valid folder: {folder}")
            continue

        print(f"Scanning folder for audio files: {folder}")
        audio_count = count_audio_files(folder)

        if audio_count == 0:
            print("No supported audio files found there.")
            print(f"Supported types: {', '.join(sorted(SUPPORTED_EXTENSIONS))}")
            if not confirm("Choose a different folder?"):
                return None, 0
            continue

        return folder, audio_count


# ------------------------------------------------------------
# Helpers
# ------------------------------------------------------------

def confirm(question, default=True):
    suffix = " [Y/n]: " if default else " [y/N]: "
    answer = input(question + suffix).strip().lower()

    if not answer:
        return default
    return answer in ("y", "yes")


def pause():
    input("\nPress Enter to continue...")


def clear_screen():
    if os.name == "nt":
        os.system("")      # enables ANSI escape codes in the Windows console
        os.system("cls")
    else:
        os.system("clear")
    # Also clear any scrollback so old menus can't be scrolled back to.
    print("\033[3J", end="", flush=True)


def banner():
    print()
    print("=" * 50)
    print("             MUSIC VIBE SEARCH")
    print("=" * 50)


def build_env(config):
    """Environment passed to the child scripts so they share one config."""
    env = os.environ.copy()
    env["MUSIC_VIBE_CONFIG"] = str(CONFIG_PATH)
    env["MUSIC_VIBE_LIBRARY"] = config["library_root"]
    env["MUSIC_VIBE_DB"] = config["db_path"]
    env["MUSIC_VIBE_PLAYLIST"] = config["playlist_path"]
    env["MUSIC_VIBE_LOG_DIR"] = str(LOG_DIR)
    return env


def run_script(script_path, config, extra_args=None):
    """Run a sibling script with the current Python interpreter."""
    if not script_path.exists():
        print()
        print(f"ERROR: Required script not found: {script_path}")
        pause()
        return False

    try:
        result = subprocess.run(
            [sys.executable, str(script_path)] + list(extra_args or []),
            env=build_env(config),
            cwd=str(SCRIPT_DIR),
        )
    except KeyboardInterrupt:
        print("\nInterrupted.")
        return False

    if result.returncode != 0:
        print()
        print(f"{script_path.name} exited with code {result.returncode}.")
        pause()
        return False

    return True


def database_exists():
    return DB_PATH.exists() and DB_PATH.stat().st_size > 0


# ------------------------------------------------------------
# Actions
# ------------------------------------------------------------

def run_scan(config, force=False):
    library = Path(config["library_root"])

    if not library.is_dir():
        print()
        print(f"Library folder not found: {library}")
        print("Delete the configuration file to run setup again:")
        print(f"  {CONFIG_PATH}")
        pause()
        return False

    print()
    print("Counting audio files...")
    audio_count = count_audio_files(library)
    show_scan_estimate(audio_count)

    if audio_count == 0:
        print("Nothing to scan.")
        pause()
        return False

    if force:
        print("Full rebuild reprocesses EVERY track, including ones already")
        print("in the database. This can take a long time.")
        if not confirm("Continue with full rebuild?", default=False):
            return False
        return run_script(SCANNER_SCRIPT, config, ["--force"])

    if not confirm("Start scan now?"):
        return False

    return run_script(SCANNER_SCRIPT, config)


def first_run_setup():
    banner()
    print()
    print("Welcome! Let's get your library set up.")
    print()

    folder, audio_count = prompt_for_library()

    if folder is None:
        print("Setup cancelled.")
        return None

    show_scan_estimate(audio_count)

    config = save_config(folder)
    print(f"Settings saved to: {CONFIG_PATH}")

    if confirm("Run the first scan now?"):
        run_script(SCANNER_SCRIPT, config)
    else:
        print("You can scan later from the main menu.")

    return config


def search_music(config):
    if not database_exists():
        print()
        print("No music database found yet. Run a scan first.")
        pause()
        return

    run_script(SEARCH_SCRIPT, config)

    if PLAYLIST_PATH.exists():
        print()
        print(f"Latest playlist: {PLAYLIST_PATH}")


# ------------------------------------------------------------
# Main menu
# ------------------------------------------------------------

def main_menu(config):
    while True:
        clear_screen()
        banner()
        print()
        print("  1) Search music and run playlist")
        print("  2) Rescan music")
        print("  3) Full rebuild (reprocess all music)")
        print("  4) Exit")
        print()

        choice = input("Select an option: ").strip()

        if choice == "1":
            search_music(config)
        elif choice == "2":
            run_scan(config)
            pause()
        elif choice == "3":
            run_scan(config, force=True)
            pause()
        elif choice == "4":
            print("Goodbye!")
            return
        else:
            print("Invalid choice.")


def main():
    ensure_app_data()

    config = load_config()

    if config is None or not config.get("library_root"):
        # Setup mode: no valid configuration found.
        config = first_run_setup()
        if config is None:
            return

    # Main Menu mode: configuration is intact.
    main_menu(config)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nExiting.")
