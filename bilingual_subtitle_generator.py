import os
import json
import time
from google import genai
from google.genai import types

# ================= 配置区域 =================
# 1. API Key: 从环境变量读取，不要硬编码
#    设置方式: export GOOGLE_API_KEY="your-api-key"
#    或在项目根目录创建 .env 文件: GOOGLE_API_KEY=your-api-key
API_KEY = os.environ.get("GOOGLE_API_KEY", "")
if not API_KEY:
    # 尝试从 .env 文件读取
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if os.path.exists(env_path):
        with open(env_path, 'r') as f:
            for line in f:
                line = line.strip()
                if line.startswith("GOOGLE_API_KEY="):
                    API_KEY = line.split("=", 1)[1].strip().strip('"').strip("'")
                    break
    if not API_KEY:
        print("错误: 未找到 GOOGLE_API_KEY。请设置环境变量或创建 .env 文件。")
        print("  方式1: export GOOGLE_API_KEY=\"your-api-key\"")
        print("  方式2: 在项目目录创建 .env 文件，写入 GOOGLE_API_KEY=your-api-key")
        exit(1)

# 2. 文件路径 (每次使用前修改)
INPUT_FILE = "/Users/ben/Downloads/Clawdbot Peter Steinberger Makes First Public Appearance Since Launch.srt"
OUTPUT_JSON = "/Users/ben/Downloads/Clawdbot Peter Steinberger Makes First Public Appearance Since Launch_bilingual.json"
OUTPUT_SRT = "/Users/ben/Downloads/Clawdbot Peter Steinberger Makes First Public Appearance Since Launch_bilingual.srt"

# 3. 每次处理多少行？
# 策略升级：Gemini Context 很大，调大块大小让它看懂上下文
# 30分钟视频大概 500-800 行字幕，设为 300 意味着只需要切 2-3 次，极大提升连贯性
CHUNK_SIZE = 300

# 4. 模型选择
# 推荐使用 gemini-2.0-flash 或 gemini-1.5-flash，速度快且窗口大
MODEL_NAME = "gemini-3-flash-preview"

# 5. [核心优化] 针对本视频的"术语表" (每次做新视频前改这里)
# 这相当于给了 Gemini 一个"外挂大脑"，强行纠正 ASR 错误
VIDEO_KEYWORDS = """
- Peter Steinberger (Person Name, creator of MoltBot/Clawdbot, Austrian developer)
- MoltBot (Product Name, personal AI agent project, formerly called "Clawdbot" or "ClaudeBot", NOT "more pot" or "multi bot" or "malt bought")
- Clawdbot (Former project name, renamed to MoltBot due to Anthropic trademark, NOT "cloud bot" or "Claude bot")
- Claude Code (Anthropic's CLI tool, NOT "cloud code" or "club co" or "codex")
- Anthropic (AI company, maker of Claude)
- Opus (Claude model name, NOT "open" or "opus is")
- vibe coding (Programming concept, NOT "white coding")
- agentic engineering (Concept, building with AI agents, NOT "attending engineering" or "a chanting engineering")
- Claude (AI model by Anthropic, NOT "cloud")
- MCP (Model Context Protocol, NOT "MCP's are crap" - he's criticizing MCP)
- CLIs (Command Line Interfaces, NOT "seal eyes")
- GPT-4o (OpenAI model, NOT "GPT-4 one")
- Codex (OpenAI's coding product, NOT "codex" when referring to Claude Code)
- Mac mini (Apple hardware product)
- WhatsApp (Messaging platform)
- Telegram (Messaging platform)
- Discord (Community platform)
- FFmpeg (Media tool, NOT "FF MPEG")
- OpenAI (AI company)
- Sonos (Smart speaker brand)
- hackathon (Event, NOT "hack a thon")
- prompt injection (Security concept)
- Jensen (Jensen Huang, NVIDIA CEO)
- Austin Powers (Movie reference)
"""
# ===========================================

# 初始化客户端
client = genai.Client(api_key=API_KEY)

