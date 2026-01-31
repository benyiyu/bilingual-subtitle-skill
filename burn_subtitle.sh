#!/bin/bash
# Netflix-style bilingual subtitle burn script
# Usage: ./burn_subtitle.sh <input_video> <subtitle_srt> <font_size> <margin_v> <output_video>
#
# Resolution presets:
#   1080p: font_size=14, margin_v=8
#   1440p: font_size=14, margin_v=9
#   4K:    font_size=16, margin_v=10
#
# Note: Requires ffmpeg-full (brew install ffmpeg-full) for libass support.
#       Using a script file avoids shell misinterpretation of '&' in color codes.

FFMPEG="/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg"

if [ ! -x "$FFMPEG" ]; then
    echo "Error: ffmpeg-full not found at $FFMPEG"
    echo "Install with: brew install ffmpeg-full"
    exit 1
fi

if [ $# -ne 5 ]; then
    echo "Usage: $0 <input_video> <subtitle.srt> <font_size> <margin_v> <output_video>"
    exit 1
fi

$FFMPEG -y \
  -i "$1" \
  -vf "subtitles=$2:force_style='FontName=PingFang SC,FontSize=$3,PrimaryColour=&H00FFFFFF,BackColour=&H80000000,BorderStyle=4,Outline=0,Shadow=0,Alignment=2,MarginV=$4'" \
  -c:a copy \
  -preset fast \
  "$5"
