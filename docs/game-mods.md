# 游戏与 Mod 管理

Arena 的控制台统一提供游戏桌面、实时动态、玩家笔记、调度与存档。游戏和扩展安装在项目忽略目录 `games/<Mod 编号>/`；对局数据保存在 `data/`，可用 `ARENA_DATA_DIR` 指定实例目录。迁移本机内容时单独备份 `games/` 与对应会话目录。

## 主持人与玩家

本地 `host-login.json` 的 `password` 用于加入当前服务，文件位置可通过 `ARENA_HOST_CONFIG` 指定。默认每次服务启动只能成功加入一次，已登录主持人可在“设置 → 房间”增加次数。修改文件不会恢复次数。管理接口接受当前服务的 HttpOnly 浏览器会话；文件口令不能直接管理服务。重启服务会使会话失效，Mod 重载继续复用会话。

玩家密钥仅用于该房间的对应席位，私有游戏接口还要求房间编号。工作目录生成器支持 `python scripts/init_workspace.py --root data/sessions/某局/players --count 3`。具体 Harness 负责把工作目录声明转成实际沙箱权限；当前聊天子代理的共享文件系统仍使用目录指令约束。

## 控制台中的 Mod

打开“设置 → Mod”查看本地模块、版本、加载顺序、依赖、声明的冲突和覆盖项。勾选后立即加载并刷新控制台，主持人会话及显示偏好保留。更改源码后点击“重载已启用”。停用扩展会撤销其接口、实例方法覆盖与前端挂载。

检查包含：缺失模块、版本范围、依赖未启用、循环顺序、显式不兼容、重复覆盖项、实际重复路由、实际重复引擎属性修改、导入错误及异常文件位置。失败时保持上一套可用运行期，显示冲突双方和具体资源。当前牌局的规则模块需要保留；更改规则版本前应开启新局或使用对应的存档版本。

Mod 执行的是主持人信任的本机 Python。声明和运行期检查无法穷尽任意 Python 代码的语义冲突；复杂规则仍需结合错误位置和实际运行日志排查。`install` 同步注册路由和实例方法，持久状态变更放在规则行动或明确的数据迁移中；类全局修改、模块外部副作用和独立后台服务不属于自动撤销范围。

## 清单与目录

除了可执行 Mod，声明式内容包可放在 `data/content-packs/`（也可用 `ARENA_CONTENT_PACKS_DIR` 指定目录）。服务端只读取 `manifest.json`，不执行包内文件；坏包会记录警告并跳过。清单至少包含：

```json
{"id":"example-world","name":"示例世界","version":"1.0.0","format":"arena.content.v1","priority":0}
```

同一 `id` 按 `priority` 选择，结果带有来源路径和 SHA-256。主持接口 `GET /api/admin/content-packs` 可用于 Mod 管理器展示导入结果。内容包适合放世界观、牌组、提示词、主题和规则参数；需要执行 Python 规则的内容仍应使用可信游戏 Mod。

每个 Mod 使用一份 `mod.json` 作为版本来源：

```text
games/某模块/
  mod.json
  game.py          # game 类型默认入口；extension 默认 mod.py
  rules.py         # 可选相对导入，加入 sources
  ui/
    view.js
    view.css
```

```json
{
  "id": "某模块",
  "name": "某模块",
  "version": "1.0",
  "type": "extension",
  "entry": "mod.py",
  "description": "模块说明",
  "dependencies": {"某前置模块": ">=1,<2"},
  "conflicts": ["不兼容模块"],
  "overrides": ["engine:advance_phase"],
  "after": ["某前置模块"],
  "sources": ["rules.py"],
  "frontend": {"module": "view.js", "stylesheet": "view.css"}
}
```

