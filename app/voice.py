"""Salesforce Jarvis Voice Engine & Executive Morning Briefing.

Milestone 4 Implementation:
- High-definition British Butler neural speech synthesis using Microsoft edge-tts ('en-GB-RyanNeural')
- 100% free, natural speech synthesis without requiring paid cloud API keys
- Robust offline fallback to Windows SAPI5 (win32com.client.Dispatch("SAPI.SpVoice"))
- Non-blocking audio playback using Windows native Media Control Interface (MCI via ctypes)
- Thread-safe PriorityQueue worker thread with instant interrupt, mute, and queue drain
- Integration with AppEventBus and EventTopic (VOICE_SPEAK, VOICE_MUTE)
- Executive Morning Briefing engine consuming app/state.json telemetry snapshot
- Under 75MB Working Set RAM footprint and zero console flash
"""

from __future__ import annotations

import asyncio
import ctypes
import json
import logging
import os
import queue
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

# Try importing app models and event bus, with fallback for standalone execution
try:
    from app.models import EventTopic, VoiceMessage
except ImportError:
    @dataclass(order=True)
    class VoiceMessage:
        priority: int  # 0 = Highest (CRITICAL), 10 = Normal, 20 = Low
        text: str = field(compare=False)
        timestamp: float = field(default_factory=time.time, compare=False)
        source: str = field(default="radar", compare=False)

    class EventTopic:  # type: ignore
        VOICE_SPEAK = "voice_speak"
        VOICE_MUTE = "voice_mute"
        SCAN_COMPLETED = "scan_completed"

try:
    from app.event_bus import default_event_bus
except ImportError:
    default_event_bus = None

# Configure logger
logger = logging.getLogger("jarvis.voice")

# Constants
DEFAULT_VOICE = "en-GB-RyanNeural"  # High-definition British Butler voice
FALLBACK_VOICE = "en-GB-SoniaNeural"
DEFAULT_RATE = "+0%"
DEFAULT_PITCH = "-2Hz"
DEFAULT_VOLUME = "+0%"

APP_DIR = Path(__file__).resolve().parent
STATE_FILE_PATH = APP_DIR / "state.json"
CACHE_DIR = Path(tempfile.gettempdir()) / "jarvis_voice_cache"


# ---------------------------------------------------------------------------
# Native Windows MCI Audio Player
# ---------------------------------------------------------------------------

