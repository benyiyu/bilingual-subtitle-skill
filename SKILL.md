---
name: bilingual-subtitle
description: 生成多语言双语字幕并烧录到视频。支持中英、中日、日英等语言组合。当用户需要制作双语字幕视频时使用。
argument-hint: "[step1|step2] [语言:en-cn|ja-cn|en-ja] [文件路径]"
allowed-tools: Bash, Read, Write, Edit, Glob
---

# 多语言双语字幕视频制作 Skill

这个 Skill 分两步完成双语字幕视频制作，支持多种语言组合。

## 推荐工作流程

```
视频/音频 → Buzz (Whisper) 生成 SRT → Claude 翻译 → 双语 SRT → ffmpeg 烧录
```

**重要**: 推荐使用 Buzz/Whisper 生成 SRT 字幕，而非 YouTube 自动字幕（时间轴常有重叠问题）。

---

## 支持的语言组合

| 代码 | 语言组合 | 说明 |
|------|---------|------|
| `en-cn` | 英语 → 中文 | 英文原声，中英双语字幕（默认） |
| `ja-cn` | 日语 → 中文 | 日文原声，日中双语字幕 |
| `en-ja` | 英语 → 日语 | 英文原声，英日双语字幕 |
| `ja-en` | 日语 → 英语 | 日文原声，日英双语字幕 |
| `cn-en` | 中文 → 英语 | 中文原声，中英双语字幕 |
| `cn-ja` | 中文 → 日语 | 中文原声，中日双语字幕 |

---

## 步骤 1: 生成双语字幕 (`/bilingual-subtitle step1`)

**输入**: SRT 字幕文件（推荐 Buzz/Whisper 生成） + 语言组合
**输出**: 双语 SRT 字幕文件

### 使用方式

```
/bilingual-subtitle step1 en-cn ~/Downloads/video.srt   # 英中双语
/bilingual-subtitle step1 ja-cn ~/Downloads/video.srt   # 日中双语
```

### 翻译规范

#### 英语 → 中文 (en-cn)
- 翻译成简体中文，适合科技/商业受众
- 术语参考：AI (人工智能), Machine Learning (机器学习), Robotics (机器人技术)

#### 日语 → 中文 (ja-cn)
- 翻译成简体中文，保留日语特有表达的韵味
- 咖啡术语：浅煎り (浅烘), 深煎り (深烘), 挽く (研磨)
- 保留品牌名原文：Comandante, Pacamara 等

#### 英语 → 日语 (en-ja)
- 日本語に翻訳、技術用語は一般的なカタカナ表記を使用

### 双语 SRT 格式

```srt
1
00:00:08,920 --> 00:00:12,000
はいどうもコーヒーに愛された男 カツヤです
大家好，我是被咖啡眷顾的男人 Katsuya

2
00:00:12,000 --> 00:00:14,960
さすがに、すいません
不好意思
```

每条字幕：第一行原文，第二行翻译。

---

## 步骤 2: 烧录字幕到视频 (`/bilingual-subtitle step2`)

**输入**: 视频文件 (mp4/mkv) + SRT 字幕文件
**输出**: 带硬字幕的 MP4 视频文件

### 重要：使用脚本避免转义问题

ffmpeg 的颜色参数包含 `&` 符号，在 shell 中有特殊含义。**必须使用脚本方式执行**：

```bash
# 创建临时脚本
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

# 执行脚本
/tmp/burn_subtitle.sh "输入视频.mp4" "字幕.srt" "字号" "边距" "输出视频.mp4"
```

### 不同分辨率的参数

| 分辨率 | FontSize | MarginV | 说明 |
|--------|----------|---------|------|
| 1080p | 12 | 8 | 标准高清 |
| 1440p | 14 | 9 | 2K |
| 4K (2160p) | 16 | 10 | 超高清（推荐） |

> **MarginV 说明**: 数字越小，字幕越靠近底边；数字越大，字幕越往上。

### 完整示例

#### 1080p 视频
```bash
/tmp/burn_subtitle.sh \
  "/Users/ben/Downloads/video.mp4" \
  "/Users/ben/Downloads/bilingual.srt" \
  12 8 \
  "/Users/ben/Downloads/video_subtitled.mp4"
```

#### 4K 视频
```bash
/tmp/burn_subtitle.sh \
  "/Users/ben/Downloads/video.mkv" \
  "/Users/ben/Downloads/bilingual.srt" \
  16 10 \
  "/Users/ben/Downloads/video_subtitled.mp4"
```

### 样式说明 (Netflix 风格)

- **FontName**: PingFang SC (支持中日英混排)
- **PrimaryColour**: &H00FFFFFF (白色字体)
- **BackColour**: &H80000000 (半透明黑色背景)
- **BorderStyle**: 4 (不透明背景框)
- **Alignment**: 2 (底部居中)

---

## 使用示例

```bash
# 完整流程示例

# 1. 用户用 Buzz 生成 SRT 字幕（时间轴准确）
#    Buzz 导出: video.srt

# 2. 翻译成双语字幕
/bilingual-subtitle step1 ja-cn ~/Downloads/video.srt

# 3. 烧录到视频（4K）
/bilingual-subtitle step2 ~/Downloads/video.mkv ~/Downloads/video_bilingual.srt
```

---

## 前置要求

1. **ffmpeg-full**:
   ```bash
   brew install ffmpeg-full
   ```
   路径: `/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg`

   > 注意：标准版 ffmpeg 不包含 libass 字幕渲染库，必须安装 ffmpeg-full

2. **Buzz** (推荐): 用于生成准确时间轴的 SRT 字幕
   - 下载: https://github.com/chidiwilliams/buzz

---

## 故障排除

### 字幕显示为黑色块（无文字）
- **原因**: shell 命令中 `&` 符号被错误解析
- **解决**: 使用脚本方式执行 ffmpeg（见上方示例）

### 字幕太小或太大
- 根据视频分辨率调整 FontSize（见参数表）

### 字幕位置太高或太低
- 调整 MarginV 值（数字越小越靠近底边，数字越大越往上）

### 字幕时间轴重叠
- **原因**: YouTube 自动字幕时间轴不准确
- **解决**: 使用 Buzz/Whisper 重新生成 SRT

### 烧录速度慢
- 使用 `-preset ultrafast`（质量略降）
- 使用硬件加速: `-c:v h264_videotoolbox` (macOS)

---

## 字幕来源对比

| 来源 | 时间轴质量 | 推荐程度 |
|------|-----------|---------|
| Buzz/Whisper 生成 SRT | ✅ 准确不重叠 | **推荐** |
| YouTube 自动字幕 | ❌ 经常重叠 | 不推荐 |
| 纯文本 transcript | ❌ 无时间轴 | 需重新对齐 |
