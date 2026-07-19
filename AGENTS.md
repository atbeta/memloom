## Learned User Preferences

- 用户偏好用中文回复
- Dashboard 目标是替代 AnythingLLM 的核心使用面（知识库浏览/检索 + 采集/管道运维），不做站内聊天
- 产品形态按运维台（C）设计，实现过复杂时可回退到只读 status/search/inspect（A）
- 设置：常用项用表单，高级配置仍改 YAML；部署按内网可信，管理面可弱鉴权
- Memloom MCP 先只接入 openclaw-coder；优先独立 `:8789/mcp`，不要进 mcp-search（`:8812`）
- 开发节奏：可直接提交并继续推进，最后再一起验收；界面阶段性够用即可，不必过度打磨
- 鉴权方向：上报/写入宜宽松（独立 ingest key），检索/MCP/管理宜收紧；主动采集（pull）与上报（push）都要支持

## Learned Workspace Facts

- Memloom 是统一 agent 记忆采集 + 本地知识库：CLI 采集/同步，`memloom serve` 提供 ingest、MCP（`search_memory`）、admin API 与同进程托管的 dashboard SPA
- 家用权威运行时在 101 `/opt/memloom`，用 PyPI 包部署（非本机源码挂载）；Dashboard 默认 `http://192.168.5.101:8789/`
- 101 上通常有 `memloom-server`（服务）与 `memloom-collect`（循环 collect→push→sleep）；LibreChat「一直有 run」多为重扫旧库去重（`new: 0` / 高 `dup`），不代表有新对话
- 当前 101 采集配置以 `host: local` 为主；openclaw 路径若未挂进 collect 容器则 discovered 会一直为 0
- hz.pnb.pub 与 Mac Studio 的远端上报/sync 尚未落地；远端宜走 push → `POST /ingest`，Server 留在 101 作权威库
- Admin 路由为 `/api/admin/...`，与 ingest 分路同进程；Gemini 那套虚构 `/api/v1` / MCP 流水 / Vim YAML 方案已作废重做
