import sys
import vlc
import json
import os
import platformdirs
import shutil
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
    QDialog,
    QComboBox,
    QDialogButtonBox,
    QLineEdit,
    QCheckBox,
)
from PySide6.QtCore import Qt, QTimer, QThread, Signal
import subprocess
from datetime import datetime
from urllib.parse import unquote
from ffmpeg import FFmpeg


CONFIG_DIR = platformdirs.user_config_dir("sermon-transcribe")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")

DEFAULT_WHISPER_CLI = "/Users/ted/dev/whisper.cpp/build/bin/whisper-cli"
DEFAULT_MODELS_DIR = "/Users/ted/dev/whisper.cpp/models"

VIDEO_ENCODER_OPTIONS = [
    ("H.264", "h264"),
    ("H.265 / HEVC", "h265"),
    ("AV1 (SVT)", "av1"),
]
DEFAULT_VIDEO_ENCODER = "h264"


def load_config():
    try:
        if os.path.exists(CONFIG_PATH):
            with open(CONFIG_PATH, "r") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def save_config(config):
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(CONFIG_PATH, "w") as f:
            json.dump(config, f, indent=2)
    except Exception as e:
        print(f"Failed to save config: {e}")


def get_installed_models():
    """Discover whisper models from the default models directory (ggml-*.bin files)."""
    models = []
    if os.path.isdir(DEFAULT_MODELS_DIR):
        for f in os.listdir(DEFAULT_MODELS_DIR):
            if f.startswith("ggml-") and f.endswith(".bin"):
                models.append(f)
    return sorted(models)


def get_default_whisper_cli():
    """Seek a reasonable default for whisper-cli when no config is loadable on first run.
    Checks PATH first (whisper-cli, whisper), then common build locations, then falls back to the
    (possibly non-portable) DEFAULT_WHISPER_CLI.
    """
    # 1. PATH lookup (cross platform)
    for candidate_name in ("whisper-cli", "whisper"):
        found = shutil.which(candidate_name)
        if found:
            return found

    # 2. Common locations (relative to known model dir or user home)
    base_from_models = os.path.dirname(DEFAULT_MODELS_DIR) if DEFAULT_MODELS_DIR else ""
    candidates = [
        os.path.join(base_from_models, "build", "bin", "whisper-cli"),
        os.path.expanduser("~/whisper.cpp/build/bin/whisper-cli"),
        os.path.expanduser("~/whisper/build/bin/whisper-cli"),
        "/usr/local/bin/whisper-cli",
        "/opt/whisper.cpp/build/bin/whisper-cli",
        DEFAULT_WHISPER_CLI,  # last resort
    ]
    for c in candidates:
        if c and os.path.isfile(c) and os.access(c, os.X_OK):
            return c

    # 3. Absolute fallback (may not exist; user will be prompted to set via settings)
    return DEFAULT_WHISPER_CLI



