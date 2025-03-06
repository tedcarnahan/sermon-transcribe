# Sermon Transcribe

GUI for assisting a user with transcribing sermons using FFmpeg and whisper.cpp

## Installation

1. Clone this repository:
2. Install dependencies: ffmpeg, whisper.cpp, poetry
3. Install Python packages using Poetry: poetry install

## TODO

- Whisper.cpp path and model is hardcoded right now (mostly because I really like using my custom compiled version that has Core ML optimizations that run 3x faster on Mac Silicon)
- Need to do the packaging work to build this as a standalone program for distribution.
- Pull requests are welcome!

## Usage

1. Run the application: poetry run python transcribe.py
2. Browse to select the video file you want to transcribe.
3. Scrub to the start and end of the sermon, at each point click to set the in and out points.
4. Run Extract and Transcribe.
5. In the directory, you'll find a trimmed video of the sermon, an audio version (in 16khz WAV for whisper.cpp) and a text file with the transcription.
