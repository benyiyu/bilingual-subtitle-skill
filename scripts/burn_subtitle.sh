#!/bin/bash
# Bilingual Subtitle Burner
# Usage: ./burn_subtitle.sh <input_video> <subtitle.srt> <font_size> <margin_v> <output_video>
#
# Recommended parameters:
#   1080p: FontSize=12, MarginV=8
#   1440p: FontSize=14, MarginV=9
#   4K:    FontSize=16, MarginV=10

if [ "$#" -lt 3 ]; then
    echo "Usage: $0 <input_video> <subtitle.srt> <output_video> [font_size] [margin_v]"
    echo ""
    echo "Examples:"
    echo "  $0 video.mkv subtitle.srt output.mp4           # Use default 4K params"
    echo "  $0 video.mp4 subtitle.srt output.mp4 12 8      # 1080p params"
    echo "  $0 video.mkv subtitle.srt output.mp4 16 10     # 4K params"
    exit 1
fi

INPUT_VIDEO="$1"
SUBTITLE="$2"
OUTPUT_VIDEO="$3"
FONT_SIZE="${4:-16}"
MARGIN_V="${5:-10}"

echo "Input: $INPUT_VIDEO"
echo "Subtitle: $SUBTITLE"
echo "Output: $OUTPUT_VIDEO"
echo "FontSize: $FONT_SIZE, MarginV: $MARGIN_V"
echo ""

/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg -y \
  -i "$INPUT_VIDEO" \
  -vf "subtitles=$SUBTITLE:force_style='FontName=PingFang SC,FontSize=$FONT_SIZE,PrimaryColour=&H00FFFFFF,BackColour=&H80000000,BorderStyle=4,Outline=0,Shadow=0,Alignment=2,MarginV=$MARGIN_V'" \
  -c:a copy \
  -preset fast \
  "$OUTPUT_VIDEO"

echo ""
echo "Done! Output saved to: $OUTPUT_VIDEO"
