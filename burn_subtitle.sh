#!/bin/bash
# Netflix-style bilingual subtitle burn script v2.1
#
# Usage:
#   ./burn_subtitle.sh <input_video> <subtitle.srt> <output_video> [--hwaccel]
#
# Auto-detects video resolution and selects appropriate FontSize/MarginV.
# Optional --hwaccel flag enables h264_videotoolbox hardware encoding (macOS).
#
# Resolution presets (auto-selected):
#   1080p: FontSize=14, MarginV=8
#   1440p: FontSize=14, MarginV=9
#   4K:    FontSize=16, MarginV=10
#
# Note: Requires ffmpeg-full (brew install ffmpeg-full) for libass support.

FFMPEG="/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg"
FFPROBE="/opt/homebrew/opt/ffmpeg-full/bin/ffprobe"
FONTS_DIR="/System/Library/Fonts"

if [ ! -x "$FFMPEG" ]; then
    echo "Error: ffmpeg-full not found at $FFMPEG"
    echo "Install with: brew install ffmpeg-full"
    exit 1
fi

if [ ! -x "$FFPROBE" ]; then
    echo "Error: ffprobe not found at $FFPROBE"
    echo "Install with: brew install ffmpeg-full"
    exit 1
fi

# Parse arguments
if [ $# -lt 3 ] || [ $# -gt 4 ]; then
    echo "Usage: $0 <input_video> <subtitle.srt> <output_video> [--hwaccel]"
    echo ""
    echo "Options:"
    echo "  --hwaccel    Use hardware acceleration (h264_videotoolbox on macOS)"
    echo ""
    echo "Resolution is auto-detected. FontSize and MarginV are set automatically."
    exit 1
fi

INPUT_VIDEO="$1"
SUBTITLE_SRT="$2"
OUTPUT_VIDEO="$3"
HWACCEL=false

if [ "$4" = "--hwaccel" ]; then
    HWACCEL=true
fi

# Validate input files
if [ ! -f "$INPUT_VIDEO" ]; then
    echo "Error: Input video not found: $INPUT_VIDEO"
    exit 1
fi

if [ ! -f "$SUBTITLE_SRT" ]; then
    echo "Error: Subtitle file not found: $SUBTITLE_SRT"
    exit 1
fi

# Auto-detect resolution
echo "Detecting video resolution..."
RESOLUTION=$("$FFPROBE" -v error -select_streams v:0 -show_entries stream=width,height -of csv=p=0 "$INPUT_VIDEO")

if [ -z "$RESOLUTION" ]; then
    echo "Error: Could not detect video resolution."
    exit 1
fi

WIDTH=$(echo "$RESOLUTION" | cut -d',' -f1)
HEIGHT=$(echo "$RESOLUTION" | cut -d',' -f2)
echo "Detected resolution: ${WIDTH}x${HEIGHT}"

# Select FontSize and MarginV based on resolution
if [ "$HEIGHT" -ge 2160 ]; then
    FONT_SIZE=16
    MARGIN_V=10
    echo "Resolution class: 4K -> FontSize=$FONT_SIZE, MarginV=$MARGIN_V"
elif [ "$HEIGHT" -ge 1440 ]; then
    FONT_SIZE=14
    MARGIN_V=9
    echo "Resolution class: 1440p -> FontSize=$FONT_SIZE, MarginV=$MARGIN_V"
else
    FONT_SIZE=14
    MARGIN_V=8
    echo "Resolution class: 1080p -> FontSize=$FONT_SIZE, MarginV=$MARGIN_V"
fi

# Build FFmpeg command
CODEC_OPTS="-preset fast"
if [ "$HWACCEL" = true ]; then
    CODEC_OPTS="-c:v h264_videotoolbox -b:v 20M"
    echo "Hardware acceleration enabled (h264_videotoolbox)"
fi

# Create safe symlink to avoid special characters (e.g. single quotes) conflicting with force_style
SAFE_SRT="/tmp/subtitle_$(date +%s).srt"
ln -sf "$(cd "$(dirname "$SUBTITLE_SRT")" && pwd)/$(basename "$SUBTITLE_SRT")" "$SAFE_SRT"

echo "Burning subtitles..."
$FFMPEG -y \
  -i "$INPUT_VIDEO" \
  -vf "subtitles=$SAFE_SRT:fontsdir=$FONTS_DIR:force_style='FontName=PingFang SC,FontSize=$FONT_SIZE,PrimaryColour=&H00FFFFFF,BackColour=&H80000000,BorderStyle=4,Outline=0,Shadow=0,Alignment=2,MarginV=$MARGIN_V'" \
  -c:a copy \
  $CODEC_OPTS \
  "$OUTPUT_VIDEO"

STATUS=$?
rm -f "$SAFE_SRT"  # cleanup temp symlink

if [ $STATUS -eq 0 ]; then
    echo ""
    echo "========================================"
    echo "Done! Output: $OUTPUT_VIDEO"
    echo "========================================"
else
    echo ""
    echo "Error: FFmpeg exited with code $STATUS"
    exit $STATUS
fi
