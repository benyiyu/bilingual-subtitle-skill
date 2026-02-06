#!/usr/bin/env python3
"""
Bilingual Subtitle Generator v2.6

CLI tool that generates Netflix-level bilingual subtitles from SRT files
using Google Gemini API with automatic keyword extraction, dual-model validation,
and Netflix-standard segmentation.

v2.6 improvements:
- CHANGED: Full-text keyword extraction (no more sampling) for better context
- CHANGED: Smaller default chunk size (30) for more resilient API calls

v2.5 improvements:
- NEW: Keyword validation phase (catches ASR errors like Cloudbot→ClawdBot at source)
- IMPROVED: Review prompt now actively corrects ASR errors, not just validates
- IMPROVED: Relaxed segmentation thresholds (EN 55 / CN 28) to reduce over-splitting
- Netflix-standard segmentation (splits long subtitles into separate blocks)
- Dual-model validation (translate with primary model, review with secondary)
- --review flag to enable/disable review phase
- Preserves original SRT timestamps (start AND end times)
- Smart timing split for segmented subtitles (CapCut-style)
- Keywords cached in checkpoint (no re-extraction on resume)
- Sample-based keyword extraction for long transcripts (>1000 lines)
- Adaptive inter-chunk delay (scales up on errors, resets on success)
- 429 rate-limit specific handling with extended cooldowns
- Global error budget: pipeline pauses after consecutive failures

Usage:
    python bilingual_subtitle_generator.py --input "/path/to/input.srt"
    python bilingual_subtitle_generator.py --input "/path/to/input.srt" --review  # Enable dual-model review
    python bilingual_subtitle_generator.py --input "/path/to/input.srt" --output-srt "/path/to/out.srt"
    python bilingual_subtitle_generator.py --input "/path/to/input.srt" --keywords "ClawdBot:AI assistant"
    python bilingual_subtitle_generator.py --input "/path/to/input.srt" --model gemini-2.5-flash
    python bilingual_subtitle_generator.py --input "/path/to/input.srt" --chunk-size 60
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
REVIEW_MODEL = "gemini-2.5-flash"  # Model for review phase (can be same or different)
DEFAULT_CHUNK_SIZE = 30  # subtitle blocks per chunk (smaller = more resilient to API failures)
BACKOFF_SCHEDULE = [5, 15, 45, 90, 180]  # seconds, up to 5 retries
RATE_LIMIT_COOLDOWN = 60  # seconds to wait on 429 before resuming retries
KEYWORD_SAMPLE_THRESHOLD = 99999  # disabled: always use full text for keyword extraction
KEYWORD_SAMPLE_LINES = 99999  # disabled: extract keywords from entire transcript
CONSECUTIVE_FAIL_LIMIT = 3  # global error budget: pause after this many consecutive chunk failures
GLOBAL_PAUSE_DURATION = 120  # seconds to pause when global error budget is exhausted
MIN_CHUNK_DELAY = 2  # seconds, base delay between chunks
MAX_CHUNK_DELAY = 30  # seconds, max adaptive delay between chunks

# Netflix subtitle standards (relaxed to reduce over-splitting)
MAX_EN_CHARS = 55  # Max characters per line for English (relaxed from 42)
MAX_CN_CHARS = 28  # Max characters per line for Chinese (relaxed from 20)
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
    parser.add_argument(
        "--review", action="store_true",
        help="Enable dual-model review phase for higher quality (slower, ~2x API cost)"
    )
    parser.add_argument(
        "--no-split", action="store_true",
        help="Disable Netflix-style subtitle splitting (keep original segmentation)"
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


def parse_srt_blocks(filepath):
    """
    Parse SRT file into structured blocks with timing information.
    Returns list of dicts: [{"index": 1, "start": "00:00:00,000", "end": "00:00:04,240", "text": "..."}, ...]
    """
    if not os.path.exists(filepath):
        print(f"Error: File not found: {filepath}")
        return []

    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    # Split by double newlines (SRT block separator)
    raw_blocks = re.split(r'\n\s*\n', content.strip())
    blocks = []

    # Regex for SRT timing line: 00:00:00,000 --> 00:00:04,240
    timing_pattern = re.compile(r'(\d{1,2}:\d{2}:\d{2}[,\.]\d{1,3})\s*-->\s*(\d{1,2}:\d{2}:\d{2}[,\.]\d{1,3})')

    for raw in raw_blocks:
        lines = [l.strip() for l in raw.strip().split('\n') if l.strip()]
        if len(lines) < 2:
            continue

        # Find timing line
        timing_match = None
        timing_line_idx = -1
        for i, line in enumerate(lines):
            timing_match = timing_pattern.match(line)
            if timing_match:
                timing_line_idx = i
                break

        if not timing_match:
            continue

        start_time = timing_match.group(1).replace('.', ',')
        end_time = timing_match.group(2).replace('.', ',')

        # Text is everything after the timing line
        text_lines = lines[timing_line_idx + 1:]
        text = ' '.join(text_lines)

        # Try to get index from line before timing (may not exist or be malformed)
        try:
            index = int(lines[timing_line_idx - 1]) if timing_line_idx > 0 else len(blocks) + 1
        except ValueError:
            index = len(blocks) + 1

        blocks.append({
            "index": index,
            "start": start_time,
            "end": end_time,
            "text": text
        })

    return blocks


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


def validate_keywords(client, keywords_text, model_name):
    """
    Validate and correct extracted keywords using a second model.
    This catches ASR errors in the keywords themselves (e.g., Cloudbot → ClawdBot).
    """
    if not keywords_text:
        return keywords_text

    print(f"  Validating keywords with {model_name}...")

    validation_prompt = """You are a terminology expert reviewing extracted keywords from a tech podcast transcript.

