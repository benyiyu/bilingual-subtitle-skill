---
name: bilingual-subtitle-video-generator
description: 根据用户提供的SRT字幕文件，通过Python脚本生成Netflix级别双语字幕，确认后用FFmpeg烧录到视频中输出成品。
argument-hint: "<srt字幕文件路径> <视频文件路径>"
allowed-tools: Bash, Read, Write, Edit, Glob, AskUserQuestion
---

# Bilingual Subtitle Video Generator

根据用户提供的 SRT 字幕文件，通过 Python 脚本（Gemini API + ASR 纠错）生成 Netflix 级别的双语字幕 SRT，经用户确认后，使用 FFmpeg 将字幕烧录进视频，输出带硬字幕的成品视频。

## 完整工作流程

```
用户提供 SRT → Python 脚本生成双语 SRT → 用户确认 → FFmpeg 烧录到视频 → 输出成品
```

---

## 第一阶段：生成双语字幕

### Python 脚本位置

脚本位于本 Skill 目录内：`bilingual_subtitle_generator.py`

> **API Key 配置**：复制 `.env.example` 为 `.env`，填入你的 Google AI Studio API Key。

### 脚本核心特性

- **ASR 纠错**：通过 `VIDEO_KEYWORDS` 术语表自动修正语音识别错误（如 "white coding" → "vibe coding"）
- **大块处理**：`CHUNK_SIZE=300`，减少分块次数，提升翻译连贯性
- **低温度生成**：`temperature=0.1`，减少幻觉，提升翻译准确度
- **Netflix 标准分段**：每行最多 42 个英文字符，语义完整不断行

### 执行步骤

1. **读取用户提供的 SRT 文件**，确认文件存在且格式正确
2. **修改脚本配置**：编辑 `bilingual_subtitle_generator.py` 顶部的配置区域：
   - `INPUT_FILE`、`OUTPUT_JSON`、`OUTPUT_SRT`：修改为用户指定的文件路径
   - `VIDEO_KEYWORDS`：根据当前视频内容更新术语表（人名、产品名、专业术语等）
3. **激活虚拟环境并运行脚本**：

```bash
cd "<skill_directory>" && pip install google-genai && python bilingual_subtitle_generator.py
```

> `<skill_directory>` 为本 Skill 所在目录。Claude Code 调用时会自动定位。

4. **读取生成的双语 SRT 文件**，展示前 10-20 条字幕给用户预览
5. **请求用户确认**：使用 AskUserQuestion 工具询问用户是否对双语字幕满意，或需要调整

> **重要**：必须等用户明确确认字幕质量后，才能进入第二阶段烧录。

---

## 第二阶段：FFmpeg 烧录字幕到视频

### 前置检查

在烧录前，必须完成以下检查：

1. **确认 ffmpeg-full 已安装**：

```bash
/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg -version
```

如果未安装，提示用户执行：

```bash
brew install ffmpeg-full
```

> **关键说明**：标准版 ffmpeg 不包含 libass 字幕渲染库，会报错 `No option name near 'subtitles'`。必须使用 ffmpeg-full。

2. **检测视频分辨率**：

```bash
/opt/homebrew/opt/ffmpeg-full/bin/ffprobe -v error -select_streams v:0 -show_entries stream=width,height -of csv=p=0 "视频文件路径"
```

### 分辨率参数对照表

| 分辨率 | FontSize | MarginV | 说明 |
|--------|----------|---------|------|
| 1080p (1920x1080) | 14 | 8 | 标准高清 |
| 1440p (2560x1440) | 14 | 9 | 2K |
| 4K (3840x2160) | 16 | 10 | 超高清 |

> **MarginV 说明**：数字越小，字幕越靠近底边；数字越大，字幕越往上。

### 烧录方法：必须使用脚本方式执行

**重要**：FFmpeg 的颜色参数包含 `&` 符号，在 shell 中会被错误解析，导致字幕显示为黑色块（无文字）。**必须使用临时脚本方式执行 FFmpeg**，绝对不能直接在命令行中拼接 FFmpeg 命令。

#### 步骤

1. **创建临时烧录脚本**：

```bash
cat > /tmp/burn_subtitle.sh << 'SCRIPT'
#!/bin/bash
/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg -y \
  -i "$1" \
  -vf "subtitles=$2:force_style='FontName=PingFang SC,FontSize=$3,PrimaryColour=&H00FFFFFF,BackColour=&H80000000,BorderStyle=4,Outline=0,Shadow=0,Alignment=2,MarginV=$4'" \
  -c:a copy \
  -preset fast \
  "$5"
SCRIPT
chmod +x /tmp/burn_subtitle.sh
```

2. **根据检测到的分辨率执行烧录**：

```bash
/tmp/burn_subtitle.sh "输入视频.mp4" "双语字幕.srt" "字号" "边距" "输出视频.mp4"
```

#### 具体示例

**1080p 视频：**
```bash
/tmp/burn_subtitle.sh \
  "/path/to/input.mp4" \
  "/path/to/bilingual.srt" \
  14 8 \
  "/path/to/output_subtitled.mp4"
```

**4K 视频：**
```bash
/tmp/burn_subtitle.sh \
  "/path/to/input.mp4" \
  "/path/to/bilingual.srt" \
  16 10 \
  "/path/to/output_subtitled.mp4"
```

### 输出文件命名规则

输出文件名 = 原视频文件名 + `_subtitled` 后缀，保存在与原视频相同的目录下。

例如：`/Users/ben/Downloads/video.mp4` → `/Users/ben/Downloads/video_subtitled.mp4`

---

## 字幕样式说明（Netflix 风格）

| 参数 | 值 | 说明 |
|------|---|------|
| FontName | PingFang SC | 苹方字体，支持中日英混排 |
| PrimaryColour | &H00FFFFFF | 白色字体 |
| BackColour | &H80000000 | 半透明黑色背景 |
| BorderStyle | 4 | 不透明背景框 |
| Outline | 0 | 无描边 |
| Shadow | 0 | 无阴影 |
| Alignment | 2 | 底部居中 |

---

## 故障排除

### `No option name near 'subtitles'`
- **原因**：标准版 ffmpeg 不包含 libass 字幕渲染库
- **解决**：`brew install ffmpeg-full`，并使用 `/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg`

### 字幕显示为黑色块（无文字）
- **原因**：shell 中 `&` 符号被错误解析
- **解决**：必须使用脚本方式执行 ffmpeg（参见上方烧录方法）

### 字幕太小或太大
- 根据视频实际分辨率选择对应的 FontSize（见参数对照表）

### 字幕位置太高或太低
- 调整 MarginV 值

### 烧录速度慢
- 可将 `-preset fast` 改为 `-preset ultrafast`（画质略降）
- 使用硬件加速：将脚本中追加 `-c:v h264_videotoolbox`（macOS 专用）