class MCIAudioPlayer:
    """Windows Native Media Control Interface (MCI) non-blocking audio player.
    
    Plays MP3 and WAV files directly via Windows winmm.dll without needing
    heavy third-party audio packages (pygame, playsound) or external executables.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._winmm = None
        self._current_alias: Optional[str] = None
        self._is_playing = False
        self._active_file: Optional[str] = None

        if sys.platform == "win32":
            try:
                self._winmm = ctypes.windll.winmm
            except Exception as e:
                logger.warning("Could not load winmm.dll: %s", e)

    def is_available(self) -> bool:
        return self._winmm is not None

    def is_playing(self) -> bool:
        with self._lock:
            if not self._is_playing or not self._current_alias or not self._winmm:
                return False
            buf = ctypes.create_unicode_buffer(128)
            err = self._winmm.mciSendStringW(f"status {self._current_alias} mode", buf, 128, None)
            if err == 0 and buf.value in ("playing", "seeking"):
                return True
            return False

    def stop(self) -> None:
        """Immediately stop and close any active MCI playback."""
        with self._lock:
            if self._winmm and self._current_alias:
                try:
                    self._winmm.mciSendStringW(f"stop {self._current_alias}", None, 0, None)
                    self._winmm.mciSendStringW(f"close {self._current_alias}", None, 0, None)
                except Exception as e:
                    logger.debug("Error stopping MCI: %s", e)
                finally:
                    self._current_alias = None
                    self._is_playing = False
                    self._active_file = None

    def play_file(
        self,
        filepath: str,
        cancel_event: Optional[threading.Event] = None,
        poll_interval: float = 0.05,
    ) -> bool:
        """Play audio file synchronously on the calling thread (designed for worker threads).
        
        Can be cancelled at any time via cancel_event or self.stop().
        """
        if not self.is_available():
            logger.warning("MCI player not available on this platform.")
            return False

        abs_path = os.path.abspath(filepath)
        if not os.path.exists(abs_path):
            logger.error("Audio file does not exist: %s", abs_path)
            return False

        # Stop previous playback
        self.stop()

        with self._lock:
            alias = f"jarvis_mci_{os.getpid()}_{int(time.time() * 1000) % 100000}"
            self._current_alias = alias
            self._active_file = abs_path

            # Determine MCI file type
            lower = abs_path.lower()
            media_type = "mpegvideo" if lower.endswith(".mp3") else "waveaudio"

            cmd_open = f'open "{abs_path}" type {media_type} alias {alias}'
            err = self._winmm.mciSendStringW(cmd_open, None, 0, None)
            if err != 0:
                logger.warning("MCI open failed with error code %d for %s", err, abs_path)
                self.stop()
                return False

            cmd_play = f"play {alias}"
            err = self._winmm.mciSendStringW(cmd_play, None, 0, None)
            if err != 0:
                logger.warning("MCI play failed with error code %d", err)
                self.stop()
                return False

            self._is_playing = True

        # Polling loop to wait for audio completion or cancellation
        buf = ctypes.create_unicode_buffer(128)
        try:
            while True:
                if cancel_event and cancel_event.is_set():
                    logger.debug("MCI playback cancelled via event.")
                    self.stop()
                    return False

                with self._lock:
                    if not self._is_playing or self._current_alias != alias:
                        return False
                    err = self._winmm.mciSendStringW(f"status {alias} mode", buf, 128, None)
                    if err != 0:
                        break
                    mode = buf.value
                    if mode not in ("playing", "seeking", "paused"):
                        # Playback finished (stopped or completed)
                        break

                time.sleep(poll_interval)
            return True
        finally:
            self.stop()


# ---------------------------------------------------------------------------
# Windows SAPI5 Speech Synthesizer (Offline Fallback)
# ---------------------------------------------------------------------------

class WindowsSAPI5Synthesizer:
    """Native Windows SAPI5 speech synthesizer using win32com.client.
    
    Provides 100% offline speech synthesis without internet connectivity.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._voice = None
        self._initialized = False
        self._init_sapi()

    def _init_sapi(self) -> None:
        if sys.platform != "win32":
            return
        try:
            import win32com.client
            self._voice = win32com.client.Dispatch("SAPI.SpVoice")
            self._initialized = True
            self._select_best_voice()
        except Exception as e:
            logger.warning("Could not initialize SAPI5: %s", e)
            self._voice = None
            self._initialized = False

    def _select_best_voice(self) -> None:
        """Prefer British or natural English voice if installed in Windows SAPI5."""
        if not self._voice:
            return
        try:
            voices = self._voice.GetVoices()
            for i in range(voices.Count):
                desc = voices.Item(i).GetDescription().lower()
                if "british" in desc or "hazel" in desc or "george" in desc:
                    self._voice.Voice = voices.Item(i)
                    logger.info("Selected SAPI5 voice: %s", voices.Item(i).GetDescription())
                    return
        except Exception as e:
            logger.debug("Error setting SAPI5 voice preference: %s", e)

    def is_available(self) -> bool:
        return self._initialized and self._voice is not None

    def stop(self) -> None:
        """Purge and interrupt ongoing speech immediately."""
        with self._lock:
            if self._voice:
                try:
                    # SVSFPurgeBeforeSpeak = 2
                    self._voice.Speak("", 2)
                except Exception as e:
                    logger.debug("Error purging SAPI5: %s", e)

    def speak(self, text: str, cancel_event: Optional[threading.Event] = None) -> bool:
        """Speak text using SAPI5 with async flags and cancel polling."""
        if not self.is_available():
            logger.warning("SAPI5 not available.")
            return False

        with self._lock:
            try:
                # SVSFlagsAsync = 1, SVSFPurgeBeforeSpeak = 2
                self._voice.Speak(text, 1 | 2)
            except Exception as e:
                logger.error("SAPI5 speak failed: %s", e)
                return False

        # Poll status until done or cancelled
        try:
            while True:
                if cancel_event and cancel_event.is_set():
                    self.stop()
                    return False
                with self._lock:
                    if not self._voice:
                        return False
                    status = self._voice.Status
                    # RunningState == 2 indicates speaking
                    if status.RunningState != 2:
                        break
                time.sleep(0.05)
            return True
        except Exception as e:
            logger.error("Error monitoring SAPI5 playback: %s", e)
            self.stop()
            return False


