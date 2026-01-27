# Release Notes

## v1.0.0 (2026-01-26)

### 新功能

- **双语字幕生成**: 支持 6 种语言组合 (en-cn, ja-cn, en-ja, ja-en, cn-en, cn-ja)
- **视频烧录**: 使用 ffmpeg + libass 将字幕硬烧录到视频
- **Netflix 风格样式**: 白色文字 + 半透明黑色背景框
- **多分辨率支持**: 针对 1080p/1440p/4K 优化的参数

### 技术细节

#### 最终确定的 4K 参数
经过多轮测试，确定最佳参数：
- **FontSize**: 16
- **MarginV**: 10
- **FontName**: PingFang SC (支持中日英混排)

#### Shell 转义问题解决方案
ffmpeg 的颜色参数 `&H00FFFFFF` 中的 `&` 符号会被 shell 错误解析。解决方案是使用 heredoc 创建临时脚本：

```bash
cat > /tmp/burn_subtitle.sh << 'SCRIPT'
#!/bin/bash
/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg -y \
  -i "$1" \
  -vf "subtitles=$2:force_style='FontName=PingFang SC,FontSize=16,...'" \
  -c:a copy \
  "$3"
SCRIPT
```

#### 字幕来源建议
| 来源 | 推荐程度 | 原因 |
|------|---------|------|
| Buzz/Whisper | 推荐 | 时间轴准确不重叠 |
| YouTube 自动字幕 | 不推荐 | 时间轴经常重叠 |

### 已知问题

- 1080p 和 1440p 参数未经充分测试，可能需要微调
- 暂不支持竖屏视频的参数优化

### 开发历程

本 Skill 由 Ben 与 Claude (Opus 4.5) 协作开发，经历了：

1. **初始设计**: 确定两步工作流 (翻译 → 烧录)
2. **ffmpeg 配置**: 解决 libass 依赖问题 (`brew install ffmpeg-full`)
3. **英文视频测试**: DeepMind CEO 访谈视频 (1080p) - 成功
4. **日文视频测试**: Comandante 咖啡器具视频 (4K) - 发现多个问题
5. **时间轴问题**: 发现 YouTube 自动字幕重叠问题，改用 Buzz/Whisper
6. **样式调试**: 解决 `&` 符号转义导致的黑色块问题
7. **参数优化**: 多轮测试确定 4K 最佳参数 (FontSize=16, MarginV=10)

### 版本迭代记录

| 版本 | FontSize | MarginV | 问题 |
|------|----------|---------|------|
| v5 | 28 | 35 | 字号太大，位置太高 |
| v6 | 20 | 55 | 字号稍大，位置未变 |
| v8 | 18 | 80 | 字号OK，位置太高 |
| v9 | 18 | 30 | 位置稍高 |
| v10 | 18 | 20 | 位置稍高 |
| v11 | 16 | 10 | **完美** |

---

## 未来计划

- [ ] 支持更多语言 (韩语、西班牙语等)
- [ ] 竖屏视频参数优化
- [ ] 字幕样式主题 (Netflix/YouTube/Disney+)
- [ ] 批量处理多个视频
