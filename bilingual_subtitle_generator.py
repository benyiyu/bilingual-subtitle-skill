#!/usr/bin/env python3
"""
Bilingual Subtitle Generator v2.0

CLI tool that generates Netflix-level bilingual subtitles from SRT files
using Google Gemini API with automatic keyword extraction and checkpoint resume.

Usage:
    python bilingual_subtitle_generator.py --input "/path/to/input.srt"
    python bilingual_subtitle_generator.py --input "/path/to/input.srt" --output-srt "/path/to/out.srt" --output-json "/path/to/out.json"
"""

import argparse
import os
import json
import time
from google import genai
from google.genai import types

# ================= Constants =================
MODEL_NAME = "gemini-2.0-flash"
CHUNK_SIZE = 300
KEYWORD_SAMPLE_LINES = 200
BACKOFF_SCHEDULE = [5, 15, 45, 90, 180]  # seconds, up to 5 retries
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

def extract_keywords(client, all_lines):
    """
    Phase 0: Send first N lines of SRT to Gemini to auto-extract keywords.
    Returns a keyword string for injection into the translation system prompt.
    """
    sample = "\n".join(all_lines[:KEYWORD_SAMPLE_LINES])

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

    print("Phase 0: Extracting keywords from transcript sample...")

    for attempt, wait in enumerate(BACKOFF_SCHEDULE):
        try:
            response = client.models.generate_content(
                model=MODEL_NAME,
                contents=f"SRT Transcript Sample:\n{sample}",
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


def process_chunk(client, system_prompt, chunk_text, chunk_index, total_chunks):
    """Call Gemini API to process a single chunk with exponential backoff."""
    print(f"Processing chunk {chunk_index}/{total_chunks} ({len(chunk_text)} chars)...")

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

    for attempt, wait in enumerate(BACKOFF_SCHEDULE):
        try:
            response = client.models.generate_content(
                model=MODEL_NAME,
                contents=f"Raw Transcript Chunk ({chunk_index}/{total_chunks}):\n{chunk_text}",
                config=config
            )
            result = json.loads(response.text)
            data = result.get('subtitles', result)
            if isinstance(data, list):
                return data
            print(f"  Unexpected response format, retrying...")
        except Exception as e:
            print(f"  Attempt {attempt + 1}/{len(BACKOFF_SCHEDULE)} failed: {e}")

        if attempt < len(BACKOFF_SCHEDULE) - 1:
            print(f"  Retrying in {wait}s...")
            time.sleep(wait)

    return None


# ================= Checkpoint =================

def get_checkpoint_path(output_json):
    """Derive checkpoint file path from output JSON path."""
    base = os.path.splitext(output_json)[0]
    return f"{base}_checkpoint.json"


def load_checkpoint(checkpoint_path):
    """Load checkpoint if exists, return (completed_chunks set, subtitles list, total_chunks)."""
    if os.path.exists(checkpoint_path):
        try:
            with open(checkpoint_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            completed = set(data.get("completed_chunks", []))
            subtitles = data.get("subtitles", [])
            total = data.get("total_chunks", 0)
            print(f"Checkpoint found: {len(completed)}/{total} chunks completed. Resuming...")
            return completed, subtitles, total
        except (json.JSONDecodeError, KeyError) as e:
            print(f"Checkpoint file corrupted, starting fresh: {e}")
    return set(), [], 0


def save_checkpoint(checkpoint_path, completed_chunks, subtitles, total_chunks):
    """Save current progress to checkpoint file."""
    data = {
        "completed_chunks": sorted(list(completed_chunks)),
        "subtitles": subtitles,
        "total_chunks": total_chunks
    }
    with open(checkpoint_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ================= Output =================

def json_to_srt(json_data):
    """Convert JSON subtitle data to SRT format."""
    srt_content = ""
    counter = 1
    for item in json_data:
        timestamp = item.get('start', '00:00').replace('.', ':')
        if len(timestamp.split(':')) == 2:
            timestamp = "00:" + timestamp

        start_time = f"{timestamp},000"
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

    # Phase 0: Auto keyword extraction
    video_keywords = extract_keywords(client, all_lines)
    system_prompt = build_system_prompt(video_keywords)

    # Chunk the input
    chunks = [all_lines[i:i + CHUNK_SIZE] for i in range(0, len(all_lines), CHUNK_SIZE)]
    total_chunks = len(chunks)
    print(f"\nTotal: {len(all_lines)} lines, {total_chunks} chunks.")

    # Load checkpoint
    checkpoint_path = get_checkpoint_path(args.output_json)
    completed_chunks, full_subtitles, saved_total = load_checkpoint(checkpoint_path)

    # If chunk count changed (different file), reset checkpoint
    if saved_total and saved_total != total_chunks:
        print("Chunk count changed, resetting checkpoint.")
        completed_chunks = set()
        full_subtitles = []

    # Process chunks
    # Build ordered subtitle collection: keep existing results, fill in gaps
    chunk_results = {}
    if completed_chunks and full_subtitles:
        # Reconstruct per-chunk results from saved subtitles
        # We store all subtitles flat, so on resume we keep them and only append new ones
        pass

    for idx, chunk in enumerate(chunks):
        if idx in completed_chunks:
            print(f"Chunk {idx + 1}/{total_chunks} already completed, skipping.")
            continue

        chunk_text = "\n".join(chunk)
        result = process_chunk(client, system_prompt, chunk_text, idx + 1, total_chunks)

        if result:
            full_subtitles.extend(result)
            completed_chunks.add(idx)
            save_checkpoint(checkpoint_path, completed_chunks, full_subtitles, total_chunks)
            print(f"  Chunk {idx + 1} saved to checkpoint.")
        else:
            print(f"WARNING: Chunk {idx + 1} failed after all retries, skipped.")

        # Brief pause between chunks to avoid rate limiting
        if idx < len(chunks) - 1:
            time.sleep(2)

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

    print(f"\n{'=' * 40}")
    print(f"Done! Output files:")
    print(f"  SRT:  {args.output_srt}")
    print(f"  JSON: {args.output_json}")
    print(f"{'=' * 40}")


if __name__ == "__main__":
    main()
