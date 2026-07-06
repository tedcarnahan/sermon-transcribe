# Sermon Transcribe - Project Familiarization Summary

**Generated:** Based on direct inspection (2026 context)

## Overview
A desktop GUI application (PySide6) for assisting manual transcription of sermon videos using local tools:
- VLC (via python-vlc + pyvlc) for video playback and timeline scrubbing with in/out point selection.
- ffmpeg-python for:
  - Trimming video segment (copy codec) between in/out.
  - Converting trimmed video to 16 kHz mono WAV.
- Subprocess call to whisper.cpp CLI for transcription (outputs text file).
- Outputs alongside input: `<name> sermon.mp4`, `<name> sermon.wav`, `<name> sermon.txt`.

Target use: fast local processing on macOS (especially Apple Silicon) for church sermon audio.

## Tech Stack & Structure
- **Language/Runtime**: Python >=3.12, managed with uv.
- **GUI**: PySide6 (Qt), single `WorshipServiceEditor` QMainWindow + background `ExtractAndTranscribeThread`.
- **Media**: python-vlc for player + native video widget embedding (darwin/win/x11).
- **Processing**: `python-ffmpeg`, `subprocess`.
- **Main Code**: Single file `transcribe.py` (373 lines).
  - Hardcoded whisper paths (TODO):
    - `/Users/ted/dev/whisper.cpp/build/bin/whisper-cli`
    - `/Users/ted/dev/whisper.cpp/models/ggml-large-v3.bin`
  - UI features: Browse video, Play/Pause, draggable timeline scrubber (with play state handling), Set In/Out, Extract+Transcribe (with cancel).
- **Packaging**: `pyinstaller.spec` (basic macOS .app bundle using `res/transcribe.icns`).
- **Config**:
  - `pyproject.toml`: dependencies + dev pyinstaller.
  - `.gitignore`: build/, dist/, .DS_Store.
- **Assets**: `res/transcribe.icns` + iconset + Affinity Designer source.
- **No tests**, no other .py modules, minimal structure.

## Current State (from README + code)
- **Run**: `uv sync` then `uv run python transcribe.py`
- **Workflow** (per README): select video → scrub + set in/out → Extract and Transcribe → results in same folder.
- **Known Limitations** (explicit in README):
  - Whisper.cpp path/model hardcoded (custom Core ML optimized build for 3x speed on Mac Silicon).
  - Packaging not production-ready (no distribution builds, no bundling of whisper/ffmpeg/VLC).
- Git repo: https://github.com/tedcarnahan/sermon-transcribe.git

## Project Files
- `transcribe.py`
- `README.md`
- `pyproject.toml`
- `uv.lock`
- `pyinstaller.spec`
- `.gitignore`
- `res/`

This matches the initial session familiarization notes exactly. Future work would address hardcodes (config/args/env) + proper packaging (PyInstaller hooks for VLC/ffmpeg/whisper, cross-platform?).
