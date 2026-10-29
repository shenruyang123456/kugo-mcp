# 本地播放器接口

本服务为后续 Windows 桌面组件提供本机 HTTP 接口。先启动 `start.bat`，默认地址为 `http://127.0.0.1:8765`。它只绑定本机；不要把端口转发到网络。服务依赖已安装的 `kugo-mcp` 和通过调试模式启动的酷狗客户端。

## 读取状态

`GET /api/state` 返回 JSON，建议每 1.5–3 秒读取一次。多个前端共享服务端缓存，不会各自启动酷狗查询。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `mcp_connected` | boolean | 网页服务是否已连接到 kugo-mcp 子进程；断开后会自动尝试重连 |
| `startup_status` | string | `checking` 检查中、`starting` 正在启动、`ready` 调试连接可用、`running_without_debug` 酷狗已运行但无法连接、`error` 启动失败 |
| `connected` | boolean | 最近一次酷狗读取是否成功；为 `false` 时不要把旧曲目当作实时状态 |
| `message` | string | 连接中或失败说明 |
| `updated_at` | number / null | 最近一次成功获取歌曲的 Unix 毫秒时间戳 |
| `song` | object / null | 当前歌曲；包含 `title`、`hash`、`mixsongid`、`playback`、`duration_ms`、`source`、`source_name` |
| `cover` | string | 当前歌曲封面 URL，空字符串表示不可用 |
| `lyrics` | string | 当前歌曲原始 LRC 文本，可能为空；仅用于个人展示 |
| `lyrics_status` | string | 歌词加载状态或失败提示，空字符串表示已获取 |
| `position_ms` | number / null | 播放位置，单位毫秒；不可用时为 `null` |
| `position_sampled_at` | number / null | 播放位置采样的 Unix 毫秒时间戳 |
| `mode` | string | 已读取的模式名称，空字符串表示不可用 |
| `recommendations` | array | 每日推荐，元素包含 `index`、`title`、`artist`、`album`、`hash`、`mixsongid`、`duration_ms` 等 |
| `daily_error` | string | 推荐读取失败提示；首次读取前可能不存在 |

`song.playback` 由酷狗原样返回，常见值为 `playing`、`stopped` 和客户端拼写的 `pasued`；也可能出现 `paused`。`song.title` 目前是客户端提供的完整标题，通常为 `歌手 - 歌曲`，不能保证总能拆分。位置来自客户端非公开字段，100 纳秒单位按当前版本实测换算，可能因版本变化失效。推荐使用 `position_sampled_at` 判断是否过期，未连接或超过 6 秒时不要继续推算歌词。

## 主动刷新

`POST /api/refresh`，JSON 请求体 `{}`。服务返回 HTTP 202 和 `{"accepted":true}`，表示已安排重新读取歌曲及每日推荐，不代表读取已经成功。随后轮询 `GET /api/state`，以 `connected`、`updated_at` 判断结果。页面打开和重新加载时均会调用此接口；如果酷狗未运行，服务会尝试通过 MCP 启动它；如果酷狗已运行但无法调试，服务不会强制结束它。推荐只在此请求时读取，不后台定时刷新。

## 播放控制

`POST /api/control`，JSON 请求体 `{"action":"play"}` 或 `{"action":"pause"}`。成功时返回上游 MCP 的验证结果及 `actual`；失败返回 HTTP 503 和 `{"error":"操作未能确认，请查看酷狗当前状态"}`。酷狗可能已执行操作但未能及时验证，失败后应读取 `/api/state`，不要立即重复操作。

## 播放每日推荐

`POST /api/play-recommendation`，JSON 请求体为 `{"index":1,"hash":"从推荐列表取得的哈希"}`。序号从 1 开始，哈希必须与当前推荐列表对应，用于防止列表变化后误播。此操作替换酷狗临时播放队列。成功返回上游验证结果；失败时也应读取状态确认实际情况。

## 请求与浏览器安全

所有 POST 请求需要 `Content-Type: application/json`，以及 `Origin: http://127.0.0.1:8765`（或 `http://localhost:8765`）。本机桌面程序应显式设置相应 Origin。服务校验 Host 和 Origin，不提供跨域接口。

```js
const base = 'http://127.0.0.1:8765';
await fetch(`${base}/api/refresh`, {
  method: 'POST', headers: {'Content-Type': 'application/json'}, body: '{}'
});
const state = await (await fetch(`${base}/api/state`, {cache: 'no-store'})).json();
```

服务在有页面轮询时约每 2.5 秒合并读取一次歌曲和位置，无页面访问超过 30 秒后降为约 20 秒；断线时会退避重试，页面刷新可立即请求重新读取。耗时接口或客户端超时会延长间隔。封面、歌词和推荐分别获取；数据来源可能不可用。歌词不会自动变成桌面组件自身的授权资源。
