# 珞策 学生政策咨询智能体

微信小程序和网页共用的本地项目。已实现真实政策文本、中文语义检索、条件对照、多轮资料补充、可定位原文、申请时限核对、会话隔离、任务幂等与人工咨询草稿。

当前是可运行的本地原型。完整技术方案仍有待开发与待验收部分，详见 [实施报告](docs/实施状态与运行报告.md)、[60项任务追踪](docs/任务实施追踪.md) 和 [资源台账](docs/资源台账.json)。

## 当前运行方式

在本项目目录执行：

```powershell
& .\scripts\Start.ps1
```

浏览器打开 http://127.0.0.1:8000。接口文档为 http://127.0.0.1:8000/docs。服务只绑定本机，不向公网开放。

停止服务：`./scripts/Stop.ps1`。需要重启时分别运行停止和启动命令。本地访客凭证有效期24小时，可在试用说明中退出或清空本人咨询。退出会撤销凭证，旧身份记录不能通过新身份找回。正式身份和自动保留清理尚未落实，演示使用虚构资料。

## 当前模型

- 嵌入：BAAI/bge-small-zh-v1.5，通过 ONNX CPU 在本地运行。93 个去重后的学生事项条款片段，结合 BM25 检索；Qdrant 嵌入式本地索引用于存储，当前小规模查询使用同一快照的内存向量矩阵。
- 生成模型实验路径：Qwen2.5-0.5B-Instruct，本地 CPU 加载。用于从检索候选选择证据，服务端只展示被选原文。不会让小模型自由补写资格或截止日期。首次加载较慢。
- 画像与规则：明确事实的结构化提取、学生表单确认、三态规则和时间程序核对。
- 可另配学校允许的模型接口：在 `.env` 填 LLM_BASE_URL（含 /v1）、LLM_MODEL、LLM_API_KEY。不要提交密钥。外部接口未配置时不向外部模型发送问题和资料。

轻量本地模型是开发实验方案，不能等同于强模型问答能力或学校业务审批。完整自然语言抽取和更复杂事项仍需持续评测。

嵌入固定为Qdrant ONNX仓库修订`46fbe35fd4374a00fee7de77dfddaeb6dd6a2c59`；Qwen固定为`7ae557604adf67be50417f59c2c2f167def9a775`。查询时从本地缓存加载，模型下载不发送政策正文或学生问题。

## 数据与审核

45 份文件已提取文本，包含7份保留原件并另存转换的 DOC。重复内容合并为检索片段，但原件映射保留。招聘任免等首期范围外文件不向学生接口开放。

所有政策副本和当前规则均标为待业务复核。完整材料附件缺失、日期边界与文号差异均显示为待确认。生产环境启动被明确阻止，防止把本地原型误当成已审核的校园服务。

## 微信小程序

源码：`frontend/student/src`，构建产物：`frontend/student/dist/build/mp-weixin`。这是实际编译的小程序工程，尚无真实 AppID、开发者登录、真机或正式发布记录。

后续在 `manifest.json` 填学校或团队的小程序 AppID，在前端环境中填手机可达的 HTTPS API 地址，再按平台要求配置请求和下载域名。127.0.0.1 指手机自己，不能用作手机访问电脑的正式地址。微信登录接口当前明确返回未配置，不冒充真实登录。

## 依赖与重建

当前已在本目录创建 `.venv`，Python 依赖锁定于 `requirements.lock.txt`；前端使用锁定的 pnpm 工程和 `pnpm-lock.yaml`。新机器先安装兼容的 Python、Node 和 pnpm，再执行：

```powershell
python -m venv .venv
& .\.venv\Scripts\python.exe -m pip install -r requirements.lock.txt
& .\.venv\Scripts\python.exe -m app.cli doctor
```

实际验证环境是Windows、Python3.13.4、Node24.22.1、pnpm11.25.0。此锁文件含Windows依赖；其他系统尚未安装验证。使用已编译网页及小程序产物时不必先重建前端。

分发包不含模型、索引或虚拟环境。新Windows机器也可直接运行 `./scripts/Setup.ps1 -DownloadModels`：安装锁定依赖、下载固定模型、建立语义索引并生成MCP配置，需要可达的包和模型下载网络。大型模型依赖与权重需要足够磁盘空间。省略DownloadModels时仅建立字符基线索引，不能称为已接入语义模型。

手动恢复模型：

```powershell
& .\.venv\Scripts\python.exe scripts/download_local_model.py
& .\.venv\Scripts\python.exe -m app.cli index --semantic
& .\.venv\Scripts\python.exe scripts/configure_workbuddy.py
```

前端：

```powershell
cd frontend/student
pnpm install --frozen-lockfile
pnpm run typecheck
pnpm run build:h5
pnpm run build:mp-weixin
```

## 测试与管理

```powershell
& .\.venv\Scripts\python.exe -m pytest tests -q
& .\.venv\Scripts\python.exe -m app.cli evaluate
& .\.venv\Scripts\python.exe -m app.cli export-openapi
& .\.venv\Scripts\python.exe -m app.cli backup
& .\.venv\Scripts\python.exe -m app.cli restore-check
& .\.venv\Scripts\python.exe scripts/smoke_live.py
& .\.venv\Scripts\python.exe scripts/smoke_mcp.py
& .\.venv\Scripts\python.exe -m app.cli review-export
```

自动评测覆盖80个检索、已编码规则、日期与边界用例；不等于人工审核正确率或小程序真机验收。详见 `evals/evaluation.json` 与交付运行报告。

## WorkBuddy 与 MCP

技能源文件为 `skills/policy-guide/SKILL.md`。`app.mcp_server` 提供5个工具，可通过 stdio 连接。项目 `.workbuddy/mcp.json` 使用本机实际解释器路径，不含密钥。工具协议测试与 WorkBuddy 客户端实际连接是两项独立验收；目前客户端未安装或未接入，不声称已完成。

迁移目录后重新运行 `scripts/configure_workbuddy.py`。接入与验证题见 [WorkBuddy接入说明](docs/WorkBuddy接入与专家说明.md)。

## 尚需外部落实

政策业务审核、缺失材料清单、真实小程序账号与 AppID、可供手机访问的测试或正式域名、学校认可的正式身份方案，以及真实人工接待渠道。项目现在只生成咨询草稿，不自动向老师发送信息。

尚需技术开发的部分包括完整LLM画像抽取、审核管理与原子发布/历史版本、正式认证与绑定、数据保留自动清理、生产监控及真实工单适配。浏览器界面、微信真机和WorkBuddy客户端尚未完成实际操作验收，详见 [运维与发布操作](docs/运维与发布操作.md)。
