# kugo-mcp 1.1 API

传输为 MCP stdio；标准输出仅用于协议，诊断写入标准错误。初始化返回 `serverInfo.version=1.1.0`。共 19 个工具，保留旧版 15 个名称。

## 轻量播放路径

| 工具 | 参数 | 结果 |
| --- | --- | --- |
| `kugo_connect` | `start_if_needed: boolean = true` | `ready`、`launched`、`debug_port`、`version` |
| `kugou_get_playback` | 无 | 当前客户端歌曲及进度快照 |
| `kugou_control_playback` | `action: play / pause / next / prev` | `accepted`、`verified`、`action`、`actual`、`playback`、`message` |
| `kugo_get_current_track` | `include_lines: boolean = false` | `playback`、`cover`、`lyrics`、`errors`、`track_changed` |
| `kugo_get_current_cover` | 无 | `playback`、`cover`、`errors`、`track_changed` |
| `kugo_get_current_lyrics` | `include_lines: boolean = false` | `playback`、`lyrics`、`errors`、`track_changed` |
| `kugo_get_current_progress` | 无 | `hash`、`playback`、`position_ms`、`position_sampled_at`、`elapsed_ms`、`duration_ms`、`progress_ratio`、`stale` |

所有状态工具共用一次原生快照和 4.4 秒缓存，没有后台原生轮询。多个工具连续调用不会分别查询酷狗。客户端状态以实际 hash 为准，歌手／歌曲名从原生 title 拆分，不搜索歌曲名匹配资源。没有窗口控件或截图读取歌曲资料。

`playback` 保留旧字段 `backend`、`available`、`title`、`hash`、`mixsongid`、`playback`、`duration_ms`、`source`、`source_name`，新增 `artist`、`song_name` 及上表进度字段。`position_ms` 是最后一次采样值，`position_sampled_at` 为 Unix 毫秒；`elapsed_ms` 是本次响应按时间推算的值。只有 playing 才推进，超出总时长会截断。采样超过 6 秒后 `stale=true`，`elapsed_ms` 与比例为空，不编造进度。

## 封面与歌词

`cover` 为 `{"url":"https://imge.kugou.com/..."}`；成功但没有封面时 url 为空，失败时 cover 为空且写入 `errors.cover`。1.1 返回封面地址，不通过 MCP 复制大图片；浏览器调用者应使用自己的本机图片代理或平台允许的 CORS，桌面组件的图片代理不包含在此 MCP 中。

`lyrics` 包括 `lyric`（LRC 原文）、`current_line`、`line_index`、`status`。`include_lines=true` 时增加 `lines: [{time_ms, text}]`。status 可为 `synced`、`intro`、`no_lyrics`、`unsynced`、`waiting_progress`；最后一种表示没有有效进度。重复时间戳取最后一句，以二分查找定位。失败时 lyrics 为空且写入 `errors.lyrics`，封面或其他播放功能继续可用。

封面／歌词按实际歌曲 hash 缓存最近 5 首；成功的空结果也缓存，失败退避 30 秒再允许补取。并发相同请求合并、只补缺失字段。Meting 两项请求并行，不调用客户端。元数据请求慢于切歌时，结果继续携带原 hash，不混入新歌曲；已知切歌会标记 `track_changed=true`，调用方应丢弃旧结果。

## 控制及失败行为

控制只提交一次，约 600 ms 后以一次快照确认，之后回到常规间隔。保留旧版 `verified`、`actual` 字段；next/prev 通过前后 hash 比较，首次调用没有旧 hash 时可能 `accepted=true, verified=false`。暂停状态兼容客户端返回的 `pasued` 拼写。

`verified=false` 或超时均不表示指令没有执行，**不要自动重复控制**，应稍后读取实际状态。重叠控制不会排队。原生调用失败后退避 30–60 秒；未响应窗口先暂停调用，正在操作酷狗时短暂避让。请求取消后仍保留互斥，直到原生工作线程真正结束。队列中过期的请求不会迟到执行。

连接工具最多启动一次客户端，先静置 3 秒，再连续检查窗口及官方调试页面就绪。已普通启动且没有调试页面时返回原因，不杀进程。其他程序占用调试端口时返回原因，不盲目复用。退出 MCP 不结束酷狗。

## 兼容接口

`kugou_get_daily_recommendations`、`kugou_play_daily_recommendations`、`kugou_get_favorites`、`kugou_get_play_mode` 的输入和行为保留；仅明确调用时启动原有 native MCP。模式读取仍使用上游控件方案，不在新轻量播放路径中自动执行；没有暴露设置模式、跳转进度、收藏播放和原生搜索等未验证工具，没有绕过版本保护。播放每日推荐可能替换临时队列，保留上游验证限制。

Meting 兼容工具：`platforms`、`search`、`song`、`album`、`artist`、`playlist`、`lyric`、`pic`，参数和原始结果沿用固定版本的上游 schema。

两类上游各按需启动、空闲 30 秒退出。有请求执行时不退出，退出服务会清理自己拥有的会话及子进程，不结束用户独立启动的 MCP。工具发现使用随版本保存的 schema，启动及 `list_tools` 不启动子进程、不查询客户端。
