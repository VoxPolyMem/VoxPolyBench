import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from memory import DemoEngine, ModelClient, SessionStore, rank_bm25, session_id


class BrokenModel:
    available = True
    model = "fake"

    def chat(self, messages, max_tokens=900):
        raise RuntimeError("provider unavailable")


class FactModel:
    available = True
    model = "fake"

    def chat(self, messages, max_tokens=900):
        return '{"facts":[{"text":"Maya prefers the morning train.","speaker":"Maya","refer_ids":["T0001"],"context_operations":[]},{"text":"Unsupported","refer_ids":["T9999"]}],"event_label":"Travel plan"}'


class LiveModel:
    available = True
    model = "fake"

    def chat(self, messages, max_tokens=900):
        system = messages[0]["content"]
        if "write evidence-grounded conversational memory" in system:
            return '{"facts":[{"text":"Maya booked the morning train.","speaker":"Maya","refer_ids":["T0001"],"context_operations":[]}],"event_label":"Train booking"}'
        if "Plan hierarchical memory retrieval" in system:
            return '{"rewritten_query":"morning train booking","routes":[{"layer":"fact","retrievers":["bm25"],"query":"morning train"}],"sub_questions":[],"time_range":null,"speaker_hint":"Maya","sort_by":"score","needs_visual_memory":false,"needs_event_scope":false,"needs_temporal_reasoning":false}'
        if "Control a bounded multi-round" in system:
            return '{"sufficient":true,"reasoning":"source turn found","missing_evidence":[],"supporting_memory_ids":["T0001"],"supporting_image_ids":[]}'
        return "Maya booked the morning train. [T0001]"


class MemoryTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.store = SessionStore(Path(self.directory.name))
        self.sid = str(uuid4())

    def tearDown(self):
        self.directory.cleanup()

    def test_session_id_rejects_paths(self):
        with self.assertRaises(ValueError):
            session_id("../../other")

    def test_raw_turn_survives_extraction_failure(self):
        engine = DemoEngine(self.store, BrokenModel())
        result = engine.ingest(self.sid, "Maya bought a blue bike", "Maya")
        self.assertEqual(result["turn"]["id"], "T0001")
        self.assertIn("failed", result["warning"])
        self.assertEqual(len(self.store.get(self.sid)["turns"]), 1)

    def test_facts_require_valid_raw_provenance(self):
        engine = DemoEngine(self.store, FactModel())
        state = engine.ingest(self.sid, "I prefer the morning train", "Maya")["state"]
        self.assertEqual(len(state["facts"]), 1)
        self.assertEqual(state["facts"][0]["refer_ids"], ["T0001"])
        self.assertEqual(state["collections"][0]["refer_ids"], ["T0001"])

    def test_offline_retrieval_returns_raw_evidence_only(self):
        source = Path(__file__).resolve().parents[2] / "voxpolymem_code"
        engine = DemoEngine(self.store, ModelClient(), source, top_k=2)
        engine.ingest(self.sid, "Maya bought a blue bike", "Maya")
        engine.ingest(self.sid, "Noah booked the red train", "Noah")
        response = engine.ask(self.sid, "Who bought the blue bike?")
        self.assertIn("T0001", [row["mem_id"] for row in response["question"]["evidence"]])
        self.assertTrue(all(row["mem_id"].startswith("T") for row in response["question"]["evidence"]))
        self.assertIn("Offline preview", response["question"]["answer"])
        self.assertEqual(len(self.store.get(self.sid)["questions"]), 1)

    def test_bm25_matches_chinese_and_english(self):
        rows = [{"text": "Maya bought a blue bicycle"}, {"text": "小明喜欢蓝色自行车"}]
        self.assertEqual(rank_bm25("blue bicycle", rows)[0]["text"], rows[0]["text"])
        self.assertEqual(rank_bm25("蓝色自行车", rows)[0]["text"], rows[1]["text"])

    def test_live_frozen_planner_and_iterative_trace(self):
        source = Path(__file__).resolve().parents[2] / "voxpolymem_code"
        engine = DemoEngine(self.store, LiveModel(), source)
        engine.ingest(self.sid, "Maya booked the morning train", "Maya")
        result = engine.ask(self.sid, "What did Maya book?")["question"]
        self.assertEqual(result["plan"]["strategy"], "unified_hybrid_route")
        self.assertEqual(result["iterative"]["rounds_executed"], 1)
        self.assertEqual(result["evidence"][0]["mem_id"], "T0001")
        self.assertIn("[T0001]", result["answer"])

    def test_audio_transcription_request_is_multipart(self):
        client = ModelClient("test-key", "https://example.test/v1")
        captured = []

        def fake_open(request_object, timeout):
            captured.append(request_object)
            return BytesIO(b'{"text":"A short spoken turn."}')

        with patch("memory.request.urlopen", side_effect=fake_open):
            text = client.transcribe(b"FAKE_AUDIO", "recording.webm", "test-asr")
        self.assertEqual(text, "A short spoken turn.")
        self.assertIn(b"FAKE_AUDIO", captured[0].data)
        self.assertIn(b"test-asr", captured[0].data)
        self.assertTrue(captured[0].full_url.endswith("/audio/transcriptions"))

    def test_acoustic_speaker_identity_and_name_binding(self):
        engine = DemoEngine(self.store, ModelClient())
        first = engine.ingest(
            self.sid, "I booked the train", "Maya", "first.wav", "ONLINE_SPK_001",
            {"acoustic_speaker_id": "ONLINE_SPK_001", "created_new_identity": True, "ema_updated": False},
        )["turn"]
        second = engine.ingest(
            self.sid, "The trip is on Saturday", "", "second.wav", "ONLINE_SPK_001",
            {"acoustic_speaker_id": "ONLINE_SPK_001", "created_new_identity": False, "top_cosine": 0.81, "ema_updated": True},
        )["turn"]
        third = engine.ingest(self.sid, "I prefer Sunday", "", "third.wav", "ONLINE_SPK_002")["turn"]
        self.assertEqual((first["speaker"], second["speaker"]), ("Maya", "Maya"))
        self.assertEqual(third["speaker"], "ONLINE_SPK_002")
        updated = engine.bind_speaker(self.sid, "ONLINE_SPK_001", "May")
        self.assertEqual([row["speaker"] for row in updated["state"]["turns"]], ["May", "May", "ONLINE_SPK_002"])
        question = engine.ask(self.sid, "When is the trip?", asker_acoustic_id="ONLINE_SPK_001")["question"]
        self.assertEqual(question["asker"], "May")
        self.assertEqual(question["asker_acoustic_id"], "ONLINE_SPK_001")


if __name__ == "__main__":
    unittest.main()
