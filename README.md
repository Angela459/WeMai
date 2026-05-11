# WeMai

<div align="center">
  <img src="https://img.shields.io/badge/Python-3.9+-blue.svg" alt="Python 3.9+">
  <img src="https://img.shields.io/badge/Platform-Windows-lightgrey.svg" alt="Platform Windows">
  <img src="https://img.shields.io/badge/License-MIT-green.svg" alt="MIT License">
</div>

WeMai 是一个把微信和 MaiBot 连接起来的桥接程序，负责：

- 监听指定微信聊天并转发给 MaiBot
- 接收 MaiBot 的回复并发回微信
- 通过 Redis 作为消息队列做解耦
- 在新版微信上自动选择合适的自动化后端

当前 `dev` 分支已经从 `wxauto` 迁移到 `pywechat` / `pyweixin` 双后端适配方案：

- 微信 `4.1+` 默认走 `pyweixin`
- 旧版微信可走 `pywechat`
- 程序会自动检测微信版本，也支持环境变量强制指定后端

## 环境要求

- Windows
- Python `3.9+`
- 已安装并登录 PC 微信
- Redis
- 已部署可用的 MaiBot 与 `maim_message`

建议：

- 微信 `4.1+` 用户开启 Windows 讲述人 / 无障碍支持后再使用 `pyweixin`
- `MAIBOT_API_URL` 应连接到 `maim_message` 的消息接口，而不是 WebUI 的 `/ws`

## 依赖管理

本项目现在同时保留三份依赖相关文件，它们分工不同：

- [pyproject.toml](/Z:/MaiBot/WeMai/pyproject.toml) 是主依赖声明文件
- [uv.lock](/Z:/MaiBot/WeMai/uv.lock) 是 `uv` 的锁文件，用于可复现安装
- [requirements.txt](/Z:/MaiBot/WeMai/requirements.txt) 是给不用 `uv` 的用户准备的兼容安装方式

推荐规则：

- 普通用户优先使用 `uv`
- 维护者优先更新 `pyproject.toml`
- 不使用 `uv` 的用户仍可用 `pip install -r requirements.txt`

## 安装

### 1. 准备 Redis

安装并启动 Redis，记下你的地址和端口，稍后需要写入 `.env`。

### 2. 准备 MaiBot

先部署 MaiBot，并确认 `maim_message` 可正常工作。

参考：

- [MaiBot](https://github.com/MaiM-with-u/MaiBot)
- [MaiBot 开发文档](https://docs.mai-mai.org/develop/)

### 3. 克隆项目

```bash
git clone https://github.com/Angela459/WeMai.git
cd WeMai
```

### 4. 安装依赖

推荐方式：`uv`

```bash
uv sync
```

兼容方式：`pip`

```bash
pip install -r requirements.txt
```

### 5. 配置环境变量

复制示例配置：

```bash
cp .env.example .env
```

然后按你的环境修改 [\.env.example](/Z:/MaiBot/WeMai/.env.example) 中对应项，重点包括：

- `WX_TARGET_CHATS`
- `MAIBOT_API_URL`
- `REDIS_URL`
- `REDIS_QUEUE_KEY`
- `API_HOST`
- `API_PORT`

## 启动

推荐方式：`uv`

```bash
uv run python main.py
```

兼容方式：`pip` / 当前 Python 环境

```bash
python main.py
```

如果你在本机使用根目录启动脚本，也可以直接运行：

- [start_services.bat](/Z:/MaiBot/start_services.bat)

这个脚本当前已按本机环境调整，`WeMai` 会通过 `uv run python .\main.py` 启动。

## 自动后端选择

WeMai 会在运行时自动探测微信环境：

- 检测到微信 `4.1+` 时，使用 `pyweixin`
- 检测到旧版微信环境时，使用 `pywechat`

也可以通过环境变量手动覆盖：

```env
WECHAT_BACKEND=pyweixin
```

可选值：

- `pyweixin`
- `pywechat`

## 常用配置项

| 配置项 | 说明 |
|---|---|
| `WX_TARGET_CHATS` | 要监听的微信聊天对象，多个用英文逗号分隔 |
| `WX_LISTEN_ALL_IF_EMPTY` | 未指定目标时是否监听全部聊天 |
| `WX_EXCLUDED_CHATS` | 排除的聊天对象 |
| `MAIBOT_API_URL` | `maim_message` 的消息接口地址 |
| `REDIS_URL` | Redis 连接地址 |
| `REDIS_QUEUE_KEY` | Redis 队列名 |
| `API_HOST` | WeMai API 监听地址 |
| `API_PORT` | WeMai API 监听端口 |
| `PLATFORM_ID` | 平台标识，通常保持默认即可 |

## 目录说明

| 路径 | 说明 |
|---|---|
| [main.py](/Z:/MaiBot/WeMai/main.py) | 程序入口 |
| [wechat_adapter.py](/Z:/MaiBot/WeMai/wechat_adapter.py) | 微信后端适配层 |
| [wx_Listener.py](/Z:/MaiBot/WeMai/wx_Listener.py) | 微信监听 |
| [wx_Processer.py](/Z:/MaiBot/WeMai/wx_Processer.py) | 微信消息转 MaiBot 消息格式 |
| [mq_Producer.py](/Z:/MaiBot/WeMai/mq_Producer.py) | MaiBot 回复写入 Redis |
| [mq_Consumer.py](/Z:/MaiBot/WeMai/mq_Consumer.py) | 从 Redis 取消息并回发微信 |
| [pywechat](/Z:/MaiBot/WeMai/pywechat) | vendored `pywechat` |
| [pyweixin](/Z:/MaiBot/WeMai/pyweixin) | vendored `pyweixin` |

## 故障排查

### 1. 连接 `/ws` 返回 403

优先检查你是不是把 `MAIBOT_API_URL` 指到了 WebUI 的 `/ws`。  
WeMai 应连接 `maim_message` 的消息接口，而不是新版 WebUI 的鉴权 WebSocket。

### 2. `pyweixin` 找不到微信主界面

如果报错类似“无法识别定位到微信主界面”，通常需要：

- 确认微信已登录
- 确认 Windows 讲述人 / 无障碍支持已开启
- 再重新启动 WeMai

### 3. 提示“查无此人”

这通常说明 `WX_TARGET_CHATS` 里的聊天名和微信里的实际备注名 / 群名不一致。

## 注意事项

- 本项目仅供学习和交流使用
- UI 自动化始终有一定风险，请谨慎使用
- 不要把 `.env`、日志文件或本地虚拟环境提交到仓库

## 致谢

- [MaiBot](https://github.com/MaiM-with-u/MaiBot)
- [pywechat](https://github.com/Hello-Mr-Crab/pywechat)
