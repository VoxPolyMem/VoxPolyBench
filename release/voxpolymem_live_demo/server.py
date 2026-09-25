#!/usr/bin/env python3
"""Localhost HTTP server for the standalone audio-first live demo."""
from __future__ import annotations

from copy import deepcopy
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.util import find_spec
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from threading import RLock
from urllib.parse import parse_qs, unquote, urlparse
from uuid import uuid4

from memory import DemoEngine, ModelClient, SessionStore, session_id


ROOT = Path(__file__).resolve().parent
MAX_AUDIO_BYTES = 15 * 1024 * 1024
MIN_AUDIO_BYTES = 256  # Reject container headers with no usable recording.
MIME_EXTENSIONS = {"audio/webm": ".webm", "audio/ogg": ".ogg", "audio/mp4": ".m4a", "audio/mpeg": ".mp3", "audio/wav": ".wav", "audio/x-wav": ".wav"}


def validate_audio_payload(data: bytes, suffix: str) -> None:
    """Reject empty clips and clearly mismatched container headers."""
    if not MIN_AUDIO_BYTES <= len(data) <= MAX_AUDIO_BYTES:
        raise ValueError("Audio must contain a recording and be no larger than 15 MB")
    valid_header = {
        ".wav": data[:4] in (b"RIFF", b"RF64") and data[8:12] == b"WAVE",
        ".webm": data.startswith(b"\x1a\x45\xdf\xa3"),
        ".ogg": data.startswith(b"OggS"),
        ".m4a": data[4:8] == b"ftyp",
        ".mp3": data.startswith(b"ID3") or (data[0] == 0xff and data[1] & 0xe0 == 0xe0),
    }.get(suffix, False)
    if not valid_header:
        raise ValueError("Audio content does not match its declared format")


def load_env(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_env(ROOT / ".env")
source_setting = os.environ.get("VOXPOLYMEM_SOURCE", "../voxpolymem_code")
SOURCE = Path(source_setting)
if not SOURCE.is_absolute():
    SOURCE = ROOT / SOURCE
STORE = SessionStore(ROOT / "runtime" / "sessions")
MODEL = ModelClient(
    os.environ.get("DEMO_API_KEY", ""),
    os.environ.get("DEMO_API_BASE", "https://api.openai.com/v1"),
    os.environ.get("DEMO_LLM_MODEL", "gpt-4.1-mini"),
)
ENGINE = DemoEngine(STORE, MODEL, SOURCE, int(os.environ.get("DEMO_TOP_K", "20")))


class AudioServices:
    def __init__(self):
        self.asr_backend = os.environ.get("DEMO_ASR_BACKEND", "openai").strip().lower()
        self.speaker_backend = os.environ.get("DEMO_SPEAKER_BACKEND", "off").strip().lower()
        self._whisper = None
        self._encoder = None
        self._memory_class = None
        self._speaker_by_session = {}
        self._lock = RLock()
        self.speaker_error = None

    def status(self):
        speaker_deps = all(find_spec(name) is not None for name in ("numpy", "soundfile", "scipy", "torch", "speechbrain"))
        speaker_available = self.speaker_backend == "ecapa" and ENGINE.frozen and speaker_deps and shutil.which("ffmpeg") is not None
        return {
            "asr_backend": self.asr_backend,
            "asr_available": self.asr_backend == "faster_whisper" or (self.asr_backend == "openai" and MODEL.available),
            "speaker_backend": self.speaker_backend,
            "speaker_available": speaker_available,
            "speaker_ready": self._encoder is not None,
            "speaker_error": self.speaker_error,
        }

    def transcribe(self, data: bytes, suffix: str) -> str:
        if self.asr_backend == "openai":
            return MODEL.transcribe(data, "recording" + suffix, os.environ.get("DEMO_ASR_MODEL", "gpt-4o-mini-transcribe"))
        if self.asr_backend == "faster_whisper":
            if self._whisper is None:
                try:
                    from faster_whisper import WhisperModel
                except ImportError as exc:
                    raise RuntimeError("Install faster-whisper for local ASR") from exc
                self._whisper = WhisperModel(os.environ.get("DEMO_WHISPER_MODEL", "small"), device="auto", compute_type="int8")
            with tempfile.NamedTemporaryFile(suffix=suffix) as handle:
                handle.write(data)
                handle.flush()
                segments, _ = self._whisper.transcribe(handle.name, vad_filter=True)
                return " ".join(segment.text.strip() for segment in segments).strip()
        raise RuntimeError("ASR is disabled; use the text-turn fallback or configure DEMO_ASR_BACKEND")

    def identify_speaker(self, sid: str, data: bytes, suffix: str, *, update_profile: bool = True) -> dict | None:
        if self.speaker_backend != "ecapa":
            return None
        if not ENGINE.frozen:
            raise RuntimeError("Frozen source is required for ECAPA speaker matching")
        with self._lock:
            if self._encoder is None:
                speaker_dir = SOURCE / "audio" / "speaker"
                sys.path.insert(0, str(speaker_dir))
                from ecapa_encoder import EcapaEncoder
                from online_speaker_identity_pipeline import OnlineSpeakerMemory
                self._encoder = EcapaEncoder(device=os.environ.get("DEMO_SPEAKER_DEVICE", "cpu"))
                self._memory_class = OnlineSpeakerMemory
            tracker = self._speaker_by_session.get(sid)
            if tracker is None:
                tracker = self._memory_class()
                for turn in STORE.get(sid)["turns"]:
                    if not turn.get("acoustic_id"):
                        continue
                    name = turn.get("audio_name")
                    if not name:
                        continue
                    old_audio = ROOT / "runtime" / "audio" / sid / name
                    if old_audio.is_file():
                        old_vector = self._voice_vector(old_audio.read_bytes(), old_audio.suffix)
                        if old_vector is not None:
                            tracker.ingest(old_vector)
                self._speaker_by_session[sid] = tracker
            vector = self._voice_vector(data, suffix)
            if vector is None:
                return None
            self.speaker_error = None
            return (tracker if update_profile else deepcopy(tracker)).ingest(vector)

    def _voice_vector(self, data: bytes, suffix: str):
        with tempfile.TemporaryDirectory(prefix="voxpolymem_demo_") as directory:
            audio_path = Path(directory) / ("input" + suffix)
            wav_path = Path(directory) / "speaker.wav"
            audio_path.write_bytes(data)
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(audio_path), "-ac", "1", "-ar", "16000", str(wav_path)], check=True, timeout=30)
            return self._encoder.encode(wav_path)


