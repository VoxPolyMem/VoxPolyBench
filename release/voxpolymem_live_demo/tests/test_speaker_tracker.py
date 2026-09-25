"""Exercise the frozen online identity policy without loading ECAPA weights."""
from dataclasses import dataclass
import importlib.util
import os
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch


@unittest.skipUnless(importlib.util.find_spec("numpy"), "numpy is needed for acoustic-vector test")
class FrozenSpeakerTrackerTest(unittest.TestCase):
    def test_repeated_voice_reuses_id_and_distinct_voice_creates_another(self):
        import numpy as np

        @dataclass(frozen=True)
        class AcousticPolicy:
            min_relative_separation: float = 1.0
            min_cohesion_ratio: float = 1.0

        encoder = types.ModuleType("ecapa_encoder")
        encoder.EcapaEncoder = object
        identity_graph = types.ModuleType("identity_graph")
        speaker_pipeline = types.ModuleType("speaker_identity_pipeline")
        speaker_pipeline.POLICY = AcousticPolicy()
        speaker_pipeline.reconcile_fragments = lambda *args, **kwargs: None
        demo_root = Path(__file__).resolve().parents[1]
        source_root = Path(os.environ.get("VOXPOLYMEM_SOURCE", "../voxpolymem_code"))
        if not source_root.is_absolute():
            source_root = demo_root / source_root
        source = source_root / "audio" / "speaker" / "online_speaker_identity_pipeline.py"
        if not source.is_file():
            self.skipTest("clone the separate VoxPolyMem code repository to run the frozen speaker test")
        spec = importlib.util.spec_from_file_location("frozen_online_speaker_for_test", source)
        module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {
            "ecapa_encoder": encoder,
            "identity_graph": identity_graph,
            "speaker_identity_pipeline": speaker_pipeline,
            "frozen_online_speaker_for_test": module,
        }):
            spec.loader.exec_module(module)

        tracker = module.OnlineSpeakerMemory()
        first = tracker.ingest(np.asarray([1.0, 0.0], dtype=np.float32))
        repeat = tracker.ingest(np.asarray([0.99, 0.10], dtype=np.float32) / np.linalg.norm([0.99, 0.10]))
        other = tracker.ingest(np.asarray([0.0, 1.0], dtype=np.float32))
        self.assertEqual(first["acoustic_speaker_id"], "ONLINE_SPK_001")
        self.assertEqual(repeat["acoustic_speaker_id"], "ONLINE_SPK_001")
        self.assertTrue(repeat["ema_updated"])
        self.assertEqual(other["acoustic_speaker_id"], "ONLINE_SPK_002")


if __name__ == "__main__":
    unittest.main()
