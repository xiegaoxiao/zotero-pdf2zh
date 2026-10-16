# 翻译失败后误报成功与列表越界修复

## 启动时报 `cannot import name 'BitStream'`

BabelDOC 0.6.2 使用 `from bitstring import BitStream`，但其依赖只声明
`bitstring>=4.3.0`。bitstring 5 已移除 `BitStream`，新装或更新环境可能因此在
引擎导入阶段退出，尚未读取 PDF 或调用翻译接口。参见
[bitstring 5 官方迁移说明](https://bitstring.readthedocs.io/en/latest/upgrading_to_version_5.html#replace-stream-classes-with-reader)。

在 PowerShell 中进入自己的 `server` 目录，使用日志里同一个翻译环境执行：

```powershell
uv pip install --python .\zotero-pdf2zh-next-venv\Scripts\python.exe --reinstall "bitstring>=4.3.0,<5"
.\zotero-pdf2zh-next-venv\Scripts\python.exe -I -c "from bitstring import BitStream; assert BitStream('0xff').read('uint:8') == 255; print('BitStream OK')"
```

第二条命令输出 `BitStream OK` 后，重启服务并重试翻译。Conda 用户应将 Python
路径改为实际 Conda 翻译环境的 `python.exe`，使用该解释器的
`-I -m pip install --force-reinstall "bitstring>=4.3.0,<5"`。

仓库的 uv/Conda 配置模板已增加兼容范围，启动配置迁移会同步到旧配置并保留用户额外依赖。
启动前及安装后的健康检查会验证 `BitStream` 的实际读取功能，失败时进入已有依赖修复流程，
不会仅凭包版本元数据宣布环境可用。请同时更新服务端源码，避免旧版更新脚本再次安装不兼容版本。

## 问题

引擎报告 `Babeldoc translation error: New` 后，服务仍打印 mono 文件生成成功，随后读取 `retList[1]` 时出现 `list index out of range`。

有两个原因：

1. 部分 PDF 的嵌入内容流含有非法指令，导致解析在翻译前失败。本地复现样本含有无对应资源的 `/F1-Times New\nRoman-arrowup\nDo`。
2. 上游 CLI 忽略单文件错误时可能仍以退出码 0 结束。原服务仅检查公共输出目录中的文件，会误取之前的 mono；如果本次所需的 dual 不存在，返回列表只有一项，后续索引越界。

## 修复

- 每个任务在独立临时目录生成新译文，旧文件不作为本次成功证据。
- 缺少所需输出或子进程非零退出时，创建原 PDF 的结构净化副本并重试一次；重试前清除当前尝试的半成品。
- 所有请求的 PDF 必须存在、非空、可读取且至少有一页，才发布到公共目录；只请求 mono 时不要求 dual。
- 非零退出不会因已有文件而被误报为成功。
- 发布失败时尝试回滚旧文件；不完整返回值提供明确错误，避免列表越界。

实现位于 `server.py` 和 `utils/translation_outputs.py`，回归测试位于 `tests/test_translation_output_isolation.py`。8 项测试覆盖旧文件、半成品、重试、子进程失败、单输出请求、发布回滚及无效 PDF，不需要翻译 API。

本地另用实际解析失败样本验证了首次失败、结构修复、重试成功的完整流程；新 mono 和 dual 均可读取，旧译文保留。该样本、译文、日志及个人配置不随源码分发。

重启服务后生效，无需重新安装插件 XPI。结构修复并非对任意损坏 PDF 都有效，重试仍失败时会保留原件和旧译文并报告错误。

## 自动术语提取的 JSON 警告

`automatic_term_extractor.py` 的 `Expecting ',' delimiter` 表示术语响应不能按 JSON 读取。复核实际响应发现，部分术语对象完整，但外围数组缺少最后一个 `]`，导致对应批次的术语被跳过；正文翻译仍可能成功，术语一致性可能受影响。

`utils/term_json_repair.py` 仅在原解析错误位于响应末尾、补上一个 `]` 后可严格解析、且所有条目均含非空字符串 `src` 和 `tgt` 时进行恢复。不会补写词语、双引号或对象括号，也不会删除损坏条目；其他问题继续保留上游警告。安装器将此处理接入 BabelDOC 的术语 JSON 清洗方法。

新增 8 项测试覆盖正确 JSON、单个缺失的数组括号、不完整词语、不完整对象、内部引号错误、非法条目、字符串内括号和额外解释文字。另用实际响应离线回放验证了恢复结果及完整条目数量；原响应、缓存和个人配置不随源码分发。

补丁从下一次启动的翻译进程生效，当前已完成术语提取的任务不会自动重做；已有缓存无需清除。不更改 API 配置，也不额外请求模型。