class ExtractAndTranscribeThread(QThread):
    status_update = Signal(str)
    finished = Signal(str)

    def __init__(self, input_file, in_point, out_point, base_name, whisper_cli=None, model_path=None, video_encoder=DEFAULT_VIDEO_ENCODER, do_transcribe=True, do_transcode=True):
        super().__init__()
        self.input_file = input_file
        self.in_point = in_point
        self.out_point = out_point
        self.base_name = base_name
        self.is_cancelled = False
        self.whisper_cli = whisper_cli or get_default_whisper_cli()
        self.model_path = model_path or os.path.join(DEFAULT_MODELS_DIR, "ggml-large-v3.bin")
        self.video_encoder = video_encoder or DEFAULT_VIDEO_ENCODER
        self.do_transcribe = bool(do_transcribe)
        self.do_transcode = bool(do_transcode)


    def run(self):
        try:
            input_dir = os.path.dirname(self.input_file)
            sermon_video = os.path.join(input_dir, f"{self.base_name} sermon.mp4")
            sermon_audio = os.path.join(input_dir, f"{self.base_name} sermon.wav")
            sermon_text = os.path.join(input_dir, f"{self.base_name} sermon.txt")

            in_time = self.format_time_with_ms(self.in_point / 1000)
            out_time = self.format_time_with_ms(self.out_point / 1000)

            if self.do_transcode:
                self.video_extract(sermon_video)
                if self.is_cancelled:
                    return
                audio_source = sermon_video
            else:
                audio_source = self.input_file

            if self.do_transcribe:
                self.audio_extract(audio_source, sermon_audio,
                                   ss=(in_time if not self.do_transcode else None),
                                   to=(out_time if not self.do_transcode else None))
                if self.is_cancelled:
                    return
                self.transcribe(sermon_audio, sermon_text)

            self.finished.emit("Process complete.")
        except Exception as e:
            self.finished.emit(f"Error during processing: {str(e)}")

    def _input_is_h264(self, path):
        """Return True if the primary video stream codec is h264 (safe to -c:v copy)."""
        if not path:
            return False
        try:
            cmd = [
                "ffprobe",
                "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=codec_name",
                "-of", "csv=p=0",
                path,
            ]
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=15
            )
            codec = (result.stdout or "").strip().lower()
            return codec in ("h264", "avc1")
        except Exception:
            # ffprobe unavailable or unreadable file -> fall back to re-encode
            return False

    def video_extract(self, sermon_video):
        in_time = self.format_time_with_ms(self.in_point / 1000)
        out_time = self.format_time_with_ms(self.out_point / 1000)

        # Decide early (and only once) whether this will be a pure copy or actual re-encode.
        is_copy = (self.video_encoder == "h264" and self._input_is_h264(self.input_file))
        if is_copy:
            self.status_update.emit("Preparing to extract video segment...")
        else:
            self.status_update.emit("Preparing to extract and transcode video segment...")

        extract = (
            FFmpeg()
            .option("y")
            .input(self.input_file, ss=in_time, to=out_time)
        )

        if is_copy:
            self.status_update.emit("Input is already H.264 — using fast copy (no re-encode)...")
            output_opts = {"vcodec": "copy", "acodec": "copy", "movflags": "+faststart"}
        elif self.video_encoder == "av1":
            # Replicate Handbrake AV1 (SVT) settings from user logs:
            # preset 6, tune=psnr, profile main (default), crf 34.50 (RF), level auto
            v_opts = {"vcodec": "libsvtav1", "preset": 6, "crf": 34.5, "svtav1-params": "tune=1"}
            output_opts = {**v_opts, "acodec": "copy", "movflags": "+faststart"}
        elif self.video_encoder == "h265":
            v_opts = {"vcodec": "libx265", "preset": "fast", "crf": 30}
            output_opts = {**v_opts, "acodec": "copy", "movflags": "+faststart"}
        else:
            # h264 default (re-encode)
            v_opts = {"vcodec": "libx264", "preset": "fast", "crf": 28}
            output_opts = {**v_opts, "acodec": "copy", "movflags": "+faststart"}

        extract_video = extract.output(sermon_video, **output_opts)
        extract_video.execute()
        self.status_update.emit("Video segment extracted successfully.")

    def audio_extract(self, video_file, audio_file, ss=None, to=None):
        self.status_update.emit("Converting video to audio...")

        input_kwargs = {}
        if ss is not None and to is not None:
            input_kwargs = {"ss": ss, "to": to}

        extract_audio = (
            FFmpeg()
            .option("y")
            .input(video_file, **input_kwargs)
            .output(audio_file, acodec="pcm_s16le", ac=1, ar=16000)
        )

        extract_audio.execute()
        self.status_update.emit("Audio conversion completed successfully.")

    def transcribe(self, sermon_audio, sermon_text):
        self.status_update.emit("Transcribing audio...")

        whisper_cmd = [
            self.whisper_cli,
            "-m",
            self.model_path,
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


class SettingsDialog(QDialog):
    """Settings dialog for whisper-cli path (model and video encoder are now in main right panel)."""

    def __init__(self, parent, current_whisper_cli=""):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(500)

        self.whisper_cli = current_whisper_cli or ""

        layout = QVBoxLayout(self)

        # Whisper CLI path with file picker
        layout.addWidget(QLabel("whisper-cli executable:"))
        cli_layout = QHBoxLayout()
        self.cli_edit = QLineEdit(self.whisper_cli)
        self.cli_edit.setReadOnly(True)  # prefer picker over manual edit for safety
        cli_layout.addWidget(self.cli_edit, 1)
        self.browse_cli_button = QPushButton("Browse...")
        self.browse_cli_button.clicked.connect(self._browse_for_whisper_cli)
        cli_layout.addWidget(self.browse_cli_button)
        layout.addLayout(cli_layout)

        layout.addStretch()

        # Dialog buttons
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    def _browse_for_whisper_cli(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select whisper-cli executable",
            self.cli_edit.text() or os.path.dirname(DEFAULT_WHISPER_CLI) or "",
            "Executables (*);;All files (*)"
        )
        if path:
            self.cli_edit.setText(path)
            self.whisper_cli = path

    def accept(self):
        if self.cli_edit.text():
            self.whisper_cli = self.cli_edit.text()
        super().accept()

    def get_whisper_cli(self):
        return self.whisper_cli


class SermonTranscriber(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Sermon Transcriber")

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

        # Load models + config early (needed for dropdowns in right panel)
        self.available_models = get_installed_models()
        config = load_config()
        self.selected_model = config.get("selected_model")
        if not self.selected_model or (self.available_models and self.selected_model not in self.available_models):
            self.selected_model = self.available_models[0] if self.available_models else "ggml-large-v3.bin"

        self.video_encoder = config.get("video_encoder", DEFAULT_VIDEO_ENCODER)
        if self.video_encoder not in (k for _, k in VIDEO_ENCODER_OPTIONS):
            self.video_encoder = DEFAULT_VIDEO_ENCODER

        self.do_transcribe = config.get("do_transcribe", True)
        self.do_transcode = config.get("do_transcode", True)

        # For whisper_cli: if no loadable config (or no key), seek a reasonable default on first run
        if not config or "whisper_cli" not in config:
            self.whisper_cli = get_default_whisper_cli()
            # Save immediately so the discovered default is persisted (include new flags)
            init_config = {
                "selected_model": self.selected_model,
                "whisper_cli": self.whisper_cli,
                "video_encoder": self.video_encoder,
                "do_transcribe": self.do_transcribe,
                "do_transcode": self.do_transcode,
            }
            save_config(init_config)
        else:
            self.whisper_cli = config.get("whisper_cli") or get_default_whisper_cli()

        # Create central widget and main horizontal layout (video+controls | right action panel)
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        self.setAcceptDrops(True)
        main_layout = QHBoxLayout(central_widget)

        # --- LEFT: video, browse, timeline, in/out/playhead ---
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 10, 0)

        # Create video widget
        self.video_widget = QWidget()
        self.video_widget.setMinimumSize(640, 360)
        left_layout.addWidget(self.video_widget)

        # File selection
        file_layout = QHBoxLayout()
        self.file_button = QPushButton("Browse")
        self.file_button.clicked.connect(self.browse_file)
        file_layout.addWidget(self.file_button)
        left_layout.addLayout(file_layout)

        # Timeline scrubber (full width above button row)
        self.timeline = QSlider(Qt.Orientation.Horizontal)
        self.timeline.setMinimum(0)
        self.timeline.valueChanged.connect(self.on_timeline_change)
        self.timeline.sliderPressed.connect(self.on_timeline_press)
        self.timeline.sliderReleased.connect(self.on_timeline_release)
        left_layout.addWidget(self.timeline)

        # In/Out points row (same groups as before)
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

        left_layout.addLayout(points_layout)
        main_layout.addWidget(left_widget, 4)

        # --- RIGHT: new panel with enable checkboxes + moved dropdowns + action button ---
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(10, 0, 0, 0)

        # Transcription enable + model dropdown (moved from settings)
        self.transcribe_cb = QCheckBox("Enable transcription")
        self.transcribe_cb.setChecked(self.do_transcribe)
        right_layout.addWidget(self.transcribe_cb)

        right_layout.addWidget(QLabel("Model:"))
        self.model_combo = QComboBox()
        if self.available_models:
            self.model_combo.addItems(self.available_models)
            if self.selected_model in self.available_models:
                self.model_combo.setCurrentText(self.selected_model)
            else:
                self.model_combo.setCurrentIndex(0)
        else:
            self.model_combo.addItem("No models found (ggml-*.bin)")
            self.model_combo.setEnabled(False)
        right_layout.addWidget(self.model_combo)

        right_layout.addSpacing(12)

        # Transcoding enable + format dropdown (moved from settings)
        self.transcode_cb = QCheckBox("Enable transcoding")
        self.transcode_cb.setChecked(self.do_transcode)
        right_layout.addWidget(self.transcode_cb)

        right_layout.addWidget(QLabel("Transcode format:"))
        self.encoder_combo = QComboBox()
        self.encoder_labels = [label for label, key in VIDEO_ENCODER_OPTIONS]
        self.encoder_keys = [key for label, key in VIDEO_ENCODER_OPTIONS]
        self.encoder_combo.addItems(self.encoder_labels)
        try:
            idx = self.encoder_keys.index(self.video_encoder)
            self.encoder_combo.setCurrentIndex(idx)
        except ValueError:
            self.encoder_combo.setCurrentIndex(0)
        right_layout.addWidget(self.encoder_combo)

        right_layout.addSpacing(16)

        # Main action button (moved here)
        self.transcribe_button = QPushButton("Extract and Transcribe")
        self.transcribe_button.clicked.connect(self.start_extract_and_transcribe)
        right_layout.addWidget(self.transcribe_button)

        # Small settings gear (kept accessible)
        self.settings_button = QPushButton("⚙️ Settings")
        self.settings_button.setFixedHeight(26)
        self.settings_button.setToolTip("Settings (whisper-cli path)")
        self.settings_button.clicked.connect(self.open_settings)
        right_layout.addWidget(self.settings_button)

        right_layout.addStretch()
        main_layout.addWidget(right_widget, 1)

        # Initialize variables
        self.playing = False
        self.was_playing = False
        self.in_point = 0
        self.out_point = 0
        self.extraction_thread = None
        self.has_valid_video = False

        # Wire config persistence for the new main-panel controls
        self.transcribe_cb.toggled.connect(self._save_config)
        self.transcode_cb.toggled.connect(self._save_config)
        self.model_combo.currentIndexChanged.connect(self._save_config)
        self.encoder_combo.currentIndexChanged.connect(self._save_config)

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
            media = self.player.get_media()
            if not media:
                self.statusBar().showMessage("No video loaded")
                return
            input_file = media.get_mrl()
            if input_file.startswith("file://"):
                input_file = input_file[7:]  # Remove 'file://' prefix

            # URL decode the path
            input_file = unquote(input_file)

            # Get the base name of the input file
            base_name = os.path.splitext(os.path.basename(input_file))[0]

            # Read live state from right panel controls
            do_transcribe = self.transcribe_cb.isChecked()
            do_transcode = self.transcode_cb.isChecked()
            model_name = self.model_combo.currentText() if (self.model_combo.count() > 0 and self.model_combo.isEnabled()) else self.selected_model
            model_path = os.path.join(DEFAULT_MODELS_DIR, model_name) if model_name else None
            video_encoder = self._get_current_video_encoder()

            self.extraction_thread = ExtractAndTranscribeThread(
                input_file, self.in_point, self.out_point, base_name,
                whisper_cli=self.whisper_cli,
                model_path=model_path,
                video_encoder=video_encoder,
                do_transcribe=do_transcribe,
                do_transcode=do_transcode,
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

    def open_settings(self):
        """Open the settings dialog (only for whisper-cli path; model + transcoder format live in main right panel)."""
        dialog = SettingsDialog(self, self.whisper_cli)
        if dialog.exec():
            new_cli = dialog.get_whisper_cli()
            if new_cli:
                self.whisper_cli = new_cli
            # Persist (model/encoder/do_* driven by main panel + _save_config)
            config = load_config()
            config["whisper_cli"] = self.whisper_cli
            save_config(config)
            self.statusBar().showMessage("Settings updated")

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
        if hasattr(self, "transcribe_button") and getattr(self, "transcribe_button", None) and self.transcribe_button.text() == "Extract and Transcribe":
            self.transcribe_button.setEnabled(enabled)

    def _save_config(self):
        """Persist model, encoder, and the two enable checkboxes from the right panel controls."""
        try:
            config = load_config()
            if self.model_combo.count() > 0 and self.model_combo.isEnabled():
                config["selected_model"] = self.model_combo.currentText()
            config["video_encoder"] = self._get_current_video_encoder()
            config["do_transcribe"] = self.transcribe_cb.isChecked()
            config["do_transcode"] = self.transcode_cb.isChecked()
            if self.whisper_cli:
                config["whisper_cli"] = self.whisper_cli
            save_config(config)
        except Exception:
            pass  # never let save break UI

    def _get_current_video_encoder(self):
        if hasattr(self, "encoder_combo") and self.encoder_combo.count() > 0:
            try:
                idx = self.encoder_combo.currentIndex()
                return self.encoder_keys[idx]
            except Exception:
                pass
        return getattr(self, "video_encoder", DEFAULT_VIDEO_ENCODER)

    def dragEnterEvent(self, event):
        """Accept drag if it contains a single local video file we support."""
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            if len(urls) == 1 and urls[0].isLocalFile():
                path = urls[0].toLocalFile()
                if self._is_supported_video(path):
                    event.acceptProposedAction()
                    return
        event.ignore()

    def dropEvent(self, event):
        """Handle dropped video file by loading it (replaces current if any)."""
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            if len(urls) == 1 and urls[0].isLocalFile():
                path = urls[0].toLocalFile()
                if self._is_supported_video(path):
                    self.load_video(path)
                    event.acceptProposedAction()
                    return
        event.ignore()

    def _is_supported_video(self, path):
        """Match the exact extensions offered by the Browse dialog."""
        if not path:
            return False
        ext = os.path.splitext(path)[1].lower()
        return ext in (".mp4", ".mov", ".mkv")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = SermonTranscriber()
    sys.exit(app.exec())
