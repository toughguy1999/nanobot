# 主 Agent 当前上下文

在项目根目录，用 PowerShell 开启上下文查看，再按平时的方式启动主 Agent：

```powershell
$env:NANOBOT_LLM_CONTEXT = "1"
uv run nanobot gateway
```

也支持 `uv run nanobot agent`。环境变量需要设置在启动 Agent 的终端中。

另开终端，在项目根目录启动查看器：

```powershell
uv run python devtools/llm_viewer.py
```

打开 http://127.0.0.1:8766 。页面只展示一个 JSON 对象：

```json
{
  "model": "模型名称",
  "messages": [
    {"role": "system", "content": "系统提示词"},
    {"role": "user", "content": "用户消息"}
  ],
  "tools": []
}
```

- 主 Agent 调用 Provider 前、模型回复加入上下文后、每个工具结果加入上下文后，都会发布最新完整上下文。页面每 500 毫秒刷新，新内容替换旧内容；最终回复无需等待下一次调用即可展示。
- 默认以可读形式展示字符串：换行、制表符、引号和反斜杠按实际内容显示。保留 JSON 的层级外观，但该视图不是严格 JSON；勾选“原始 JSON”可查看标准 JSON 转义形式。不会再次解码文本中本来就存在的字面量反斜杠，也不会改写上下文数据。
- 仅覆盖主 Agent `_run_turn`，包括工具执行后的后续调用和后台任务回到主 Agent 后的调用。不采集子 Agent 和记忆整理。
- 模型调用仍在主 Agent 中执行；开发者模块仅发布上下文，不调用模型。
- `.nanobot/debug/context.json` 是查看器读取的最新快照，每次覆盖，不追加调用历史，不记录独立响应、调用 ID 或时间。先写临时文件再替换，避免页面读到未完成的 JSON。
- 展示的是主 Agent 当前的 messages、model 和 tools，不包含 Provider 内部追加的参数或最终 HTTP 报文。模型完整返回后即发布更新，仍使用现有非流式模型调用。
- 页面也会显示上次运行留下的快照，直到下一次主 Agent 调用覆盖它。多个主 Agent 共用此文件时展示最近发布的上下文。
- 关闭功能：启动 Agent 前执行 `$env:NANOBOT_LLM_CONTEXT = "0"`。旧开关 `NANOBOT_LLM_TRACE` 已移除；旧版 JSONL 文件不再读取或写入。
