# GitHub私有仓库协作说明

准备日期：2026-10-31。用户已选择GitHub，已有账号，并提供目标仓库 `https://github.com/linchanica/campus-policy-agent`。本文为协作操作说明，是否完成关联和上传以实际验证结果为准。

GitHub Free支持私有仓库及多人协作，当前仅使用代码托管，不开通付费套餐或额外计算服务。官方说明：[仓库与协作](https://docs.github.com/en/repositories/creating-and-managing-repositories/about-repositories)。

## 1. 在本人账号下创建空私有仓库

打开 <https://github.com/new>，确认Owner是你本人或已获授权的团队。

- Repository name：`campus-policy-agent`。
- Description：可填写“校院政策咨询智能体”。
- Visibility：选择 **Private**。
- 不初始化README、.gitignore或License，本地工程已有文件和提交历史。
- 点击Create repository。

创建后复制仓库网页地址，例如 `https://github.com/你的用户名/campus-policy-agent`。不要复制带令牌的地址，不发送密码、验证码或访问令牌。

官方流程：[将现有本地代码添加到GitHub](https://docs.github.com/en/migrations/importing-source-code/using-the-command-line-to-import-source-code/adding-locally-hosted-code-to-github)。

## 2. 关联现有工程

本机Git仓库位于：

```text
C:\Users\asus\Documents\Codex\2026-10-30\llm-rag-agent-nlp-agent\outputs\policy-agent
```

已有main分支和本地版本历史，不需要重新git init，不需要把整个上级Documents目录上传。收到实际仓库地址后再执行关联和推送；下面只是流程示意，不要直接使用占位用户名：

```text
git remote add origin https://github.com/linchanica/campus-policy-agent.git
git push -u origin main
```

首次上传前核对目标仓库确实为Private。若需要GitHub登录或授权，由本人在官方网页或本机凭据窗口完成；不要将密码或令牌粘贴到聊天、源码或远程URL中。若仓库已经存在文件，先检查历史差异，不使用force push覆盖。

## 3. 本次上传范围

Git记录源码、配置模板、整理后的政策文本与清单、测试、文档和必要工具文件。当前.gitignore排除了：

- 真实.env、本机工作目录、登录码和运行数据库。
- 模型缓存、Python虚拟环境、node_modules。
- 原始政策二进制文件和转换缓存。
- 本机MCP配置及学生端生成目录。

因此，克隆仓库可以取得源码历史，但不会自动取得模型、原始政策附件、微信密钥或已经编译的小程序。协作者需按README安装依赖并构建前端；模型和政策原件可从现有部署资源包准备。

本次检查覆盖183个跟踪文件、9次提交及240个历史blob；当前已配置的密钥值未出现在这些内容中，未发现禁止上传的运行文件或超过50MiB的历史blob。此检查只说明所覆盖项目的结果，不保证识别一切未知凭证。检查原始报告保留在被忽略的work/git-export-check.json。

## 4. 邀请共同开发者

仓库创建并上传成功后，进入仓库Settings → Collaborators，按实际页面提示添加同学的GitHub用户名，由对方接受邀请。

GitHub协作者与微信小程序开发者是两套权限：需要上传或调试微信项目的同学，还需在微信公众平台配置对应成员权限。不要共享管理员账号。

官方说明：[邀请个人仓库协作者](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/repository-access-and-collaboration/inviting-collaborators-to-a-personal-repository)。

## 5. 团队日常版本流程

协作者接受仓库邀请后，在自己的电脑克隆：

```text
git clone https://github.com/linchanica/campus-policy-agent.git
cd campus-policy-agent
```

建议约定main保存可运行版本，每人从最新main建立自己的功能分支，例如 `feature/profile-form`，修改后提交并推送，通过Pull Request说明改动和验证结果，再合并。

这是一项团队协作约定，不表示免费私有仓库已配置强制审核或分支保护。成员在自己电脑配置本人Git作者信息，不沿用工具作者身份。

需要复现旧版时，按提交记录、标签或分支取出对应源码，再按该版本要求准备依赖、模型和数据。微信后台的版本编号不会自动替代Git提交历史。

## 6. 运行资源与版本对应

已有含模型部署包是一个经隔离验收的本地试用快照，其版本可能早于Git当前main。不要把整个旧部署包解压覆盖刚克隆的最新源码；需要时仅按对应说明恢复原件、模型和索引，再核对与当前代码的兼容性。

原件下载、模型加载和咨询均需要后端运行。代码托管不提供当前Python后端的自动部署，暂不注册云资源的决定保持不变。
