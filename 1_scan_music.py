import os
import sys
import time
import argparse
import sqlite3
import logging
import json
from pathlib import Path

import numpy as np
import librosa
from tqdm import tqdm

try:
    import miniaudio
except ImportError:
    miniaudio = None


# ============================================================
# MUSIC VIBE SEARCH
# SCRIPT 1 - AUDIO FEATURE / FINGERPRINT DATABASE BUILDER
# ============================================================

APP_NAME = "Music-Vibe-Search"

APP_DATA_DIR = (
    Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    / APP_NAME
)

CONFIG_PATH = APP_DATA_DIR / "config.json"

TARGET_SR = 22050

SUPPORTED_EXTENSIONS = {
    ".mp3",
    ".wav",
    ".flac",
    ".m4a",
    ".ogg",
}

ROOT = None
DB_PATH = None
LOG_PATH = None


# ============================================================
# CONFIGURATION LOADING
# ============================================================

def load_configuration():
    global ROOT
    global DB_PATH
    global LOG_PATH

    if not CONFIG_PATH.exists():
        raise RuntimeError(
            f"Configuration file not found:\n{CONFIG_PATH}\n\n"
            "Run Script 0 first to complete Music Vibe Search setup."
        )

    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            config = json.load(f)

    except Exception as exc:
        raise RuntimeError(
            f"Unable to read configuration file:\n"
            f"{CONFIG_PATH}\n\n"
            f"{exc}"
        )

    library_root = config.get("library_root")

    if not library_root:
        raise RuntimeError(
            "The configuration file does not contain a "
            "'library_root' value."
        )

    ROOT = Path(library_root)

    if not ROOT.exists() or not ROOT.is_dir():
        raise RuntimeError(
            f"The configured Library ROOT does not exist "
            f"or is not a folder:\n{ROOT}"
        )

    configured_db_path = config.get("db_path")

    if configured_db_path:
        DB_PATH = Path(configured_db_path)
    else:
        DB_PATH = APP_DATA_DIR / "music_fingerprints.db"

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    LOG_PATH = APP_DATA_DIR / "logs" / "vibe_engine_errors.log"
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)


# ============================================================
# LOGGING
# ============================================================

def initialize_logging():
    if LOG_PATH.exists():
        try:
            LOG_PATH.unlink()
        except Exception:
            pass

    logging.basicConfig(
        filename=LOG_PATH,
        level=logging.ERROR,
        format="%(asctime)s | %(levelname)s | %(message)s",
    )


# ============================================================
# DATABASE DEFINITION
# ============================================================

CORE_COLUMNS = [
    "path",
    "duration",
    "bpm",
    "energy_mean",
    "energy_std",
    "bright_mean",
    "bright_std",
    "flatness_mean",
    "mfcc_0",
    "mfcc_1",
    "mfcc_2",
    "mfcc_3",
    "mfcc_4",
    "chroma_0",
    "chroma_1",
    "chroma_2",
    "chroma_3",
    "chroma_4",
    "chroma_5",
    "chroma_6",
    "chroma_7",
    "chroma_8",
    "chroma_9",
    "chroma_10",
    "chroma_11",
]


CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS tracks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    path TEXT NOT NULL UNIQUE,
    duration REAL,
    bpm REAL,
    energy_mean REAL,
    energy_std REAL,
    bright_mean REAL,
    bright_std REAL,
    flatness_mean REAL,
    mfcc_0 REAL,
    mfcc_1 REAL,
    mfcc_2 REAL,
    mfcc_3 REAL,
    mfcc_4 REAL,
    chroma_0 REAL,
    chroma_1 REAL,
    chroma_2 REAL,
    chroma_3 REAL,
    chroma_4 REAL,
    chroma_5 REAL,
    chroma_6 REAL,
    chroma_7 REAL,
    chroma_8 REAL,
    chroma_9 REAL,
    chroma_10 REAL,
    chroma_11 REAL
)
"""


# ============================================================
# DATABASE INITIALIZATION / MIGRATION
# ============================================================

def initialize_database():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type='table' AND name='tracks'
        """
    )

    table_exists = cursor.fetchone() is not None

    if not table_exists:
        cursor.execute(CREATE_TABLE_SQL)
        conn.commit()
        return conn

    cursor.execute("PRAGMA table_info(tracks)")
    existing_columns = [row[1] for row in cursor.fetchall()]

    required_columns = ["id"] + CORE_COLUMNS

    if existing_columns == required_columns:
        return conn

    print()
    print("Existing database schema differs from the simplified Vibe schema.")
    print("Rebuilding the tracks table while preserving compatible audio data...")

    cursor.execute("DROP TABLE IF EXISTS tracks_migration_backup")
    cursor.execute(
        "ALTER TABLE tracks RENAME TO tracks_migration_backup"
    )

    cursor.execute(CREATE_TABLE_SQL)

    old_columns = set(existing_columns)

    copy_columns = [
        column
        for column in CORE_COLUMNS
        if column in old_columns
    ]

    if "path" in copy_columns:
        column_list = ", ".join(copy_columns)

        cursor.execute(
            f"""
            INSERT OR IGNORE INTO tracks ({column_list})
            SELECT {column_list}
            FROM tracks_migration_backup
            """
        )

    cursor.execute("DROP TABLE tracks_migration_backup")

    conn.commit()

    print("Database schema simplified successfully.")
    print()

    return conn


