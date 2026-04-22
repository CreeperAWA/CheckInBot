# CheckInBot

基于 [NoneBot2](https://nonebot.dev/docs/) 框架开发的 QQ 机器人应用，用于与考试服务器进行 WebSocket 通讯，实现 QQ 号验证、试卷提交处理和入群申请自动审批等功能。

## 功能概述

### 1. 服务器通讯
- 通过 WebSocket 与考试服务器建立双向实时通讯
- 支持 JWT Token 认证
- 内置断线重连机制（指数退避：5s → 10s → 1min → 5min）
- 支持同时接收和处理多种消息类型

### 2. QQ 号验证流程
当收到服务器的验证询问时，机器人会检查请求中的 QQ 号是否在配置的群聊列表中：
- **已在群内**：返回 `need_verify: false`（无需验证）
- **不在群内**：返回 `need_verify: true`（需要验证）

当收到服务器的验证请求后：
- 机器人会查找该 QQ 号的入群申请，比对申请内容与验证字符串（`verify_content`）
- **内容一致**：返回 `success`，同意入群
- **内容不一致**：返回 `failed`，拒绝入群
- **超时未验证**：返回 `timeout`（超时时间可配置，默认 3 分钟）
- **异常情况**：返回 `cannot_verify`

### 3. 用户试卷提交处理
收到服务器发来的用户提交试卷消息时：
- 检查消息中的 `rating_id` 是否在配置文件的 `allowed_rating_ids` 列表中
- 若 rating_id 在允许列表中：查找是否有对应 QQ 号的入群请求，**有则同意**，无则忽略
- 若 rating_id 不在允许列表中：当 `answer_count` 等于 `max_answer_count` 时，**拒绝入群请求**

### 4. 入群申请处理
收到用户加群申请但未收到服务端验证请求时：
- 向服务器查询该用户的历次考试成绩
- 检查用户最新记录的 `rating_id` 是否在允许的列表中
- **在列表中**：同意申请
- **不在列表中**：拒绝申请

## 项目结构

```
CheckInBot/
├── bot.py                      # 机器人启动入口
├── bot_config.yaml             # 机器人配置文件
├── pyproject.toml              # 项目依赖配置
├── .env                        # 环境配置
├── .env.dev                    # 开发环境配置
├── .env.prod                   # 生产环境配置
└── src/plugins/checkin_bot/
    ├── __init__.py             # 插件包初始化
    ├── config.py               # 配置模型与加载器
    ├── websocket_client.py     # WebSocket 客户端实现
    ├── verification_handler.py # QQ 验证流程处理
    ├── paper_handler.py        # 试卷提交处理
    ├── group_handler.py        # 入群请求处理
    └── main.py                 # 插件入口与事件处理
```

## 快速开始

### 环境要求
- Python 3.9 或更高版本
- pip 包管理器

### 安装依赖

```bash
# 激活虚拟环境（如尚未创建，请先创建）
.venv\Scripts\Activate.ps1

# 安装项目依赖
pip install -e .
```

## 配置指南

本项目包含两类配置文件，它们的用途和填写方式不同：

| 文件 | 用途 | 是否需要修改 |
|------|------|-------------|
| `.env` | NoneBot 框架的运行环境配置 | 通常无需修改 |
| `bot_config.yaml` | 机器人的业务逻辑配置 | **必须填写** |

### 一、环境配置（.env）

此文件用于配置 NoneBot 框架的基础运行参数，通常使用默认值即可。

```env
DRIVER=~fastapi+~websockets
HOST=127.0.0.1
PORT=8080
```

**各字段说明：**

| 字段 | 含义 | 如何修改 |
|------|------|---------|
| `DRIVER` | 驱动类型，指定 NoneBot 使用的 Web 框架和协议 | 保持默认值 `~fastapi+~websockets` 即可，不要修改 |
| `HOST` | 机器人本地服务的监听地址 | `127.0.0.1` 表示仅本机可访问。如需局域网内其他设备访问，改为 `0.0.0.0` |
| `PORT` | 机器人本地服务的端口号 | 默认 `8080`。如与其他服务冲突，可改为其他未被占用的端口，如 `8081` |

**修改方法：** 用任意文本编辑器打开 `.env` 文件，修改对应字段值后保存即可。

---

### 二、机器人配置（bot_config.yaml）

**此文件是核心配置文件，必须根据实际情况填写。** 使用任何文本编辑器（如记事本、VS Code 等）打开 `bot_config.yaml` 即可编辑。

#### 完整配置示例

```yaml
# WebSocket 服务器设置
server:
  host: "exam.example.com"     # 服务器地址
  port: 443                    # 服务器端口
  protocol: "wss"              # ws 或 wss（生产环境建议使用 wss）
  sid: "019d9fbb-e479-7f6b-a587-5348a1b23706"   # 机器人唯一标识（UUID）
  jwt_token: "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."  # JWT 认证令牌

# 需要监控的群聊列表（QQ 群号）
group_list:
  - 640265417
  - 1032389222

# QQ 验证超时时间（分钟）
verify_timeout: 3

# 允许的评级 ID（用于自动审批入群）
allowed_rating_ids:
  - "passed"
  - "excellent"
```

#### 逐项填写说明

##### 1. server.host —— 服务器地址

**这是什么：** 考试服务器的主机地址。

**如何填写：**
- 如果服务器部署在本地：填 `"localhost"` 或 `"127.0.0.1"`
- 如果服务器在远程：填服务器的域名（如 `"exam.example.com"`）或公网 IP（如 `"123.45.67.89"`）

**示例：**
```yaml
# 本地服务器
host: "localhost"

# 远程域名
host: "exam.example.com"

# 远程 IP
host: "123.45.67.89"
```

##### 2. server.port —— 服务器端口

**这是什么：** 考试服务器监听的端口号。

**如何填写：** 与服务端配置保持一致。
- HTTP 环境通常为 `80` 或 `8080`
- HTTPS/WSS 环境通常为 `443`

**示例：**
```yaml
port: 8080   # 测试环境常用
port: 443    # 生产环境常用
```

##### 3. server.protocol —— 通信协议

**这是什么：** WebSocket 使用的协议类型。

**如何填写：**
- `"ws"`：用于测试环境或未配置 SSL 证书的服务器（不加密传输）
- `"wss"`：用于生产环境或已配置 SSL 证书的服务器（加密传输，**推荐**）

**示例：**
```yaml
protocol: "ws"    # 开发/测试环境
protocol: "wss"   # 生产环境（推荐）
```

##### 4. server.sid —— 机器人唯一标识

**这是什么：** 用于在服务端区分不同机器人的唯一标识符，必须为 UUID 格式。

**如何填写：**
- 从服务器管理后台获取已分配的 SID
- 或自行生成一个 UUID，使用工具如：
  - 在线生成：搜索 "UUID Generator"
  - Python 生成：运行 `python -c "import uuid; print(uuid.uuid4())"`
  - PowerShell 生成：运行 `[guid]::NewGuid().ToString()`

**格式要求：** 必须为 `xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx` 格式。

**示例：**
```yaml
sid: "019d9fbb-e479-7f6b-a587-5348a1b23706"
```

##### 5. server.jwt_token —— JWT 认证令牌

**这是什么：** 用于 WebSocket 连接时的身份认证令牌。

**如何填写：**
- 从服务器管理后台获取对应的 JWT Token
- 将完整的 Token 字符串粘贴到引号内

**示例：**
```yaml
jwt_token: "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"
```

##### 6. group_list —— 监控群聊列表

**这是什么：** 机器人需要监控的 QQ 群号列表。当收到验证询问时，机器人会检查用户的 QQ 号是否在这些群中。

**如何填写：**
- 每个群号占一行，以 `- `（短横线加空格）开头
- 可以添加任意数量的群号
- 如果不需要此功能，保留空列表 `[]` 即可

**示例：**
```yaml
# 监控两个群
group_list:
  - 640265417
  - 1032389222

# 只监控一个群
group_list:
  - 123456789

# 不监控任何群
group_list: []
```

##### 7. verify_timeout —— 验证超时时间

**这是什么：** 用户完成验证的时限（单位：分钟）。超过此时限后，机器人会自动向服务器返回超时状态。

**如何填写：**
- 填写一个正整数，代表分钟数
- 建议值：`3`（3 分钟）到 `10`（10 分钟）之间
- 默认值：`3`

**示例：**
```yaml
verify_timeout: 3    # 3 分钟超时
verify_timeout: 5    # 5 分钟超时
verify_timeout: 10   # 10 分钟超时
```

##### 8. allowed_rating_ids —— 允许的评级 ID 列表

**这是什么：** 当用户提交试卷后，如果其评级 ID 在此列表中，机器人会自动同意其入群申请。

**如何填写：**
- 填写服务器端定义的评级 ID 值
- 每个评级 ID 占一行，以 `- ` 开头，并用引号包裹
- 如果不需要自动审批，保留空列表 `[]`

**常见取值参考：** 取决于服务端配置，通常为表示"通过"、"优秀"等含义的标识符。

**示例：**
```yaml
# 通过和优秀评级均可自动入群
allowed_rating_ids:
  - "passed"
  - "excellent"

# 只有特定评级可自动入群
allowed_rating_ids:
  - "rating_abc123"

# 不自动审批任何评级
allowed_rating_ids: []
```

---

### 配置修改后的生效方式

**修改配置文件后，需要重启机器人才能生效。**

```bash
# 如果使用的是 nb run --reload（开发模式），文件保存后会自动重载
# 否则需要手动停止并重新启动：

# 停止当前运行（按 Ctrl+C）
# 重新启动
python bot.py
# 或
nb run --reload
```

### 配置验证

启动机器人后，查看控制台日志确认配置是否正确加载：

```
[INFO] Configuration loaded from D:\Projects\CheckInBot\bot_config.yaml
[INFO] All handlers initialized
[INFO] Connecting to server: ws://exam.example.com:8080/api/websocket/thirdParty/your-uuid
```

如果看到连接错误（如 `Connection error`），请检查：
1. `server.host` 和 `server.port` 是否正确
2. `server.sid` 是否已在服务端注册
3. `server.jwt_token` 是否有效
4. 网络连接是否正常

---

### 启动机器人

```bash
# 开发模式（自动重载，配置文件修改后自动生效）
nb run --reload

# 或使用 Python 直接运行
python bot.py
```

## 消息处理流程

### QQ 验证完整流程

```
用户点击生成题目
    ↓
服务端发送 qq_verify_check（验证询问）
    ↓
机器人检查 QQ 是否在监控群聊中
    ↓
返回 need_verify: true/false
    ↓
（如果需要验证）服务端发送 qq_verify_request
    ↓
机器人存储验证内容，等待入群申请
    ↓
用户提交入群申请（申请内容 = 验证字符串）
    ↓
机器人比对内容，返回验证结果
    ↓
成功 → 同意入群 / 失败 → 拒绝入群
```

### 试卷提交通知处理流程

```
用户提交试卷
    ↓
服务端发送 notification_paper_submit
    ↓
机器人记录 rating_id 和答题次数
    ↓
判断是否允许/拒绝对应的入群申请
```

### 入群申请处理流程

```
用户申请加群
    ↓
机器人检查是否有待验证的请求
    ↓
有 → 验证申请内容
    ↓
无 → 检查是否有试卷提交数据
    ↓
有 → 根据 rating_id 判断
    ↓
无 → 查询服务器考试记录
    ↓
根据最新记录的 rating_id 决定同意或拒绝
```

## 服务器消息类型

机器人支持以下 WebSocket 消息类型：

| 消息类型 | 说明 |
|----------|------|
| `success` | 认证成功 |
| `blacklist_full` | 完整黑名单列表 |
| `blacklist_add` | 新增黑名单条目 |
| `blacklist_remove` | 移除黑名单条目 |
| `qq_verify_check` | QQ 验证询问 |
| `qq_verify_request` | QQ 验证请求 |
| `notification_paper_submit` | 用户提交试卷通知 |
| `notification_exam_start` | 用户开始考试通知 |
| `notification_login_success` | 用户登录成功通知 |
| `notification_login_failure` | 用户登录失败通知 |
| `notification_quick_submit` | 快速提交通知 |
| `notification_submit_frequency` | 频繁提交通知 |
| `exam_records_response` | 考试成绩查询响应 |
| `error` | 错误消息 |

## 开发文档

- [NoneBot 官方文档](https://nonebot.dev/docs/)
- [OneBot V11 适配器文档](https://onebot.adapters.nonebot.dev/)
- [WebSocket API 文档](./WEBSOCKET_API.md)
