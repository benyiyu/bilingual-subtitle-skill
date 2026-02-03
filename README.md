# Bilingual Subtitle Video Generator

一个 [Claude Code](https://docs.anthropic.com/en/docs/claude-code) Skill，基于 Google Gemini API 将单语 SRT 字幕自动翻译为 Netflix 级别的中英双语字幕，并通过 FFmpeg 烧录到视频中，输出带硬字幕的成品视频。

## Features

- **CLI 工具化**：通过命令行参数传入文件路径，无需手动编辑脚本配置
- **自动关键词提取**：Gemini 自动分析字幕内容，提取人名、术语、品牌名等关键词用于 ASR 纠错
- **ASR 纠错**：基于自动提取的术语表，修正语音识别错误（如 "white coding" → "vibe coding"）
- **Netflix 标准分段**：英文每行不超过 42 个字符，按语义完整切分
- **指数退避重试**：5→15→45→90→180 秒，最多 5 次重试，应对 API 过载
- **增量保存 (Checkpoint)**：每处理完一个 chunk 立即保存进度，中断后重跑自动续传
- **自动分辨率检测**：烧录脚本自动检测视频分辨率，选择对应的字号和边距
- **硬件加速**：可选 `--hwaccel` 使用 macOS h264_videotoolbox 加速编码
- **Netflix 风格字幕样式**：白色字体 + 半透明黑色背景，PingFang SC 字体，底部居中

## Workflow

```
用户提供 SRT + 视频 → CLI 生成双语 SRT → 用户确认 → FFmpeg 烧录到视频 → 输出成品
```

**第一阶段** — 双语字幕生成：CLI 工具读取 SRT，自动提取关键词，通过 Gemini API 进行 ASR 纠错 + 翻译 + Netflix 标准分段，输出双语 SRT。

**第二阶段** — 字幕烧录：FFmpeg 自动检测分辨率，烧录双语 SRT 硬字幕到视频。

## Prerequisites

| 依赖 | 说明 |
|------|------|
| **Python 3.x** | 运行翻译脚本 |
| **google-genai** | Google Gemini API SDK (`pip install google-genai`) |
| **ffmpeg-full** | 包含 libass 字幕渲染库 (`brew install ffmpeg-full`) |
| **Google AI Studio API Key** | [获取地址](https://aistudio.google.com/apikey) |
| **Claude Code** | Anthropic 官方 CLI 工具 |

> **注意**：标准版 `ffmpeg` 不包含 libass，会报错 `No option name near 'subtitles'`。必须安装 `ffmpeg-full`。

## Installation

### 1. 克隆项目到 Claude Code Skills 目录

```bash
git clone <repo-url> ~/.claude/skills/bilingual-subtitle-video-generator
```

### 2. 配置 API Key

```bash
cd ~/.claude/skills/bilingual-subtitle-video-generator
cp .env.example .env
```

编辑 `.env` 文件，填入你的 Google AI Studio API Key：

```
GOOGLE_API_KEY=your-api-key-here
```

### 3. 安装 Python 依赖

```bash
pip install google-genai
```

### 4. 安装 FFmpeg（macOS）

```bash
brew install ffmpeg-full
```

## Usage

### 通过 Claude Code Skill 使用

```
/bilingual-subtitle-video-generator <字幕文件.srt> <视频文件.mp4>
```

Claude Code 将自动执行完整的两阶段工作流。

### 手动使用

#### 第一阶段：生成双语字幕

```bash
# 基本用法（输出文件自动生成 _bilingual 后缀）
python bilingual_subtitle_generator.py --input "/path/to/input.srt"

# 指定输出路径
python bilingual_subtitle_generator.py \
  --input "/path/to/input.srt" \
  --output-srt "/path/to/bilingual.srt" \
  --output-json "/path/to/bilingual.json"
```

如果中途失败，直接重跑同一命令，checkpoint 自动续传已完成的 chunk。

#### 第二阶段：烧录字幕到视频

```bash
# 基本用法（自动检测分辨率）
./burn_subtitle.sh "/path/to/video.mp4" "/path/to/bilingual.srt" "/path/to/output.mp4"

# 使用硬件加速（推荐 4K 视频）
./burn_subtitle.sh "/path/to/video.mp4" "/path/to/bilingual.srt" "/path/to/output.mp4" --hwaccel
```

## Configuration

### 脚本参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `MODEL_NAME` | gemini-2.0-flash | Gemini 模型（正式版，稳定） |
| `CHUNK_SIZE` | 300 | 每块处理的行数 |
| `KEYWORD_SAMPLE_LINES` | 200 | 用于关键词提取的样本行数 |
| `BACKOFF_SCHEDULE` | [5, 15, 45, 90, 180] | 指数退避重试间隔（秒） |
| `temperature` | 0.1 | 生成温度，越低越稳定 |

### 分辨率预设（自动检测）

| 分辨率 | FontSize | MarginV | 说明 |
|--------|----------|---------|------|
| 1080p (1920x1080) | 14 | 8 | 标准高清 |
| 1440p (2560x1440) | 14 | 9 | 2K |
| 4K (3840x2160) | 16 | 10 | 超高清 |

## Subtitle Style

字幕采用 Netflix 风格渲染：

| 参数 | 值 | 说明 |
|------|---|------|
| FontName | PingFang SC | 苹方字体，支持中日英混排 |
| PrimaryColour | `&H00FFFFFF` | 白色字体 |
| BackColour | `&H80000000` | 半透明黑色背景 |
| BorderStyle | 4 | 不透明背景框 |
| Alignment | 2 | 底部居中 |

## Troubleshooting

| 问题 | 原因 | 解决方案 |
|------|------|----------|
| `No option name near 'subtitles'` | 标准版 ffmpeg 缺少 libass | `brew install ffmpeg-full` |
| 字幕显示为黑色块（无文字） | Shell 中 `&` 被错误解析 | 必须通过 `burn_subtitle.sh` 脚本执行 |
| 字幕太小或太大 | 分辨率参数不匹配 | 脚本已自动检测，如需微调可修改脚本内的预设值 |
| 烧录速度慢 | 软编码 | 使用 `--hwaccel` 启用硬件加速 |
| API 503/断连错误 | Gemini 模型过载 | 脚本内置指数退避重试，通常自动恢复 |
| 中途失败 | 网络/API 问题 | 直接重跑脚本，checkpoint 自动续传 |

## File Structure

```
bilingual-subtitle-video-generator/
├── SKILL.md                          # Claude Code Skill 定义文档
├── README.md                         # 项目说明（本文档）
├── bilingual_subtitle_generator.py   # Gemini 双语字幕生成 CLI 工具
├── burn_subtitle.sh                  # FFmpeg 字幕烧录脚本（自动检测分辨率）
├── RELEASE_NOTES.md                  # 版本发布记录
├── .env.example                      # API Key 配置模板
└── .gitignore                        # Git 忽略规则
```

## License

MIT