`settings` 是 Mod 管理器可编辑的声明式设置。每项必须有 `type`、`label` 和 `default`，支持 `boolean`、`integer`、`number`、`string`、`text`、`color`、`select`；数值可声明 `min`、`max`、`step`，选择项声明 `options`，需要重新加载规则的设置标记 `restart_required: true`。设置值按 Mod 编号保存到房间快照，不混入通用房间设置。控制台会生成对应控件、显示说明和重载提示，服务端再次校验类型与范围。

Mod 运行时可声明 `configure(settings, context)` 接收变更后的命名空间值；`context.settings` 只包含当前 Mod 设置，`context.get(name, fallback)` 用于读取。没有 `configure` 的 Mod 仍可在下一次游戏创建或重载时读取值。`install(app, engine, context)` 的第三个参数是同一上下文，旧的两参数入口仍可工作，便于现有本地 Mod 逐步迁移。

`type` 为 `game` 或 `extension`，id 与目录名一致。版本范围由 `packaging` 按 Python 版本规范解析；该依赖用于可靠处理组合范围，随项目 requirements 更新。入口提供 `API_VERSION = 1`；加载器从清单注入 `VERSION` 与 `CLIENT`，入口不需要重复维护版本。

`dependencies` 决定前置关系，`after` 补充已启用模块的加载顺序。`overrides` 声明独占资源，例如 `engine:advance_phase`、`ui:table`。依赖需一并启用，不能靠加载顺序掩盖重复覆盖。入口可用 `from .rules import ...`；所有影响规则的辅助源文件列入 `sources`，参与校验并在重载时更新。

## 规则与底层扩展

### 通用行动选项

游戏或扩展可以在 `requests()` 返回 `action_options`，每项包含稳定 `option_id`、`text`、`value`、`targets`、`value_schema`、`text_schema` 和 `risk_tags`。宿主会把它保存在 `ActionRequest.action_options`，旧的 `options: string[]` 继续有效。该协议只描述候选动作，最终规则校验仍由 Mod 的 `step()` 完成。

游戏入口提供：

| 接口 | 职责 |
|---|---|
| `create(seat_ids, options) -> dict` | 创建可 JSON 序列化的完整状态；宿主在 `options.mod_settings` 提供该 Mod 当前设置 |
| `observe(state, seat_id) -> dict` | 返回该席位可见状态，不修改输入 |
| `requests(state) -> list[dict]` | 指定应行动的席位，支持同时行动 |
| `step(state, seat_id, data) -> list[dict]` | 验证并结算，非法行动抛出 ValueError |
| `install(app, engine, context)`（可选） | 注册路由、中间件及引擎实例行为；context 提供 Mod 设置 |

`phase`、`turn`、`finished` 同步 Arena 阶段、回合和终局；其余状态由 Mod 定义。私密信息仅保存在完整状态，`observe` 使用字段白名单。请求支持 `target_seat`、`prompt`、`key`、行动类型、选项、时限和结果范围；稳定的阶段 key 可用于多人同时决策。

行动、状态、事件、收据与下次派发由同一次快照事务保存，非法行动或写入失败会回滚，重试不重复结算。取消或超时暂停游戏，继续时派发新请求。原始提交默认仅主持人可见，`step` 返回的事件才是规则确认结果。

重载会构造新的路由和中间件组合，再替换运行期；同一个引擎实例、玩家待办和主持人会话继续使用。`install` 可以给引擎实例替换方法，管理器记录原值，在停用时还原；不要直接修改引擎类或不可撤销的外部资源。

## 前端组件与事件摘要

游戏 `view.js` 导出 `mount(container, context)`，返回 `update(payload)` 和可选的 `destroy()`。context 提供 `adminRequest` 与 `showNotice`；payload 含 `state`、`status`、`perspective`（null 为全知）与 `seats`。未提供组件时展示 JSON 状态。

扩展的前端同样导出 `mount`，挂载到控制台扩展区域；context 额外提供 `root`，update 接收当前观察视角的快照。样式采用本模块类名前缀，并使用宿主 `--bg-surface`、`--text-main` 等语义变量适配主题。启停时刷新整个界面，让前端依赖和监听器随页面重新装载。

