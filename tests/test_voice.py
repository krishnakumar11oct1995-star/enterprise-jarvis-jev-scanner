"""Unit and integration tests for Salesforce Jarvis Voice Engine & Executive Briefing.

Milestone 4 Verification:
- High-definition British Butler neural voice (edge-tts)
- Windows SAPI5 offline fallback
- MCI audio player integration
- Non-blocking PriorityQueue speech worker
- Executive Morning Briefing telemetry ingestion (app/state.json)
- Event bus and verbal command triggering
"""

from __future__ import annotations

import json
import os
import queue
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.models import EventTopic, VoiceMessage
from app.event_bus import EventBus
from app.voice import (
    DEFAULT_VOICE,
    EdgeTTSButlerSynthesizer,
    ExecutiveBriefing,
    MCIAudioPlayer,
    VoiceEngine,
    WindowsSAPI5Synthesizer,
    get_voice_engine,
    run_executive_briefing,
)
from app.briefing import generate_briefing_text


class TestVoiceModelsAndPriority(unittest.TestCase):
    """Test priority queue ordering and VoiceMessage contracts."""

    def test_voice_message_priority_comparison(self):
        msg_critical = VoiceMessage(priority=0, text="Critical error", source="radar")
        msg_briefing = VoiceMessage(priority=5, text="Executive briefing", source="briefing")
        msg_info = VoiceMessage(priority=10, text="Scan clean", source="radar")

        # Lower number = higher priority
        self.assertLess(msg_critical, msg_briefing)
        self.assertLess(msg_briefing, msg_info)

        pq = queue.PriorityQueue()
        pq.put(msg_info)
        pq.put(msg_critical)
        pq.put(msg_briefing)

        first = pq.get()
        second = pq.get()
        third = pq.get()

        self.assertEqual(first.priority, 0)
        self.assertEqual(second.priority, 5)
        self.assertEqual(third.priority, 10)


class TestMCIAudioPlayer(unittest.TestCase):
    """Test Windows native MCI Audio Player."""

    def setUp(self):
        self.player = MCIAudioPlayer()

    def test_mci_availability_on_windows(self):
        if os.name == "nt":
            self.assertTrue(self.player.is_available(), "MCI should be available on Windows")

    def test_mci_stop_idempotent(self):
        # Calling stop on idle player should not throw
        self.player.stop()
        self.assertFalse(self.player.is_playing())

    def test_mci_play_nonexistent_file(self):
        res = self.player.play_file("C:\\nonexistent_audio_file_12345.mp3")
        self.assertFalse(res)


class TestWindowsSAPI5Synthesizer(unittest.TestCase):
    """Test Windows SAPI5 Offline Synthesizer Fallback."""

    def setUp(self):
        self.sapi = WindowsSAPI5Synthesizer()

    def test_sapi_availability_on_windows(self):
        if os.name == "nt":
            self.assertTrue(self.sapi.is_available(), "SAPI5 should initialize on Windows")

    def test_sapi_stop_idempotent(self):
        self.sapi.stop()


class TestEdgeTTSSynthesizer(unittest.TestCase):
    """Test Edge-TTS British Butler neural synthesis."""

    def setUp(self):
        self.synth = EdgeTTSButlerSynthesizer(voice=DEFAULT_VOICE)

    def test_synthesizer_voice_default(self):
        self.assertEqual(self.synth.voice, "en-GB-RyanNeural")

    def test_synthesize_short_phrase(self):
        # Test real synthesis of short phrase
        test_path = Path(tempfile.gettempdir()) / "test_synth_unit.mp3"
        if test_path.exists():
            test_path.unlink()
        try:
            res_path = self.synth.synthesize_to_file("Jarvis online, sir.", output_path=test_path)
            self.assertIsNotNone(res_path)
            self.assertTrue(res_path.exists())
            self.assertGreater(res_path.stat().st_size, 1000)
        finally:
            if test_path.exists():
                try:
                    test_path.unlink()
                except Exception:
                    pass


class TestVoiceEngine(unittest.TestCase):
    """Test VoiceEngine lifecycle, queueing, and mute/unmute."""

    def setUp(self):
        self.engine = VoiceEngine()

    def tearDown(self):
        self.engine.stop()

    def test_voice_engine_initial_state(self):
        self.assertFalse(self.engine.is_muted())
        self.assertEqual(self.engine.voice_name, "en-GB-RyanNeural")

    def test_voice_engine_mute_toggle(self):
        self.engine.mute(True)
        self.assertTrue(self.engine.is_muted())

        new_state = self.engine.toggle_mute()
        self.assertFalse(new_state)
        self.assertFalse(self.engine.is_muted())

        self.engine.unmute()
        self.assertFalse(self.engine.is_muted())

    def test_voice_engine_non_blocking_speak(self):
        # speak() must return almost instantly without blocking caller
        start = time.time()
        self.engine.speak("Test speech non-blocking.", priority=10)
        elapsed = time.time() - start
        self.assertLess(elapsed, 0.1, "speak() must be strictly non-blocking")

    def test_voice_engine_event_bus_integration(self):
        bus = EventBus()
        engine = VoiceEngine()
        engine.subscribe_to_event_bus(bus)

        # Publish mute
        bus.publish(EventTopic.VOICE_MUTE, True)
        self.assertTrue(engine.is_muted())

        bus.publish(EventTopic.VOICE_MUTE, False)
        self.assertFalse(engine.is_muted())

        engine.stop()


