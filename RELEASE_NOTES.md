# Release Notes

## v2.6.0 - 2026-02-06

### Overview

针对长视频（1-2小时）场景的稳定性优化。通过全文关键词提取提升翻译准确性，通过更小的 chunk size 提升 API 调用成功率。

### Changes

#### 1. 全文关键词提取（移除采样限制）

```
旧: >1000 行 transcript 采样 300 行 × 3 段 ≈ 900 行
新: 始终使用全文提取关键词
```

**Why**: 采样可能遗漏关键术语。对于 1-2 小时视频（约 2000-4000 行），全文提取仍在 API 承受范围内，且能获得更完整的术语表。

#### 2. 更小的默认 Chunk Size

```
旧: DEFAULT_CHUNK_SIZE = 60
新: DEFAULT_CHUNK_SIZE = 30
```

**Why**: 更小的 chunk 意味着：
- 单次 API payload 减半，超时风险降低
- checkpoint 粒度更细，失败时损失的工作量减半
- API 调用次数翻倍，但每次调用更稳定

对于 2 小时视频（约 2000 条字幕）：
- 旧: ~34 chunks
- 新: ~67 chunks

### Constants Reference

| 常量 | 旧值 | 新值 | 说明 |
|------|-----|-----|------|
| `DEFAULT_CHUNK_SIZE` | 60 | 30 | 更小的请求，更高的成功率 |
| `KEYWORD_SAMPLE_THRESHOLD` | 1000 | 99999 | 禁用采样，全文提取 |
| `KEYWORD_SAMPLE_LINES` | 300 | 99999 | 禁用采样，全文提取 |

---

## v2.2.0 - 2026-02-04

### Overview

针对长视频（1 小时+、1200+ 行 SRT）场景的可靠性升级。解决了长文件处理中 API 配额耗尽、关键词重复提取浪费配额、连续失败雪崩等问题。

### Changes

#### 1. 关键词缓存到 Checkpoint

关键词提取结果（Phase 0）现在保存到 `_checkpoint.json` 中。重跑脚本时直接从缓存加载，不再重新调用 API 提取。

```
旧: 每次运行都重新提取关键词（即使 checkpoint 已有 16/25 chunks）
新: 提取一次，缓存到 checkpoint，后续 resume 直接复用
```

**Why**: 关键词提取是最大的单次 API 请求（发送整个/采样后的 transcript）。之前每次 resume 都重复这一步，既浪费配额又容易因请求过大而失败。

#### 2. 采样式关键词提取

对于超过 1000 行的长 transcript，不再发送全文，而是采样开头、中间、结尾各 300 行（去重后约 900 行）进行关键词提取。

```
旧: 3627 行全部发送（~6000+ chars 的单次请求）
新: 采样 ~900 行（请求体积减小 ~75%）
```

**Why**: 全文发送对长视频容易触发 "Server disconnected"，采样覆盖了 transcript 的代表性片段，关键词提取质量几乎不受影响。

#### 3. 自适应 Chunk 间延迟

```
旧: 固定 2 秒间隔
新: 初始 2 秒，失败后翻倍（最高 30 秒），成功后重置为 2 秒
```

**Why**: 固定 2 秒对 25 个 chunk 的长文件过于激进，连续请求容易触发 API 限流。自适应延迟在 API 压力大时自动降速。

#### 4. 429 限流专项处理

新增 `_is_rate_limit_error()` 检测 `429` 和 `RESOURCE_EXHAUSTED` 错误。触发时应用最低 60 秒冷却，而非普通的 5-15 秒退避。

```
旧: 所有错误使用相同的退避策略（5→15→45→90→180s）
新: 普通错误正常退避，429 错误至少等 60 秒
```

**Why**: 之前对 429 错误使用短间隔重试（5s、15s），不仅无法恢复，反而加速耗尽配额。

#### 5. `--chunk-size` CLI 参数

新增 `--chunk-size` 参数，允许用户根据 API 配额情况调整每次请求的大小。

```bash
# 默认 150 行/chunk（与 v2.1 一致）
python bilingual_subtitle_generator.py --input "long.srt"

# 缩小到 100 行/chunk，请求更小、更不容易失败
python bilingual_subtitle_generator.py --input "long.srt" --chunk-size 100
```

如果修改了 chunk size，checkpoint 会保留已缓存的关键词但重置 chunk 进度（因为分块方式变了）。

#### 6. 全局错误预算

连续 3 个 chunk 失败后，暂停整个 pipeline 120 秒，让 API 恢复。暂停期间进度已保存，用户也可以 Ctrl+C 后稍后重跑。

