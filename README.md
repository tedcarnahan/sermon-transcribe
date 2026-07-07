# Sermon Transcriber

GUI for transcribing sermons using FFmpeg and whisper.cpp

## Installation

1. Clone this repository.
2. Install system dependencies: `ffmpeg`, `whisper.cpp` (with `whisper-cli`), and `uv`.
3. Install Python packages: `uv sync`

To run from source: `uv run python transcribe.py`

## Building a standalone macOS app

The project includes a PyInstaller spec that produces a self-contained `.app` bundle for macOS (the Python + PySide6/Qt parts are bundled; external tools are not).

**Recommended:**

```bash
./build.sh
```

This script:
- Ensures dev dependencies (PyInstaller) via `uv sync --extra dev`
- Cleans `build/` and `dist/`
- Runs `pyinstaller pyinstaller.spec --clean`

The resulting app is at `dist/Sermon Transcriber.app`. Drag it to `/Applications` or run directly.

**Manual alternative** (if not using the script):

1. Make sure dev dependencies are available: `uv sync --extra dev`
2. Build:
   ```
   uv run --extra dev pyinstaller pyinstaller.spec --clean --noconfirm
   ```
   Or: `./.venv/bin/pyinstaller pyinstaller.spec --clean`

**Notes:**
- The bundled app is a GUI executable. On first launch, use the ⚙️ gear button to configure the path to your `whisper-cli` executable (it auto-seeks common locations on first run).
- You must have VLC installed on the system (the app embeds python-vlc which loads `libvlc` at runtime).
- `ffmpeg` must be in your `PATH`.
- `whisper.cpp` models are discovered from the directory configured in settings (or use the file picker).
- Build artifacts go to `build/` and `dist/` (ignored by git).
- Rebuilding after code changes: the script always cleans; for manual use `--clean`.

## TODO

- Some paths for whisper.cpp are still discovered via heuristics; custom builds (e.g. with Core ML) can be selected in Settings.
- Pull requests are welcome!

## Usage

1. Run the application (from source or the built `.app`).
2. Browse to select the video file you want to transcribe.
3. Scrub to the start and end of the sermon, at each point click to set the in and out points.
4. Run Extract and Transcribe.
5. In the directory, you'll find a trimmed video of the sermon, an audio version (in 16khz WAV for whisper.cpp) and a text file with the transcription.