The keywords were extracted from ASR (speech-to-text) output, which may contain phonetic errors.

Your task:
1. Review each keyword for potential ASR misspellings
2. Correct any errors based on your knowledge of tech terms, products, and people
3. Pay special attention to:
   - Product names: "Cloudbot" is likely "ClawdBot" (an AI assistant project)
   - "Cloud Code" might be "Claude Code" (Anthropic's coding tool)
   - "Claud" or "Cloud" alone might be "Claude" (Anthropic's AI)
   - Company/person names that sound similar but are spelled wrong

Return a JSON object with:
{"corrected_keywords": "the full corrected keyword list as a string, same format as input", "changes": ["list of changes made, or empty if none"]}

If no corrections needed, return the original text unchanged."""

    config = types.GenerateContentConfig(
        system_instruction=validation_prompt,
        response_mime_type="application/json",
        temperature=0.1,
    )

    for attempt, wait in enumerate(BACKOFF_SCHEDULE[:3]):
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=f"Review and correct these keywords:\n{keywords_text}",
                config=config
            )
            result = json.loads(response.text)
            corrected = result.get("corrected_keywords", keywords_text)
            changes = result.get("changes", [])

            if changes and len(changes) > 0:
                print(f"  Keyword validation made {len(changes)} corrections:")
                for change in changes[:5]:  # Show first 5 changes
                    print(f"    - {change}")
                if len(changes) > 5:
                    print(f"    ... and {len(changes) - 5} more")
                return corrected
            else:
                print(f"  Keyword validation passed, no corrections needed.")
                return keywords_text

        except Exception as e:
            print(f"  Keyword validation attempt {attempt + 1}/3 failed: {e}")
            if attempt < 2:
                time.sleep(wait)

    print(f"  Keyword validation failed, using original keywords.")
    return keywords_text


# ================= Translation =================

def build_system_prompt(video_keywords, enable_split=True):
    """Build the translation system prompt with keyword table."""
    keyword_section = ""
    if video_keywords:
        keyword_section = f"""
### Global Context & Terminology (CRITICAL)
Use the following keywords to correct ASR errors and ensure consistent translation:
{video_keywords}
"""

    split_section = ""
    if enable_split:
        split_section = f"""
6. **Netflix Segmentation** (when text is too long):
   - If English exceeds {MAX_EN_CHARS} chars OR Chinese exceeds {MAX_CN_CHARS} chars:
     - Split into 2-3 semantic segments
     - Output as arrays: {{"id": 1, "en": ["Part 1", "Part 2"], "cn": ["部分1", "部分2"]}}
   - If text is short enough, output as strings: {{"id": 1, "en": "text", "cn": "文本"}}
   - Split at natural boundaries: punctuation, conjunctions, prepositions
   - NEVER split in the middle of a name, term, or grammatical unit
   - English and Chinese arrays MUST have the same length"""

    return f"""You are a Netflix-level Subtitle Specialist and Linguistic Expert.
Your task is to translate pre-segmented subtitle lines from English to Chinese. Each line has a unique ID that MUST be preserved.
{keyword_section}
### Processing Rules
1. **ASR Correction**:
   - If a phrase sounds like a keyword in the Context but is spelled wrong, **CORRECT the English source** first.
   - Do NOT hallucinate new meanings. Only correct if phonetically similar and contextually appropriate.
2. **Cleaning**: Remove filler words (uh, um, you know, like) and source tags from the English text.
3. **Line Preservation (CRITICAL)**:
   - You MUST output EXACTLY the same number of subtitle entries as the input.
   - Each entry MUST have the same "id" as the input.
   - Do NOT merge or skip any entries.
4. **Translation**:
   - Translate into **Simplified Chinese**.
   - Style: Professional Tech/Software Development context.
   - Tone: Natural, concise, matching the speaker's vibe.
5. **Output Format**:
   - Return a strictly valid JSON list under the key "subtitles".
   - The "id" field MUST match the input id exactly.
{split_section}
"""


def build_review_prompt(video_keywords):
    """Build the review system prompt for quality validation and ASR correction."""
    keyword_section = ""
    if video_keywords:
        keyword_section = f"""
### Terminology Reference (USE THIS TO CORRECT ERRORS)
{video_keywords}
"""

    return f"""You are a Senior Subtitle QA Specialist. Your PRIMARY job is to ACTIVELY CORRECT errors, not just validate.
{keyword_section}
### Your Responsibilities (in order of priority)

1. **ASR CORRECTION (MOST IMPORTANT)**:
   - ACTIVELY fix any misspelled terms using the Terminology Reference above
   - Common corrections: "Cloudbot/CloudBot" → "ClawdBot", "Cloud Code" → "Claude Code", "Claud" → "Claude"
   - If you see a term that SOUNDS like something in the reference but is spelled wrong, CORRECT IT
   - Do NOT leave ASR errors unfixed

2. **Translation Accuracy**:
   - Fix any Chinese translations that don't match the English meaning
   - Ensure technical terms are translated correctly

3. **Segmentation Validation**:
   - If en/cn are arrays, they MUST have the same length
   - If lengths don't match, merge back into single strings

### Output Rules
- Return the SAME structure as input, with ALL corrections applied
- ALWAYS correct ASR errors - this is mandatory
- Add "reviewed": true to each entry
- Add "changes": "description" if you made any changes

### Output Format
{{"subtitles": [{{"id": 1, "en": "corrected english", "cn": "修正后的中文", "reviewed": true, "changes": "fixed Cloudbot→ClawdBot"}}]}}
"""


def format_chunk_for_api(blocks):
    """Format a list of subtitle blocks for the API input."""
    lines = []
    for b in blocks:
        lines.append(f"[{b['index']}] {b['text']}")
    return "\n".join(lines)


def process_chunk(client, system_prompt, chunk_blocks, chunk_index, total_chunks, model_name):
    """Call Gemini API to process a single chunk with exponential backoff and 429 handling."""
    chunk_text = format_chunk_for_api(chunk_blocks)
    expected_count = len(chunk_blocks)
    print(f"Processing chunk {chunk_index}/{total_chunks} ({expected_count} subtitles, {len(chunk_text)} chars) with {model_name}...")

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
                contents=f"Translate these {expected_count} subtitle lines (chunk {chunk_index}/{total_chunks}):\n{chunk_text}",
                config=config
            )
            result = json.loads(response.text)
            data = result.get('subtitles', result)
            if isinstance(data, list):
                # Validate count matches
                if len(data) != expected_count:
                    print(f"  Warning: Expected {expected_count} subtitles, got {len(data)}. Retrying...")
                else:
                    return data
            else:
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


def review_chunk(client, review_prompt, translated_data, chunk_index, total_chunks, model_name):
    """Call Gemini API to review and validate a translated chunk."""
    print(f"  Reviewing chunk {chunk_index}/{total_chunks} with {model_name}...")

    # Format translated data for review
    review_input = json.dumps({"subtitles": translated_data}, ensure_ascii=False, indent=2)

    config = types.GenerateContentConfig(
        system_instruction=review_prompt,
        response_mime_type="application/json",
        temperature=0.1,
        safety_settings=[
            types.SafetySetting(category="HARM_CATEGORY_HATE_SPEECH", threshold="BLOCK_NONE"),
            types.SafetySetting(category="HARM_CATEGORY_HARASSMENT", threshold="BLOCK_NONE"),
            types.SafetySetting(category="HARM_CATEGORY_SEXUALLY_EXPLICIT", threshold="BLOCK_NONE"),
            types.SafetySetting(category="HARM_CATEGORY_DANGEROUS_CONTENT", threshold="BLOCK_NONE"),
        ]
    )

    for attempt, wait in enumerate(BACKOFF_SCHEDULE[:3]):  # Fewer retries for review
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=f"Review and validate this translation (chunk {chunk_index}/{total_chunks}):\n{review_input}",
                config=config
            )
            result = json.loads(response.text)
            data = result.get('subtitles', result)
            if isinstance(data, list) and len(data) == len(translated_data):
                # Count changes
                changes_made = sum(1 for item in data if item.get('changes'))
                if changes_made > 0:
                    print(f"    Review made {changes_made} corrections.")
                else:
                    print(f"    Review passed, no changes needed.")
                return data
            else:
                print(f"    Review returned unexpected format, using original translation.")
                return translated_data
        except Exception as e:
            print(f"    Review attempt {attempt + 1}/3 failed: {e}")
            if attempt < 2:
                time.sleep(wait)

    print(f"    Review failed, using original translation.")
    return translated_data


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


# ================= Output & Timing =================

def timestamp_to_ms(ts):
    """Convert SRT timestamp (HH:MM:SS,mmm) to milliseconds."""
    ts = ts.replace(',', '.')
    parts = ts.split(':')
    if len(parts) == 3:
        h, m, s = parts
        s_parts = s.split('.')
        seconds = int(s_parts[0])
        millis = int(s_parts[1].ljust(3, '0')[:3]) if len(s_parts) > 1 else 0
        return int(h) * 3600000 + int(m) * 60000 + seconds * 1000 + millis
    return 0


def ms_to_timestamp(ms):
    """Convert milliseconds to SRT timestamp (HH:MM:SS,mmm)."""
    h = ms // 3600000
    ms %= 3600000
    m = ms // 60000
    ms %= 60000
    s = ms // 1000
    millis = ms % 1000
    return f"{h:02d}:{m:02d}:{s:02d},{millis:03d}"


def split_timing(start_ts, end_ts, num_parts):
    """
    Split a time range into proportional segments.
    Returns list of (start, end) timestamp tuples.
    """
    start_ms = timestamp_to_ms(start_ts)
    end_ms = timestamp_to_ms(end_ts)
    duration = end_ms - start_ms

    if num_parts <= 1 or duration <= 0:
        return [(start_ts, end_ts)]

    segment_duration = duration // num_parts
    segments = []

    for i in range(num_parts):
        seg_start = start_ms + i * segment_duration
        seg_end = start_ms + (i + 1) * segment_duration if i < num_parts - 1 else end_ms
        segments.append((ms_to_timestamp(seg_start), ms_to_timestamp(seg_end)))

    return segments


def normalize_timestamp(raw):
    """
    Normalize a timestamp string to SRT format HH:MM:SS,mmm.
    Handles formats like MM:SS, MM:SS.ms, HH:MM:SS.ms, HH:MM:SS,mmm, etc.
    """
    if not raw:
        return "00:00:00,000"
    # Normalize comma to dot for parsing
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


def merge_translations_with_timing(original_blocks, translated_items):
    """
    Merge translated items back with original timing information.
    Handles both string and array (split) translations.
    Returns list of complete subtitle entries with timing.
    """
    # Build lookup by ID
    trans_by_id = {}
    for item in translated_items:
        item_id = item.get('id')
        if item_id is not None:
            trans_by_id[item_id] = item

    merged = []
    for block in original_blocks:
        block_id = block['index']
        trans = trans_by_id.get(block_id, {})

        en_data = trans.get('en', block['text'])
        cn_data = trans.get('cn', '')

        # Check if this is a split subtitle (arrays)
        if isinstance(en_data, list) and isinstance(cn_data, list):
            # Split timing proportionally
            num_parts = len(en_data)
            if len(cn_data) != num_parts:
                # Mismatch - fall back to original as single block
                print(f"  Warning: ID {block_id} has mismatched en/cn array lengths, using original.")
                merged.append({
                    "index": block_id,
                    "start": block['start'],
                    "end": block['end'],
                    "en": ' '.join(en_data) if isinstance(en_data, list) else str(en_data),
                    "cn": ' '.join(cn_data) if isinstance(cn_data, list) else str(cn_data),
                    "original": block['text']
                })
            else:
                # Split into multiple blocks with proportional timing
                time_segments = split_timing(block['start'], block['end'], num_parts)
                for i, (seg_start, seg_end) in enumerate(time_segments):
                    merged.append({
                        "index": f"{block_id}.{i+1}",  # e.g., "42.1", "42.2"
                        "start": seg_start,
                        "end": seg_end,
                        "en": en_data[i].strip() if i < len(en_data) else '',
                        "cn": cn_data[i].strip() if i < len(cn_data) else '',
                        "original": block['text'],
                        "split_from": block_id
                    })
        else:
            # Regular single-line subtitle
            merged.append({
                "index": block_id,
                "start": block['start'],
                "end": block['end'],
                "en": en_data.strip() if isinstance(en_data, str) else str(en_data),
                "cn": cn_data.strip() if isinstance(cn_data, str) else str(cn_data),
                "original": block['text']
            })

    return merged


def json_to_srt(merged_data):
    """Convert merged subtitle data to SRT format with proper timing."""
    srt_content = ""
    counter = 1
    for item in merged_data:
        start_time = normalize_timestamp(item.get('start', '00:00:00,000'))
        end_time = normalize_timestamp(item.get('end', '00:00:00,000'))

        en_text = item.get('en', '').strip()
        cn_text = item.get('cn', '').strip()

        if en_text:
            # Format: English on top, Chinese below
            if cn_text:
                srt_content += f"{counter}\n{start_time} --> {end_time}\n{en_text}\n{cn_text}\n\n"
            else:
                srt_content += f"{counter}\n{start_time} --> {end_time}\n{en_text}\n\n"
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

    # Parse SRT into structured blocks (with timing)
    all_blocks = parse_srt_blocks(args.input)
    if not all_blocks:
        print("Error: Input file is empty or has no valid SRT blocks.")
        exit(1)

    # Also read raw lines for keyword extraction
    all_lines = read_file(args.input)

    model_name = args.model
    chunk_size = args.chunk_size
    enable_review = args.review
    enable_split = not args.no_split

    print(f"Using model: {model_name} (fallback: {FALLBACK_MODEL})")
    print(f"Chunk size: {chunk_size} subtitle blocks per chunk")
    print(f"Netflix segmentation: {'enabled' if enable_split else 'disabled'}")
    print(f"Dual-model review: {'enabled (review model: ' + REVIEW_MODEL + ')' if enable_review else 'disabled'}")

    # Load checkpoint first to check for cached keywords
    checkpoint_path = get_checkpoint_path(args.output_json)
    completed_chunks, translated_items, saved_total, cached_keywords, saved_chunk_size = load_checkpoint(checkpoint_path)

    # If chunk size changed from checkpoint, reset chunk progress but preserve cached keywords
    if saved_chunk_size is not None and saved_chunk_size != chunk_size:
        print(f"Chunk size changed ({saved_chunk_size} -> {chunk_size}), resetting chunk progress (keywords preserved).")
        completed_chunks = set()
        translated_items = []

    # Phase 0: Auto keyword extraction (use cache if available)
    if cached_keywords is not None:
        video_keywords = cached_keywords
        print(f"Phase 0: Using cached keywords from checkpoint.")
    else:
        video_keywords = extract_keywords(client, all_lines, model_name)
        # Validate keywords with a different model to catch ASR errors
        if video_keywords and enable_review:
            video_keywords = validate_keywords(client, video_keywords, FALLBACK_MODEL)

    # Merge manual keywords if provided
    manual_kw = parse_manual_keywords(args.keywords)
    if manual_kw:
        print(f"  Injecting manual keywords.")
        if video_keywords:
            video_keywords = video_keywords + "\n" + manual_kw
        else:
            video_keywords = manual_kw

    system_prompt = build_system_prompt(video_keywords, enable_split=enable_split)
    review_prompt = build_review_prompt(video_keywords) if enable_review else None

    # Chunk the blocks (not lines)
    chunks = [all_blocks[i:i + chunk_size] for i in range(0, len(all_blocks), chunk_size)]
    total_chunks = len(chunks)
    print(f"\nTotal: {len(all_blocks)} subtitle blocks, {total_chunks} chunks.")

    # If chunk count changed (different file or different chunk size), reset checkpoint
    if saved_total and saved_total != total_chunks:
        print(f"Chunk count changed ({saved_total} -> {total_chunks}), resetting chunk progress.")
        completed_chunks = set()
        translated_items = []

    # Save keywords to checkpoint immediately so they survive restarts
    save_checkpoint(checkpoint_path, completed_chunks, translated_items, total_chunks,
                    keywords=video_keywords, chunk_size=chunk_size)

    # Adaptive delay and global error budget state
    current_delay = MIN_CHUNK_DELAY
    consecutive_failures = 0

    for idx, chunk_blocks in enumerate(chunks):
        if idx in completed_chunks:
            print(f"Chunk {idx + 1}/{total_chunks} already completed, skipping.")
            continue

        result = process_chunk(client, system_prompt, chunk_blocks, idx + 1, total_chunks, model_name)

        # Fallback: if primary model failed, retry with fallback model
        if result is None and model_name != FALLBACK_MODEL:
            print(f"  Primary model failed. Retrying chunk {idx + 1} with fallback model {FALLBACK_MODEL}...")
            result = process_chunk(client, system_prompt, chunk_blocks, idx + 1, total_chunks, FALLBACK_MODEL)

        if result:
            # Phase 2: Review (if enabled)
            if enable_review and review_prompt:
                result = review_chunk(client, review_prompt, result, idx + 1, total_chunks, REVIEW_MODEL)

            translated_items.extend(result)
            completed_chunks.add(idx)
            save_checkpoint(checkpoint_path, completed_chunks, translated_items, total_chunks,
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

    # Merge translations with original timing
    merged_subtitles = merge_translations_with_timing(all_blocks, translated_items)

    # Export results
    output_dir = os.path.dirname(args.output_json)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    with open(args.output_json, 'w', encoding='utf-8') as f:
        json.dump(merged_subtitles, f, ensure_ascii=False, indent=2)

    srt_output = json_to_srt(merged_subtitles)
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
