# VoxPolyMem Live Demo

An audio-first, per-turn memory interaction demo. It is deliberately **separate**
from the frozen VoxPolyMem v1 research code. Nothing here edits the benchmark
pipeline or its reported results.

## What you can see

- Record in the browser or upload an audio clip. With ASR connected, it is
  transcribed and added as a timestamped raw turn. Without ASR, the audio is
  saved locally and you enter/correct its transcript before adding the turn.
- The memory panel updates after each turn, displaying grounded facts, event
  collections, speaker identities, and the `refer_ids` back to raw turns.
- Ask a question by voice or text. The right panel shows the route plan,
  retrieval rounds, selected bottom-level evidence, and the answer.
- A session is saved under `runtime/` so reloading the page keeps its state.

"Live" here means the view updates after each submitted turn, not token-level
streaming ASR. The speaker panel distinguishes a manually supplied name from an
ECAPA acoustic identity; it never silently treats two unknown voices as one.
The interface deliberately accepts **one speaker per recording/turn**. It does
not claim to diarize a long recording containing overlapping speakers.

The demo imports the **unchanged** `core.planner.unified_hybrid_plan` and
`core.iterative_retrieval.retrieve_iteratively` from the frozen v1 source when
that source is available. Its online writer and lightweight BM25 executor are
demo adapters; they are **not** a claim that a live session reproduces the
published Mem-Gallery, H2HMem, or VoxPolyBench scores. Dense/Qwen image search,
the full batch 12-turn fact builder, and benchmark answer protocol remain in
the release, not in this interactive adapter. The UI displays which capabilities
are active rather than silently pretending they ran.

## Run locally

Requires Python 3.12 or newer and `ffmpeg` only if ECAPA speaker matching is
enabled. The basic server itself uses the Python standard library.

```sh
cd voxpolymem_live_demo
cp .env.example .env
# Fill DEMO_API_KEY in .env for hosted ASR and LLM calls.
python3 server.py
```

Open <http://127.0.0.1:8788>. The first run without a key is an explicitly
labeled offline preview: audio recording with manual transcription, raw memory,
lexical search, and provenance work; hosted transcription, fact extraction,
planning, and answer generation do not. The page never invents a model answer
or an ASR transcript.

Keep the frozen code and demo as sibling directories when both are needed:

```text
release/
  voxpolymem_code/       # reproducible benchmark implementation
  voxpolymem_live_demo/  # this interactive adapter
```

The default `VOXPOLYMEM_SOURCE=../voxpolymem_code` loads the frozen planner,
iterative retrieval, and speaker pipeline from the code repository. Override
that environment variable if you use a different checkout name. The demo can
start without the code checkout, but then shows a clearly labeled local BM25
fallback rather than the frozen planner.

For local ASR, install `requirements-optional.txt`, set
`DEMO_ASR_BACKEND=faster_whisper`, and choose a local model. For optional
acoustic speaker matching, use Python 3.12, install
`requirements-speaker.txt`, set
`DEMO_SPEAKER_BACKEND=ecapa`, and point `VOXPOLYMEM_SOURCE` to the frozen v1
directory. ECAPA uses its guarded online EMA update to assign stable anonymous
IDs within a session. A supplied name binds to that ID, and later clips from
the same voice inherit the name. The speaker panel can correct this binding.
Voice questions use the same acoustic tracker to identify the asker. Without
the ECAPA dependencies/model, the UI explicitly shows **not connected** and
manual names remain unverified labels; it does not pretend to distinguish
voices from text alone.
Question-audio matching compares against the current profiles without updating
their EMA prototypes. This keeps a one-off question from changing the stored
speaker memory.

The current Mac preview has no ECAPA dependencies or model weights installed.
The identity binding logic is unit-tested with simulated acoustic IDs, but an
end-to-end multi-speaker audio acceptance test still requires the model and
real clips. Do not interpret manually entered names as verified voice identity.

## Acceptance status (2026-09-25)

- Passed: twelve unit tests, including same-voice ID reuse, distinct-voice ID
  separation, name binding, grounded `refer_ids`, retrieval fallback, and
  rejection of empty or mismatched audio uploads.
- Passed in a browser: file-picker upload, manual transcript, raw-turn and fact
  display, grounded answer generation through `gpt-4.1-mini`, source-audio
  link, and persistence after reload. A separate nonempty 4.3-second synthetic
  Mandarin clip passed local upload and audio download with matching byte count.
- Passed with a two-turn time update: the answer selected the newer raw turn
  and cited its ID. The demo's lightweight online fact writer still displays
  historical facts; it does not mark superseded facts as current state.
- Not yet verified: real ECAPA inference on two speakers and automatic ASR.
  The local speaker packages/model are absent, and the configured remote GPU
  host was unreachable during this check. Hosted ASR was not used for test
  audio; keep `DEMO_ASR_BACKEND=off` when only testing the text model.
- One later AIGC text extraction failed due to a DNS error. Its raw turn was
  saved and the UI showed a warning; model-backed steps require a reachable
  provider. The server now rejects trivially empty audio clips.

This acceptance check validates the interactive adapter, **not** benchmark
accuracy or acoustic speaker-recognition quality.

This is a single-user localhost prototype, not a public multi-tenant service.
Audio and memory are kept in ignored `runtime/`; avoid recording private data
you do not want stored locally. Only bind to a public network after adding
authentication, request limits, and a data-retention policy. API keys stay
server-side; never put them in browser code or Git.
If hosted ASR is enabled, submitted recordings are sent to the configured API
provider; choose local ASR for recordings that must stay on this machine.

## Git packaging

This folder is separate from the frozen benchmark code. Keep
`runtime/` and `.env` ignored. The frozen implementation is a sibling
dependency referenced by `VOXPOLYMEM_SOURCE`, not copied into the demo. Before
publishing, confirm rights for any example audio you choose to include.

## Check

```sh
python3 -m unittest discover -s tests -v
```
