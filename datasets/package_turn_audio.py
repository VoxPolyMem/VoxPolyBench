#!/usr/bin/env python3
"""Package the canonical turn WAVs as individually playable demo MP3s."""

import argparse
import json
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


def encode_turn(source: Path, destination: Path) -> int:
    destination.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(source), "-codec:a", "libmp3lame", "-b:a", "64k",
            "-ac", "1", "-threads", "1", str(destination),
        ],
        check=True,
    )
    size = destination.stat().st_size
    if size < 1000:
        raise ValueError(f"Encoded turn is unexpectedly small: {destination}")
    return size


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case_root", type=Path)
    parser.add_argument(
        "--output", type=Path,
        default=Path(__file__).parent / "assets/audio/family-city-break",
    )
    args = parser.parse_args()
    case_root = args.case_root.resolve(strict=True)
    output = args.output.resolve(strict=True)
    manifest_path = output / "demo_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("case_id") != "family-city-break" or len(manifest.get("sessions", [])) != 8:
        raise ValueError("Unexpected demo manifest")

    jobs = []
    for session in manifest["sessions"]:
        session_id = session["session_id"]
        source_dir = case_root / "audio" / session_id
        source_manifest = json.loads(
            (source_dir / f"{session_id}_manifest.json").read_text(encoding="utf-8")
        )
        turns = sorted(source_manifest["turns"], key=lambda item: int(item["turn_idx"]))
        if (
            source_manifest.get("session_id") != session_id
            or len(turns) != session["turn_count"]
            or [int(item["turn_idx"]) for item in turns] != list(range(len(turns)))
        ):
            raise ValueError(f"Incomplete source audio: {session_id}")
        session["turns"] = []
        for turn in turns:
            index = int(turn["turn_idx"])
            source = source_dir / Path(turn["audio_path"]).name
            if not source.is_file():
                raise FileNotFoundError(source)
            relative = f"turns/{session_id}/{index:03d}.mp3"
            entry = {
                "turn_idx": index,
                "speaker_name": turn["speaker_name"],
                "file": relative,
                "duration_sec": turn["duration_sec"],
            }
            session["turns"].append(entry)
            jobs.append((source, output / relative, entry))

    if len(jobs) != 480:
        raise ValueError(f"Expected 480 dialogue turns, found {len(jobs)}")
    with ThreadPoolExecutor(max_workers=4) as pool:
        sizes = pool.map(lambda job: encode_turn(job[0], job[1]), jobs)
        for (_, _, entry), size in zip(jobs, sizes):
            entry["bytes"] = size

    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Packaged {len(jobs)} turn MP3s ({sum(item[2]['bytes'] for item in jobs) / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