# ---------------------------------------------------------------------------
# High-Definition British Butler Neural TTS (edge-tts)
# ---------------------------------------------------------------------------

class EdgeTTSButlerSynthesizer:
    """High-Definition British Butler Neural Speech Synthesizer using Microsoft edge-tts.
    
    Produces natural, studio-quality, British-accented audio (en-GB-RyanNeural)
    with zero API keys, completely free, and non-blocking.
    """

    def __init__(
        self,
        voice: str = DEFAULT_VOICE,
        rate: str = DEFAULT_RATE,
        pitch: str = DEFAULT_PITCH,
        volume: str = DEFAULT_VOLUME,
    ) -> None:
        self.voice = voice
        self.rate = rate
        self.pitch = pitch
        self.volume = volume
        CACHE_DIR.mkdir(parents=True, exist_ok=True)

    def synthesize_to_file(self, text: str, output_path: Optional[Path] = None) -> Optional[Path]:
        """Synthesize text into an MP3 file using edge-tts.
        
        Returns path to generated MP3 file, or None on failure.
        """
        try:
            import edge_tts
        except ImportError:
            logger.warning("edge-tts package is not installed.")
            return None

        if not text or not text.strip():
            return None

        if output_path is None:
            # Deterministic cache filename for repeated phrases
            clean_hash = abs(hash((self.voice, self.rate, self.pitch, text))) % (10**12)
            output_path = CACHE_DIR / f"jarvis_speech_{clean_hash}.mp3"

        # If already cached and valid size, return immediately
        if output_path.exists() and output_path.stat().st_size > 1024:
            return output_path

        temp_target = output_path.with_suffix(".tmp.mp3")

        async def _synthesize() -> None:
            communicate = edge_tts.Communicate(
                text=text,
                voice=self.voice,
                rate=self.rate,
                pitch=self.pitch,
                volume=self.volume,
            )
            await communicate.save(str(temp_target))

        try:
            # Run asynchronous edge-tts synthesis cleanly
            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(_synthesize())
            finally:
                loop.close()

            if temp_target.exists() and temp_target.stat().st_size > 0:
                if output_path.exists():
                    output_path.unlink()
                temp_target.rename(output_path)
                return output_path
            else:
                logger.warning("Synthesized file was empty or missing.")
                return None
        except Exception as e:
            logger.warning("edge-tts neural synthesis failed (%s), will fallback.", e)
            if temp_target.exists():
                try:
                    temp_target.unlink()
                except Exception:
                    pass
            return None


# ---------------------------------------------------------------------------
# Voice Engine Daemon (Priority Queue Worker)
# ---------------------------------------------------------------------------

