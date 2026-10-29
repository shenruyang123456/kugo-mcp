# kugo-mcp

一个本地 MCP 服务：连接 Windows 酷狗音乐客户端，并通过 Meting-Agent 查询多平台音乐资料。整合了 [kugou-native-mcp](https://github.com/yuan-yannick/kugou-native-mcp) 和 [Meting-Agent](https://github.com/ELDment/Meting-Agent)。本项目非酷狗官方项目。

## 功能

| 类别 | MCP 工具 | 用途 |
| --- | --- | --- |
| 客户端 | `kugou_get_playback` | 读取当前歌曲和播放状态 |
| 客户端 | `kugou_get_daily_recommendations` | 读取账号的每日推荐 |
| 客户端 | `kugou_play_daily_recommendations` | 从指定曲序播放每日推荐 |
| 客户端 | `kugou_get_favorites` | 分页读取收藏歌单 |
| 客户端 | `kugou_control_playback` | 播放或暂停 |
| 客户端 | `kugou_get_play_mode` | 读取当前播放模式 |
| 资料 | `platforms`、`search` | 列出平台、按关键词搜索 |
| 资料 | `song`、`album`、`artist`、`playlist` | 查询歌曲、专辑、歌手和歌单 |
| 资料 | `lyric`、`pic` | 查询歌词和封面链接 |
| 组合 | `kugo_get_current_cover` | 根据当前酷狗歌曲获取封面 |

资料查询支持 `kugou`、`netease`、`tencent` 和 `kuwo`。上游还包含客户端搜索、搜索结果播放、收藏播放、设置播放模式和音频链接功能，但这些功能在本机测试中未通过完整验证，因此本服务不对外暴露它们。

播放每日推荐会替换临时播放队列，不修改收藏；服务验证实际播放的歌曲，但无法逐项验证队列。结果受版权、会员、地区和平台接口变化影响。

## 环境要求

- Windows 10/11，Python 3.11+ 和 Node.js 20+。
- 官方酷狗 Windows 客户端；使用账号相关功能时须登录。
- Python 和 Node 可从终端运行。若 `py` 没有找到 Python，可用 Python 安装路径替换下文的 `py -3`。

## 安装与启动

建议把仓库克隆到持久目录，进入项目目录后执行：

```powershell
git clone https://github.com/shenruyang123456/kugo-mcp.git
cd kugo-mcp
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install .\vendor\kugou-native
npm ci
```

启动酷狗的本机调试连接。若酷狗已用普通方式启动，请先完全退出，包括系统托盘中的进程：

```powershell
.\.venv\Scripts\python.exe -m kugou_native_mcp start
.\.venv\Scripts\python.exe -m kugou_native_mcp doctor
```

在酷狗中打开“推荐”页。默认调试地址为 `127.0.0.1:9225`，仅供本机使用，不要转发或开放到网络。可用 `--port` 指定端口，并在 MCP 配置中同步设置 `KUGOU_CDP_PORT`。

## 接入 Codex

将下面两个路径替换为实际的项目绝对路径，添加到 Codex 用户目录的 `config.toml`，然后重启 Codex：

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
# 如 Node 20+ 不在 PATH，设置 KUGOU_MCP_NODE 为 node.exe 的绝对路径。
```

可以对 Codex 说：“当前播放什么？”、“显示当前歌曲封面”、“读取我的每日推荐”，或“搜索周杰伦的歌曲”。客户端工具依赖已启动的酷狗；资料查询单独访问各音乐平台。

## 排查

- **无法连接客户端**：确认酷狗已完全退出并通过上述 `start` 命令启动，在客户端打开“推荐”页，再执行 `doctor`。启动工具不会自动结束正在播放的客户端。
- **工具无法启动**：确认使用 Node 20+，且已运行 `npm ci` 和 Python 安装命令。如果 Codex 的 PATH 不包含 Node，在配置的环境变量中设置 `KUGOU_MCP_NODE`。
- **资料为空**：平台可能限制资源或要求登录。Meting-Agent 支持 `METING_KUGOU_COOKIE` 等平台 Cookie 环境变量；不要将 Cookie、账号令牌或私人歌单提交到仓库。

项目在酷狗 20.1.55.27979 上做过有限实测；它依赖非公开的客户端接口，升级后可能需要重新验证。

## 开发与许可

使用 `.\.venv\Scripts\python.exe -m unittest discover -s tests` 运行不需要登录酷狗的测试。客户端的端到端功能仍需真实 Windows 客户端验证。

本项目采用 MIT 许可。`vendor/kugou-native` 保留上游源码及其 MIT 许可；Meting-Agent 作为 npm 依赖安装。平台、客户端和音乐内容归其各自权利人所有。
