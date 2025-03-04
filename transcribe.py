import sys
import vlc
from PySide6.QtWidgets import (
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
from PySide6.QtCore import Qt, QTimer, QThread, Signal
import subprocess
import os
from datetime import datetime
from urllib.parse import unquote
from ffmpeg import FFmpeg


class ExtractAndTranscribeThread(QThread):
    status_update = Signal(str)
    finished = Signal(str)

    def __init__(self, input_file, in_point, out_point, base_name):
        super().__init__()
        self.input_file = input_file
        self.in_point = in_point
        self.out_point = out_point
        self.base_name = base_name
        self.is_cancelled = False

    def run(self):
        try:
            input_dir = os.path.dirname(self.input_file)
            sermon_video = os.path.join(input_dir, f"{self.base_name} sermon.mp4")
            sermon_audio = os.path.join(input_dir, f"{self.base_name} sermon.wav")
            sermon_text = os.path.join(input_dir, f"{self.base_name} sermon.txt")

            self.video_extract(sermon_video)
            if self.is_cancelled:
                return

            self.audio_extract(sermon_video, sermon_audio)
            if self.is_cancelled:
                return

            self.transcribe(sermon_audio, sermon_text)

            self.finished.emit("Transcription process complete.")
        except Exception as e:
            self.finished.emit(f"Error during processing: {str(e)}")

    def video_extract(self, sermon_video):
        self.status_update.emit("Preparing to extract video segment...")
        in_time = self.format_time_with_ms(self.in_point / 1000)
        out_time = self.format_time_with_ms(self.out_point / 1000)

        extract_video = (
            FFmpeg()
            .option("y")
            .input(self.input_file, ss=in_time)
            .output(sermon_video, to=out_time, codec="copy")
        )

        extract_video.execute()
        self.status_update.emit("Video segment extracted successfully.")

    def audio_extract(self, video_file, audio_file):
        self.status_update.emit("Converting video to audio...")

        extract_audio = (
            FFmpeg()
            .option("y")
            .input(video_file)
            .output(audio_file, acodec="pcm_s16le", ac=1, ar=16000)
        )

        extract_audio.execute()
        self.status_update.emit("Audio conversion completed successfully.")

    def transcribe(self, sermon_audio, sermon_text):
        self.status_update.emit("Transcribing audio...")

        whisper_cmd = [
            "/Users/ted/dev/whisper.cpp/build/bin/whisper-cli",
            "-m",
            "/Users/ted/dev/whisper.cpp/models/ggml-large-v3.bin",
            "-np",
            "-nt",
            "-f",
            sermon_audio,
        ]

        process = subprocess.Popen(
            whisper_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
        )

        # Initialize an empty list to store the output
        transcription_output = []

        while True:
            if self.is_cancelled:
                process.terminate()
                self.status_update.emit("Transcription cancelled.")
                return

            output = process.stdout.readline()
            if output:
                transcription_output.append(output.strip())
            if output == "" and process.poll() is not None:
                break

        if process.returncode == 0:
            with open(sermon_text, "w") as f:
                # Join the lines and write to the file
                f.write("\n".join(transcription_output))
            self.status_update.emit("Transcription completed successfully.")
        else:
            self.status_update.emit(f"Transcription failed: {process.stderr.read()}")

    def format_time_with_ms(self, seconds):
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        seconds = seconds % 60
        return f"{hours:02d}:{minutes:02d}:{seconds:06.3f}"

    def cancel(self):
        self.is_cancelled = True


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

        # Process buttons
        self.transcribe_button = QPushButton("Extract and Transcribe")
        self.transcribe_button.clicked.connect(self.start_extract_and_transcribe)
        layout.addWidget(self.transcribe_button)

        # Initialize variables
        self.playing = False
        self.in_point = 0
        self.out_point = 0
        self.extraction_thread = None

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
        if self.extraction_thread is None or not self.extraction_thread.isRunning():
            # Get the input file path from the current media
            input_file = self.player.get_media().get_mrl()
            if input_file.startswith("file://"):
                input_file = input_file[7:]  # Remove 'file://' prefix

            # URL decode the path
            input_file = unquote(input_file)

            # Get the base name of the input file
            base_name = os.path.splitext(os.path.basename(input_file))[0]

            self.extraction_thread = ExtractAndTranscribeThread(
                input_file, self.in_point, self.out_point, base_name
            )
            self.extraction_thread.status_update.connect(self.update_status)
            self.extraction_thread.finished.connect(self.process_finished)
            self.extraction_thread.start()

            self.transcribe_button.setText("Cancel")
            self.transcribe_button.clicked.disconnect()
            self.transcribe_button.clicked.connect(self.cancel_extract_and_transcribe)
        else:
            self.cancel_extract_and_transcribe()

    def cancel_extract_and_transcribe(self):
        if self.extraction_thread and self.extraction_thread.isRunning():
            self.extraction_thread.cancel()
            self.extraction_thread.wait()
            self.process_finished("Process cancelled.")

    def update_status(self, message):
        self.statusBar().showMessage(message)

    def process_finished(self, message):
        self.statusBar().showMessage(message)
        self.transcribe_button.setText("Extract and Transcribe")
        self.transcribe_button.clicked.disconnect()
        self.transcribe_button.clicked.connect(self.start_extract_and_transcribe)
        self.extraction_thread = None


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = WorshipServiceEditor()
    sys.exit(app.exec())