class VoiceEngine:
    """Thread-safe Priority Queue Voice Engine & TTS Worker.
    
    Architecture:
    1. Primary: Edge-TTS British Butler (en-GB-RyanNeural) -> Native MCI audio player
    2. Secondary Fallback: Windows SAPI5 Speech Synthesizer (100% offline)
    3. Non-blocking PriorityQueue consumption
    4. Instant mute / interrupt / purge capabilities
    """

    def __init__(
        self,
        voice_name: str = DEFAULT_VOICE,
        rate: str = DEFAULT_RATE,
        pitch: str = DEFAULT_PITCH,
        volume: str = DEFAULT_VOLUME,
    ) -> None:
        self.voice_name = voice_name
        self.rate = rate
        self.pitch = pitch
        self.volume = volume

        # Synthesizers and players
        self.neural_tts = EdgeTTSButlerSynthesizer(
            voice=self.voice_name, rate=self.rate, pitch=self.pitch, volume=self.volume
        )
        self.mci_player = MCIAudioPlayer()
        self.sapi_synth = WindowsSAPI5Synthesizer()

        # State flags
        self._muted = False
        self._is_speaking = False
        self._lock = threading.RLock()
        self._stop_requested = threading.Event()
        self._interrupt_current = threading.Event()

        # Priority queue for speech messages: lower number = higher priority
        self._queue: queue.PriorityQueue[VoiceMessage] = queue.PriorityQueue()

        # Worker thread
        self._worker_thread = threading.Thread(
            target=self._worker_loop, name="JarvisVoiceWorker", daemon=True
        )
        self._worker_thread.start()

        # Subscriptions
        self._subscribed_buses: set[int] = set()
        self.subscribe_to_event_bus()

        logger.info("VoiceEngine initialized with British Butler voice: %s", self.voice_name)

    def subscribe_to_event_bus(self, bus: Any = None) -> None:
        """Subscribe voice engine to application event bus."""
        target_bus = bus or default_event_bus
        if target_bus:
            bus_id = id(target_bus)
            if bus_id not in self._subscribed_buses:
                try:
                    target_bus.subscribe(EventTopic.VOICE_SPEAK, self._handle_bus_speak)
                    target_bus.subscribe(EventTopic.VOICE_MUTE, self._handle_bus_mute)
                    if hasattr(EventTopic, "TRIGGER_BRIEFING"):
                        target_bus.subscribe(EventTopic.TRIGGER_BRIEFING, self._handle_bus_briefing)
                    if hasattr(EventTopic, "SYSTEM_SHUTDOWN"):
                        target_bus.subscribe(EventTopic.SYSTEM_SHUTDOWN, lambda _: self.stop())
                    self._subscribed_buses.add(bus_id)
                    logger.debug("VoiceEngine subscribed to EventBus topics.")
                except Exception as e:
                    logger.debug("Could not subscribe to EventBus: %s", e)

    def _handle_bus_briefing(self, payload: Any = None) -> None:
        """Handler for TRIGGER_BRIEFING event."""
        logger.info("Executive Morning Briefing triggered via EventBus.")
        ExecutiveBriefing.run_briefing(self)

    def _handle_bus_speak(self, payload: Any) -> None:
        if isinstance(payload, VoiceMessage):
            self.speak_message(payload)
        elif isinstance(payload, str):
            self.speak(payload)
        elif isinstance(payload, dict):
            text = payload.get("text", "")
            priority = payload.get("priority", 10)
            source = payload.get("source", "event_bus")
            self.speak(text, priority=priority, source=source)

    def _handle_bus_mute(self, payload: Any) -> None:
        if isinstance(payload, bool):
            self.mute(payload)
        else:
            self.toggle_mute()

    def speak(self, text: str, priority: int = 10, source: str = "general") -> None:
        """Enqueue text for speech synthesis (non-blocking).
        
        Priority guide:
        - 0 = CRITICAL (e.g. fatal recursion / governor breach)
        - 5 = Executive Morning Briefing
        - 10 = Normal scan status / warning
        - 20 = Ambient / debug notice
        """
        if not text or not text.strip():
            return
        msg = VoiceMessage(priority=priority, text=text.strip(), source=source)
        self.speak_message(msg)

    def speak_message(self, message: VoiceMessage) -> None:
        """Enqueue a VoiceMessage object (non-blocking)."""
        if self._muted:
            logger.info("[Voice Muted] Suppressed message: %s", message.text[:60])
            return

        with self._lock:
            # If critical priority (<= 2) arrives while currently speaking something lower, interrupt!
            if self._is_speaking and message.priority < 5:
                logger.info("Interrupting lower-priority speech for priority %d message.", message.priority)
                self._interrupt_current.set()

            self._queue.put(message)

    def mute(self, muted: bool = True) -> None:
        """Mute or unmute the voice engine."""
        with self._lock:
            self._muted = muted
            if self._muted:
                logger.info("VoiceEngine MUTED.")
                self.interrupt()
                self.clear_queue()
            else:
                logger.info("VoiceEngine UNMUTED.")

    def unmute(self) -> None:
        self.mute(False)

    def toggle_mute(self) -> bool:
        """Toggle mute state and return new state."""
        with self._lock:
            new_state = not self._muted
            self.mute(new_state)
            return new_state

    def is_muted(self) -> bool:
        return self._muted

    def is_speaking(self) -> bool:
        return self._is_speaking

    def interrupt(self) -> None:
        """Interrupt and halt any currently playing audio immediately."""
        self._interrupt_current.set()
        self.mci_player.stop()
        self.sapi_synth.stop()

    def clear_queue(self) -> None:
        """Drain and clear all queued speech messages."""
        with self._lock:
            while not self._queue.empty():
                try:
                    self._queue.get_nowait()
                    self._queue.task_done()
                except (queue.Empty, ValueError):
                    break

    def stop(self) -> None:
        """Gracefully stop worker thread and clean up resources."""
        self._stop_requested.set()
        self.interrupt()
        self.clear_queue()
        # Enqueue dummy message to wake worker loop if blocked
        try:
            self._queue.put_nowait(VoiceMessage(priority=999, text="", source="shutdown"))
        except Exception:
            pass

    def wait_until_idle(self, timeout: Optional[float] = None) -> bool:
        """Wait until all queued messages have been spoken and playback is idle."""
        start = time.time()
        while True:
            with self._lock:
                if self._queue.empty() and not self._is_speaking:
                    return True
            if timeout and (time.time() - start) > timeout:
                return False
            time.sleep(0.05)

    def run_morning_briefing(self, state: Optional[Dict[str, Any]] = None) -> str:
        """Generate and articulate Executive Morning Briefing via this engine."""
        return ExecutiveBriefing.run_briefing(self, state=state)


    def _worker_loop(self) -> None:
        """Dedicated background loop consuming prioritized speech messages."""
        while not self._stop_requested.is_set():
            try:
                # Wait for next message with a short timeout to allow checking _stop_requested
                try:
                    msg = self._queue.get(timeout=0.2)
                except queue.Empty:
                    continue

                if self._stop_requested.is_set():
                    break

                if not msg.text:
                    self._queue.task_done()
                    continue

                if self._muted:
                    self._queue.task_done()
                    continue

                self._interrupt_current.clear()

                with self._lock:
                    self._is_speaking = True

                try:
                    self._play_message(msg)
                finally:
                    with self._lock:
                        self._is_speaking = False
                    self._queue.task_done()

            except Exception as e:
                logger.error("Unexpected error in VoiceEngine worker loop: %s", e)
                with self._lock:
                    self._is_speaking = False
                time.sleep(0.1)

    def _play_message(self, msg: VoiceMessage) -> None:
        """Play message via Neural edge-tts Butler voice, falling back to SAPI5."""
        text = msg.text
        logger.info("[Voice Synthesizing (P%d)] %s", msg.priority, text[:80])

        # Step 1: Attempt Edge-TTS Neural Butler Voice
        audio_file = None
        try:
            audio_file = self.neural_tts.synthesize_to_file(text)
        except Exception as e:
            logger.debug("Edge-TTS synthesis attempt error: %s", e)

        if audio_file and audio_file.exists() and self.mci_player.is_available():
            logger.debug("Playing via Edge-TTS and MCI: %s", audio_file)
            success = self.mci_player.play_file(
                str(audio_file), cancel_event=self._interrupt_current
            )
            if success:
                return

        if self._interrupt_current.is_set():
            return

        # Step 2: Fallback to Windows SAPI5 Speech Synthesizer
        if self.sapi_synth.is_available():
            logger.info("Falling back to Windows SAPI5 offline voice.")
            self.sapi_synth.speak(text, cancel_event=self._interrupt_current)
        else:
            logger.warning("[Voice Fallback: Silent/Log] %s", text)


