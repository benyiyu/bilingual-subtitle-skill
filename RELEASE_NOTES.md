# Release Notes

## v2.0.0 - 2026-02-03

### Overview

Major upgrade: CLI 工具化、自动关键词提取、增量保存、指数退避重试、自动分辨率检测、硬件加速支持。消除了 Claude Code 手动编辑脚本配置和读取 SRT 全文的步骤，大幅减少 token 消耗和操作复杂度。

### Breaking Changes

- `bilingual_subtitle_generator.py` 现在通过命令行参数接收文件路径，不再使用脚本内硬编码的 `INPUT_FILE`/`OUTPUT_*` 变量
- `burn_subtitle.sh` 参数从 5 个改为 3 个（+可选 `--hwaccel`），FontSize/MarginV 由脚本自动检测
- `VIDEO_KEYWORDS` 硬编码术语表已移除，改为 Gemini 自动提取
- `SKILL.md` 中 `allowed-tools` 移除了 `Write` 和 `Edit`（不再需要编辑脚本）

### Changes

#### 1. bilingual_subtitle_generator.py — CLI 工具化

**旧用法**（需要 Claude Code 编辑脚本）：
```python
# 每次需要手动修改这些变量
INPUT_FILE = "/path/to/input.srt"
OUTPUT_JSON = "/path/to/output.json"
OUTPUT_SRT = "/path/to/output.srt"
VIDEO_KEYWORDS = """..."""
```

**新用法**（纯命令行参数）：
```bash
python bilingual_subtitle_generator.py --input "/path/to/input.srt"
# 输出自动生成 _bilingual.srt / _bilingual.json
```

**Why**: 消除 Claude Code 每次需要 Edit 工具修改配置的步骤，节省 ~3K tokens/次。

#### 2. 自动关键词提取 (Phase 0)

翻译前自动读取 SRT 前 200 行，通过 Gemini API 分析内容，提取人名、机构名、产品名、专业术语等关键词，注入后续翻译的 System Prompt。

**Why**: 消除 Claude Code 需要读取 SRT 全文 → 理解内容 → 手写 VIDEO_KEYWORDS 的步骤。这是 v1.0 最大的 token 浪费项（~20K tokens 用于读 SRT + 生成关键词）。

#### 3. 模型更改

```
旧: gemini-3-flash-preview
新: gemini-2.0-flash
```

**Why**: preview 模型不稳定，v1.0 测试中 chunk 4 连续 3 次 "Server disconnected"。正式版稳定性更好。

#### 4. 指数退避重试

```
旧: 固定 time.sleep(5)，最多 3 次重试
新: 5 → 15 → 45 → 90 → 180 秒，最多 5 次重试
```

**Why**: 固定 5 秒等待对服务器过载无效。指数退避给服务器恢复时间。

#### 5. 增量保存 (Checkpoint)

每处理完一个 chunk，立即保存到 `_checkpoint.json`。重新运行时自动检测 checkpoint 文件，跳过已完成的 chunk，从断点续传。所有 chunk 完成后自动清理 checkpoint 文件。

**Why**: v1.0 中 chunk 失败后需要手动写补丁脚本重跑 + 合并。现在直接重跑即可。

#### 6. burn_subtitle.sh — 自动分辨率检测

**旧用法**（5 个参数，需手动查参数表）：
```bash
./burn_subtitle.sh <video> <srt> <font_size> <margin_v> <output>
```

**新用法**（3 个参数，自动检测）：
```bash
./burn_subtitle.sh <video> <srt> <output> [--hwaccel]
```

脚本内部调用 ffprobe 检测分辨率，根据 1080p/1440p/4K 自动选择 FontSize 和 MarginV。

#### 7. 硬件加速

新增 `--hwaccel` 选项，使用 `h264_videotoolbox`（macOS）。4K 软编码需数十分钟，硬件加速可显著缩短。

#### 8. 字体路径

新增 `fontsdir` 参数指定系统字体目录 (`/System/Library/Fonts`)，避免 macOS 字体访问权限警告。

#### 9. SKILL.md 简化

Claude Code 的工作从 "读 SRT → 编辑脚本配置 → 运行 → 手动修复" 简化为 "执行 CLI 命令 → 预览 → 确认烧录"。

移除的步骤：
- 修改脚本配置（INPUT_FILE 等）
- 编辑 VIDEO_KEYWORDS 术语表
- 手动检测视频分辨率
- 手动选择 FontSize/MarginV

新增指令：
- 使用 `run_in_background` 运行 FFmpeg，不轮询进度
- 失败后直接重跑脚本（checkpoint 自动续传）

### Token Savings Estimate

| 步骤 | v1.0 消耗 | v2.0 消耗 | 节省 |
|------|-----------|-----------|------|
| 编辑脚本配置 | ~3K tokens | 0 | 3K |
| 读 SRT + 写关键词 | ~20K tokens | 0 | 20K |
| 手动检测分辨率 | ~1K tokens | 0 | 1K |
| 查参数表选参数 | ~500 tokens | 0 | 500 |
| **合计** | | | **~24.5K tokens/次** |

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
