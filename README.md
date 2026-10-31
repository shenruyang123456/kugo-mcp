# kugo-mcp 1.1

轻量的本地音乐 MCP：连接 Windows 酷狗客户端，读取当前歌曲、封面、同步歌词与进度，控制播放／暂停和上下曲，并通过 Meting-Agent 查询多平台音乐资料。整合 [kugou-native-mcp](https://github.com/yuan-yannick/kugou-native-mcp) 与 [Meting-Agent](https://github.com/ELDment/Meting-Agent)，非酷狗官方项目。

## 1.1 的改进

- 一条持久 CDP 连接，一份歌曲／状态／进度快照，普通查询共用 **4.4 秒缓存**，没有后台原生轮询。
- 当前歌曲封面与歌词使用客户端真实 hash，缓存最近 **5 首**，空结果也缓存；只补缺失项，并发相同请求合并。
- 歌词解析一次、二分定位当前句；进度本地推算，超过 6 秒停止推算。
- 播放控制只提交一次，约 600 ms 后读回；重叠操作不排队，超时不自动重复命令。
- 新启动酷狗后先静置 3 秒，再检查窗口与页面就绪；已有普通客户端或其他程序占用端口时给出原因，不强制结束进程。
- 上游 MCP **按需启动、空闲 30 秒退出**，有请求时不退出。启动与列出工具不连接酷狗、不启动子进程。
- 旧版 15 个工具名全部保留。每日推荐、收藏和模式只在明确调用时启用，不自动查询。

## 工具

| 用途 | 工具 |
| --- | --- |
| 启动或复用酷狗 | `kugo_connect`（新增） |
| 一次读取歌曲、歌手、封面、歌词和进度 | `kugo_get_current_track`（新增，优先使用） |
| 当前歌曲状态 | `kugou_get_playback` |
| 当前封面 | `kugo_get_current_cover` |
| 当前 LRC、当前句及可选时间轴 | `kugo_get_current_lyrics`（新增） |
| 当前进度和总时长 | `kugo_get_current_progress`（新增） |
| 播放、暂停、上一首、下一首 | `kugou_control_playback`，action 为 `play/pause/prev/next` |
| 原有账号与模式功能 | `kugou_get_daily_recommendations`、`kugou_play_daily_recommendations`、`kugou_get_favorites`、`kugou_get_play_mode` |
| 多平台音乐资料 | `platforms`、`search`、`song`、`album`、`artist`、`playlist`、`lyric`、`pic` |

共 19 个工具。完整参数、返回值、缓存和错误行为见 [API.md](API.md)，升级变化见 [CHANGELOG.md](CHANGELOG.md)。

## 安装

Windows 客户端功能需要 Windows 10/11、Python 3.11+、Node.js 20+ 和已安装的官方酷狗。纯 Meting 资料查询不需要启动酷狗。建议安装到持久的用户目录，例如 `%USERPROFILE%\.codex\mcp\kugo-mcp`，不要放入会清理的临时工作区。

```powershell
git clone https://github.com/shenruyang123456/kugo-mcp.git
cd kugo-mcp
git checkout v1.1.0
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install .\vendor\kugou-native
npm ci
.\.venv\Scripts\python.exe server.py --version
```

保留整个仓库，`server.py` 会导入同目录的 `kugo_mcp` 包；不要只复制单个 server.py。Python 依赖随 vendor 安装，Meting 固定为 npm 版本 1.6.11。vendor 的版本号保留上游 0.1.0，聚合服务版本为 1.1.0。

已有安装可先备份配置与本地修改，再更新到 `v1.1.0`，重新执行 Python 安装和 `npm ci`，并重启 MCP 客户端。不需要替换 Windows 酷狗或清除账号资料。自定义的 Meting 路径可以继续使用 `KUGO_MCP_HOME`（支持根目录 node_modules 及 meting/node_modules 两种布局）；它只指定依赖位置，不改变源码或服务版本。

## 连接酷狗

可直接在 MCP 中调用 `kugo_connect`，或者执行：

```powershell
.\.venv\Scripts\python.exe server.py start
.\.venv\Scripts\python.exe server.py doctor
```

doctor 只核对窗口和官方调试页面，不读取歌曲，也不会启动酷狗。start 最多启动一次，不会循环拉起。默认调试地址 `127.0.0.1:9225` 仅供本机使用，不要转发到外网。可设置 `KUGOU_CDP_PORT` 改端口；客户端与 MCP 必须一致。可用 `KUGOU_EXE_PATH` 指定已安装的 KuGou.exe。

若已普通启动酷狗、没有调试页面，请先完全退出（包括托盘），再执行 start。在客户端打开“推荐”页，让官方内嵌页面可用。退出 MCP 会清理自己启动的上游子进程，保持酷狗运行。

## 接入 Codex

在 Codex 用户目录的 config.toml 中填写实际绝对路径，重启 Codex：

```toml
[mcp_servers.kugo-mcp]
command = 'C:\path\to\kugo-mcp\.venv\Scripts\python.exe'
args = ['C:\path\to\kugo-mcp\server.py']
startup_timeout_sec = 30
tool_timeout_sec = 60
default_tools_approval_mode = 'prompt'

[mcp_servers.kugo-mcp.env]
PYTHONIOENCODING = 'utf-8'
KUGOU_CDP_PORT = '9225'
# Node 不在 PATH 时设置 KUGOU_MCP_NODE = 'C:\path\to\node.exe'
```

可说：“连接酷狗”、“显示当前歌曲、封面和歌词”、“下一首”或“搜索周杰伦的歌曲”。显示连续进度的应用应根据采样时间本地更新，不必每帧查询 MCP；优先一次调用整合信息工具。并行运行多套客户端采样器仍会叠加压力。

## 限制及排查

- 本项目使用非公开客户端接口，不能保证所有酷狗版本或长期运行都不挂起。20.1.55.27979 有历史有限实测；新旧接口仍需分别验证。
- `accepted=true` 或超时不保证操作结果。`verified=false` 时不要自动重发，应稍后读取实际状态。next/prev 需要旧 hash 才能比较验证。
- 兼容的模式读取沿用上游控件方案；不自动调用、不新增设置模式，也不绕过原有版本保护。每日推荐播放会替换临时队列，不能逐项验证队列内容。
- 进度跳转、原生搜索及收藏播放等旧版未暴露工具仍未启用。桌面组件界面和 EXE 不在这个 MCP 仓库中。
- 资料结果受版权、会员、地区与接口变化影响；封面或歌词失败会单独报告，其他功能继续可用。Cookie 可由 Meting 环境变量提供，不要提交账号令牌、Cookie 或私人歌单。
- Meting 空闲退出后，下一次缺失资料会有进程初始化耗时；播放控制与其独立。封面返回 URL，不携带大图片。此仓库没有桌面组件的 HTTP 服务端口，因此不占用 8765。
- 初始化和 list_tools 成功并不表示酷狗已经连接；先使用 connect 或 start，遇到窗口未响应时等待，避免频繁重试。

## 开发与发布

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
node tests/test_native_bridge.cjs
```

测试覆盖持久连接、输入校验、缓存与限频、取消与过期控制、启动等待、5 首 LRU、歌词定位及上游进程生命周期。Windows 实机验证需要真正的客户端；自动测试不依赖登录或改动收藏。

GitHub Actions 在 main 与 PR 上测试 Python 3.11/3.13；main 测试通过后，根据 package.json 版本与 RELEASE_NOTES.md 创建同名版本标签及 Release。已存在的 Release 不覆盖。详细本地验收记录见 [VALIDATION.md](VALIDATION.md)。

MIT 许可；vendor/kugou-native 保留上游代码和许可，Meting-Agent 作为 npm 依赖。音乐、平台与客户端归各自权利人所有。