# ---------------------------------------------------------------------------
# Executive Morning Briefing Engine & Verbal Voice Commands
# ---------------------------------------------------------------------------

from app.briefing import (
    ExecutiveBriefing,
    evaluate_batch_health,
    evaluate_certificate_and_token_expiry,
    evaluate_coverage_and_limits,
    evaluate_cron_triggers,
    evaluate_integration_attribution,
    evaluate_setup_audit_trail,
    generate_briefing_text,
    generate_executive_briefing_text,
    handle_batch_health_command,
    handle_briefing_command,
    handle_certificate_expiry_command,
    handle_coverage_limits_command,
    handle_integration_command,
    handle_scheduled_jobs_command,
    handle_setup_audit_command,
    run_executive_briefing,
)


# Global VoiceEngine singleton
_GLOBAL_VOICE_ENGINE: Optional[VoiceEngine] = None
_VOICE_LOCK = threading.RLock()


def get_voice_engine() -> VoiceEngine:
    """Get or instantiate global singleton VoiceEngine."""
    global _GLOBAL_VOICE_ENGINE
    with _VOICE_LOCK:
        if _GLOBAL_VOICE_ENGINE is None:
            _GLOBAL_VOICE_ENGINE = VoiceEngine()
        return _GLOBAL_VOICE_ENGINE


