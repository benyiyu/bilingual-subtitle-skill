---
name: bilingual-subtitle-video-generator
description: 根据用户提供的SRT字幕文件，通过Python脚本生成Netflix级别双语字幕，确认后用FFmpeg烧录到视频中输出成品。
argument-hint: "<srt字幕文件路径> <视频文件路径>"
allowed-tools: Bash, Read, AskUserQuestion
---

# Bilingual Subtitle Video Generator v2.1

根据用户提供的 SRT 字幕文件，通过 CLI 工具（Gemini API + 自动关键词提取 + ASR 纠错 + 手动术语注入 + 备用模型自动切换）生成 Netflix 级别的双语字幕 SRT，经用户确认后，使用 FFmpeg 将字幕烧录进视频，输出带硬字幕的成品视频。

## 完整工作流程

```
用户提供 SRT → CLI 生成双语 SRT（自动提取关键词）→ 预览确认 → FFmpeg 烧录 → 输出成品
```

---

## 第一阶段：生成双语字幕

### 脚本位置

脚本位于本 Skill 目录内：`bilingual_subtitle_generator.py`

> **API Key 配置**：复制 `.env.example` 为 `.env`，填入你的 Google AI Studio API Key。

### 执行步骤

1. **运行 CLI 命令生成双语字幕**：

```bash
cd "<skill_directory>" && python bilingual_subtitle_generator.py --input "<srt文件路径>"
```

输出文件自动生成在输入文件同目录，后缀 `_bilingual.srt` / `_bilingual.json`。

可选参数：

```bash
python bilingual_subtitle_generator.py \
  --input "<srt文件路径>" \
  --output-srt "<输出srt路径>" \
  --output-json "<输出json路径>" \
  --keywords "Clawd:OpenClaw的AI助手, Claude Code:Anthropic的编码工具" \
  --model gemini-2.5-flash
```

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--input` | 输入 SRT 文件路径（必填） | — |
| `--output-srt` | 输出双语 SRT 路径 | `<input>_bilingual.srt` |
| `--output-json` | 输出双语 JSON 路径 | `<input>_bilingual.json` |
| `--keywords` | 手动注入术语，格式 `term:description, ...`，追加到自动提取结果 | 无 |
| `--model` | 指定 Gemini 模型 | `gemini-2.5-flash` |

> **不需要**手动编辑脚本配置、不需要读取 SRT 内容。脚本自动完成全文关键词提取，`--keywords` 用于补充自动提取遗漏的术语。

2. **读取生成的双语 SRT 文件前 15 条字幕**预览：

```bash
head -60 "<输出srt路径>"
```

3. **使用 AskUserQuestion 确认**字幕质量，询问用户是否满意或需要调整。

> **重要**：必须等用户明确确认字幕质量后，才能进入第二阶段烧录。

4. **如果字幕生成中途失败**，直接重跑同一命令即可。脚本内置 checkpoint 机制，自动从断点续传。

---

## 第二阶段：FFmpeg 烧录字幕到视频

### 执行步骤

1. **使用 `run_in_background` 运行烧录脚本**（不要用 TaskOutput 轮询进度）：

```bash
"<skill_directory>/burn_subtitle.sh" "<输入视频.mp4>" "<双语字幕.srt>" "<输出视频.mp4>"
```

硬件加速（推荐 4K 视频使用）：

```bash
"<skill_directory>/burn_subtitle.sh" "<输入视频.mp4>" "<双语字幕.srt>" "<输出视频.mp4>" --hwaccel
```

> 脚本自动检测视频分辨率，自动选择 FontSize/MarginV，不需要手动查参数表。

2. **等待完成通知**，报告结果。

### 输出文件命名规则

输出文件名 = 原视频文件名 + `_subtitled` 后缀，保存在与原视频相同的目录下。

例如：`/Users/ben/Downloads/video.mp4` → `/Users/ben/Downloads/video_subtitled.mp4`

---

## 关键指令

- **不要**手动编辑 Python 脚本的配置（INPUT_FILE、VIDEO_KEYWORDS 等已移除）
- **不要**手动检测视频分辨率或查参数表
- **不要**用 TaskOutput 轮询 FFmpeg 进度，使用 `run_in_background` 后等待完成通知
- 如果字幕生成失败，直接重跑脚本（checkpoint 自动续传）

---

## 前置要求

| 依赖 | 说明 |
|------|------|
| **Python 3.x** | 运行翻译脚本 |
| **google-genai** | `pip install google-genai` |
| **ffmpeg-full** | `brew install ffmpeg-full` |
| **GOOGLE_API_KEY** | 在 `.env` 文件中配置 |

---

## 故障排除

| 问题 | 解决方案 |
|------|----------|
| `No option name near 'subtitles'` | `brew install ffmpeg-full` |
| 字幕显示为黑色块 | 必须通过 `burn_subtitle.sh` 脚本执行 |
| API 503/断连 | 脚本内置指数退避重试（5→15→45→90→180 秒），通常自动恢复 |
| 中途失败 | 直接重跑脚本，checkpoint 自动续传 |
| 烧录速度慢 | 使用 `--hwaccel` 开启硬件加速 |
| 文件名含特殊字符（如 `'`）导致烧录失败 | v2.1 已修复：脚本自动创建临时 symlink 避免冲突 |
