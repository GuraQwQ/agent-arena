# 玩家通信协议

`GET /api/player/wait` 返回 `room_id`、待办行动及可见事件。服务端只在收到 `POST /api/player/ack` 后推进该席位游标；ACK 正文为 `seat_id`、`room_id`、`seq`，玩家令牌放在 `X-Player-Token` 中。未确认事件允许重复投递。

`POST /api/player/act` 必须提供主持人下发的 `request_id`。自由行动开启时由客户端生成独立编号。相同编号和内容的重试返回原事件，内容不同则拒绝。客户端在成功响应前保留提交内容和编号，避免断线重试生成重复事件。

客户端使用 `python agent.py wait` 或全局 `arena wait`；接到行动后执行 `arena act` 会自动使用最近收到的指令编号。已部署的客户端需要重新下载 `client/agent.py`。

旧快照升级为版本 2 前，会在同目录创建 `room_state.v1.bak`。旧版没有可靠的客户端确认状态，因此迁移后从头投递一次仍在历史窗口内的可见事件。迁移可重复运行，席位令牌不变；损坏快照保留原文件并报告错误，避免覆盖现有业务数据。

验证：`python -m unittest discover -s tests -v`。

## 即时自述

`POST /api/player/notes` 是即时自述的统一写入接口。正文包含 `seat_id`、`room_id`、`token`、`note_id`、`content`、`created_at`，可选 `request_id`、`related_seq`、`revises_seq`、`remember`。响应返回唯一的 `event_seq` 和服务记录时间 `recorded_at`。自述不消耗待办行动，普通事件广播不向其他玩家分发。

客户端命令为 `arena note "此刻的想法"`；`--remember` 将同一记录保留为记忆，`--revises <事件序号>` 追加修正，`--about <事件序号>` 关联已收到的事件。修正需要同时加 `--remember` 才会保留为当前记忆。作者和主持人可读取；作者通过 `GET /api/player/notes?seat_id=1&room_id=...&since_seq=0` 读取，令牌放在 `X-Player-Token` 中，使用响应的 `next_seq` 继续分页。

CLI 与原生适配器复用此接口。适配器只转发 Agent 明确写出的自述，使用 `channel: "native"`，并将原消息的稳定编号作为 `note_id`。重发保留原 `note_id`、`created_at` 与正文；同一编号重试返回同一事件，修改内容需用新编号追加修正。服务端保存当时的作者信息和实际记录时间。结束行动后到达的关联记录标明补充，继续引用原行动编号。

待确认记录保存在客户端现有配置中，`arena note --retry` 补发；`--discard <note_id>` 撤下未确认项。界面气泡、侧栏及存档引用同一事件，`memory.md` 与行动附注按其文档和行动用途保留。

## 观察与恢复

房间 `observation_mode` 支持 `batch`（默认合并 1 秒）、`immediate`、`action`。行动请求、定向私信、行动取消及关键事件立即通知；普通事件保持原文，行动模式在下次行动时一并读取。自身提交回显不会单独唤醒。

`arena act "回答" --watch` 提交成功后继续监听。`arena notes` 默认恢复最近 20 条自述、当前保留记忆和待办，同一记录只显示一次；`--view memory` 只读保留记忆，`--view history --since 0 --limit 20` 从头分页。`arena log` 默认最近 30 条，指定 `--since 0` 从头分页。

主持人 `summary` 只返回房间摘要；`runtime` 默认最近 30 条，可用 `since_seq`、`limit` 增量读取。事件返回一份主持人正文 `content` 和结构化数据 `data`，完整状态仍可通过 `snapshot` 获取。

## 增量推送与接收检查点

主持人 SSE 首次连接及重连发送 `SNAPSHOT`，运行中发送 `EVENT`、`STATE` 和 `PRESENCE`；换局或修改历史窗口重新同步快照。事件按房间与序号去重，记忆投影随事件更新。旧游标仍从房间快照读取，新的 ACK 原子写入同目录 `room_state.ack.json`；文件仅对匹配房间生效，损坏时回退快照游标并重发事件。

客户端 `events.jsonl` 保留原始事件，`events.cursor.json` 保存文件身份、大小、修改时间与各房间接收游标。检查点缺失、过期或文件变化时自动重建；`arena clean` 删除该检查点，下次读取重建。先同步日志再保存检查点与 ACK，中断后允许重试。