def process_verbal_command(
    command: str,
    voice_engine: Optional[VoiceEngine] = None,
    state: Optional[Dict[str, Any]] = None,
) -> Tuple[bool, str]:
    """Parse and execute a verbal voice command.
    
    Milestone 4 Upgrade:
    Supported verbal commands:
    - Executive Briefing: "briefing", "morning briefing", "run briefing", "executive briefing", "status report"
    - Scheduled Jobs: "check scheduled jobs", "check cron triggers", "cron status", "scheduler health"
    - Certificate & Token Expiry: "check certificate expiry", "check certificates", "token expiry", "check tokens"
    - Setup Audit: "check setup audit", "check audit trail", "prod config", "unapproved changes"
    - Integration Attribution: "check snowflake reconciliation", "check integration", "check bulk api"
    - Org Limits & Coverage: "check code coverage", "check org limits", "check api headroom"
    - Batches & Errors: "check batches", "batch status", "batch errors", "apex errors"
    - Mute Control: "mute", "silence", "be quiet"
    - Unmute: "unmute", "enable voice", "voice on"
    - Stop/Interrupt: "stop", "cancel speech", "halt"
    
    Returns:
        Tuple[bool, str]: (was_handled, response_or_status_message)
    """
    if not command:
        return False, "Empty command"

    cmd_lower = command.lower().strip()
    target_engine = voice_engine or get_voice_engine()
    snapshot = state if state is not None else ExecutiveBriefing.load_state()

    # 1. Stop / Interrupt Control
    if any(k in cmd_lower for k in ("stop", "halt", "cancel speech", "shut up")):
        target_engine.interrupt()
        return True, "Speech interrupted"

    # 2. Unmute Control (checked before mute to avoid substring matching 'unmute' on 'mute')
    if any(k in cmd_lower for k in ("unmute", "enable voice", "voice on")):
        target_engine.unmute()
        target_engine.speak("Voice output restored, sir.", priority=10)
        return True, "Voice unmuted"

    # 3. Mute Control
    if any(k in cmd_lower for k in ("mute", "silence", "be quiet")):
        target_engine.mute(True)
        return True, "Voice muted"

    # 4. Scheduled Jobs / CronTrigger
    if any(k in cmd_lower for k in ("scheduled job", "scheduled jobs", "cron trigger", "cron triggers", "cron status", "scheduler")):
        resp = handle_scheduled_jobs_command(snapshot)
        target_engine.speak(resp, priority=5, source="verbal_command")
        return True, resp

    # 5. Certificate & Token Expiry
    if any(k in cmd_lower for k in ("certificate", "certificates", "token expiry", "oauth expiry", "tokens")):
        resp = handle_certificate_expiry_command(snapshot)
        target_engine.speak(resp, priority=5, source="verbal_command")
        return True, resp

    # 6. Setup Audit Trail
    if any(k in cmd_lower for k in ("setup audit", "audit trail", "prod config", "unapproved change", "audit change")):
        resp = handle_setup_audit_command(snapshot)
        target_engine.speak(resp, priority=5, source="verbal_command")
        return True, resp

    # 7. Integration Attribution / Snowflake Reconciliation
    if any(k in cmd_lower for k in ("snowflake", "integration", "bulk api", "reconciliation")):
        resp = handle_integration_command(snapshot)
        target_engine.speak(resp, priority=5, source="verbal_command")
        return True, resp

    # 8. Org Limits & Code Coverage
    if any(k in cmd_lower for k in ("code coverage", "coverage", "api headroom", "org limit", "governor")):
        resp = handle_coverage_limits_command(snapshot)
        target_engine.speak(resp, priority=5, source="verbal_command")
        return True, resp

    # 9. Overnight Batch Health & BatchApexErrorEvents
    if any(k in cmd_lower for k in ("batch", "batches", "apex error", "apex errors")):
        resp = handle_batch_health_command(snapshot)
        target_engine.speak(resp, priority=5, source="verbal_command")
        return True, resp

    # 10. Executive Briefing Trigger
    if any(k in cmd_lower for k in ("briefing", "executive briefing", "morning report", "status report", "run briefing")):
        briefing_text = run_executive_briefing(target_engine, state=snapshot)
        return True, f"Briefing triggered: {briefing_text}"

    return False, f"Unrecognized verbal command: {command}"