# ============================================================
# AUDIO DECODING
# ============================================================

def decode_audio(path):
    if miniaudio is not None:
        try:
            decoded = miniaudio.decode_file(
                str(path),
                nchannels=1,
                sample_rate=TARGET_SR,
            )

            samples = np.asarray(
                decoded.samples,
                dtype=np.float32,
            )

            if samples.size > 0:
                return samples, TARGET_SR

        except Exception:
            pass

    try:
        audio, sr = librosa.load(
            str(path),
            sr=TARGET_SR,
            mono=True,
        )

        return audio.astype(np.float32), sr

    except Exception as exc:
        raise RuntimeError(
            f"Unable to decode audio: {exc}"
        )


# ============================================================
# CHUNK SELECTION
# ============================================================

def select_audio_chunks(audio, sr):
    total_samples = len(audio)
    duration = total_samples / sr

    if duration <= 40:
        return [audio]

    chunk_seconds = 10
    chunk_samples = int(chunk_seconds * sr)

    chunks = []

    for position in (0.25, 0.50, 0.75):
        center = int(total_samples * position)

        start = center - (chunk_samples // 2)
        end = start + chunk_samples

        if start < 0:
            start = 0
            end = chunk_samples

        if end > total_samples:
            end = total_samples
            start = max(0, end - chunk_samples)

        chunk = audio[start:end]

        if len(chunk) > 0:
            chunks.append(chunk)

    return chunks


# ============================================================
# FEATURE EXTRACTION
# ============================================================

def extract_features(path):
    start_time = time.time()

    audio, sr = decode_audio(path)

    if len(audio) == 0:
        raise RuntimeError("Decoded audio contains no samples.")

    duration = len(audio) / sr

    chunks = select_audio_chunks(audio, sr)

    rms_values = []
    brightness_values = []
    flatness_values = []

    mfcc_values = []
    chroma_values = []
    bpm_values = []

    for chunk in chunks:

        rms = librosa.feature.rms(
            y=chunk,
            frame_length=2048,
            hop_length=512,
        )

        rms_values.extend(rms[0])

        centroid = librosa.feature.spectral_centroid(
            y=chunk,
            sr=sr,
            n_fft=2048,
            hop_length=512,
        )

        brightness_values.extend(centroid[0])

        flatness = librosa.feature.spectral_flatness(
            y=chunk,
            n_fft=2048,
            hop_length=512,
        )

        flatness_values.extend(flatness[0])

        mfcc = librosa.feature.mfcc(
            y=chunk,
            sr=sr,
            n_mfcc=5,
            n_fft=2048,
            hop_length=512,
        )

        mfcc_values.append(
            np.mean(mfcc, axis=1)
        )

        chroma = librosa.feature.chroma_stft(
            y=chunk,
            sr=sr,
            n_fft=2048,
            hop_length=512,
            n_chroma=12,
        )

        chroma_values.append(
            np.mean(chroma, axis=1)
        )

        try:
            tempo = librosa.feature.tempo(
                y=chunk,
                sr=sr,
                hop_length=512,
            )

            if len(tempo) > 0:
                bpm_values.append(float(np.median(tempo)))

        except Exception:
            pass

    energy_mean = float(np.mean(rms_values))
    energy_std = float(np.std(rms_values))

    bright_mean = float(np.mean(brightness_values))
    bright_std = float(np.std(brightness_values))

    flatness_mean = float(np.mean(flatness_values))

    mfcc_final = np.mean(
        np.asarray(mfcc_values),
        axis=0,
    )

    chroma_final = np.mean(
        np.asarray(chroma_values),
        axis=0,
    )

    if bpm_values:
        bpm = float(np.median(bpm_values))
    else:
        bpm = 0.0

    elapsed = time.time() - start_time

    return {
        "path": str(path.resolve()),
        "duration": duration,
        "bpm": bpm,
        "energy_mean": energy_mean,
        "energy_std": energy_std,
        "bright_mean": bright_mean,
        "bright_std": bright_std,
        "flatness_mean": flatness_mean,
        "mfcc_0": float(mfcc_final[0]),
        "mfcc_1": float(mfcc_final[1]),
        "mfcc_2": float(mfcc_final[2]),
        "mfcc_3": float(mfcc_final[3]),
        "mfcc_4": float(mfcc_final[4]),
        "chroma_0": float(chroma_final[0]),
        "chroma_1": float(chroma_final[1]),
        "chroma_2": float(chroma_final[2]),
        "chroma_3": float(chroma_final[3]),
        "chroma_4": float(chroma_final[4]),
        "chroma_5": float(chroma_final[5]),
        "chroma_6": float(chroma_final[6]),
        "chroma_7": float(chroma_final[7]),
        "chroma_8": float(chroma_final[8]),
        "chroma_9": float(chroma_final[9]),
        "chroma_10": float(chroma_final[10]),
        "chroma_11": float(chroma_final[11]),
    }


# ============================================================
# DATABASE WRITE
# ============================================================

def save_track(conn, data):
    placeholders = ", ".join(["?"] * len(CORE_COLUMNS))
    columns = ", ".join(CORE_COLUMNS)

    values = tuple(
        data[column]
        for column in CORE_COLUMNS
    )

    sql = f"""
        INSERT OR REPLACE INTO tracks
        ({columns})
        VALUES ({placeholders})
    """

    conn.execute(sql, values)
    conn.commit()


# ============================================================
# EXISTING-TRACK CHECK
# ============================================================

def track_exists(conn, path):
    cursor = conn.execute(
        "SELECT 1 FROM tracks WHERE path = ? LIMIT 1",
        (str(path.resolve()),),
    )

    return cursor.fetchone() is not None


# ============================================================
# FILE SCANNING
# ============================================================

def find_audio_files():
    print("Scanning drive folder tree for audio tracks...")

    if not ROOT.exists():
        raise RuntimeError(
            f"Target ROOT does not exist:\n{ROOT}"
        )

    files = []

    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue

        if path.suffix.lower() in SUPPORTED_EXTENSIONS:
            files.append(path)

    files.sort(
        key=lambda p: str(p).lower()
    )

    return files


# ============================================================
# MAIN
# ============================================================

def main():

    parser = argparse.ArgumentParser(
        description=(
            "Build/update the Music Vibe audio-feature database."
        )
    )

    parser.add_argument(
        "--force",
        action="store_true",
        help="Reprocess tracks already present in the database.",
    )

    parser.add_argument(
        "--test",
        type=int,
        metavar="N",
        help="Process only the first N discovered audio files.",
    )

    parser.add_argument(
        "--show-files",
        action="store_true",
        help="Display each file as it is processed.",
    )

    args = parser.parse_args()

    try:
        load_configuration()
        initialize_logging()

    except Exception as exc:
        print()
        print("ERROR: Unable to initialize Music Vibe Search.")
        print()
        print(exc)
        print()
        return 1

    print(f"Library ROOT: {ROOT}")
    print(f"Database: {DB_PATH}")
    print()

    try:
        files = find_audio_files()

    except Exception as exc:
        logging.error(
            f"Unable to scan Library ROOT: {exc}",
            exc_info=True,
        )

        print()
        print("ERROR while scanning the Library ROOT:")
        print(exc)
        print()
        return 1

    if args.test is not None:

        if args.test < 1:
            print("--test must be at least 1.")
            return 1

        print(
            f"--test switch active: "
            f"Limiting queue to the first {args.test} files."
        )

        files = files[:args.test]

    print(
        f"Found {len(files)} total tracks in target execution paths."
    )

    if not files:
        print("No supported audio files were found.")
        return 0

    conn = initialize_database()

    processed = 0
    skipped = 0
    errors = 0

    print()

    progress = tqdm(
        files,
        desc="Building Vibe Fingerprint Database",
        unit="track",
        dynamic_ncols=True,
    )

    for path in progress:

        progress.set_postfix_str(
            f"Current: {path.name}",
            refresh=True,
        )

        try:

            if not args.force and track_exists(conn, path):

                skipped += 1

                progress.set_postfix_str(
                    f"SKIP: {path.name}",
                    refresh=True,
                )

                continue

            data = extract_features(path)

            save_track(conn, data)

            processed += 1

            progress.set_postfix_str(
                f"Saved: {path.name}",
                refresh=True,
            )

        except Exception as exc:

            errors += 1

            message = (
                f"{path}: {type(exc).__name__}: {exc}"
            )

            logging.error(
                message,
                exc_info=True,
            )

            progress.set_postfix_str(
                f"ERROR: {path.name}",
                refresh=True,
            )

    progress.close()

    conn.close()

    print()
    print("Vibe Fingerprint Database pass finalized successfully.")
    print()
    print(f"  Processed : {processed}")
    print(f"  Skipped   : {skipped}")
    print(f"  Errors    : {errors}")
    print(f"  Database  : {DB_PATH}")
    print(f"  Error log : {LOG_PATH}")

    return 0


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    sys.exit(main())