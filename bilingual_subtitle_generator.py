#!/usr/bin/env python3
"""
Bilingual Subtitle Generator v2.2

CLI tool that generates Netflix-level bilingual subtitles from SRT files
using Google Gemini API with automatic keyword extraction and checkpoint resume.

v2.2 improvements:
- Keywords cached in checkpoint (no re-extraction on resume)
- Sample-based keyword extraction for long transcripts (>1000 lines)
- Adaptive inter-chunk delay (scales up on errors, resets on success)
- 429 rate-limit specific handling with extended cooldowns
- Configurable --chunk-size CLI parameter
- Global error budget: pipeline pauses after consecutive failures

Usage:
    python bilingual_subtitle_generator.py --input "/path/to/input.srt"
    python bilingual_subtitle_generator.py --input "/path/to/input.srt" --output-srt "/path/to/out.srt" --output-json "/path/to/out.json"
    python bilingual_subtitle_generator.py --input "/path/to/input.srt" --keywords "Clawd:AI assistant, Claude Code:coding tool"
    python bilingual_subtitle_generator.py --input "/path/to/input.srt" --model gemini-2.5-flash
    python bilingual_subtitle_generator.py --input "/path/to/input.srt" --chunk-size 100
"""

import os
os.environ['PYTHONUNBUFFERED'] = '1'

import argparse
import json
import re
import time
from google import genai
from google.genai import types

# ================= Constants =================
DEFAULT_MODEL = "gemini-2.5-flash"
FALLBACK_MODEL = "gemini-3-flash-preview"
DEFAULT_CHUNK_SIZE = 150
BACKOFF_SCHEDULE = [5, 15, 45, 90, 180]  # seconds, up to 5 retries
RATE_LIMIT_COOLDOWN = 60  # seconds to wait on 429 before resuming retries
KEYWORD_SAMPLE_THRESHOLD = 1000  # lines; above this, use sampling for keyword extraction
KEYWORD_SAMPLE_LINES = 300  # lines to sample from each section (begin/mid/end)
CONSECUTIVE_FAIL_LIMIT = 3  # global error budget: pause after this many consecutive chunk failures
GLOBAL_PAUSE_DURATION = 120  # seconds to pause when global error budget is exhausted
MIN_CHUNK_DELAY = 2  # seconds, base delay between chunks
MAX_CHUNK_DELAY = 30  # seconds, max adaptive delay between chunks
# ==============================================