class TestExecutiveBriefing(unittest.TestCase):
    """Test Executive Morning Briefing Generation and Ingestion."""

    def test_generate_briefing_text_nominal(self):
        sample_state = {
            "org_name": "Alliance Prod",
            "revenue": {
                "status": "nominal",
                "amount": 4120500,
            },
            "batches": {
                "YesterdayDenialSyncBatch": {
                    "status": "Completed",
                    "completed_time": "02:00 AM",
                    "errors": 0,
                    "total_processed": 1420,
                },
                "UpdateEncounterOwnerAndRoutingBatch": {
                    "status": "Completed",
                    "completed_time": "03:15 AM",
                    "errors": 0,
                    "total_processed": 3850,
                },
            },
            "radar_summary": {
                "critical_count": 0,
            },
        }

        text = ExecutiveBriefing.generate_briefing_text(sample_state)

        # Must contain key phrases specified in Milestone 4 requirements:
        self.assertIn("Checking Alliance Prod now, sir.", text)
        self.assertIn("Revenue is nominal.", text)
        self.assertIn("YesterdayDenialSyncBatch completed at 02:00 AM with zero errors.", text)
        self.assertIn("UpdateEncounterOwnerAndRoutingBatch processed 3,850 records.", text)
        self.assertIn("Conflict Radar reports zero critical regressions.", text)
        self.assertIn("All primary systems nominal, sir.", text)

    def test_generate_briefing_text_degraded(self):
        sample_state = {
            "org_name": "Alliance Stage",
            "revenue": {
                "status": "degraded",
            },
            "batches": {
                "YesterdayDenialSyncBatch": {
                    "completed_time": "04:30 AM",
                    "errors": 14,
                },
                "UpdateEncounterOwnerAndRoutingBatch": {
                    "total_processed": 1200,
                },
            },
            "radar_summary": {
                "critical_count": 2,
            },
        }

        text = ExecutiveBriefing.generate_briefing_text(sample_state)
        self.assertIn("Checking Alliance Stage now, sir.", text)
        self.assertIn("Revenue status is flagged as degraded.", text)
        self.assertIn("YesterdayDenialSyncBatch completed at 04:30 AM with 14 errors.", text)
        self.assertIn("Warning: Conflict Radar detected 2 critical architectural conflicts.", text)

    def test_load_state_auto_creates_default(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_state_file = Path(tmpdir) / "state.json"
            self.assertFalse(temp_state_file.exists())

            state = ExecutiveBriefing.load_state(temp_state_file)
            self.assertTrue(temp_state_file.exists())
            self.assertEqual(state["org_name"], "Alliance Prod")
            self.assertIn("YesterdayDenialSyncBatch", state["batches"])

    def test_run_briefing_returns_text(self):
        # Mock voice engine to avoid audio playback delay during test
        mock_engine = MagicMock(spec=VoiceEngine)
        text = run_executive_briefing(mock_engine)
        self.assertTrue(len(text) > 20)
        self.assertIn("Checking Alliance Prod now, sir.", text)
        mock_engine.speak.assert_called_once()


class TestVerbalCommands(unittest.TestCase):
    """Test verbal voice command recognition and routing."""

    def setUp(self):
        self.mock_engine = MagicMock(spec=VoiceEngine)

    def test_verbal_briefing_command(self):
        from app.voice import process_verbal_command
        handled, msg = process_verbal_command("Jarvis, run the morning briefing", self.mock_engine)
        self.assertTrue(handled)
        self.assertIn("Briefing triggered", msg)
        self.mock_engine.speak.assert_called_once()

    def test_verbal_mute_command(self):
        from app.voice import process_verbal_command
        handled, msg = process_verbal_command("Jarvis, please mute", self.mock_engine)
        self.assertTrue(handled)
        self.assertEqual(msg, "Voice muted")
        self.mock_engine.mute.assert_called_with(True)

    def test_verbal_unmute_command(self):
        from app.voice import process_verbal_command
        handled, msg = process_verbal_command("enable voice now", self.mock_engine)
        self.assertTrue(handled)
        self.assertEqual(msg, "Voice unmuted")
        self.mock_engine.unmute.assert_called_once()

    def test_verbal_stop_command(self):
        from app.voice import process_verbal_command
        handled, msg = process_verbal_command("Jarvis stop", self.mock_engine)
        self.assertTrue(handled)
        self.assertEqual(msg, "Speech interrupted")
        self.mock_engine.interrupt.assert_called_once()

    def test_verbal_unknown_command(self):
        from app.voice import process_verbal_command
        handled, msg = process_verbal_command("make a cup of coffee", self.mock_engine)
        self.assertFalse(handled)


if __name__ == "__main__":
    unittest.main()
