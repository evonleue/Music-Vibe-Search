import os
import sys
import subprocess
import sqlite3
import random
import tkinter as tk
from tkinter import messagebox
import numpy as np
from pathlib import Path, PureWindowsPath
import json


APP_NAME = "Music-Vibe-Search"

APP_DATA_DIR = (
    Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    / APP_NAME
)

CONFIG_PATH = APP_DATA_DIR / "config.json"


def load_config():
    if not CONFIG_PATH.exists():
        return None

    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


CONFIG = load_config()

if not CONFIG:
    raise RuntimeError(
        "Music Vibe Search configuration could not be loaded."
    )

try:
    DB_PATH = Path(CONFIG["db_path"])
    M3U_OUTPUT_PATH = Path(CONFIG["playlist_path"])
except KeyError as e:
    raise RuntimeError(
        f"Music Vibe Search configuration is missing: {e}"
    )


CORE_BLACKLIST = {'audiobooks', 'sound effects', 'comedy', 'soundtrack'}
HOLIDAY_FOLDERS = {'christmas', 'halloween'}


def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def get_vibe_matches_within_threshold(seed_absolute_path, max_distance_threshold=0.05, include_holiday=False, is_preview=False):
    """Computes Euclidean distance across population-standardized Z-scores."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT path, energy_mean, energy_std, bright_mean, bright_std, flatness_mean,
                   mfcc_0, mfcc_1, mfcc_2, mfcc_3, mfcc_4
            FROM tracks
        """)
        all_rows = cursor.fetchall()
        if not all_rows:
            return []

        paths = [r['path'] for r in all_rows]
        feature_matrix = np.array([[
            r['energy_mean'], r['energy_std'], r['bright_mean'], r['bright_std'],
            r['flatness_mean'], r['mfcc_0'], r['mfcc_1'], r['mfcc_2'], r['mfcc_3'], r['mfcc_4']
        ] for r in all_rows])

        global_means = np.mean(feature_matrix, axis=0)
        global_stds = np.std(feature_matrix, axis=0)
        global_stds[global_stds == 0] = 1.0

        try:
            seed_idx = paths.index(seed_absolute_path)
            seed_raw = feature_matrix[seed_idx]
        except ValueError:
            return []

        seed_z = (seed_raw - global_means) / global_stds
        weights = np.array([2.0, 1.5, 2.0, 1.5, 4.0, 2.0, 2.5, 2.0, 2.0, 2.0])
        seed_weighted = seed_z * weights

        active_blacklist = set(CORE_BLACKLIST)
        if not include_holiday:
            active_blacklist.update(HOLIDAY_FOLDERS)

        playlist_pool = []
        for idx, track_path in enumerate(paths):
            if track_path == seed_absolute_path:
                continue

            path_parts = set(p.lower() for p in PureWindowsPath(track_path).parts)

            if path_parts.intersection(active_blacklist):
                continue

            candidate_raw = feature_matrix[idx]
            candidate_z = (candidate_raw - global_means) / global_stds
            candidate_weighted = candidate_z * weights

            total_distance = np.linalg.norm(seed_weighted - candidate_weighted)

            if total_distance <= max_distance_threshold:
                playlist_pool.append(track_path)

        return playlist_pool
    except Exception as e:
        if not is_preview:
            print(f"❌ Population search engine breakdown: {e}")
        return []
    finally:
        conn.close()


def play_playlist(playlist_path):
    """Open the M3U in the system's default media player."""
    if sys.platform.startswith("win"):
        os.startfile(str(playlist_path))
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(playlist_path)])
    else:
        subprocess.Popen(["xdg-open", str(playlist_path)])


class VibeSearchApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Music Vibe Search Engine (Gatekeeper Mode)")
        self.root.geometry("600x670")

        self.displayed_track_paths = []

        # 1. USER ACTIONS INPUT
        tk.Label(root, text="1. Type Artist or Track Keyword:", font=("Arial", 11, "bold")).pack(anchor="w", padx=20, pady=(15, 2))

        self.search_var = tk.StringVar()
        self.entry_search = tk.Entry(root, textvariable=self.search_var, font=("Arial", 12), width=55)
        self.entry_search.pack(padx=20, pady=5)
        self.entry_search.focus_set()

        # HOLIDAY TOGGLE COMPONENT
        self.holiday_var = tk.BooleanVar(value=False)
        # self.chk_holiday = tk.Checkbutton(root, text="Include Holiday Music (Christmas / Halloween)",
        #                                  variable=self.holiday_var, font=("Arial", 10), command=self.update_preview)
        # self.chk_holiday.pack(anchor="w", padx=20, pady=5)

        # 2. SELECTION DROPDOWN/LISTBOX
        tk.Label(root, text="2. Select Seed Track From Results:", font=("Arial", 11, "bold")).pack(anchor="w", padx=20, pady=(10, 2))

        list_frame = tk.Frame(root)
        list_frame.pack(padx=20, pady=5, fill="x")

        self.scrollbar = tk.Scrollbar(list_frame, orient=tk.VERTICAL)
        self.listbox = tk.Listbox(list_frame, font=("Arial", 10), width=62, height=10, yscrollcommand=self.scrollbar.set)
        self.scrollbar.config(command=self.listbox.yview)

        self.listbox.pack(side=tk.LEFT, fill="both", expand=True)
        self.scrollbar.pack(side=tk.RIGHT, fill="y")
        self.listbox.bind('<<ListboxSelect>>', self.on_track_select)

        # 3. SLIDER CONTROL STRICTION
        tk.Label(root, text="3. Adjust Vibe Strictness (Lower = Closer Match):", font=("Arial", 10, "bold")).pack(anchor="w", padx=20, pady=(10, 2))

        self.threshold_slider = tk.Scale(root, from_=0.08, to=3.00, resolution=0.05, orient=tk.HORIZONTAL, length=550, command=self.on_slider_move)
        self.threshold_slider.set(1.50)
        self.threshold_slider.pack(padx=20, pady=5)
        self.threshold_slider.bind("<Button-1>", self.snap_slider_to_pointer)

        self.lbl_live_count = tk.Label(root, text="Pool Preview: Select a seed track to begin.", fg="#2980b9", font=("Arial", 10, "bold"))
        self.lbl_live_count.pack(anchor="w", padx=20, pady=(2, 10))

        # 4. PLAYLIST GENERATOR EXECUTION
        self.btn_generate = tk.Button(root, text="4. Generate Vibe Playlist", font=("Arial", 12, "bold"), bg="#2ecc71", fg="white", command=self.generate_playlist)
        self.btn_generate.pack(fill="x", padx=20, pady=10)
        self.lbl_status = tk.Label(root, text="Ready.", fg="gray", font=("Arial", 10, "italic"))
        self.lbl_status.pack(pady=5)

        self.search_var.trace_add("write", self.on_type)

    def snap_slider_to_pointer(self, event):
        try:
            width = self.threshold_slider.winfo_width()
            slider_from = self.threshold_slider.cget("from")
            slider_to = self.threshold_slider.cget("to")
            click_val = slider_from + (float(event.x) / width) * (slider_to - slider_from)
            self.threshold_slider.set(click_val)
        except Exception:
            pass

    def on_type(self, *args):
        if not hasattr(self, 'displayed_track_paths') or not hasattr(self, 'listbox'):
            return

        q = self.search_var.get().strip()

        if len(q) < 2:
            self.listbox.delete(0, tk.END)
            self.displayed_track_paths = []
            return

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT path FROM tracks WHERE path LIKE ?",
            (f"%{q}%",)
        )
        rows = cursor.fetchall()
        conn.close()

        self.listbox.delete(0, tk.END)
        self.displayed_track_paths = [r['path'] for r in rows]

        for r in rows:
            file_name = PureWindowsPath(r['path']).name
            self.listbox.insert(tk.END, file_name)

    def get_selected_path(self):
        sel = self.listbox.curselection()

        if sel:
            # ABSOLUTE FIX: Pull index out of tuple using explicit array item 0
            idx = sel[0]

            if len(self.displayed_track_paths) > idx:
                return self.displayed_track_paths[idx]

        return None

    def on_track_select(self, event):
        self.update_preview()

    def on_slider_move(self, val):
        self.update_preview()

    def update_preview(self):
        path = self.get_selected_path()

        if path:
            thresh = self.threshold_slider.get()
            inc_holiday = self.holiday_var.get()

            matches = get_vibe_matches_within_threshold(
                path,
                max_distance_threshold=thresh,
                include_holiday=inc_holiday,
                is_preview=True
            )

            self.lbl_live_count.config(
                text=f"Pool Preview: Found {len(matches)} matching texture profiles."
            )

    def generate_playlist(self):
        seed_path = self.get_selected_path()

        if not seed_path:
            messagebox.showwarning(
                "Warning",
                "Please select a seed track first."
            )
            return

        thresh = self.threshold_slider.get()
        inc_holiday = self.holiday_var.get()

        self.lbl_status.config(
            text="Processing final pool filtering...",
            fg="blue"
        )

        self.root.update_idletasks()

        matches = get_vibe_matches_within_threshold(
            seed_path,
            max_distance_threshold=thresh,
            include_holiday=inc_holiday,
            is_preview=False
        )

        if not matches:
            messagebox.showinfo(
                "Result",
                "No matching vibe vectors found inside that criteria limit."
            )

            self.lbl_status.config(
                text="Ready.",
                fg="gray"
            )

            return

        random.shuffle(matches)

        selection = matches[:49]
        selection.insert(0, seed_path)

        try:
            with open(M3U_OUTPUT_PATH, "w", encoding="utf-8") as f:
                f.write("#EXTM3U\n")

                for track in selection:
                    f.write(f"{track}\n")

            self.lbl_status.config(
                text=f"Saved {len(selection)} tracks to configured playlist.",
                fg="green"
            )

            messagebox.showinfo(
                "Success",
                f"M3U generated successfully with {len(selection)} matching entries."
            )

            try:
                play_playlist(M3U_OUTPUT_PATH)
            except Exception as e:
                messagebox.showwarning(
                    "Playlist Saved",
                    f"The playlist was saved but could not be started "
                    f"automatically:\n\n{e}\n\nLocation:\n{M3U_OUTPUT_PATH}"
                )

            self.root.destroy()

        except Exception as e:
            self.lbl_status.config(
                text="Write Error",
                fg="red"
            )

            messagebox.showerror(
                "Error",
                f"Could not write target playlist file: {e}"
            )


if __name__ == '__main__':
    root = tk.Tk()
    app = VibeSearchApp(root)
    root.mainloop()