AUDIO = AudioServices()


class Handler(BaseHTTPRequestHandler):
    server_version = "VoxPolyMemDemo/0.1"

    def _json(self, value, status=HTTPStatus.OK):
        body = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _error(self, exc, status=HTTPStatus.BAD_REQUEST):
        self._json({"error": str(exc)}, status)

    def _read_json(self):
        length = int(self.headers.get("Content-Length", "0"))
        if not 0 < length <= 100_000:
            raise ValueError("Invalid JSON request size")
        return json.loads(self.rfile.read(length))

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/status":
            return self._json({**ENGINE.status(), **AUDIO.status()})
        if parsed.path == "/api/state":
            try:
                sid = session_id(parse_qs(parsed.query).get("sid", [None])[0])
                return self._json(STORE.get(sid))
            except ValueError as exc:
                return self._error(exc)
        if parsed.path.startswith("/api/audio/"):
            pieces = parsed.path.split("/")
            if len(pieces) != 5:
                return self.send_error(HTTPStatus.NOT_FOUND)
            try:
                sid = session_id(pieces[3])
            except ValueError:
                return self.send_error(HTTPStatus.NOT_FOUND)
            name = pieces[4]
            if name != Path(name).name or not name.startswith("turn-"):
                return self.send_error(HTTPStatus.NOT_FOUND)
            path = ROOT / "runtime" / "audio" / sid / name
            if not path.is_file():
                return self.send_error(HTTPStatus.NOT_FOUND)
            body = path.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "audio/" + ("webm" if path.suffix == ".webm" else "mpeg" if path.suffix == ".mp3" else "wav" if path.suffix == ".wav" else "mp4"))
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        files = {"/": ("index.html", "text/html"), "/app.js": ("app.js", "text/javascript"), "/styles.css": ("styles.css", "text/css")}
        if parsed.path not in files:
            return self.send_error(HTTPStatus.NOT_FOUND)
        name, content_type = files[parsed.path]
        body = (ROOT / name).read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type + "; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/api/turn":
                data = self._read_json()
                sid = session_id(data.get("sid"))
                audio_name = str(data.get("audio_name") or "")
                if audio_name:
                    audio_path = ROOT / "runtime" / "audio" / sid / audio_name
                    if audio_name != Path(audio_name).name or not audio_name.startswith("turn-") or not audio_path.is_file():
                        raise ValueError("Audio clip does not belong to this session")
                acoustic_id = None
                speaker_match = None
                speaker_warning = None
                if audio_name and AUDIO.speaker_backend == "ecapa":
                    try:
                        speaker_match = AUDIO.identify_speaker(sid, audio_path.read_bytes(), audio_path.suffix)
                        acoustic_id = speaker_match["acoustic_speaker_id"] if speaker_match else None
                    except Exception as exc:
                        AUDIO.speaker_error = str(exc)
                        speaker_warning = f"Speaker model unavailable: {exc}"
                result = ENGINE.ingest(sid, str(data.get("text") or ""), str(data.get("speaker") or ""), audio_name or None, acoustic_id, speaker_match)
                if speaker_warning:
                    result["warning"] = "; ".join(filter(None, [result.get("warning"), speaker_warning]))
                return self._json(result)
            if parsed.path == "/api/ask":
                data = self._read_json()
                return self._json(ENGINE.ask(session_id(data.get("sid")), str(data.get("question") or ""), str(data.get("asker") or "")))
            if parsed.path == "/api/speaker-label":
                data = self._read_json()
                return self._json(ENGINE.bind_speaker(
                    session_id(data.get("sid")), str(data.get("acoustic_id") or ""), str(data.get("label") or "")
                ))
            if parsed.path == "/api/audio":
                length = int(self.headers.get("Content-Length", "0"))
                if not MIN_AUDIO_BYTES <= length <= MAX_AUDIO_BYTES:
                    raise ValueError("Audio must contain a recording and be no larger than 15 MB")
                mime = self.headers.get("Content-Type", "").split(";", 1)[0].lower()
                suffix = MIME_EXTENSIONS.get(mime)
                if not suffix:
                    raise ValueError("Unsupported audio format")
                sid = session_id(self.headers.get("X-Session-ID"))
                purpose = self.headers.get("X-Purpose", "turn")
                if purpose not in {"turn", "question"}:
                    raise ValueError("Unknown audio purpose")
                data = self.rfile.read(length)
                validate_audio_payload(data, suffix)
                try:
                    transcript = AUDIO.transcribe(data, suffix)
                    if not transcript:
                        raise RuntimeError("ASR returned an empty transcript")
                except Exception as exc:
                    if purpose == "question":
                        raise
                    audio_name = self._save_audio(sid, data, suffix)
                    return self._json({
                        "pending_transcript": True, "audio_name": audio_name,
                        "warning": f"Audio saved locally. ASR unavailable ({exc}); enter or correct the transcript below, then add the turn.",
                    })
                speaker = unquote(self.headers.get("X-Speaker", "")).strip()
                if purpose == "question":
                    asker_match = None
                    speaker_warning = None
                    try:
                        asker_match = AUDIO.identify_speaker(sid, data, suffix, update_profile=False)
                    except Exception as exc:
                        AUDIO.speaker_error = str(exc)
                        speaker_warning = f"Question speaker model unavailable: {exc}"
                    asker_acoustic_id = asker_match["acoustic_speaker_id"] if asker_match else None
                    result = ENGINE.ask(sid, transcript, speaker, asker_acoustic_id)
                    result["transcript"] = transcript
                    if speaker_warning:
                        result["warning"] = speaker_warning
                    return self._json(result)
                acoustic_id = None
                speaker_match = None
                warning = None
                try:
                    speaker_match = AUDIO.identify_speaker(sid, data, suffix)
                    acoustic_id = speaker_match["acoustic_speaker_id"] if speaker_match else None
                except Exception as exc:
                    AUDIO.speaker_error = str(exc)
                    warning = f"Speaker model unavailable: {exc}"
                audio_name = self._save_audio(sid, data, suffix)
                result = ENGINE.ingest(sid, transcript, speaker, audio_name, acoustic_id, speaker_match)
                result["transcript"] = transcript
                if warning:
                    result["warning"] = "; ".join(filter(None, [result.get("warning"), warning]))
                return self._json(result)
            return self.send_error(HTTPStatus.NOT_FOUND)
        except (ValueError, KeyError, json.JSONDecodeError) as exc:
            self._error(exc)
        except Exception as exc:
            self._error(exc, HTTPStatus.BAD_GATEWAY)

    @staticmethod
    def _save_audio(sid: str, data: bytes, suffix: str) -> str:
        audio_dir = ROOT / "runtime" / "audio" / sid
        audio_dir.mkdir(parents=True, exist_ok=True)
        audio_name = "turn-" + uuid4().hex + suffix
        (audio_dir / audio_name).write_bytes(data)
        return audio_name


def main():
    host = os.environ.get("DEMO_HOST", "127.0.0.1")
    port = int(os.environ.get("DEMO_PORT", "8788"))
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"VoxPolyMem live demo: http://{host}:{port}")
    print(f"LLM: {'connected' if MODEL.available else 'offline preview'}; frozen core: {'loaded' if ENGINE.frozen else 'not found'}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
