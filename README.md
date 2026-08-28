# epub-to-audiobook

Convert an `.epub` file into a chaptered `.m4b` audiobook using [Kokoro TTS](https://huggingface.co/hexgrad/Kokoro-82M) — a local, free, open-source text-to-speech model. Runs fully offline after the one-time model download.

## Features

- Extracts chapters directly from epub markup (`ebooklib` + `BeautifulSoup`), stripping scripts, styles, footnote markers, and nav elements so only narrated text remains
- Detects chapter titles from headings, falling back to the source filename when none is found
- Splits chapter text on sentence boundaries into TTS-friendly chunks, so long chapters don't get truncated or run together
- Synthesizes audio locally with Kokoro — no API keys, no per-word cost, no data leaving your machine
- Stitches chapters into a single `.m4b` with embedded chapter markers, so it behaves like any other audiobook in players that support chapters (Apple Books, Plex, etc.)
- Multiple voices and adjustable speech speed

## Setup

```bash
uv sync
```

`ffmpeg` must also be installed (not a Python package):

```bash
# macOS
brew install ffmpeg

# Ubuntu / Debian
sudo apt install ffmpeg
```

Kokoro downloads its model weights (~300MB) from Hugging Face the first time you run a conversion, so you'll need internet access once. After that, everything runs offline.

## Usage

```bash
uv run main.py mybook.epub --voice af_heart --out mybook.m4b
```

### Options

| Flag | Description | Default |
|---|---|---|
| `--voice` | Kokoro voice name | `af_heart` |
| `--speed` | Speech speed multiplier | `1.0` |
| `--out` | Output `.m4b` path | `<epub name>.m4b` |
| `--list-voices` | Print available voices and exit | — |

List available voices:

```bash
uv run main.py --list-voices
```

## How it works

1. **Extract** — Each document item in the epub is parsed with BeautifulSoup, non-narrated tags are stripped, and whitespace is normalized. Near-empty sections (cover pages, empty TOC stubs) are skipped.
2. **Chunk** — Chapter text is split on sentence boundaries and packed into ~400-character chunks so Kokoro synthesizes coherent, appropriately-paced audio.
3. **Synthesize** — Each chunk is passed through a Kokoro `KPipeline`, and the resulting audio segments are concatenated into a single 24kHz `.wav` per chapter.
4. **Build** — `ffprobe` measures each chapter's duration, `ffmpeg` concatenates all chapter `.wav` files into one AAC stream, and an FFMETADATA chapter file is muxed in to produce the final `.m4b` with working chapter navigation.

Temporary per-chapter audio and intermediate concat/metadata files are cleaned up automatically once the audiobook is built.

## License

GPL-3.0 — see [LICENSE](LICENSE).
