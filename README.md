# Bilingual Subtitle Video Generator

一个 [Claude Code](https://docs.anthropic.com/en/docs/claude-code) Skill，基于 Google Gemini API 将单语 SRT 字幕自动翻译为 Netflix 级别的中英双语字幕，并通过 FFmpeg 烧录到视频中，输出带硬字幕的成品视频。

## Features

- **ASR 纠错**：通过可自定义的 `VIDEO_KEYWORDS` 术语表，自动修正语音识别中的常见错误（如 "white coding" → "vibe coding"）
- **Netflix 标准分段**：英文每行不超过 42 个字符，按语义完整切分，不在语法单元中间断行
- **大块上下文处理**：`CHUNK_SIZE=300`，减少分块次数，保持翻译连贯性
- **低温度生成**：`temperature=0.1`，降低模型幻觉，提升翻译准确度
- **自动重试**：每个分块最多重试 3 次，自动处理 API 临时故障（如 503 overloaded）
- **Netflix 风格字幕样式**：白色字体 + 半透明黑色背景，PingFang SC 字体，底部居中
- **多分辨率适配**：内置 1080p / 1440p / 4K 分辨率参数预设

## Workflow

```
用户提供 SRT + 视频 → Python 脚本生成双语 SRT → 用户确认 → FFmpeg 烧录到视频 → 输出成品
```

**第一阶段** — 双语字幕生成：Python 脚本读取原始 SRT，通过 Gemini API 进行 ASR 纠错 + 翻译 + Netflix 标准分段，输出双语 SRT 文件。

**第二阶段** — 字幕烧录：使用 FFmpeg（需 libass）将双语 SRT 以硬字幕形式烧录到原视频中。

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

在 Claude Code 中使用 Skill 命令触发：

```
/bilingual-subtitle-video-generator <字幕文件.srt> <视频文件.mp4>
```

Claude Code 将自动执行完整的两阶段工作流：

1. 读取 SRT 文件，修改脚本配置（文件路径、术语表）
2. 运行 Python 脚本生成双语 SRT
3. 展示字幕预览，等待用户确认
4. 检测视频分辨率，选择对应参数
5. 通过 FFmpeg 烧录字幕到视频
6. 输出成品：`原文件名_subtitled.mp4`

## Configuration

### 术语表（VIDEO_KEYWORDS）

编辑 `bilingual_subtitle_generator.py` 中的 `VIDEO_KEYWORDS` 变量，添加当前视频相关的人名、产品名、专业术语等：

```python
VIDEO_KEYWORDS = """
- Peter Steinberger (Person Name, Austrian developer)
- MoltBot (Product Name, personal AI agent project)
- vibe coding (Programming concept, NOT "white coding")
"""
```

术语表通过 System Prompt 注入 Gemini，用于自动纠正 ASR 转录错误。

### 脚本参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `CHUNK_SIZE` | 300 | 每块处理的行数，越大上下文越完整 |
| `MODEL_NAME` | gemini-3-flash-preview | Gemini 模型，推荐 flash 系列 |
| `temperature` | 0.1 | 生成温度，越低越稳定 |

## Resolution Presets

| 分辨率 | FontSize | MarginV | 说明 |
|--------|----------|---------|------|
| 1080p (1920x1080) | 14 | 8 | 标准高清 |
| 1440p (2560x1440) | 14 | 9 | 2K |
| 4K (3840x2160) | 16 | 10 | 超高清 |

> MarginV 数字越小字幕越靠近底边，数字越大越往上。

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
| 字幕太小或太大 | 分辨率参数不匹配 | 参考 Resolution Presets 选择正确的 FontSize |
| 字幕位置偏移 | MarginV 不合适 | 调整 MarginV 值 |
| 烧录速度慢 | 编码预设较保守 | 将 `-preset fast` 改为 `-preset ultrafast`，或添加 `-c:v h264_videotoolbox`（macOS 硬件加速） |
| API 503 错误 | Gemini 模型过载 | 脚本内置重试机制，通常自动恢复 |

## File Structure

```
bilingual-subtitle-video-generator/
├── SKILL.md                          # Claude Code Skill 定义文档
├── README.md                         # 项目说明（本文档）
├── bilingual_subtitle_generator.py   # Gemini 双语字幕生成脚本
├── burn_subtitle.sh                  # FFmpeg 字幕烧录脚本
├── RELEASE_NOTES.md                  # 版本发布记录
├── .env.example                      # API Key 配置模板
└── .gitignore                        # Git 忽略规则
```

## License

MIT
