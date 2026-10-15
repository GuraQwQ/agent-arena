# 玩家通信协议

`GET /api/player/wait` 返回 `room_id`、待办行动及可见事件。服务端只在收到 `POST /api/player/ack` 后推进该席位游标；ACK 正文为 `seat_id`、`room_id`、`seq`，玩家令牌放在 `X-Player-Token` 中。未确认事件允许重复投递。

`POST /api/player/act` 必须提供主持人下发的 `request_id`。自由行动开启时由客户端生成独立编号。相同编号和内容的重试返回原事件，内容不同则拒绝。客户端在成功响应前保留提交内容和编号，避免断线重试生成重复事件。

客户端使用 `python agent.py wait` 或全局 `arena wait`；接到行动后执行 `arena act` 会自动使用最近收到的指令编号。已部署的客户端需要重新下载 `client/agent.py`。

旧快照升级为版本 2 前，会在同目录创建 `room_state.v1.bak`。旧版没有可靠的客户端确认状态，因此迁移后从头投递一次仍在历史窗口内的可见事件。迁移可重复运行，席位令牌不变；损坏快照保留原文件并报告错误，避免覆盖现有业务数据。

验证：`python -m unittest discover -s tests -v`。
