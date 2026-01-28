# Bilingual Subtitle Skill for Claude Code

一个用于 Claude Code 的双语字幕制作 Skill，支持将视频字幕翻译成双语并烧录到视频中。

## Demo
http://xhslink.com/o/1PzmIRnbC6L 


## 功能特点

- **多语言支持**: 中英、日中、英日等 6 种语言组合
- **Netflix 风格字幕**: 白色文字 + 半透明黑色背景
- **4K 优化**: 针对不同分辨率优化的字号和位置参数
- **两步工作流**: 翻译 → 烧录，灵活可控

## 快速开始

### 前置要求

1. **Claude Code** (Anthropic 官方 CLI)
2. **ffmpeg-full** (包含 libass 字幕渲染库)
   ```bash
   brew install ffmpeg-full
   ```
3. **Buzz** (推荐，用于生成准确的 SRT 字幕)
   - 下载: https://github.com/chidiwilliams/buzz
4. 安装Google Generative AI SDK依赖
   ```pip 
   install -r requirements.txt
   ```

### 安装 Skill

将 `SKILL.md` 复制到 Claude Code 的 Skills 目录：

```bash
mkdir -p ~/.claude/skills/bilingual-subtitle
cp SKILL.md ~/.claude/skills/bilingual-subtitle/
```

### 使用方法

```bash
# 步骤 1: 翻译字幕 (日语 → 中文)
/bilingual-subtitle step1 ja-cn ~/Downloads/video.srt

# 步骤 2: 烧录到视频
/bilingual-subtitle step2 ~/Downloads/video.mkv ~/Downloads/video_bilingual.srt
```

## 支持的语言组合

| 代码 | 语言组合 | 说明 |
|------|---------|------|
| `en-cn` | 英语 → 中文 | 英文原声，中英双语字幕 |
| `ja-cn` | 日语 → 中文 | 日文原声，日中双语字幕 |
| `en-ja` | 英语 → 日语 | 英文原声，英日双语字幕 |
| `ja-en` | 日语 → 英语 | 日文原声，日英双语字幕 |
| `cn-en` | 中文 → 英语 | 中文原声，中英双语字幕 |
| `cn-ja` | 中文 → 日语 | 中文原声，中日双语字幕 |

## 分辨率参数参考

| 分辨率 | FontSize | MarginV |
|--------|----------|---------|
| 1080p | 12 | 8 |
| 1440p | 14 | 9 |
| 4K (2160p) | 16 | 10 |

> **MarginV**: 数字越小，字幕越靠近底边

## 推荐工作流程

```
视频/音频 → Buzz (Whisper) 生成 SRT → Claude 翻译 → 双语 SRT → ffmpeg 烧录
```

**为什么推荐 Buzz/Whisper？**
- YouTube 自动字幕时间轴经常重叠
- Buzz 使用 OpenAI Whisper，时间轴准确

## 项目结构

```
bilingual-subtitle-skill/
├── SKILL.md              # Claude Code Skill 定义文件
├── README.md             # 本文档
├── scripts/
│   └── burn_subtitle.sh  # ffmpeg 烧录脚本
└── examples/
    └── sample.srt        # 示例双语字幕
```

## 常见问题

### 字幕显示为黑色块
- **原因**: shell 中 `&` 符号被错误解析
- **解决**: 使用脚本方式执行 ffmpeg

### 字幕时间轴重叠
- **原因**: YouTube 自动字幕不准确
- **解决**: 使用 Buzz/Whisper 重新生成 SRT

### ffmpeg 报错 "No option name near 'subtitles'"
- **原因**: 标准版 ffmpeg 不包含 libass
- **解决**: `brew install ffmpeg-full`

## License

MIT

## 致谢

- [Claude Code](https://claude.ai/claude-code) - Anthropic
- [Buzz](https://github.com/chidiwilliams/buzz) - Whisper GUI
- [ffmpeg](https://ffmpeg.org/) - 视频处理
