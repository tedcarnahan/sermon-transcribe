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
    QGroupBox,
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
            .input(self.input_file, ss=in_time, to=out_time)
            .output(sermon_video, codec="copy")
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

        # Attach event handlers for state sync (prevents UI desync after seeks/ends)
        em = self.player.event_manager()
        em.event_attach(vlc.EventType.MediaPlayerEndReached, self._on_end_reached)
        em.event_attach(vlc.EventType.MediaPlayerPlaying, self._on_playing)
        em.event_attach(vlc.EventType.MediaPlayerPaused, self._on_paused)
        em.event_attach(vlc.EventType.MediaPlayerStopped, self._on_stopped)

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

        # Timeline scrubber (full width above button row)
        self.timeline = QSlider(Qt.Orientation.Horizontal)
        self.timeline.setMinimum(0)
        self.timeline.valueChanged.connect(self.on_timeline_change)
        self.timeline.sliderPressed.connect(self.on_timeline_press)
        self.timeline.sliderReleased.connect(self.on_timeline_release)
        layout.addWidget(self.timeline)

        # In/Out points row:
        # Left: QGroupBox("In:") containing set-in + jump-in buttons + centered timestamp label
        # Center: QGroupBox("Playhead:") with play/pause button (▶️/⏸️) above the time label
        # Right: QGroupBox("Out:") containing jump-out + set-out buttons + centered timestamp label
        points_layout = QHBoxLayout()

        emoji_style = """
    QPushButton {
        background: transparent;
        border: none;
        font-size: 24px; /* Adjust size of the emoji */
    }
"""

        # In group box
        in_group = QGroupBox("In:")
        in_v = QVBoxLayout()
        in_buttons_h = QHBoxLayout()
        self.in_button = QPushButton("]")
        self.in_button.setStyleSheet(emoji_style)
        self.in_button.clicked.connect(self.set_in_point)
        in_buttons_h.addWidget(self.in_button)
        self.jump_in_button = QPushButton("]←")
        self.jump_in_button.setStyleSheet(emoji_style)
        self.jump_in_button.clicked.connect(self.jump_to_in_point)
        in_buttons_h.addWidget(self.jump_in_button)
        in_v.addLayout(in_buttons_h)
        self.in_label = QLabel("00:00:00")
        self.in_label.setAlignment(Qt.AlignCenter)
        in_v.addWidget(self.in_label)
        in_group.setLayout(in_v)
        points_layout.addWidget(in_group)

        # Playhead group: play/pause button above the current playback time label
        playhead_group = QGroupBox("Playhead:")
        playhead_v = QVBoxLayout()
        self.play_button = QPushButton("▶️")
        self.play_button.setStyleSheet(emoji_style)
        self.play_button.clicked.connect(self.toggle_play)
        playhead_v.addWidget(self.play_button)
        self.time_label = QLabel("00:00:00")
        self.time_label.setAlignment(Qt.AlignCenter)
        playhead_v.addWidget(self.time_label)
        playhead_group.setLayout(playhead_v)
        points_layout.addWidget(playhead_group)

        # Out group box
        out_group = QGroupBox("Out:")
        out_v = QVBoxLayout()
        out_buttons_h = QHBoxLayout()
        self.jump_out_button = QPushButton("→[")
        self.jump_out_button.setStyleSheet(emoji_style)
        self.jump_out_button.clicked.connect(self.jump_to_out_point)
        out_buttons_h.addWidget(self.jump_out_button)
        self.out_button = QPushButton("[")
        self.out_button.setStyleSheet(emoji_style)
        self.out_button.clicked.connect(self.set_out_point)
        out_buttons_h.addWidget(self.out_button)
        out_v.addLayout(out_buttons_h)
        self.out_label = QLabel("00:00:00")
        self.out_label.setAlignment(Qt.AlignCenter)
        out_v.addWidget(self.out_label)
        out_group.setLayout(out_v)
        points_layout.addWidget(out_group)

        layout.addLayout(points_layout)

        # Process buttons
        self.transcribe_button = QPushButton("Extract and Transcribe")
        self.transcribe_button.clicked.connect(self.start_extract_and_transcribe)
        layout.addWidget(self.transcribe_button)

        # Initialize variables
        self.playing = False
        self.was_playing = False
        self.in_point = 0
        self.out_point = 0
        self.extraction_thread = None
        self.has_valid_video = False

        # Timer for updates
        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self.update_ui)
        self.timer.start()

        # Add scrubbing state
        self.is_scrubbing = False

        # Start with no video loaded: disable all media controls
        # (timeline scrubber + in/out + play/pause buttons)
        self._set_video_controls_enabled(False)

        self.show()

    def browse_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Video File", "", "Video Files (*.mp4 *.mov *.mkv)"
        )
        if file_path:
            self.load_video(file_path)

    def load_video(self, file_path):
        try:
            # Stop any existing playback
            self.player.stop()
            self.has_valid_video = False
            self._set_video_controls_enabled(
                False
            )  # disable until successful load of this file
            self.statusBar().showMessage("Loading video...")
            self.playing = False
            self.was_playing = False
            self.is_scrubbing = False

            # Reset in/out points + labels for the *new* video (prevents stale values from previous file)
            self.in_point = 0
            self.out_point = 0
            self.in_label.setText("00:00:00")
            self.out_label.setText("00:00:00")

            # Set video output target *before* set_media (required for reliable embedding on macOS)
            if sys.platform.startswith("darwin"):
                self.player.set_nsobject(int(self.video_widget.winId()))
            elif sys.platform.startswith("win"):
                self.player.set_hwnd(self.video_widget.winId())
            else:
                self.player.set_xwindow(self.video_widget.winId())

            # Create a new media
            media = self.instance.media_new(file_path)
            media.parse_with_options(vlc.MediaParseFlag.local, 0)
            self.player.set_media(media)

            # Ensure timeline (playhead bar) is visible with placeholder range immediately.
            # Real duration will override once known (via cue or update_ui).
            self.timeline.setRange(
                0, 600000
            )  # ~10min placeholder so bar renders visibly
            self.timeline.setValue(0)
            self.timeline.setVisible(True)
            self.timeline.show()
            self.timeline.update()
            self.time_label.setText(self.format_time(0))

            # Cue a brief play/pause so first frame renders and sticks (without leaving playing).
            # Delay lets embedding settle and avoids prior deadlock issues.
            QTimer.singleShot(250, self._cue_initial_frame)
            self.play_button.setText("▶️")
            self.statusBar().showMessage("Video loaded successfully")

        except Exception as e:
            self.has_valid_video = False
            self._set_video_controls_enabled(False)
            self.statusBar().showMessage(f"Error loading video: {e}")
            print(f"Error loading video: {e}")

    def _cue_initial_frame(self):
        """Play briefly to force first-frame render into the video widget, then pause+setup.
        This keeps the initial frame visible (unlike stop() which blacks it out).
        """
        try:
            self.player.play()
            # Short delay to let first frame decode/render, then pause.
            QTimer.singleShot(80, self._pause_and_setup)
        except Exception as e:
            print(f"Error cueing initial frame: {e}")
            # Fallback to old setup path
            self.setup_timeline()

    def _pause_and_setup(self):
        try:
            self.player.pause()
            # Force to start to ensure consistent first frame is the one shown.
            self.player.set_time(0)
            duration = self.player.get_length()
            if duration <= 0:
                # Keep placeholder; update_ui will upgrade range once duration known
                duration = 600000
            self._apply_duration(duration)
            # Force clean paused state (events should have synced, but be explicit)
            self.playing = False
            self.was_playing = False
            self.is_scrubbing = False
            self.play_button.setText("▶️")
            # Repaint to help the paused frame stick in the video widget on macOS
            self.video_widget.update()
            self.timeline.update()
        except Exception as e:
            print(f"Error in pause-and-setup: {e}")
            self.setup_timeline()

    def setup_timeline(self):
        """Legacy/fallback path. Set up timeline after media is loaded. Starts paused."""
        try:
            duration = self.player.get_length()
            if duration <= 0:
                # Fallback: try brief play to populate length, then stop (legacy, may black frame)
                self.player.play()
                QTimer.singleShot(200, lambda: self._finish_setup_after_play())
                return

            self._apply_duration(duration)

        except Exception as e:
            print(f"Error setting up timeline: {e}")

    def _finish_setup_after_play(self):
        try:
            self.player.stop()
            duration = self.player.get_length()
            self._apply_duration(duration)
        except Exception as e:
            print(f"Error in fallback setup: {e}")

    def _apply_duration(self, duration):
        self.timeline.setRange(0, duration)
        self.timeline.setValue(0)
        self.timeline.setVisible(True)
        self.timeline.show()
        self.timeline.update()
        self.time_label.setText(self.format_time(0))
        # Do not pause here (caller already did for cue path); legacy fallbacks may rely on it
        self.playing = False
        self.play_button.setText("▶️")

        # Only consider "valid video loaded" (and enable controls) when we have a real positive duration.
        # Placeholder (600000) or <=0 means load not yet succeeded or invalid file.
        if duration > 0 and duration != 600000:
            self.has_valid_video = True
            self._set_video_controls_enabled(True)

            # Default out point to end of video (in_point stays 0). Update labels.
            # This is the requested "out point defaults to end on load".
            # (User can still override later via the set-out button.)
            self.in_point = 0
            self.out_point = duration
            self.in_label.setText(self.format_time(0))
            self.out_label.setText(self.format_time(duration / 1000))
        else:
            self.has_valid_video = False
            self._set_video_controls_enabled(False)

    def _on_end_reached(self, event):
        """Handle end of media (e.g. scrubbed to end or natural end)."""
        self.playing = False
        self.was_playing = False
        self.is_scrubbing = False
        self.play_button.setText("▶️")
        # Keep timeline at end; allow replay via play (will restart)
        print("Media end reached (or seeked to end)")

    def _on_playing(self, event):
        self.play_button.setText("⏸️")
        self.playing = True

    def _on_paused(self, event):
        self.play_button.setText("▶️")
        self.playing = False

    def _on_stopped(self, event):
        self.play_button.setText("▶️")
        self.playing = False
        self.was_playing = False

    def toggle_play(self):
        if self.player.is_playing():
            self.player.pause()
            self.play_button.setText("▶️")
            self.playing = False
            self.statusBar().showMessage("Paused")
        else:
            state = self.player.get_state()
            if state in (vlc.State.Ended, vlc.State.Stopped):
                # Restart from beginning after end/seek-to-end (common for scrub-to-end)
                self.player.stop()
                self.player.set_time(0)
                self.timeline.setValue(0)
                self.time_label.setText(self.format_time(0))
            self.player.play()
            self.play_button.setText("⏸️")
            self.playing = True
            self.statusBar().showMessage("Playing")

    def on_timeline_press(self):
        """Called when user starts dragging the timeline"""
        self.is_scrubbing = True
        self.was_playing = self.player.is_playing()
        if self.was_playing:
            self.player.pause()
            # Button stays reflecting prior "playing" intent until release or toggle

    def on_timeline_release(self):
        """Called when user releases the timeline (after click or drag).
        Always seek to final slider value to ensure click-to-jump works reliably.
        Then resume play if it was playing before press (except at end).
        """
        self.is_scrubbing = False
        # Ensure seek to the (possibly clicked) final position. Harmless if already set by change handler.
        pos = self.timeline.value()
        duration = self.timeline.maximum()
        if duration > 0 and pos > duration - 100:
            pos = duration
        self.player.set_time(pos)
        self.time_label.setText(self.format_time(pos / 1000))

        if self.was_playing:
            state = self.player.get_state()
            if state in (vlc.State.Ended, vlc.State.Stopped):
                # If released at end, don't auto-resume (or restart?); leave paused at end
                self.playing = False
                self.play_button.setText("▶️")
            else:
                self.player.play()
                # event will sync button/flag
        self.was_playing = False

    def on_timeline_change(self, value):
        """Called on user interaction via valueChanged (catches groove clicks reliably + continuous drags).
        Guard prevents seeking on programmatic setValue (from update_ui, jumps, load, etc.).
        Pause is done in press; seek here. Clamp near end to avoid deadlock issues.
        """
        if not (getattr(self, "is_scrubbing", False) or self.timeline.isSliderDown()):
            return
        duration = self.timeline.maximum()
        if duration > 0 and value > duration - 100:  # ~100ms buffer from very end
            value = duration
        self.player.set_time(value)
        # Update time label immediately during scrubbing
        self.time_label.setText(self.format_time(value / 1000))

    def update_ui(self):
        """Regular UI updates. Always sync position when not scrubbing (works for paused too).
        Also auto-upgrades timeline range once real duration is available from VLC.
        """
        if self.is_scrubbing:
            return
        time_pos = self.player.get_time()
        if time_pos < 0:
            return
        dur = self.player.get_length()
        if dur > 0 and dur != self.timeline.maximum():
            self.timeline.setRange(0, dur)
            if self.timeline.value() > dur:
                self.timeline.setValue(dur)
        if dur > 0 and not getattr(self, "has_valid_video", False):
            self.has_valid_video = True
            self._set_video_controls_enabled(True)

            # Default out point to video end when duration first becomes known via this path.
            # (Mirrors the logic in _apply_duration for cue/setup paths.)
            self.in_point = 0
            self.out_point = dur
            self.in_label.setText(self.format_time(0))
            self.out_label.setText(self.format_time(dur / 1000))
        self.timeline.setValue(time_pos)
        self.time_label.setText(self.format_time(time_pos / 1000))

    def format_time(self, seconds):
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        seconds = int(seconds % 60)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

    def set_in_point(self):
        self.in_point = self.player.get_time()
        self.in_label.setText(self.format_time(self.in_point / 1000))

    def set_out_point(self):
        self.out_point = self.player.get_time()
        self.out_label.setText(self.format_time(self.out_point / 1000))

    def jump_to_in_point(self):
        """Jump playhead (and UI) to the current in_point.
        If video was playing, resume playing after the jump for smooth continuation.
        Pause briefly only for the seek to avoid VLC buffer/deadlock issues.
        """
        if not hasattr(self, "in_point"):
            return
        try:
            was_playing = self.player.is_playing()
            if was_playing:
                self.player.pause()
                # Do not force flags yet; will resume

            target = self.in_point
            duration = self.player.get_length()
            if duration > 0 and target > duration:
                target = duration

            self.player.set_time(target)
            self.timeline.setValue(target)
            self.time_label.setText(self.format_time(target / 1000))

            if was_playing:
                state = self.player.get_state()
                if state in (vlc.State.Ended, vlc.State.Stopped):
                    self.playing = False
                    self.play_button.setText("▶️")
                else:
                    self.player.play()
                    # _on_playing event will sync button + self.playing=True
                self.was_playing = False
            else:
                self.play_button.setText("▶️")
                self.playing = False
            self.is_scrubbing = False
        except Exception as e:
            self.statusBar().showMessage(f"Error jumping to in point: {e}")
            print(f"Error jumping to in point: {e}")

    def jump_to_out_point(self):
        """Jump playhead (and UI) to the current out_point.
        If video was playing, resume playing after the jump for smooth continuation.
        Pause briefly only for the seek to avoid VLC buffer/deadlock issues.
        Symmetric to jump_to_in_point.
        """
        if not hasattr(self, "out_point"):
            return
        try:
            was_playing = self.player.is_playing()
            if was_playing:
                self.player.pause()
                # Do not force flags yet; will resume

            target = self.out_point
            duration = self.player.get_length()
            if duration > 0 and target > duration:
                target = duration

            self.player.set_time(target)
            self.timeline.setValue(target)
            self.time_label.setText(self.format_time(target / 1000))

            if was_playing:
                state = self.player.get_state()
                if state in (vlc.State.Ended, vlc.State.Stopped):
                    self.playing = False
                    self.play_button.setText("▶️")
                else:
                    self.player.play()
                    # _on_playing event will sync button + self.playing=True
                self.was_playing = False
            else:
                self.play_button.setText("▶️")
                self.playing = False
            self.is_scrubbing = False
        except Exception as e:
            self.statusBar().showMessage(f"Error jumping to out point: {e}")
            print(f"Error jumping to out point: {e}")

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

    def _set_video_controls_enabled(self, enabled):
        """Enable or disable the in/out point buttons, play/pause button, and playhead scrubber (timeline).
        Use when no valid video is loaded (initial state, load error) vs after successful load.
        """
        self.timeline.setEnabled(enabled)
        self.in_button.setEnabled(enabled)
        self.jump_in_button.setEnabled(enabled)
        self.play_button.setEnabled(enabled)
        self.jump_out_button.setEnabled(enabled)
        self.out_button.setEnabled(enabled)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = WorshipServiceEditor()
    sys.exit(app.exec())