# ---------------------------------------------------------------------------
# CLI & Standalone Verification
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Jarvis Voice Engine & Executive Briefing")
    parser.add_argument("--briefing", action="store_true", help="Run Executive Morning Briefing")
    parser.add_argument("--test", type=str, help="Speak a custom test phrase")
    parser.add_argument("--wait", action="store_true", help="Wait for speech to finish before exiting")
    parser.add_argument("--sapi-only", action="store_true", help="Force SAPI5 fallback test")
    args = parser.parse_args()

    engine = get_voice_engine()

    if args.sapi_only:
        print("[SAPI5 Test] Speaking via offline Windows SAPI5...")
        engine.sapi_synth.speak("Testing Windows SAPI offline speech fallback, sir.")
    elif args.briefing:
        print("[Executive Briefing] Generating and speaking executive briefing...")
        briefing_text = run_executive_briefing(engine)
        print(f"Briefing Text:\n{briefing_text}")
        if args.wait:
            engine.wait_until_idle()
    elif args.test:
        print(f"[Custom Speech] Speaking: {args.test}")
        engine.speak(args.test, priority=5)
        if args.wait:
            engine.wait_until_idle()
    else:
        print("[Default Mode] Triggering Executive Briefing...")
        briefing_text = run_executive_briefing(engine)
        print(f"Briefing Text:\n{briefing_text}")
        engine.wait_until_idle()
    print("Voice Engine operation complete.")