宿主目前保持无构建步骤的原生 ES Module，原因是 Mod UI 可动态加载、游戏目录被本地忽略且不要求 Node 工具链。若未来需要组件化编辑器，优先引入 Lit 或 Preact 作为宿主/Mod 组件层，不把 React/Next 运行时塞进本机静态控制台。当前已在事件进入、笔记更新、设置抽屉和 Mod 重载后刷新加入短动效，并尊重减少动态效果设置；牌桌强调色由 Mod 设置传入。

游戏组件可额外导出 `describeEvent(event, parsed) -> {title, text} | null`，把结构化行动翻译为本游戏的可读摘要。原始记录保留在详情和存档中。实时及回放共用事件类型、范围、席位与关键词过滤；“对局动态”默认显示结果与消息，笔记独立展示，“全部事件”包含指令与原始提交。

## 存档与 Mod 组合

存档记录启用清单、版本和规则源码校验值；规则校验只包含清单中的规则字段、入口与 sources，不混入绝对路径、前端样式或显示主题。UI 修改不会造成规则失配。

复盘选择存档后，可检查所需 Mod、缺失模块、版本与源码差异。原有存档缺少清单时，由保存的游戏名称和规则版本推导，明确提示历史源码无法核验；读取不改写旧文件，重复保存会补齐清单。

恢复前保存独立的“恢复前备份”，使用确定的备份编号避免重试产生重复备份，也不会覆盖选中的源存档。校验通过才一起恢复规则和状态，失败保留当前对局。恢复生成新对局编号和玩家凭证，避免旧客户端的事件序号与恢复后的历史混用；运行中的游戏暂停，玩家重新接入后由主持人继续。存档恢复不改写玩家本机工作目录中的文件。

## 接口

- `GET /api/admin/mods`：目录、启用状态、顺序、版本、诊断。
- `GET /api/admin/content-packs`：扫描声明式内容包，返回包清单、哈希和导入警告。
- `GET /api/admin/summary`、`GET /api/admin/runtime`：分别返回轻量房间摘要和脱敏运行快照。
- `GET /api/admin/events?since_seq=0&limit=100`：按序号分页读取规范化事件，适合高频观察者。
- `POST /api/admin/mods/validate`、`POST /api/admin/mods`：`{"enabled":["某模块"]}`，检查或立即应用组合。
- `GET /api/admin/archives/{room_id}/mods`：检查存档所需组合。
- `POST /api/admin/archives/{room_id}/restore`：备份当前对局并恢复。
- `GET /api/admin/games`、`POST /api/admin/game`：列出游戏，或用 `{"name":"某游戏","seats":[1,2,3],"options":{}}` 开始游戏。
- `POST /api/admin/game/{pause|resume|stop}`：调度游戏。
- `GET /api/player/game?seat_id=1&room_id=...`：玩家令牌读取自身视野；客户端可用 `arena game`。
- `GET /api/admin/perspective?seat_id=1`：主持人会话观察玩家视野。
- `POST /api/admin/workspaces`：用 `seat_id` 与 `directory` 登记笔记目录。

根路径与 `/game` 都进入同一个 Arena 控制台。所有管理接口需要主持人会话。

## 本机斗地主

```powershell
python games/斗地主/host.py install
python games/斗地主/host.py serve
# 另一个终端
python games/斗地主/host.py open
```

`install` 幂等补齐目录，保留牌局、玩家凭证和笔记；首次发牌暂停等待验收。`open` 打开控制台，由主持人输入本地口令。各玩家在自己的目录运行 `player.py state / bid / play / pass / wait`。主持人从控制台调度，`host.py status / report` 可离线读取快照；CLI 调度使用环境变量 `ARENA_HOST_SESSION` 提供临时会话。
