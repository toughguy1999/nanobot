# nanobot-enhanced

基于 [HKUDS/nanobot](https://github.com/HKUDS/nanobot) 扩展的个人 AI Agent 全栈实践项目。围绕浏览器交互、工具执行、上下文管理和本地知识库检索，探索从模型调用到应用交互的完整开发链路。

后端使用 Python、FastAPI 和 asyncio，前端使用 TypeScript、React 和 Next.js。本项目处于本地开发与验证阶段。

## 原项目基础与本项目贡献

原项目提供 Agent 循环、多模型 Provider、CLI、基础工具、子 Agent、定时任务、Heartbeat 和聊天渠道接入。本仓库在这些基础上新增或重构以下模块：

| 方向 | 本项目的增强内容 | 主要代码 |
| --- | --- | --- |
| Web 全栈交互 | 新增浏览器对话界面、会话管理、附件上传、推理与工具调用过程展示；拆分 Web 业务服务，统一 HTTP 历史与 WebSocket 实时消息的数据格式 | [web/](web/)、[webservice/](nanobot/webservice/)、[Web 渠道](nanobot/channels/web.py) |
| 工具调度 | 为主 Agent 和子 Agent 增加受限并发、串行屏障、单工具异常隔离及有序结果回填 | [scheduler.py](nanobot/harness/tools/scheduler.py)、[registry.py](nanobot/harness/tools/registry.py) |
| 上下文管理 | 增加工具结果裁剪、旧工具结果与推理清理、阈值触发的历史摘要；重构会话记录与上下文投影 | [compress/](nanobot/harness/compress/)、[session/](nanobot/harness/session/) |
| 记忆与 Skills | 改为注入记忆索引、按需读取主题正文；注入技能摘要，通过工具加载技能正文 | [context.py](nanobot/harness/context.py)、[skills.py](nanobot/harness/skills.py) |
| 本地 RAG | 新增文档切分、稠密与稀疏检索、加权 RRF 融合、模型重排及 Agent 检索工具 | [rag/](nanobot/rag/)、[检索工具](nanobot/harness/tools/rag.py) |
| 本地 MCP | 新增 stdio Python MCP 服务管理、工具发现、调用与结果归一化 | [mcp/](nanobot/mcp/)、[工具适配器](nanobot/harness/tools/mcp.py) |
| 状态与调试 | 增加会话 Todo、本轮计时与状态快照，以及主 Agent 上下文查看器；将网络搜索切换为 Tavily | [status.py](nanobot/harness/status.py)、[devtools/](devtools/)、[web.py](nanobot/harness/tools/web.py) |

## 关键设计

- **并发执行与历史顺序分离：**只有显式声明 `isConcurrencySafe` 的相邻工具调用才并发执行，每个 Agent 默认上限为 4。Shell、文件修改、MCP 等调用形成串行屏障；普通工具失败不阻断同批其他调用，结果始终按模型调用顺序写回。
- **原始记录与模型上下文分离：**会话使用 JSONL 持久化，历史清理与摘要作用于模型可见的投影，不覆盖原始聊天记录。摘要保留完整工具调用与结果组，失败时继续使用已有投影。历史清理与摘要目前仅用于主 Agent。
- **前后端共享消息身份：**使用稳定消息 ID 合并前端乐观更新、WebSocket 事件和 HTTP 历史记录，处理重复展示与消息状态同步。WebSocket 推送阶段消息和最终回复，当前模型调用并非逐 token 流式输出。
- **按需提供上下文：**主 Agent 每轮读取记忆索引，主题正文按需读取；Skills 默认提供名称和描述，正文通过 `load_skill` 加载，避免一次性注入全部内容。
- **混合检索：**使用 BGE-M3 生成稠密与稀疏向量，分别存入 ChromaDB 与 SQLite，经加权 RRF 融合后使用 Reranker 重排，再将片段返回给 Agent。

完整模块关系与执行流程见 [架构文档](docs/architecture.md)。

## 本地运行

需要 Python 3.11+、uv；运行 Web 前端还需 Node.js 20+ 和 pnpm。以下命令以 PowerShell 为例。

### 1. 获取代码并安装依赖

```powershell
git clone https://github.com/toughguy1999/nanobot.git nanobot-enhanced
cd nanobot-enhanced
uv sync
```

默认依赖包含 RAG 使用的 PyTorch、FlagEmbedding 和 ChromaDB，首次安装体积较大。本仓库的增强功能请从源码运行。

### 2. 初始化并配置模型

```powershell
$env:NANOBOT_HOME = (Get-Location).Path
uv run nanobot onboard
```

设置 `NANOBOT_HOME` 后，配置位于该目录的 `.nanobot/config.json`，默认工作区位于 `.nanobot/workspace`。不设置时使用用户主目录。后续启动后端、RAG 命令和调试工具的终端应设置相同的 `NANOBOT_HOME`。

编辑生成的配置，将以下字段合并进去。模型名替换为所用服务支持且具备工具调用能力的模型，密钥自行填写：

```json
{
  "providers": {
    "openrouter": {
      "apiKey": "YOUR_API_KEY"
    }
  },
  "agents": {
    "defaults": {
      "model": "YOUR_MODEL_ID"
    }
  },
  "channels": {
    "web": {
      "enabled": true,
      "host": "127.0.0.1",
      "port": 8765
    }
  }
}
```

也可配置其他 Provider，或通过 `vllm` 的 `apiBase` 接入兼容接口的本地服务。支持项与字段见 [配置模型](nanobot/config/schema.py) 和 [Provider 注册表](nanobot/providers/registry.py)。

### 3. 启动对话

命令行直接使用：

```powershell
uv run nanobot agent -m "你好，请介绍你能使用的工具"
# 或进入交互模式
uv run nanobot agent
```

浏览器使用需要两个终端。在项目根目录启动后端：

```powershell
$env:NANOBOT_HOME = (Get-Location).Path
uv run nanobot gateway
```

另一个终端在 `web/` 目录启动前端：

```powershell
pnpm install
pnpm dev
```

打开 [http://localhost:3000](http://localhost:3000)。前端默认连接 `http://localhost:8765` 和 `ws://localhost:8765/ws`。如需修改，在 `web/.env.local` 设置 `NEXT_PUBLIC_NANOBOT_HTTP_URL` 与 `NEXT_PUBLIC_NANOBOT_WS_URL`，并相应调整后端的 `channels.web.corsOrigins`。

## 可选能力配置

| 能力 | 使用方式 |
| --- | --- |
| 网络搜索 | 在配置中填写 `tools.web.search.apiKey`，或设置环境变量 `TAVILY_API_KEY`；显式配置优先，修改后重启后端 |
| 工具并发 | `tools.maxConcurrency` 设置每个 Agent 的工具并发上限，默认 4；仅对显式允许并发的工具生效 |
| 上下文压缩 | `agents.defaults.maxToolResultTokens` 控制工具结果预算；`agents.defaults.historyCompression` 配置清理、摘要阈值与摘要模型 |
| 长期记忆 | 工作区中的 `memory/MEMORY.md` 存放索引，主题 Markdown 文件存放正文；写入行为由提示词规则约束 |
| 自定义 Skills | 在工作区 `skills/` 下添加技能；同名工作区技能覆盖内置技能 |
| 上下文查看 | 按 [调试工具说明](devtools/README.md) 开启快照并运行本地查看器 |

### 本地知识库

在上述 `NANOBOT_HOME` 设置下，将 `.md` 或 `.txt` 资料放入项目根目录的 `rag-test/source/`，然后执行：

```powershell
uv run nanobot rag init
```

该命令重建知识库索引，首次使用会下载 Embedding 和 Reranker 模型。当前以小说知识库为实验场景，工具名为 `absurd_novel_knowledge_search`。模型、切分、融合权重和设备设置集中在 [RAG 配置](nanobot/rag/config.py)；默认使用 CUDA，无可用 CUDA 设备时需调整设备及精度设置。

### 本地 MCP

在配置中添加本地 Python 服务：

```json
{
  "mcp": {
    "servers": [
      {
        "name": "weather",
        "path": "mcp_test/server.py",
        "enabled": true
      }
    ]
  }
}
```

`path` 必须指向 `NANOBOT_HOME` 内实际存在的 `.py` 文件，使用相对路径。修改后重启后端。当前支持本地 stdio 工具，尚未实现远程传输、热重载或自动重连。

## 聊天渠道（Chat Apps）

保留上游的 Telegram、Discord、WhatsApp、飞书、Mochat、钉钉、Slack、Email 和 QQ 适配器。它们通过统一消息总线接入 Agent，本项目的交互开发重点是 Web 客户端。

接入时在 `channels.<渠道名>` 下启用渠道并填写凭据，再运行 `uv run nanobot gateway`；使用 `uv run nanobot channels status` 查看配置状态。WhatsApp 还需通过 `uv run nanobot channels login` 连接桥接服务。

平台注册与权限设置参考 [上游接入指南](https://github.com/HKUDS/nanobot#-chat-apps)，本仓库的具体配置字段以 [schema.py](nanobot/config/schema.py) 为准。各渠道的允许用户策略应按对应配置设置。

## 项目结构

```text
nanobot/
├── harness/       # Agent 循环、上下文、工具、子 Agent、压缩与会话存储
├── webservice/    # 会话、消息、附件等 Web 业务逻辑
├── channels/      # Web 与聊天平台适配
├── providers/     # 模型 Provider 与 LiteLLM 适配
├── rag/           # 切分、向量化、索引、融合与重排
├── mcp/           # 本地 MCP 服务生命周期与结果处理
├── bus/           # 异步消息总线
├── config/        # 配置模型与加载
├── cli/           # 命令行入口与运行时组装
├── skills/        # 内置技能
├── cron/          # 定时任务
└── heartbeat/     # 周期唤醒
web/               # Next.js 前端，测试位于 web/test/
tests/             # Python 行为测试
bridge/            # WhatsApp Node.js 桥接服务
devtools/          # 主 Agent 上下文查看器
docs/              # 架构与设计文档
```

## 开发与验证

后端使用 uv 管理依赖，前端使用 pnpm。现有测试覆盖工具调度、上下文压缩、记忆与技能加载、消息一致性及部分前端交互。

```powershell
# 项目根目录：后端测试
uv run python -m unittest discover -s tests
```

```powershell
# web/ 目录：前端检查
pnpm test
pnpm lint
pnpm typecheck
pnpm build
```

测试与实现代码不等同于真实模型或外部服务的验证结果。目前不宣称未经评测的性能提升、检索准确率或生产环境可靠性。后续计划补充完整场景演示、固定问题集检索评测，以及工具串并行和上下文压缩的可复现实验。

当前主要面向本地使用。`tools.restrictToWorkspace` 提供文件路径与 Shell 检查，不是进程沙箱，也不隔离本地 MCP 服务。

## 致谢与许可证

感谢 [HKUDS/nanobot](https://github.com/HKUDS/nanobot) 提供的基础实现。本仓库基于其继续开发，遵循 [MIT 许可证](LICENSE)。
