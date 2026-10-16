# Fork 维护说明

本仓库基于 [guaguastandup/zotero-pdf2zh](https://github.com/guaguastandup/zotero-pdf2zh)，保留原作者署名、提交历史和 AGPL-3.0 许可证。以下改动涉及 Python 服务端及插件设置界面。插件版本为 `4.1.8-fork.6`，更新地址指向本 Fork，避免自动更新时覆盖自定义设置。

## 新增修复

1. **翻译失败处理**：任务使用独立输出目录，完整验证本次请求的 PDF 后再发布，避免误取旧文件、误报成功及 `list index out of range`。解析失败时生成 PDF 结构修复副本并重试一次。发布失败会尝试还原旧输出。
2. **PDF 排版与字体**：处理重叠文本检测框、重复字形、首字下沉、部分跨页句子和居中标题；补充短小的旋转文字标签，并按源字体编码恢复遗漏的斜角标签，支持 Type3 和 CID 字体；保留原有简单 TrueType 字体，避免压缩字体时将数字画成错误的字形；纯数字刻度序列保留原有位置和样式。
3. **加粗一致性**：含粗细变化的段落保留源字重，即使请求关闭富文本翻译也保留强调边界；跨页句子前后保持粗体，普通正文维持常规字重。含字重变化的长段落不因超过 40 个占位符而整段丢弃样式。
4. **术语 JSON 兼容**：仅在术语对象完整、响应只缺最后一个数组右括号且严格校验通过时补齐 `]`；其他 JSON 损坏仍保留警告，不猜测或补写术语内容。
5. **参考文献默认保留原文**：新增“翻译参考文献”开关，默认关闭；按章节与分栏识别参考文献，跨页生效，同页正文继续翻译。详见 [设置说明与识别范围](server/doc/reference-translation.md)。
6. **重复翻译加速**：缓存匹配页面的版面检测框，自动校验输入、模型、代码与运行配置；异常缓存回退到重新计算。默认保持原线程策略，另提供可选的 CPU 调参。详见 [性能说明](server/doc/performance.md)。
7. **智谱 LLM API 配置**：新建智谱配置优先填入 `glm-4.5-flash`，补充 `glm-4.7-flash`，内置模型无需先获取列表即可保存。默认地址改为 `https://open.bigmodel.cn/api/paas/v4`，打开或保存配置时修正旧的 `api.zhipu.com/v1` 预设，保留已选模型、密钥及自定义地址。在线模型列表使用官方 `/models` 接口，错误消息支持完整换行显示。

8. **精简服务入口**：新建 API 配置只提供 Zhipu、DeepSeek、Chat Compatible，已有其他服务仍可编辑。主界面只显示激活的 API 配置，2.x 始终保留内置 SiliconFlow Free；停用或删除当前服务时自动回退，移除重复的服务代码输入框。
9. **通用思考开关**：主设置提供全局“启用深度思考”开关，默认关闭，旁注“默认关闭（推荐）”，所有翻译服务共用，不再给每个 API 单独设置。托管的 1.x/2.x 引擎按每次请求设置 GLM、DeepSeek 和常见 Qwen 混合模型的思考参数，覆盖正文翻译及术语提取。未知接口及仅思考模型不强加不支持的参数。此项需同时更新服务端并重启，单独安装 XPI 无法改变旧服务端的请求参数。

10. **API 连通性测试**：API 编辑器增加“测试连通性”，使用当前未保存的地址、密钥与模型发起最小 Chat Completions 请求，显示返回正文和耗时。区分鉴权、额度、限流及超时错误，并保留服务错误码；测试不保存或激活配置，修改表单后旧测试结果自动失效。

11. **OpenCode 网关测试兼容**：连通性测试及模型列表请求访问 `opencode.ai` 时自动附带 `x-opencode-session: zotero-pdf2zh`，与现有翻译端的路由会话头一致，修复网关返回“Request is missing x-opencode-session”的 HTTP 400 错误；其他域名不添加该请求头。

12. **进度窗口与任务取消**：每批任务使用可关闭、可调整大小的独立进度窗口；关闭窗口后后台继续，进度更新不再把窗口弹回来。新增“取消本批次任务”，通过任务 ID 请求服务端停止对应引擎进程及其子进程，并跳过余下文件；取消与失败单独计数。等待任务提交返回期间也可取消，附件导入期间暂禁取消，防止产生半套附件。服务端未确认前继续监视任务，旧服务端不支持时明确提示更新、重启。此项需要更新 XPI 并重启新版服务端。

13. **通用首字下沉修复**：支持字号约为正文 70%–115% 的词尾，包括 TeX 常见的 80% 小型大写字母，以及 `IN` 等两字母开头；按正文基线和字号归一化整个首词，消除间距推断插入的词内空格，避免 `FACIAL` 被拆成首字与公式残片。仅处理正文段首、首字明显放大下沉、词尾与正文同基线的字形，已有公式、上标及标题继续沿用原规则。使用实际 Xue 论文首段的解析、离线中文排版和图片检查验证，无需调用翻译 API。

14. **Fork 发布与更新链接**：插件主页、下载链接、服务端更新源均指向 `xiegaoxiao/zotero-pdf2zh`，保留原作者署名和插件 ID 以支持覆盖更新。统一插件与 Server 版本，移除源码树中的旧 XPI 和静态 `server.zip`；发布时从 Git 跟踪的源码生成干净附件，校验 XPI manifest、版本、下载 URL 和哈希。版本 Release 使用固定附件名 `zotero-pdf-2-zh.xpi` / `server.zip`，`release` 标签仅提供更新清单，不作为最新版本。安装与下载应使用本 Fork 的 [最新 Release](https://github.com/xiegaoxiao/zotero-pdf2zh/releases/latest)。

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
python -m unittest discover -s tests -p test_layout_performance.py -v
python -m unittest discover -s tests -p test_task_cancellation.py -v
```

以上回归测试不需要调用翻译 API。版面缓存测试需使用安装了 NumPy、ONNX Runtime 和 BabelDOC 的托管引擎环境。中文字体相关的一项测试在缺少 BabelDOC 缓存字体时跳过。数字字体及斜角 Type3 标签测试使用自行生成的合成字形文件，未分发个人论文或第三方字体。插件在 `plugin` 目录运行 `npm ci`、`npm test` 和 `npm run build`；XPI 位于 `plugin/build/`，可通过 Zotero 插件管理器“从文件安装插件”安装。

## 与上游同步

原项目 README 当前包含重构期间暂不接收贡献的公告，因此本 Fork 暂时独立维护，未向上游提交 PR。可先 `git fetch upstream`，检查差异后在开发分支合并更新并运行相关测试。直接使用上游发布包或自动更新可能覆盖本分支的服务端修改。

个人配置、API 密钥、运行日志、虚拟环境和译文不属于本 Fork 的提交内容。新增的 `.gitignore` 规则排除本地运行目录，配置模板仍沿用原项目的示例文件。