def load_api_key():
    """Load API key from environment variable or .env file."""
    api_key = os.environ.get("GOOGLE_API_KEY", "")
    if not api_key:
        env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
        if os.path.exists(env_path):
            with open(env_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("GOOGLE_API_KEY="):
                        api_key = line.split("=", 1)[1].strip().strip('"').strip("'")
                        break
    if not api_key:
        print("Error: GOOGLE_API_KEY not found.")
        print("  Option 1: export GOOGLE_API_KEY=\"your-api-key\"")
        print("  Option 2: Create .env file in project directory with GOOGLE_API_KEY=your-api-key")
        exit(1)
    return api_key


def parse_args():
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(
        description="Generate Netflix-level bilingual subtitles from SRT files using Gemini API."
    )
    parser.add_argument(
        "--input", required=True,
        help="Path to input SRT file"
    )
    parser.add_argument(
        "--output-srt", default=None,
        help="Path to output bilingual SRT file (default: <input>_bilingual.srt)"
    )
    parser.add_argument(
        "--output-json", default=None,
        help="Path to output bilingual JSON file (default: <input>_bilingual.json)"
    )
    parser.add_argument(
        "--keywords", default=None,
        help='Manual keyword injection. Format: "term:description, term:description" (appended to auto-extracted keywords)'
    )
    parser.add_argument(
        "--model", default=DEFAULT_MODEL,
        help=f"Gemini model to use (default: {DEFAULT_MODEL})"
    )
    parser.add_argument(
        "--chunk-size", type=int, default=DEFAULT_CHUNK_SIZE,
        help=f"Number of SRT lines per chunk (default: {DEFAULT_CHUNK_SIZE}). "
             "Smaller values = smaller API requests = more resilient but more calls."
    )
    args = parser.parse_args()

    # Auto-generate output paths if not specified
    input_base = os.path.splitext(args.input)[0]
    if args.output_srt is None:
        args.output_srt = f"{input_base}_bilingual.srt"
    if args.output_json is None:
        args.output_json = f"{input_base}_bilingual.json"

    return args


def read_file(filepath):
    """Read SRT file and return non-empty lines."""
    if not os.path.exists(filepath):
        print(f"Error: File not found: {filepath}")
        return []
    with open(filepath, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    return [line.strip() for line in lines if line.strip()]


# ================= Phase 0: Auto Keyword Extraction =================

def parse_manual_keywords(keywords_str):
    """Parse manual --keywords string into formatted keyword lines."""
    if not keywords_str:
        return ""
    lines = []
    for pair in keywords_str.split(","):
        pair = pair.strip()
        if not pair:
            continue
        if ":" in pair:
            term, desc = pair.split(":", 1)
            lines.append(f"- {term.strip()} ({desc.strip()})")
        else:
            lines.append(f"- {pair}")
    return "\n".join(lines)


def _sample_lines(all_lines, threshold=KEYWORD_SAMPLE_THRESHOLD, sample_size=KEYWORD_SAMPLE_LINES):
    """For long transcripts, sample beginning/middle/end instead of sending everything."""
    if len(all_lines) <= threshold:
        return all_lines
    mid_start = max(0, len(all_lines) // 2 - sample_size // 2)
    begin = all_lines[:sample_size]
    middle = all_lines[mid_start:mid_start + sample_size]
    end = all_lines[-sample_size:]
    # Deduplicate while preserving order
    seen = set()
    sampled = []
    for line in begin + middle + end:
        if line not in seen:
            seen.add(line)
            sampled.append(line)
    return sampled


def _is_rate_limit_error(error):
    """Check if an exception is a 429 rate-limit error."""
    err_str = str(error)
    return "429" in err_str or "RESOURCE_EXHAUSTED" in err_str


def extract_keywords(client, all_lines, model_name):
    """
    Phase 0: Extract keywords from transcript using Gemini.
    For long transcripts (>KEYWORD_SAMPLE_THRESHOLD lines), samples
    beginning/middle/end instead of sending the full text.
    Returns a keyword string for injection into the translation system prompt.
    """
    sampled = _sample_lines(all_lines)
    sample = "\n".join(sampled)
    if len(sampled) < len(all_lines):
        print(f"  Transcript too long ({len(all_lines)} lines), sampling {len(sampled)} lines for keyword extraction.")

    keyword_prompt = """Analyze this SRT subtitle transcript sample. Extract all important keywords that need special attention during translation, including:

- Person names (speakers, people mentioned)
- Organization/company names
- Product/brand names
- Technical terms and jargon
- Words that ASR (speech-to-text) commonly misspells

Return a strictly valid JSON object with this format:
{"keywords": [{"term": "AlphaFold", "description": "Google DeepMind's AI system for protein structure prediction", "correction": "NOT 'alpha fold' or 'alpha-fold'"}]}

Only include terms that genuinely appear or are referenced in the transcript. Do not hallucinate terms."""

    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        temperature=0.1,
    )

    print("Phase 0: Extracting keywords from full transcript...")

    for attempt, wait in enumerate(BACKOFF_SCHEDULE):
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=f"SRT Transcript:\n{sample}",
                config=types.GenerateContentConfig(
                    system_instruction=keyword_prompt,
                    response_mime_type="application/json",
                    temperature=0.1,
                )
            )
            result = json.loads(response.text)
            keywords = result.get("keywords", [])

            if not keywords:
                print("  No keywords extracted, proceeding without keyword table.")
                return ""

            # Format keywords into the terminology table string
            lines = []
            for kw in keywords:
                term = kw.get("term", "")
                desc = kw.get("description", "")
                correction = kw.get("correction", "")
                entry = f"- {term}"
                if desc:
                    entry += f" ({desc}"
                    if correction:
                        entry += f", {correction}"
                    entry += ")"
                elif correction:
                    entry += f" ({correction})"
                lines.append(entry)

            keyword_text = "\n".join(lines)
            print(f"  Extracted {len(keywords)} keywords.")
            return keyword_text

        except Exception as e:
            print(f"  Keyword extraction attempt {attempt + 1}/{len(BACKOFF_SCHEDULE)} failed: {e}")
            if attempt < len(BACKOFF_SCHEDULE) - 1:
                if _is_rate_limit_error(e):
                    cooldown = max(wait, RATE_LIMIT_COOLDOWN)
                    print(f"  Rate limit hit. Cooling down for {cooldown}s...")
                    time.sleep(cooldown)
                else:
                    print(f"  Retrying in {wait}s...")
                    time.sleep(wait)

    print("  Keyword extraction failed after all retries. Proceeding without keywords.")
    return ""


# ================= Translation =================

def build_system_prompt(video_keywords):
    """Build the translation system prompt with keyword table."""
    keyword_section = ""
    if video_keywords:
        keyword_section = f"""
### Global Context & Terminology (CRITICAL)
Use the following keywords to correct ASR errors and ensure consistent translation:
{video_keywords}
"""

    return f"""You are a Netflix-level Subtitle Specialist and Linguistic Expert.
Your task is to process raw ASR (speech-to-text) transcripts. The transcripts may contain phonetic errors.
{keyword_section}
### Processing Rules
1. **ASR Correction**:
   - If a phrase sounds like a keyword in the Context but is spelled wrong, **CORRECT the English source** first.
   - Do NOT hallucinate new meanings. Only correct if phonetically similar and contextually appropriate.
2. **Cleaning**: Remove filler words (uh, um, you know, like) and source tags.
3. **Segmentation (Netflix Standard)**:
   - Split text into subtitle lines.
   - **Max 42 characters** per line for English.
   - **Semantic Splitting**: NEVER break a line inside a grammatical unit (e.g., "of the", "Peter Steinberger").
4. **Translation**:
   - Translate into **Simplified Chinese**.
   - Style: Professional Tech/Software Development context.
   - Tone: Natural, concise, matching the speaker's vibe.
5. **Output Format**:
   - Return a strictly valid JSON list under the key "subtitles".
   - Format: {{"subtitles": [{{"start": "MM:SS", "en": "...", "cn": "..."}}]}}
"""


def process_chunk(client, system_prompt, chunk_text, chunk_index, total_chunks, model_name):
    """Call Gemini API to process a single chunk with exponential backoff and 429 handling."""
    print(f"Processing chunk {chunk_index}/{total_chunks} ({len(chunk_text)} chars) with {model_name}...")

    config = types.GenerateContentConfig(
        system_instruction=system_prompt,
        response_mime_type="application/json",
        temperature=0.1,
        safety_settings=[
            types.SafetySetting(category="HARM_CATEGORY_HATE_SPEECH", threshold="BLOCK_NONE"),
            types.SafetySetting(category="HARM_CATEGORY_HARASSMENT", threshold="BLOCK_NONE"),
            types.SafetySetting(category="HARM_CATEGORY_SEXUALLY_EXPLICIT", threshold="BLOCK_NONE"),
            types.SafetySetting(category="HARM_CATEGORY_DANGEROUS_CONTENT", threshold="BLOCK_NONE"),
        ]
    )

    last_error = None
    for attempt, wait in enumerate(BACKOFF_SCHEDULE):
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=f"Raw Transcript Chunk ({chunk_index}/{total_chunks}):\n{chunk_text}",
                config=config
            )
            result = json.loads(response.text)
            data = result.get('subtitles', result)
            if isinstance(data, list):
                return data
            print(f"  Unexpected response format, retrying...")
        except Exception as e:
            last_error = e
            print(f"  Attempt {attempt + 1}/{len(BACKOFF_SCHEDULE)} failed: {e}")

        if attempt < len(BACKOFF_SCHEDULE) - 1:
            if last_error and _is_rate_limit_error(last_error):
                cooldown = max(wait, RATE_LIMIT_COOLDOWN)
                print(f"  Rate limit hit. Cooling down for {cooldown}s...")
                time.sleep(cooldown)
            else:
                print(f"  Retrying in {wait}s...")
                time.sleep(wait)

    return None


