# Release Notes

## v1.0.0 - 2025-01-30

### Overview

Bilingual Subtitle Video Generator 是一个 Claude Code Skill，实现了从单语 SRT 字幕到双语硬字幕视频的全自动化流水线。

### Development Timeline

#### Phase 1: Skill 设计与创建

基于已有的 `bilingual-subtitle` skill 经验，设计了新的完整工作流：

```
SRT 字幕 → Gemini 翻译 → 双语 SRT → 用户确认 → FFmpeg 烧录 → 成品视频
```

创建 `SKILL.md`，定义了两阶段工作流程、分辨率参数对照表、FFmpeg 脚本模板和故障排除指南。

#### Phase 2: 实战测试

使用测试素材 "Clawdbot Peter Steinberger Makes First Public Appearance Since Launch"（36 分钟，1080p）进行端到端测试。

**第一阶段测试 - 双语字幕生成：**
- 输入：1419 行英文 SRT
- Python 脚本分 24 个块通过 Gemini API 处理
- 遇到 503 (model overloaded) 错误，重试机制成功处理
- 输出：2300 行英中双语 SRT

**第二阶段测试 - FFmpeg 烧录：**
- 自动检测视频分辨率 1920x1080
- 通过 `/tmp/burn_subtitle.sh` 脚本执行（避免 `&` 解析问题）
- 使用 ffmpeg-full 8.0.1（含 libass）
- 成功输出 441MB 带字幕视频

#### Phase 3: 脚本升级 (bilingual_subtitle_generator.py)

基于测试反馈，对 Python 脚本进行了重大升级：

1. **ASR 纠错系统**：新增 `VIDEO_KEYWORDS` 术语表，通过 System Prompt 注入，自动修正语音识别错误（如 "white coding" → "vibe coding"）
2. **大块处理优化**：`CHUNK_SIZE` 从 60 提升至 300，减少分块次数（24 块 → 约 5 块），显著提升翻译连贯性
3. **Temperature 控制**：设置 `temperature=0.1`，降低模型幻觉概率
4. **字号调优**：1080p 视频 FontSize 从 12 调整为 14，改善可读性

#### Phase 4: GitHub 发布准备

1. **安全处理**：将硬编码 API Key 替换为环境变量 + `.env` 文件方案
2. **`.gitignore`**：排除 `.env`、`__pycache__`、`.venv`、视频/JSON 输出文件、`.DS_Store`
3. **`.env.example`**：提供 API Key 配置模板
4. **`burn_subtitle.sh`**：独立的 FFmpeg 烧录脚本，包含参数校验和 ffmpeg-full 检查

### Key Decisions & Lessons Learned

| Issue | Solution |
|-------|----------|
| FFmpeg `&` 符号被 shell 错误解析 | 必须使用脚本文件执行，不能内联命令 |
| 标准 ffmpeg 缺少 libass | 使用 `brew install ffmpeg-full` |
| ASR 转录错误（人名、产品名） | VIDEO_KEYWORDS 术语表 + System Prompt 注入 |
| 翻译分块导致上下文断裂 | CHUNK_SIZE 从 60 提升至 300 |
| 翻译出现幻觉/过度意译 | temperature 降至 0.1 |
| 1080p 字幕偏小 | FontSize 从 12 调整为 14 |
| API Key 泄露风险 | 环境变量 + .env + .gitignore |

### File Structure

```
bilingual-subtitle-video-generator/
├── SKILL.md                          # Claude Code Skill 定义文档
├── bilingual_subtitle_generator.py   # Gemini 双语字幕生成脚本
├── burn_subtitle.sh                  # FFmpeg 字幕烧录脚本
├── .env.example                      # API Key 配置模板
├── .gitignore                        # Git 忽略规则
└── RELEASE_NOTES.md                  # 本文档
```

### Prerequisites

- **Python 3.x** + `google-genai` SDK
- **ffmpeg-full**: `brew install ffmpeg-full` (macOS, 需含 libass)
- **Google AI Studio API Key**: [获取地址](https://aistudio.google.com/apikey)

### Resolution Presets

| Resolution | FontSize | MarginV |
|-----------|----------|---------|
| 1080p     | 14       | 8       |
| 1440p     | 14       | 9       |
| 4K        | 16       | 10      |
