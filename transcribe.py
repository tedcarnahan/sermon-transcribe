#!./.venv/bin/python

import sys
import vlc
from PyQt6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QLabel,
    QFileDialog,
    QSlider,
)
from PyQt6.QtCore import Qt, QTimer, QThread, pyqtSignal
import subprocess
import os
from datetime import datetime
from urllib.parse import unquote
import asyncio
from ffmpeg import Progress
from ffmpeg.asyncio import FFmpeg


class WorshipServiceEditor(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Worship Service Video Editor")

        # Create status bar
        self.statusBar().showMessage("Ready")

        # Initialize VLC
        self.instance = vlc.Instance()
        self.player = self.instance.media_player_new()

        # Create central widget and layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)

        # Create video widget
        self.video_widget = QWidget()
        self.video_widget.setMinimumSize(640, 360)
        layout.addWidget(self.video_widget)

        # File selection
        file_layout = QHBoxLayout()
        self.file_button = QPushButton("Browse")
        self.file_button.clicked.connect(self.browse_file)
        file_layout.addWidget(self.file_button)
        layout.addLayout(file_layout)

        # Controls
        controls_layout = QHBoxLayout()
        self.play_button = QPushButton("Play")
        self.play_button.clicked.connect(self.toggle_play)
        controls_layout.addWidget(self.play_button)

        # Enhanced timeline with scrubbing
        self.timeline = QSlider(Qt.Orientation.Horizontal)
        self.timeline.setMinimum(0)
        self.timeline.sliderMoved.connect(self.on_timeline_change)
        self.timeline.sliderPressed.connect(self.on_timeline_press)
        self.timeline.sliderReleased.connect(self.on_timeline_release)
        controls_layout.addWidget(self.timeline)

        self.time_label = QLabel("00:00:00")
        controls_layout.addWidget(self.time_label)
        layout.addLayout(controls_layout)

        # In/Out points
        points_layout = QHBoxLayout()
        self.in_button = QPushButton("Set In Point")
        self.in_button.clicked.connect(self.set_in_point)
        self.in_label = QLabel("In: 00:00:00")
        points_layout.addWidget(self.in_button)
        points_layout.addWidget(self.in_label)

        self.out_button = QPushButton("Set Out Point")
        self.out_button.clicked.connect(self.set_out_point)
        self.out_label = QLabel("Out: 00:00:00")
        points_layout.addWidget(self.out_button)
        points_layout.addWidget(self.out_label)
        layout.addLayout(points_layout)

        # Process buttons (removed process_button)
        self.transcribe_button = QPushButton("Extract and Transcribe")
        self.transcribe_button.clicked.connect(self.start_extract_and_transcribe)
        layout.addWidget(self.transcribe_button)

        # Initialize variables
        self.playing = False
        self.in_point = 0
        self.out_point = 0

        # Timer for updates
        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self.update_ui)
        self.timer.start()

        # Add scrubbing state
        self.is_scrubbing = False

        self.show()

    def browse_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Video File", "", "Video Files (*.mp4 *.mov)"
        )
        if file_path:
            self.load_video(file_path)

    def load_video(self, file_path):
        try:
            # Stop any existing playback
            self.player.stop()
            self.statusBar().showMessage("Loading video...")

            # Create a new media
            media = self.instance.media_new(file_path)
            media.parse_with_options(vlc.MediaParseFlag.local, 0)
            self.player.set_media(media)

            # Set up video output
            if sys.platform.startswith("darwin"):
                self.player.set_nsobject(int(self.video_widget.winId()))
            elif sys.platform.startswith("win"):
                self.player.set_hwnd(self.video_widget.winId())
            else:
                self.player.set_xwindow(self.video_widget.winId())

            # Wait for media to be ready
            self.player.play()
            QTimer.singleShot(500, self.setup_timeline)
            self.statusBar().showMessage("Video loaded successfully")

        except Exception as e:
            self.statusBar().showMessage(f"Error loading video: {e}")
            print(f"Error loading video: {e}")

    def setup_timeline(self):
        """Set up timeline after media is loaded"""
        try:
            # Pause the playback
            self.player.pause()

            # Get the duration
            duration = self.player.get_length()
            print(f"Video duration: {duration}")  # Debug print

            # Set up timeline with the duration
            self.timeline.setRange(0, duration)
            self.timeline.setValue(0)
            self.timeline.show()  # Ensure the timeline is visible

            # Update the time label
            self.time_label.setText(self.format_time(0))

        except Exception as e:
            print(f"Error setting up timeline: {e}")

    def toggle_play(self):
        if self.player.is_playing():
            self.player.pause()
            self.play_button.setText("Play")
            self.playing = False
            self.statusBar().showMessage("Paused")
        else:
            self.player.play()
            self.play_button.setText("Pause")
            self.playing = True
            self.statusBar().showMessage("Playing")

    def on_timeline_press(self):
        """Called when user starts dragging the timeline"""
        self.is_scrubbing = True
        if self.player.is_playing():
            self.player.pause()

    def on_timeline_release(self):
        """Called when user releases the timeline"""
        self.is_scrubbing = False
        if self.playing:
            self.player.play()

    def on_timeline_change(self, value):
        """Called while dragging the timeline"""
        self.player.set_time(value)
        # Update time label immediately during scrubbing
        self.time_label.setText(self.format_time(value / 1000))

    def update_ui(self):
        """Regular UI updates"""
        if self.player.is_playing() and not self.is_scrubbing:
            time_pos = self.player.get_time()
            self.timeline.setValue(time_pos)
            self.time_label.setText(self.format_time(time_pos / 1000))

    def format_time(self, seconds):
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        seconds = int(seconds % 60)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

    def set_in_point(self):
        self.in_point = self.player.get_time()
        self.in_label.setText(f"In: {self.format_time(self.in_point/1000)}")

    def set_out_point(self):
        self.out_point = self.player.get_time()
        self.out_label.setText(f"Out: {self.format_time(self.out_point/1000)}")

    def start_extract_and_transcribe(self):
        """
        Starts the extraction and transcription process asynchronously using python-ffmpeg.
        """
        try:
            # Get the input file path from the current media
            input_file = self.player.get_media().get_mrl()
            if input_file.startswith("file://"):
                input_file = input_file[7:]  # Remove 'file://' prefix

            # URL decode the path
            input_file = unquote(input_file)

            # Get the directory and base name of the input file
            input_dir = os.path.dirname(input_file)
            base_name = os.path.splitext(os.path.basename(input_file))[0]

            # Generate output filenames with full paths
            sermon_video = os.path.join(input_dir, f"{base_name} sermon.mp4")
            sermon_audio = os.path.join(input_dir, f"{base_name} sermon.wav")
            sermon_text = os.path.join(input_dir, f"{base_name} sermon.txt")

            # Format timestamps for ffmpeg
            in_time = self.format_time_with_ms(self.in_point / 1000)
            out_time = self.format_time_with_ms(self.out_point / 1000)

            # Extract video segment
            self.update_status(f"Preparing to extract video segment...")
            extract_ffmpeg = (
                FFmpeg()
                .option("y")
                .input(input_file, ss=in_time)
                .output(sermon_video, to=out_time, codec="copy")
            )

            @extract_ffmpeg.on("progress")
            def on_extract_progress(progress: Progress):
                self.update_status(
                    f"Extracting video: {progress.frame}/{progress.total}"
                )

            await extract_ffmpeg.execute()
            self.update_status("Video segment extracted successfully.")

            # Convert to audio
            self.update_status("Converting video to audio...")
            audio_ffmpeg = (
                FFmpeg()
                .option("y")
                .input(sermon_video)
                .output(sermon_audio, acodec="pcm_s16le", ac=1, ar=16000)
            )

            @audio_ffmpeg.on("progress")
            def on_audio_progress(progress: Progress):
                self.update_status(
                    f"Converting to audio: {progress.frame}/{progress.total}"
                )

            await audio_ffmpeg.execute()
            self.update_status("Audio conversion completed successfully.")

            # Transcribe
            self.update_status("Transcribing audio...")
            whisper_cmd = [
                "/Users/ted/dev/whisper.cpp/build/bin/whisper-cli",
                "-m",
                "/Users/ted/dev/whisper.cpp/models/ggml-large-v3.bin",
                "-np",
                "-nt",
                "-f",
                sermon_audio,
            ]

            whisper_process = await asyncio.create_subprocess_exec(
                *whisper_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, stderr = await whisper_process.communicate()
            if whisper_process.returncode == 0:
                with open(sermon_text, "w") as f:
                    f.write(stdout.decode())
                self.update_status("Transcription completed successfully.")
            else:
                self.update_status(f"Transcription failed: {stderr.decode()}")

            self.statusBar().showMessage("Transcription process complete.")
        except Exception as e:
            self.statusBar().showMessage(f"Error during processing: {str(e)}")

    def update_status(self, message):
        """Update the status bar message."""
        self.statusBar().showMessage(message)

    def format_time_with_ms(self, seconds):
        """Format time as HH:MM:SS.mmm for ffmpeg"""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        seconds = seconds % 60
        return f"{hours:02d}:{minutes:02d}:{seconds:06.3f}"


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = WorshipServiceEditor()
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    loop = asyncio.get_event_loop()
    loop.run_until_complete(window.start_extract_and_transcribe())
    sys.exit(app.exec())
