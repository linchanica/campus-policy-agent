# 珞策 学生政策咨询智能体

微信小程序和网页共用的本地项目。已实现政策检索、条件核对、多轮画像确认、可定位原文、管理与审核工作台、版本发布/回滚、微信登录适配与跨端绑定、内部人工接待闭环。

当前为本地试用系统，完整技术方案仍有校方认证、生产配置、全面事实核验及真实客户端/业务验收待完成。详见 [操作与验收步骤](docs/本地验收与上线接续.md)、[实施报告](docs/实施状态与运行报告.md)、[60项任务追踪](docs/任务实施追踪.md) 和 [资源台账](docs/资源台账.json)。

## 当前运行方式

在本项目目录执行：

```powershell
& .\scripts\Start.ps1
```

学生入口 http://127.0.0.1:8000；管理入口 http://127.0.0.1:8000/admin/；接口文档 http://127.0.0.1:8000/docs。服务只绑定本机，不向公网开放。

停止服务：`./scripts/Stop.ps1`。重启时分别运行停止和启动命令。访客凭证有效期24小时，可退出或清空本人咨询。退出仅撤销当前设备凭证；微信身份可重新登录，匿名访客不能通过新访客身份找回记录。管理一次性登录码30分钟内一次有效，登录会话8小时。本地维护者不具有学校正式审核权限。

## 当前模型

- 嵌入：BAAI/bge-small-zh-v1.5，通过 ONNX CPU 在本地运行。93 个去重后的学生事项条款片段，结合 BM25 检索；Qdrant 嵌入式本地索引用于存储，当前小规模查询使用同一快照的内存向量矩阵。
- 生成模型：Qwen2.5-0.5B-Instruct，本地CPU加载。选择检索原文，以及从有逐字证据的类型化画像选项中选择一条候选。候选必须由学生在资料面板确认；模型不自由补写资格或截止日期。首次加载较慢。
- 画像与规则：本人明确陈述、逐字证据校验、否定/条件/他人过滤、学生表单确认、三态规则与时间核对。0.5B自由生成JSON不稳定，因此使用受限选择和表单兜底，不宣称复杂理解准确率。
- 云端模型按用户最新要求暂不切换、当前问答不启用外部调用。可选模型配置保留在本机服务端；不要填入前端变量、提交密钥或复用Codex登录凭证。未来启用需另行完成接口适配、学生数据发送同意与专项评测。

轻量本地模型是开发实验方案，不能等同于强模型问答能力或学校业务审批。完整自然语言抽取和更复杂事项仍需持续评测。

嵌入固定为Qdrant ONNX仓库修订`46fbe35fd4374a00fee7de77dfddaeb6dd6a2c59`；Qwen固定为`7ae557604adf67be50417f59c2c2f167def9a775`。查询时从本地缓存加载，模型下载不发送政策正文或学生问题。

## 数据与审核

45 份文件已提取文本，包含7份保留原件并另存转换的 DOC。重复内容合并为检索片段，但原件映射保留。招聘任免等首期范围外文件不向学生接口开放。

所有政策副本和当前规则均标为待业务复核。完整材料附件缺失、日期边界与文号差异均显示为待确认。生产环境启动被明确阻止，防止把本地原型误当成已审核的校园服务。

## 微信小程序

源码：`frontend/student/src`，真实构建产物：`frontend/student/dist/build/mp-weixin`。AppID `wx819a8152776e26fa` 已写入源码和编译配置；用户已在本机保存AppSecret。开发工具已导入并恢复模拟器首页，真实wx.login/code交换、原生请求、咨询及登记表下载哈希通过；按钮完整路径、手机真机和正式发布仍待验收。

服务端微信code交换与本人一次性跨端绑定已实现，未配置时明确不可用。下一步设置手机可达的HTTPS API、配置平台网络域名并完成真机联调。127.0.0.1在手机上指手机自己，不能用作手机访问电脑的正式地址。微信身份不证明学籍或学校工作人员权限。

## 管理与人工接待

用户已有本地项目维护者角色。登录管理台后可编辑草稿、上传/校正原件、记录试用复核、编辑版本规则卡、构建并发布试用快照、回滚和检查审计。正式候选需要已验证学校身份的独立审核，当前不具备。

内部人工队列支持明确同意、接收方核对、幂等提交、经办受理与答复、学生回执和撤回。真实接待人尚未确认，当前保持关闭；不会自动向微信、邮件或老师发送消息。详见 [完整操作步骤](docs/本地验收与上线接续.md)。

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
& .\.venv\Scripts\python.exe scripts/verify_release_recovery.py
& .\.venv\Scripts\python.exe scripts/smoke_profile_model.py
```

自动评测覆盖80个检索、已编码规则、日期与边界用例；不等于人工审核正确率或小程序真机验收。详见 `evals/evaluation.json` 与交付运行报告。

## WorkBuddy 与 MCP

技能源文件为 `skills/policy-guide/SKILL.md`。`app.mcp_server` 提供5个工具，可通过 stdio 连接。项目 `.workbuddy/mcp.json` 使用本机实际解释器路径，不含密钥。工具协议测试与 WorkBuddy 客户端实际连接是两项独立验收；目前客户端未安装或未接入，不声称已完成。

迁移目录后重新运行 `scripts/configure_workbuddy.py`。接入与验证题见 [WorkBuddy接入说明](docs/WorkBuddy接入与专家说明.md)。

## 尚需外部落实

政策业务审核、缺失材料清单、手机可达HTTPS环境、学校身份协议、真实接待人、微信开发者工具/真机及WorkBuddy客户端。小程序账号、AppID和本机AppSecret配置已就绪。

学校SSO适配、生产身份与配置需按校方实际协议继续实施；全部事实/数字核验、广泛模型评测、生产容量及告警也尚未完成。管理审核、试用快照原子发布/历史版本、内部队列和匿名保留清理已实现。浏览器完整操作、微信真机和WorkBuddy客户端仍需实际验收；自动电脑控制因无法可靠确认浏览器URL已停止，没有绕过安全检查。

微信专项验证与复现步骤见 [模拟器联调](tools/wechat-qa/README.md)。修复过WXSS通配选择器导致的白屏，现已加入官方WXML/WXSS原生语法检查；uni-app构建通过不能单独当作微信运行通过。
