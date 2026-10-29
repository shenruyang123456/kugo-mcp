# KuGou Native MCP

让 AI Agent 控制 **Windows 官方酷狗音乐客户端**：搜索、每日推荐、收藏播放、暂停/续播、播放模式及状态验证。

这是非官方本地 MCP 服务。音乐由已安装的酷狗客户端播放；无需 Windows-MCP。搜索、推荐、收藏和播放使用客户端原生网页桥接；播放模式使用可访问性控件与定向窗口消息后备，不是纯播放 API。

## 支持与限制

- Windows 10/11，Python 3.11+，已安装并登录的官方酷狗客户端。
- 已在客户端 **20.0.22.27032**、Python 3.13 上实测。模式切换仅接受已验证的客户端版本号 `20022`；升级后需重测。
- 使用仅限本机的 CDP 通道，默认 `127.0.0.1:9225`。不要把调试端口转发或开放到网络。
- 保留客户端自身的会员、版权与网络限制，不提供音频下载或绕过权限功能。
- 在线搜索返回综合搜索页前 15 个候选；尚无搜索分页。
- 播放会替换临时队列，不修改收藏。返回值区分实际歌曲播放验证和完整队列逐项读回：`queue_contents_verified` 目前为 `false`。
- 依赖未公开承诺兼容的客户端接口；不是酷狗官方 SDK 产品。

## 安装

下载本仓库源码或 Release 源码包并解压。在 PowerShell 中进入项目目录：

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install .
```

也可以安装 Release 中的 wheel 文件：

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install .\kugou_native_mcp-0.1.0-py3-none-any.whl
```

依赖由 pip 安装，不包含酷狗程序、账号配置或预先制作的虚拟环境。无需管理员权限，也不会修改 Windows 安全设置。

## 打开酷狗连接

```powershell
.\.venv\Scripts\kugou-mcp.exe start
.\.venv\Scripts\kugou-mcp.exe doctor
```

启动工具从已注册的 `kugou://` 处理程序或标准安装目录查找 `KuGou.exe`。如需指定：

```powershell
.\.venv\Scripts\kugou-mcp.exe start --exe "C:\path\to\KuGou.exe"
```

如果酷狗已经通过普通快捷方式启动，单实例客户端可能忽略调试参数。请先关闭它，再运行 `start`；启动工具不会自动终止正在播放的进程。开启后，在酷狗中打开“推荐”页即可。支持 `--port`，服务端对应环境变量为 `KUGOU_CDP_PORT`。

## 接入 Codex

```powershell
.\.venv\Scripts\kugou-mcp.exe install-codex
```

随后重启 Codex。安装命令仅添加 `kugou-native` 配置，写入前在配置目录备份原文件。尊重 `CODEX_HOME`；已存在同名 MCP 时拒绝覆盖。非标准安装目录可给 `install-codex` 添加 `--exe`。

也可手动配置（把 Python 路径替换为自己的路径）：

```toml
[mcp_servers.kugou-native]
command = "C:/path/to/.venv/Scripts/python.exe"
args = ["-m", "kugou_native_mcp", "serve"]
startup_timeout_sec = 30.0
tool_timeout_sec = 40.0

[mcp_servers.kugou-native.env]
KUGOU_CDP_PORT = "9225"
PYTHONIOENCODING = "utf-8"
# 非标准客户端安装目录可设置 KUGOU_EXE_PATH
```

其他支持 stdio 的 MCP 客户端也可用相同命令：

```json
{
  "mcpServers": {
    "kugou-native": {
      "command": "C:/path/to/.venv/Scripts/python.exe",
      "args": ["-m", "kugou_native_mcp", "serve"],
      "env": {"KUGOU_CDP_PORT": "9225", "PYTHONIOENCODING": "utf-8"}
    }
  }
}
```

## 10 个工具

| 工具 | 用途 |
| --- | --- |
| `kugou_get_playback` | 当前歌曲、播放状态、队列来源 |
| `kugou_get_daily_recommendations` | 当前账户的每日推荐 |
| `kugou_play_daily_recommendations` | 从指定曲序播放推荐，默认第 1 首 |
| `kugou_search_music` | 在线搜索，默认返回 5 个候选 |
| `kugou_play_search_result` | 播放精确候选；候选有效期 10 分钟 |
| `kugou_control_playback` | 明确暂停或续播 |
| `kugou_get_play_mode` | 读取模式按钮实际名称 |
| `kugou_set_play_mode` | 顺序、列表循环、单曲循环、随机 |
| `kugou_get_favorites` | 默认读取“我喜欢”；支持歌单名和分页 |
| `kugou_play_favorites` | 一次调用读取、加载收藏并验证播放 |

收藏快速播放参数：

```json
{"collection_name": "我喜欢", "start_index": 1, "mode": "keep"}
```

`mode` 可选 `keep`、`order`、`list_loop`、`single_loop`、`shuffle`。默认保持现有模式。歌单标识每次从当前客户端解析，不硬编码账号或收藏编号。

可直接对 Agent 说：

- “播放我的收藏。”
- “播放我喜欢里的第二首，改为顺序播放。”
- “读取每日推荐所有歌曲并汇总。”
- “每日推荐从第一首播放，然后切换为随机。”
- “搜索某首歌曲，先列出歌手和版本，再播放指定结果。”

## 隐私与本机权限

服务不导出 Cookie、账号令牌或原始鉴权字段。服务不提供任意 JavaScript、任意文件或通用桌面控制工具。音乐数据访问复用用户已经登录的酷狗客户端。

发布包不包含本机配置、私人歌单列表、真实测试结果或虚拟环境。问题反馈时也请不要上传这些信息。

## 测试与开发

```powershell
python -m pip install -e .
python -m unittest discover -s tests -v
```

自动化测试检查打包资源、MCP 工具发现、输入约束、配置注册/回退和路径校验，不需要酷狗账号。真实客户端功能需要 Windows、已登录的酷狗及开启的本机连接；兼容性验证摘要见 [docs/verification.md](docs/verification.md)。

## 回退

```powershell
.\.venv\Scripts\kugou-mcp.exe uninstall-codex
```

只移除本包创建的管理区块，并保留其他配置。手动添加的配置需手动移除。关闭酷狗、使用原快捷方式重新打开，即恢复正常启动方式。

## 许可与来源

本项目源码使用 MIT 许可。酷狗名称、客户端及其服务属于相应权利人；本仓库不分发酷狗程序或第三方 SDK 文件。

- [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)
- [websocket-client](https://github.com/websocket-client/websocket-client)
- [Windows UIAutomation Python 封装](https://github.com/yinkaisheng/Python-UIAutomation-for-Windows)
- [酷狗 PC 调用接口参考](https://pc.service.kugou.com/search/2024/dev/js/supercall-v3.1.js)