# 升级后的 System Prompt
SYSTEM_PROMPT = f"""
You are a Netflix-level Subtitle Specialist and Linguistic Expert.
Your task is to process raw ASR (speech-to-text) transcripts. The transcripts may contain phonetic errors (e.g., "white coding" instead of "vibe coding").

### Global Context & Terminology (CRITICAL)
Use the following keywords to correct ASR errors and ensure consistent translation:
{VIDEO_KEYWORDS}

### Processing Rules
1. **ASR Correction**:
   - If a phrase sounds like a keyword in the Context but is spelled wrong (e.g., "more pot" -> "MoltBot"), **CORRECT the English source** first.
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

def read_file(filepath):
    if not os.path.exists(filepath):
        print(f"错误: 找不到文件 {filepath}")
        return []
    with open(filepath, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    return [line.strip() for line in lines if line.strip()]

def process_chunk(chunk_text, chunk_index, total_chunks):
    """调用 Gemini 处理单个文本块"""
    print(f"正在处理第 {chunk_index}/{total_chunks} 块 (长度: {len(chunk_text)} 字符)...")

    # [核心优化] 添加 temperature 控制
    generate_config = types.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT,
        response_mime_type="application/json",
        temperature=0.1, # 降低温度，减少幻觉，强制模型"听话"
        safety_settings=[
            types.SafetySetting(
                category="HARM_CATEGORY_HATE_SPEECH",
                threshold="BLOCK_NONE"
            ),
            types.SafetySetting(
                category="HARM_CATEGORY_HARASSMENT",
                threshold="BLOCK_NONE"
            ),
            types.SafetySetting(
                category="HARM_CATEGORY_SEXUALLY_EXPLICIT",
                threshold="BLOCK_NONE"
            ),
            types.SafetySetting(
                category="HARM_CATEGORY_DANGEROUS_CONTENT",
                threshold="BLOCK_NONE"
            ),
        ]
    )

    try:
        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=f"Raw Transcript Chunk ({chunk_index}/{total_chunks}):\n{chunk_text}",
            config=generate_config
        )
        return json.loads(response.text)
    except Exception as e:
        print(f"Error processing chunk {chunk_index}: {e}")
        return None

def json_to_srt(json_data):
    srt_content = ""
    counter = 1
    for item in json_data:
        # 简单的时间戳格式化
        timestamp = item.get('start', '00:00').replace('.', ':')
        if len(timestamp.split(':')) == 2:
            timestamp = "00:" + timestamp

        start_time = f"{timestamp},000"
        end_time = "00:00:00,000" # 由后续 Arctime 对齐

        # 确保中英文都不为空
        en_text = item.get('en', '').strip()
        cn_text = item.get('cn', '').strip()

        if en_text and cn_text:
            srt_content += f"{counter}\n{start_time} --> {end_time}\n{en_text}\n{cn_text}\n\n"
            counter += 1
    return srt_content

def main():
    # 1. 读取文件
    all_lines = read_file(INPUT_FILE)
    if not all_lines: return

    # 分块逻辑
    chunks = [all_lines[i:i + CHUNK_SIZE] for i in range(0, len(all_lines), CHUNK_SIZE)]
    total_chunks = len(chunks)
    print(f"共计 {len(all_lines)} 行，分为 {total_chunks} 个块处理。")

    full_subtitles = []

    # 2. 循环处理
    for idx, chunk in enumerate(chunks):
        chunk_text = "\n".join(chunk)

        success = False
        for attempt in range(3):
            result = process_chunk(chunk_text, idx + 1, total_chunks)
            if result:
                data = result.get('subtitles', result)
                if isinstance(data, list):
                    full_subtitles.extend(data)
                success = True
                break
            else:
                print(f"重试中 ({attempt+1}/3)...")
                time.sleep(5)

        if not success:
            print(f"警报：第 {idx+1} 块处理失败，已跳过。")

        # 即使模型快，也稍微歇一下避免速率限制
        time.sleep(2)

    # 3. 导出结果
    # 自动创建目录（如果不存在）
    output_dir = os.path.dirname(OUTPUT_JSON)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    with open(OUTPUT_JSON, 'w', encoding='utf-8') as f:
        json.dump(full_subtitles, f, ensure_ascii=False, indent=2)

    srt_output = json_to_srt(full_subtitles)
    with open(OUTPUT_SRT, 'w', encoding='utf-8') as f:
        f.write(srt_output)

    print(f"\n=======================================")
    print(f"完成！字幕文件已生成: {OUTPUT_SRT}")
    print(f"=======================================")

if __name__ == "__main__":
    main()