# ================= Checkpoint =================

def get_checkpoint_path(output_json):
    """Derive checkpoint file path from output JSON path."""
    base = os.path.splitext(output_json)[0]
    return f"{base}_checkpoint.json"


def load_checkpoint(checkpoint_path):
    """Load checkpoint if exists, return (completed_chunks set, subtitles list, total_chunks, cached_keywords)."""
    if os.path.exists(checkpoint_path):
        try:
            with open(checkpoint_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            completed = set(data.get("completed_chunks", []))
            subtitles = data.get("subtitles", [])
            total = data.get("total_chunks", 0)
            keywords = data.get("keywords", None)
            chunk_size = data.get("chunk_size", None)
            print(f"Checkpoint found: {len(completed)}/{total} chunks completed. Resuming...")
            if keywords is not None:
                print(f"  Using cached keywords from checkpoint.")
            return completed, subtitles, total, keywords, chunk_size
        except (json.JSONDecodeError, KeyError) as e:
            print(f"Checkpoint file corrupted, starting fresh: {e}")
    return set(), [], 0, None, None


def save_checkpoint(checkpoint_path, completed_chunks, subtitles, total_chunks, keywords=None, chunk_size=None):
    """Save current progress to checkpoint file, including cached keywords."""
    data = {
        "completed_chunks": sorted(list(completed_chunks)),
        "subtitles": subtitles,
        "total_chunks": total_chunks,
    }
    if keywords is not None:
        data["keywords"] = keywords
    if chunk_size is not None:
        data["chunk_size"] = chunk_size
    with open(checkpoint_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ================= Output =================

def normalize_timestamp(raw):
    """
    Normalize a timestamp string to SRT format HH:MM:SS,mmm.
    Handles formats like MM:SS, MM:SS.ms, HH:MM:SS.ms, HH:MM:SS,mmm, etc.
    """
    # Strip commas that Gemini may insert (e.g. "00:16:11,560,000")
    raw = raw.replace(',', '.')
    # Count colons to distinguish MM:SS vs HH:MM:SS before splitting
    colon_count = raw.count(':')
    # Split on ':' and '.' to extract numeric parts
    parts = re.split(r'[:.]', raw)
    parts = [p for p in parts if p]  # remove empty strings

    if len(parts) == 2:
        # MM:SS
        hours, minutes, seconds, millis = 0, int(parts[0]), int(parts[1]), 0
    elif len(parts) == 3:
        if colon_count >= 2:
            # HH:MM:SS (no millis)
            hours, minutes, seconds, millis = int(parts[0]), int(parts[1]), int(parts[2]), 0
        else:
            # MM:SS.ms
            hours, minutes = 0, int(parts[0])
            seconds = int(parts[1])
            millis = int(parts[2][:3].ljust(3, '0'))
    elif len(parts) >= 4:
        # HH:MM:SS.ms (or more parts from extra commas/dots)
        hours, minutes, seconds = int(parts[0]), int(parts[1]), int(parts[2])
        millis = int(parts[3][:3].ljust(3, '0'))
    else:
        hours, minutes, seconds, millis = 0, 0, 0, 0

    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


def json_to_srt(json_data):
    """Convert JSON subtitle data to SRT format."""
    srt_content = ""
    counter = 1
    for item in json_data:
        raw_timestamp = item.get('start', '00:00')
        start_time = normalize_timestamp(raw_timestamp)
        end_time = "00:00:00,000"

        en_text = item.get('en', '').strip()
        cn_text = item.get('cn', '').strip()

        if en_text and cn_text:
            srt_content += f"{counter}\n{start_time} --> {end_time}\n{en_text}\n{cn_text}\n\n"
            counter += 1
    return srt_content


# ================= Main =================

def main():
    args = parse_args()

    # Validate input
    if not os.path.exists(args.input):
        print(f"Error: Input file not found: {args.input}")
        exit(1)

    # Initialize API client
    api_key = load_api_key()
    client = genai.Client(api_key=api_key)

    # Read input
    all_lines = read_file(args.input)
    if not all_lines:
        print("Error: Input file is empty or unreadable.")
        exit(1)

    model_name = args.model
    chunk_size = args.chunk_size
    print(f"Using model: {model_name} (fallback: {FALLBACK_MODEL})")
    print(f"Chunk size: {chunk_size} lines")

    # Load checkpoint first to check for cached keywords
    checkpoint_path = get_checkpoint_path(args.output_json)
    completed_chunks, full_subtitles, saved_total, cached_keywords, saved_chunk_size = load_checkpoint(checkpoint_path)

    # If chunk size changed from checkpoint, reset chunk progress but preserve cached keywords
    if saved_chunk_size is not None and saved_chunk_size != chunk_size:
        print(f"Chunk size changed ({saved_chunk_size} -> {chunk_size}), resetting chunk progress (keywords preserved).")
        completed_chunks = set()
        full_subtitles = []

    # Phase 0: Auto keyword extraction (use cache if available)
    if cached_keywords is not None:
        video_keywords = cached_keywords
        print(f"Phase 0: Using cached keywords from checkpoint.")
    else:
        video_keywords = extract_keywords(client, all_lines, model_name)

    # Merge manual keywords if provided
    manual_kw = parse_manual_keywords(args.keywords)
    if manual_kw:
        print(f"  Injecting manual keywords.")
        if video_keywords:
            video_keywords = video_keywords + "\n" + manual_kw
        else:
            video_keywords = manual_kw

    system_prompt = build_system_prompt(video_keywords)

    # Chunk the input
    chunks = [all_lines[i:i + chunk_size] for i in range(0, len(all_lines), chunk_size)]
    total_chunks = len(chunks)
    print(f"\nTotal: {len(all_lines)} lines, {total_chunks} chunks.")

    # If chunk count changed (different file or different chunk size), reset checkpoint
    if saved_total and saved_total != total_chunks:
        print(f"Chunk count changed ({saved_total} -> {total_chunks}), resetting chunk progress.")
        completed_chunks = set()
        full_subtitles = []

    # Save keywords to checkpoint immediately so they survive restarts
    save_checkpoint(checkpoint_path, completed_chunks, full_subtitles, total_chunks,
                    keywords=video_keywords, chunk_size=chunk_size)

    # Adaptive delay and global error budget state
    current_delay = MIN_CHUNK_DELAY
    consecutive_failures = 0

    for idx, chunk in enumerate(chunks):
        if idx in completed_chunks:
            print(f"Chunk {idx + 1}/{total_chunks} already completed, skipping.")
            continue

        chunk_text = "\n".join(chunk)
        result = process_chunk(client, system_prompt, chunk_text, idx + 1, total_chunks, model_name)

        # Fallback: if primary model failed, retry with fallback model
        if result is None and model_name != FALLBACK_MODEL:
            print(f"  Primary model failed. Retrying chunk {idx + 1} with fallback model {FALLBACK_MODEL}...")
            result = process_chunk(client, system_prompt, chunk_text, idx + 1, total_chunks, FALLBACK_MODEL)

        if result:
            full_subtitles.extend(result)
            completed_chunks.add(idx)
            save_checkpoint(checkpoint_path, completed_chunks, full_subtitles, total_chunks,
                            keywords=video_keywords, chunk_size=chunk_size)
            remaining = total_chunks - len(completed_chunks)
            print(f"  Chunk {idx + 1} saved. Progress: {len(completed_chunks)}/{total_chunks} ({remaining} remaining)")
            # Reset adaptive delay and error budget on success
            current_delay = MIN_CHUNK_DELAY
            consecutive_failures = 0
        else:
            consecutive_failures += 1
            # Increase adaptive delay on failure
            current_delay = min(current_delay * 2, MAX_CHUNK_DELAY)
            print(f"WARNING: Chunk {idx + 1} failed after all retries (both models), skipped.")
            print(f"  Consecutive failures: {consecutive_failures}/{CONSECUTIVE_FAIL_LIMIT}")

            # Global error budget: pause pipeline after too many consecutive failures
            if consecutive_failures >= CONSECUTIVE_FAIL_LIMIT:
                print(f"\n{'!' * 40}")
                print(f"  Global error budget exhausted ({consecutive_failures} consecutive failures).")
                print(f"  Pausing pipeline for {GLOBAL_PAUSE_DURATION}s to let API recover...")
                print(f"  Progress saved. You can also Ctrl+C and resume later.")
                print(f"{'!' * 40}\n")
                time.sleep(GLOBAL_PAUSE_DURATION)
                consecutive_failures = 0  # reset after pause
                current_delay = MIN_CHUNK_DELAY

        # Adaptive delay between chunks
        if idx < len(chunks) - 1 and (idx + 1) not in completed_chunks:
            print(f"  Waiting {current_delay}s before next chunk...")
            time.sleep(current_delay)

    # Export results
    output_dir = os.path.dirname(args.output_json)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    with open(args.output_json, 'w', encoding='utf-8') as f:
        json.dump(full_subtitles, f, ensure_ascii=False, indent=2)

    srt_output = json_to_srt(full_subtitles)
    with open(args.output_srt, 'w', encoding='utf-8') as f:
        f.write(srt_output)

    # Clean up checkpoint on success
    if len(completed_chunks) == total_chunks and os.path.exists(checkpoint_path):
        os.remove(checkpoint_path)
        print("All chunks completed, checkpoint removed.")
    else:
        skipped = total_chunks - len(completed_chunks)
        print(f"\nWARNING: {skipped} chunk(s) were skipped due to errors.")
        print(f"  Re-run the same command to retry failed chunks (checkpoint preserved).")

    print(f"\n{'=' * 40}")
    print(f"Done! Output files:")
    print(f"  SRT:  {args.output_srt}")
    print(f"  JSON: {args.output_json}")
    print(f"{'=' * 40}")


if __name__ == "__main__":
    main()