```
旧: 每个 chunk 独立重试，失败后立即尝试下一个，可能连续烧光所有 chunk 的重试配额
新: 3 次连续失败 → 暂停 120 秒 → 重置计数 → 继续
```

**Why**: 当 API 持续不可用时，逐个 chunk 重试 5 次 × 2 模型 = 每个 chunk 最多 10 次失败请求。25 个 chunk 可能产生 250 次无效请求。全局错误预算提前熔断，避免配额雪崩。

### Constants Reference

| 常量 | 值 | 说明 |
|------|---|------|
| `DEFAULT_CHUNK_SIZE` | 150 | 默认每 chunk 行数（可通过 `--chunk-size` 覆盖） |
| `RATE_LIMIT_COOLDOWN` | 60s | 429 错误最低冷却时间 |
| `KEYWORD_SAMPLE_THRESHOLD` | 1000 | 超过此行数启用采样式关键词提取 |
| `KEYWORD_SAMPLE_LINES` | 300 | 每段采样行数（开头/中间/结尾） |
| `CONSECUTIVE_FAIL_LIMIT` | 3 | 全局错误预算：连续失败上限 |
| `GLOBAL_PAUSE_DURATION` | 120s | 错误预算耗尽后的暂停时间 |
| `MIN_CHUNK_DELAY` | 2s | 自适应延迟下限 |
| `MAX_CHUNK_DELAY` | 30s | 自适应延迟上限 |

---

## v2.1.0 - 2026-02-04

### Overview

翻译质量和鲁棒性升级：可配置模型与备用模型自动切换、手动术语注入、时间戳格式兼容、特殊字符文件名修复。

### Changes

#### 1. 实时输出

设置 `PYTHONUNBUFFERED=1`，脚本输出不再被 Python 缓冲，可实时观察进度。

**Why**: v2.0 在后台运行时 stdout 被缓冲，无法通过 `tail` 观察进度。

#### 2. CHUNK_SIZE 300 → 150

```
旧: 300 行/chunk（~5 个 chunk/1400 行文件）
新: 150 行/chunk（~25 个 chunk/3600 行文件）
```

**Why**: 300 行的 chunk 过大，导致翻译质量下降（上下文混乱）。150 行在翻译质量和 API 调用次数间取得更好平衡。

#### 3. 时间戳格式兼容

新增 `normalize_timestamp()` 函数，替换原来简单的字符串替换。支持 Gemini 返回的所有时间戳变体：

| 格式 | 示例 | 处理 |
|------|------|------|
| MM:SS | `01:30` | → `00:01:30,000` |
| MM:SS.ms | `01:30.500` | → `00:01:30,500` |
| HH:MM:SS | `00:01:30` | → `00:01:30,000` |
| HH:MM:SS.ms | `00:01:30.500` | → `00:01:30,500` |
| HH:MM:SS,mmm | `00:01:30,500` | → `00:01:30,500` |
| 异常双逗号 | `00:16:11,560,000` | → `00:16:11,560` |

**Why**: v2.0 使用简单的 `replace('.', ':')` 处理时间戳，无法正确处理 Gemini 返回的多种格式变体，导致 SRT 时间戳错乱。

#### 4. `--keywords` 手动术语注入

新增 `--keywords` 参数，允许用户手动补充自动提取遗漏的术语：

```bash
python bilingual_subtitle_generator.py --input "video.srt" \
  --keywords "Clawd:OpenClaw的AI助手, Claude Code:Anthropic的编码工具"
```

手动关键词追加到自动提取结果之后，不会覆盖。

**Why**: 自动关键词提取有时遗漏特定领域术语或 ASR 高频错误词，需要人工补充。

#### 5. `--model` 参数 + 备用模型自动切换

```
旧: 硬编码 gemini-2.0-flash，无备用
新: --model 可指定（默认 gemini-2.5-flash），失败后自动切换 gemini-3-flash-preview
```

每个 chunk 独立切换：主模型 5 次重试失败 → 备用模型 5 次重试。

**Why**: 单一模型遇到持续性故障时无法恢复。备用模型提供第二条路径。

#### 6. 关键词提取范围：200 行采样 → 全文

```
旧: 仅读取前 200 行提取关键词
新: 发送全文提取关键词
```

**Why**: 200 行样本可能遗漏视频后半段出现的重要术语。

#### 7. burn_subtitle.sh 特殊字符修复

文件名包含单引号（`'`）等特殊字符时，FFmpeg 的 `force_style` 参数会解析失败。v2.1 在烧录前创建临时 symlink 到 `/tmp/`，烧录完成后清理。

**Why**: 实际使用中经常遇到文件名包含 `'`、`(`、`)` 等字符的视频/字幕文件。

---

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
