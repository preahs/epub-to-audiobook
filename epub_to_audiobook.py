#!/usr/bin/env python3
"""
epub_to_audiobook.py

Convert an .epub file into an .m4b audiobook using Kokoro TTS (local, free, open-source).

--------------------------------------------------------------------
SETUP (run once)
--------------------------------------------------------------------
pip install ebooklib beautifulsoup4 kokoro soundfile numpy
# ffmpeg must also be installed on your system (not via pip):
#   macOS:   brew install ffmpeg
#   Ubuntu:  sudo apt install ffmpeg
#   Windows: https://ffmpeg.org/download.html

Kokoro will download its model weights (~300MB) from Hugging Face
the first time you run it, so you'll need internet access once.
After that it runs fully offline.

--------------------------------------------------------------------
USAGE
--------------------------------------------------------------------
python epub_to_audiobook.py mybook.epub --voice af_heart --out mybook.m4b

Run `python epub_to_audiobook.py --list-voices` to see available voices.
--------------------------------------------------------------------
"""

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

import ebooklib
from ebooklib import epub
from bs4 import BeautifulSoup


# ---------- 1. Extract chapters from epub ----------

def extract_chapters(epub_path: Path):
    """Return a list of (title, text) tuples, one per chapter/section."""
    book = epub.read_epub(str(epub_path))
    chapters = []

    for item in book.get_items():
        if item.get_type() != ebooklib.ITEM_DOCUMENT:
            continue

        soup = BeautifulSoup(item.get_content(), "html.parser")

        # Strip elements that shouldn't be read aloud
        for tag in soup(["script", "style", "sup", "nav"]):
            tag.decompose()

        text = soup.get_text(separator=" ", strip=True)
        text = re.sub(r"\s+", " ", text).strip()

        if len(text) < 50:  # skip near-empty files (cover, toc stubs, etc.)
            continue

        # Try to find a chapter title from the first heading
        heading = soup.find(["h1", "h2", "h3"])
        title = heading.get_text(strip=True) if heading else item.get_name()

        chapters.append((title, text))

    return chapters


# ---------- 2. Split chapter text into TTS-friendly chunks ----------

def chunk_text(text: str, max_chars: int = 400):
    """Split on sentence boundaries, keeping chunks under max_chars."""
    sentences = re.split(r"(?<=[.!?])\s+", text)
    chunks, current = [], ""

    for sentence in sentences:
        if len(current) + len(sentence) + 1 <= max_chars:
            current = f"{current} {sentence}".strip()
        else:
            if current:
                chunks.append(current)
            current = sentence
    if current:
        chunks.append(current)

    return chunks


# ---------- 3. Synthesize audio with Kokoro ----------

def synthesize_chapter(pipeline, chunks, out_path: Path, voice: str, speed: float):
    import soundfile as sf
    import numpy as np

    audio_segments = []
    for chunk in chunks:
        for _, _, audio in pipeline(chunk, voice=voice, speed=speed):
            audio_segments.append(audio)

    full_audio = np.concatenate(audio_segments)
    sf.write(str(out_path), full_audio, 24000)  # Kokoro outputs 24kHz


# ---------- 4. Stitch chapters + build .m4b with chapter markers ----------

def build_audiobook(chapter_files, chapter_titles, out_path: Path, book_title: str):
    import wave
    import contextlib

    # Get duration of each chapter to build ffmpeg chapter metadata
    durations = []
    for f in chapter_files:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(f)],
            capture_output=True, text=True
        )
        durations.append(float(result.stdout.strip()))

    # Build ffmpeg concat list
    concat_list = out_path.parent / "concat_list.txt"
    with open(concat_list, "w") as f:
        for cf in chapter_files:
            f.write(f"file '{cf.resolve()}'\n")

    # Build chapter metadata file
    metadata_path = out_path.parent / "chapters.txt"
    with open(metadata_path, "w") as f:
        f.write(";FFMETADATA1\n")
        f.write(f"title={book_title}\n\n")
        start = 0.0
        for title, dur in zip(chapter_titles, durations):
            end = start + dur
            f.write("[CHAPTER]\n")
            f.write("TIMEBASE=1/1000\n")
            f.write(f"START={int(start * 1000)}\n")
            f.write(f"END={int(end * 1000)}\n")
            f.write(f"title={title}\n\n")
            start = end

    # Concatenate audio, then mux in chapter metadata, output as .m4b
    temp_concat = out_path.parent / "_temp_concat.m4a"
    subprocess.run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", str(concat_list), "-c:a", "aac", "-b:a", "64k", str(temp_concat)
    ], check=True)

    subprocess.run([
        "ffmpeg", "-y", "-i", str(temp_concat), "-i", str(metadata_path),
        "-map_metadata", "1", "-codec", "copy", str(out_path)
    ], check=True)

    temp_concat.unlink()
    concat_list.unlink()
    metadata_path.unlink()


# ---------- Main ----------

def main():
    parser = argparse.ArgumentParser(description="Convert an epub to an audiobook using Kokoro TTS.")
    parser.add_argument("epub", nargs="?", help="Path to the .epub file")
    parser.add_argument("--voice", default="af_heart", help="Kokoro voice name (default: af_heart)")
    parser.add_argument("--speed", type=float, default=1.0, help="Speech speed multiplier (default: 1.0)")
    parser.add_argument("--out", default=None, help="Output .m4b path (default: <epub name>.m4b)")
    parser.add_argument("--list-voices", action="store_true", help="List available Kokoro voices and exit")
    args = parser.parse_args()

    if args.list_voices:
        from kokoro import KPipeline
        print("Common Kokoro voices: af_heart, af_bella, af_nicole, am_michael, "
              "bf_emma, bm_george, and more — see the Kokoro model card on Hugging Face "
              "for the full list per language.")
        sys.exit(0)

    if not args.epub:
        parser.error("Please provide a path to an .epub file (or use --list-voices).")

    if not shutil.which("ffmpeg"):
        sys.exit("ffmpeg not found. Install it first (brew/apt/choco install ffmpeg).")

    epub_path = Path(args.epub)
    out_path = Path(args.out) if args.out else epub_path.with_suffix(".m4b")
    work_dir = epub_path.parent / f"_{epub_path.stem}_chapters"
    work_dir.mkdir(exist_ok=True)

    print(f"Extracting chapters from {epub_path.name} ...")
    chapters = extract_chapters(epub_path)
    print(f"Found {len(chapters)} chapters/sections.")

    from kokoro import KPipeline
    pipeline = KPipeline(lang_code="a")  # 'a' = American English; see Kokoro docs for other languages

    chapter_files, chapter_titles = [], []
    for i, (title, text) in enumerate(chapters, start=1):
        print(f"[{i}/{len(chapters)}] Synthesizing: {title[:60]}")
        chunks = chunk_text(text)
        out_file = work_dir / f"chapter_{i:03d}.wav"
        synthesize_chapter(pipeline, chunks, out_file, args.voice, args.speed)
        chapter_files.append(out_file)
        chapter_titles.append(title)

    print("Stitching chapters into final audiobook ...")
    build_audiobook(chapter_files, chapter_titles, out_path, book_title=epub_path.stem)

    shutil.rmtree(work_dir)
    print(f"Done! Audiobook saved to: {out_path}")


if __name__ == "__main__":
    main()
