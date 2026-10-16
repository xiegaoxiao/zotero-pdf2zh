# Fork 维护说明

本仓库基于 [guaguastandup/zotero-pdf2zh](https://github.com/guaguastandup/zotero-pdf2zh)，保留原作者署名、提交历史和 AGPL-3.0 许可证。以下改动涉及 Python 服务端及插件设置界面。插件版本为 `4.1.8-fork.1`，更新地址指向本 Fork，避免自动更新时覆盖自定义设置。

## 新增修复

1. **翻译失败处理**：任务使用独立输出目录，完整验证本次请求的 PDF 后再发布，避免误取旧文件、误报成功及 `list index out of range`。解析失败时生成 PDF 结构修复副本并重试一次。发布失败会尝试还原旧输出。
2. **PDF 排版与字体**：处理重叠文本检测框、重复字形、首字下沉、部分跨页句子和居中标题；补充短小的旋转文字标签；保留原有简单 TrueType 字体，避免压缩字体时将数字画成错误的字形；纯数字刻度序列保留原有位置和样式。
3. **加粗一致性**：含粗细变化的段落保留源字重，即使请求关闭富文本翻译也保留强调边界；跨页句子前后保持粗体，普通正文维持常规字重。含字重变化的长段落不因超过 40 个占位符而整段丢弃样式。
4. **术语 JSON 兼容**：仅在术语对象完整、响应只缺最后一个数组右括号且严格校验通过时补齐 `]`；其他 JSON 损坏仍保留警告，不猜测或补写术语内容。
5. **参考文献默认保留原文**：新增“翻译参考文献”开关，默认关闭；按章节与分栏识别参考文献，跨页生效，同页正文继续翻译。详见 [设置说明与识别范围](server/doc/reference-translation.md)。

详见 [翻译输出处理](server/doc/translation-errors.md) 和 [PDF 排版修复](server/doc/layout-repair.md)。

## 使用与验证

按原项目说明安装运行环境，使用本分支的 `server` 源码。重启服务后，托管的 `pdf2zh_next` 环境会自动检查并应用排版补丁。补丁已在 `pdf2zh-next 2.9.0 / BabelDOC 0.6.2` 验证；不支持的源码结构会明确报错。旧译文需从原 PDF 重新翻译。

相关测试在安装 `server/requirements.txt` 后，从 `server` 目录运行：

```sh
python -m unittest discover -s tests -p test_translation_output_isolation.py -v
python -m unittest discover -s tests -p test_pdf_layout_repair.py -v
python -m unittest discover -s tests -p test_rotated_labels.py -v
python -m unittest discover -s tests -p test_safe_font_subset.py -v
python -m unittest discover -s tests -p test_openai_config_compat.py -v
python -m unittest discover -s tests -p test_download_filename_routing.py -v
python -m unittest discover -s tests -p test_source_font_weight.py -v
python -m unittest discover -s tests -p test_term_json_repair.py -v
python -m unittest discover -s tests -p test_reference_filter.py -v
```

以上共 60 项测试，不需要调用翻译 API。中文字体相关的一项测试在缺少 BabelDOC 缓存字体时跳过。数字字体测试使用自行生成的合成字形文件，未分发个人论文或第三方字体。插件在 `plugin` 目录运行 `npm ci`、`npm test` 和 `npm run build`；XPI 位于 `plugin/build/`，可通过 Zotero 插件管理器“从文件安装插件”安装。

## 与上游同步

原项目 README 当前包含重构期间暂不接收贡献的公告，因此本 Fork 暂时独立维护，未向上游提交 PR。可先 `git fetch upstream`，检查差异后在开发分支合并更新并运行相关测试。直接使用上游发布包或自动更新可能覆盖本分支的服务端修改。

个人配置、API 密钥、运行日志、虚拟环境和译文不属于本 Fork 的提交内容。新增的 `.gitignore` 规则排除本地运行目录，配置模板仍沿用原项目的示例文件。
