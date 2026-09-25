# VoxPolyBench website preview

This repository hosts a static research-preview website with one selected, synthesized-audio history. It includes eight compressed dialogue sessions, ten spoken personalized questions, 480 dialogue turns, and 75 question–answer examples for that history. The full benchmark data are not included.

The frozen VoxPolyMem v1 research implementation and the interactive, audio-first demo are packaged separately under [`release/voxpolymem_code/`](release/voxpolymem_code/) and [`release/voxpolymem_live_demo/`](release/voxpolymem_live_demo/). The demo imports the frozen core when the folders remain siblings; it does not change benchmark results. Start with each folder's README. The public replay archive contains only per-question scores, not benchmark questions, answers, predictions, or dialogue evidence.

Once GitHub Pages is enabled for the `main` branch at the repository root, the site is available at [voxpolymem.github.io/VoxPolyBench](https://voxpolymem.github.io/VoxPolyBench/).

To preview locally from the repository root, run `python3 -m http.server 8771` and open `http://127.0.0.1:8771/`. The site has no build step. Audio is supplied as compressed MP3 files; the original turn-level WAVs are not part of this repository.
