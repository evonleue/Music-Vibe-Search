# Music Vibe Search

Pick a song, and Music Vibe Search builds a playlist of tracks from your own library that *sound* similar. It analyzes the audio itself (not genre tags or lyrics), stores a fingerprint for each track in a local database, and finds the closest matches to a seed track of your choice.

Everything runs locally. Your music is never uploaded or modified.

## Screenshots

<!-- Add screenshots to a /docs folder and uncomment:
![Main menu](docs/main-menu.png)
![Search window](docs/search-window.png)
-->

## How it works

1. **Scan:** each audio file is analyzed for energy, brightness, spectral flatness and timbre (MFCC) features. The results are stored in a local SQLite database.
2. **Search:** you pick a seed track. Every track is compared to it using weighted, standardized distances across those features.
3. **Playlist:** tracks within your chosen strictness are shuffled, up to 20 are written to an `.m3u` file (with your seed first), and the playlist opens in your default media player.

## Requirements

- Windows (the app stores its data under `%LOCALAPPDATA%`)
- Python 3 with Tkinter (developed and tested on Python 3.12). The standard python.org installer includes it; keep the **tcl/tk and IDLE** option ticked.
- The packages in `requirements.txt`

Supported audio formats: `.mp3`, `.wav`, `.flac`, `.m4a`, `.ogg`

## Installation

```
git clone https://github.com/evonleue/Music-Vibe-Search.git
cd Music-Vibe-Search
pip install -r requirements.txt
```

`miniaudio` in `requirements.txt` is optional. The scanner uses it for decoding when available and falls back to `librosa` otherwise.

## Usage

Double-click **`Start.bat`**, or run:

```
python 0_setup.py
```

### First Run (Setup mode)

If no configuration is found, the program starts in Setup mode:

1. Choose the folder that contains your music.
2. Review the file count and estimated scan time (about 0.7 seconds per file).
3. Run the first scan.

Your settings are saved, and subsequent launches go straight to the Main Menu.

### Main Menu

| Option | What it does |
|---|---|
| **1) Search music and run playlist** | Opens the search window. Generating a playlist saves it and starts playback. |
| **2) Rescan music** | Scans the library. Tracks already in the database are skipped, so this picks up newly added files. |
| **3) Full rebuild** | Reprocesses *every* track, including ones already in the database. Slow; asks for confirmation. |
| **4) Exit** | Quits. |

### Searching

1. Type at least two characters of an artist, folder or file name. Matches are looked up in the full file path.
2. Select a seed track from the list.
3. Adjust **Vibe Strictness**. Lower values mean closer matches and smaller pools; a live count shows how many tracks fit.
4. Click **Generate Vibe Playlist**.

Notes:

- Folders named `audiobooks`, `sound effects`, `comedy` and `soundtrack` are always excluded from results.
- If the playlist doesn't start, make sure Windows has a default app for `.m3u` files (right-click the file, *Open with*, *Always use this app*).

## Where files are stored

Everything lives in `%LOCALAPPDATA%\Music-Vibe-Search\`:

| File | Purpose |
|---|---|
| `config.json` | Your library location and paths |
| `music_fingerprints.db` | The audio fingerprint database |
| `Latest_Vibe_Playlist.m3u` | The most recently generated playlist |
| `logs\` | Scanner logs |

To point the app at a different music folder, delete `config.json`. The next launch runs Setup mode again.

## Advanced: running the scanner directly

```
python 1_scan_music.py [--force] [--test N] [--show-files]
```

| Flag | Effect |
|---|---|
| `--force` | Reprocess tracks already in the database |
| `--test N` | Process only the first N discovered files (useful for a quick trial) |
| `--show-files` | Print each file as it is processed |

## Project layout

| File | Role |
|---|---|
| `Start.bat` | Launcher |
| `0_setup.py` | Setup and main menu |
| `1_scan_music.py` | Builds the fingerprint database |
| `2_search_music.py` | Search window and playlist generation |
| `requirements.txt` | Python dependencies |

## License

Released under the [MIT License](LICENSE).
