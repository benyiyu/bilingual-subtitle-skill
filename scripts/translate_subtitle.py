"""
Bilingual Subtitle Translator
使用 Google Gemini API 将单语字幕翻译成双语字幕

使用方法:
1. 设置环境变量: export GOOGLE_API_KEY="your-api-key"
2. 运行脚本: python translate_subtitle.py input.srt output.srt

或者创建 .env 文件:
GOOGLE_API_KEY=your-api-key
"""

import os
import json
import time
import sys
from google import genai
from google.genai import types

# ================= 配置区域 =================

# API Key 从环境变量读取（安全方式）
API_KEY = os.environ.get("GOOGLE_API_KEY")

if not API_KEY:
    # 尝试从 .env 文件读取
    env_file = os.path.join(os.path.dirname(__file__), '.env')
    if os.path.exists(env_file):
        with open(env_file) as f:
            for line in f:
                if line.startswith('GOOGLE_API_KEY='):
                    API_KEY = line.strip().split('=', 1)[1]
                    break

if not API_KEY:
    print("错误: 请设置 GOOGLE_API_KEY 环境变量")
    print("方法 1: export GOOGLE_API_KEY='your-api-key'")
    print("方法 2: 创建 .env 文件并添加 GOOGLE_API_KEY=your-api-key")
    sys.exit(1)

# 每次处理多少行
CHUNK_SIZE = 60

# 模型选择
MODEL_NAME = "gemini-2.0-flash"

# ===========================================

# 初始化客户端
client = genai.Client(api_key=API_KEY)

# 系统提示词
SYSTEM_PROMPT = """
You are a Netflix-level Subtitle Specialist.
Your task is to convert raw speech transcripts into a strictly valid JSON list of subtitles.

Processing Rules:
1. **Cleaning**: Remove filler words (uh, um, you know), stuttering, and source tags.
2. **Segmentation**: Split text into subtitle lines.
   - Max 42 characters per line for English.
   - NEVER break a semantic unit.
3. **Translation**: Translate into simplified Chinese suitable for a Tech/Automotive audience.
4. **Output Format**: return a JSON Object containing a list under the key "subtitles".
   - Format: {"subtitles": [{"start": "MM:SS", "en": "...", "cn": "..."}]}
"""


def read_srt(filepath):
    """读取 SRT 文件"""
    if not os.path.exists(filepath):
        print(f"错误: 找不到文件 {filepath}")
        return []

    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    # 解析 SRT 格式
    blocks = content.strip().split('\n\n')
    subtitles = []

    for block in blocks:
        lines = block.strip().split('\n')
        if len(lines) >= 3:
            index = lines[0]
            timestamp = lines[1]
            text = ' '.join(lines[2:])
            subtitles.append({
                'index': index,
                'timestamp': timestamp,
                'text': text
            })

    return subtitles


def process_chunk(chunk_text, chunk_index):
    """调用 Gemini API 处理文本块"""
    print(f"正在处理第 {chunk_index} 块...")

    config = types.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT,
        response_mime_type="application/json",
    )

    try:
        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=f"Translate the following subtitles:\n{chunk_text}",
            config=config
        )
        return json.loads(response.text)
    except Exception as e:
        print(f"处理第 {chunk_index} 块时出错: {e}")
        return None


def write_bilingual_srt(subtitles, output_path):
    """写入双语 SRT 文件"""
    with open(output_path, 'w', encoding='utf-8') as f:
        for i, sub in enumerate(subtitles, 1):
            f.write(f"{i}\n")
            f.write(f"{sub.get('timestamp', '00:00:00,000 --> 00:00:00,000')}\n")
            f.write(f"{sub.get('original', sub.get('en', ''))}\n")
            f.write(f"{sub.get('translation', sub.get('cn', ''))}\n")
            f.write("\n")


def main():
    if len(sys.argv) < 3:
        print("用法: python translate_subtitle.py <input.srt> <output.srt>")
        sys.exit(1)

    input_file = sys.argv[1]
    output_file = sys.argv[2]

    # 读取字幕
    subtitles = read_srt(input_file)
    if not subtitles:
        return

    print(f"读取了 {len(subtitles)} 条字幕")

    # 分块处理
    chunks = [subtitles[i:i + CHUNK_SIZE]
              for i in range(0, len(subtitles), CHUNK_SIZE)]

    all_results = []

    for idx, chunk in enumerate(chunks):
        chunk_text = "\n".join([s['text'] for s in chunk])

        result = process_chunk(chunk_text, idx + 1)
        if result:
            data = result.get('subtitles', result)
            if isinstance(data, list):
                # 合并时间戳
                for i, item in enumerate(data):
                    if i < len(chunk):
                        item['timestamp'] = chunk[i]['timestamp']
                all_results.extend(data)

        time.sleep(1)  # 避免 rate limit

    # 写入输出
    write_bilingual_srt(all_results, output_file)
    print(f"完成! 输出文件: {output_file}")


if __name__ == "__main__":
    main()
