# 机器人 WebSocket API 文档

## 1. 简介

本API设计用于群聊机器人等服务端应用与客户端之间的实时双向通信，基于WebSocket协议。该API与用户使用的API区分开来，支持多机器人连接，并提供黑名单管理、QQ号验证和消息通知等功能。

## 2. 连接与认证

### 2.1 连接URL

```
{protocol}://{host}:{port}/api/websocket/thirdParty/{sid}
```

- `protocol`: 协议，根据服务器配置选择 `ws` 或 `wss`
- `host`: 服务器主机地址
- `port`: 服务器端口
- `sid`: 机器人唯一标识符（UUID格式）

**注意**：在生产环境中建议使用WSS协议确保数据传输安全，测试环境或无SSL证书的环境可使用WS协议

### 2.2 认证流程

1. 客户端建立WebSocket连接时，通过URL参数提供`sid`（UUID）
2. 连接建立后，客户端立即发送包含JWT Token的认证消息
3. 服务端验证Token，验证通过后建立正式连接

### 2.3 认证消息

#### 客户端发送认证消息

```json
{
  "type": "token",
  "messageId": "550e8400-e29b-41d4-a716-446655440000",
  "data": {
    "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
  }
}
```

#### 服务端发送认证结果

```json
{
  "type": "success",
  "messageId": "550e8400-e29b-41d4-a716-446655440000"
}
```

## 3. 消息格式

所有WebSocket消息采用JSON格式，包含以下字段：

```json
{
  "type": "消息类型",
  "messageId": "消息唯一标识符",
  "data": {
    // 消息数据
  }
}
```

- `type`: 消息类型，字符串
- `messageId`: 消息唯一标识符，UUID格式
- `data`: 消息数据，JSON对象

### 3.1 时间格式

服务端返回的时间数据采用数组格式，具体结构如下：

```json
[年, 月, 日, 时, 分, 秒, 纳秒]
```

- 年：4位数字，如2026
- 月：1-12的数字，如4表示4月
- 日：1-31的数字
- 时：0-23的数字
- 分：0-59的数字
- 秒：0-59的数字（可选，默认为0）
- 纳秒：0-999999999的数字（可选，默认为0）

**示例**：
- `[2026, 4, 16, 10, 30, 0, 0]` 表示2026年4月16日10时30分0秒0纳秒

**前端解析示例**：
```javascript
const formatTime = (timeStr) => {
  if (!timeStr) return "";
  try {
    let date;
    if (Array.isArray(timeStr) && timeStr.length >= 5) {
      const year = timeStr[0];
      const month = timeStr[1] - 1; // JavaScript月份从0开始
      const day = timeStr[2];
      const hours = timeStr[3];
      const minutes = timeStr[4];
      const seconds = timeStr[5] || 0;
      const nanos = timeStr[6] || 0;
      const milliseconds = Math.floor(nanos / 1000000);
      date = new Date(year, month, day, hours, minutes, seconds, milliseconds);
    } else {
      return timeStr;
    }
    // 格式化日期为本地字符串
    return date.toLocaleString();
  } catch (error) {
    console.error('时间格式化错误:', error);
    return timeStr;
  }
};
```

## 4. 功能API

### 规范说明

本章节列出了所有第三方客户端必须遵循的核心规范，违反这些规范将导致验证流程失败或多用户并发问题。

#### 4.0.1 MessageID 处理规范

**核心原则：回复消息时必须使用与请求相同的 messageId**

当服务端发送消息给第三方客户端时，会携带一个唯一的 `messageId`（UUID格式）。第三方客户端在回复该消息时，**必须在响应中使用相同的 messageId**，以便服务端正确匹配请求和响应。

**正确示例**：

```
服务端发送 → 客户端:
{
  "type": "qq_verify_check",
  "messageId": "550e8400-e29b-41d4-a716-446655440000",  ← 服务端生成的ID
  "data": { "qq": "123456789" }
}

客户端回复 → 服务端:
{
  "type": "qq_verify_check_response",
  "messageId": "550e8400-e29b-41d4-a716-446655440000",  ← 必须使用相同的ID
  "data": { "qq": "123456789", "need_verify": true }
}
```

**错误示例（会导致请求/响应脱节）**：

```
客户端回复 → 服务端:
{
  "type": "qq_verify_check_response",
  "messageId": "新的-uuid-自己生成的",  ← ❌ 错误！不能使用新的messageId
  "data": { "qq": "123456789", "need_verify": true }
}
```

**为什么重要**：
- 服务端使用 `messageId` 来追踪和匹配待处理的请求
- 如果客户端使用不同的 `messageId`，服务端将无法找到对应的待处理请求
- 这会导致请求超时、验证失败、用户体验受损

**例外情况**：
- 当客户端主动发送消息（如黑名单更新通知）时，应生成新的 `messageId`
- 当客户端回复服务端的请求时，必须使用请求中的 `messageId`

#### 4.0.2 多用户并发处理规范

**核心原则：支持同时处理多个用户的验证请求，互不干扰**

服务端可能同时有多个用户在答题验证，每个用户都有独立的验证流程。第三方客户端必须能够正确处理并发验证场景。

**并发场景示例**：

```
时间 T0: 用户A(123456789) 点击生成题目
  → 服务端发送: { "type": "qq_verify_check", "messageId": "uuid-A-1", "data": { "qq": "123456789" } }

时间 T1: 用户B(987654321) 点击生成题目
  → 服务端发送: { "type": "qq_verify_check", "messageId": "uuid-B-1", "data": { "qq": "987654321" } }

时间 T2: 客户端回复 A 的验证询问
  → 客户端发送: { "type": "qq_verify_check_response", "messageId": "uuid-A-1", "data": { "qq": "123456789", "need_verify": true } }

时间 T3: 客户端回复 B 的验证询问
  → 客户端发送: { "type": "qq_verify_check_response", "messageId": "uuid-B-1", "data": { "qq": "987654321", "need_verify": true } }
```

**实现要求**：
1. **独立追踪每个验证请求**：使用 `messageId` 或 `qq` 字段区分不同用户
2. **并发处理**：不要阻塞或串行化验证流程，应支持并行处理
3. **正确路由响应**：确保每个验证结果返回给对应的用户
4. **独立超时管理**：每个验证请求应有独立的超时计时器

**客户端实现建议**：

```javascript
// JavaScript 伪代码示例
class QQVerificationHandler {
  constructor() {
    this.pendingVerifications = new Map(); // messageId -> verification context
  }

  // 接收服务端的验证询问
  onQQVerifyCheck(message) {
    const { messageId, data } = message;
    const qq = data.qq;
    
    // 创建验证上下文
    const context = {
      messageId,
      qq,
      startTime: Date.now()
    };
    
    // 存储待处理验证
    this.pendingVerifications.set(messageId, context);
    
    // 异步处理验证逻辑（不阻塞其他请求）
    this.processVerification(qq, messageId);
  }

  // 异步处理验证
  async processVerification(qq, messageId) {
    // 设置独立超时（2分钟）
    const timeout = setTimeout(() => {
      this.sendVerifyResponse(messageId, qq, 'timeout');
    }, 2 * 60 * 1000);
    
    try {
      // 执行验证逻辑...
      const result = await doVerify(qq);
      clearTimeout(timeout);
      this.sendVerifyResponse(messageId, qq, result ? 'success' : 'failed');
    } catch (error) {
      clearTimeout(timeout);
      this.sendVerifyResponse(messageId, qq, 'cannot_verify');
    }
  }

  // 发送验证响应（使用相同的 messageId）
  sendVerifyResponse(messageId, qq, status) {
    const response = {
      type: 'qq_verify_response',
      messageId: messageId,  // ⚠️ 必须使用请求中的 messageId
      data: {
        qq,
        status
      }
    };
    websocket.send(JSON.stringify(response));
  }
}
```

#### 4.0.3 响应时效性规范

| 消息类型 | 建议响应时间 | 超时时间 | 说明 |
|---------|------------|---------|------|
| `qq_verify_check` | < 1秒 | 30秒 | 验证询问应立即响应 |
| `qq_verify_request` | 用户操作 | 2分钟 | 取决于用户完成验证的时间 |

**注意事项**：
- `qq_verify_check` 响应越快，用户体验越好
- `qq_verify_request` 超时由客户端控制，建议在2分钟后自动发送 `timeout` 状态
- 超时后不应再发送其他状态，避免状态混乱

#### 4.0.4 错误处理规范

当遇到以下情况时，应返回相应的状态码：

| 情况 | 状态码 | 说明 |
|------|-------|------|
| 用户验证成功 | `success` | 用户按要求完成验证 |
| 用户验证失败 | `failed` | 用户输入错误或拒绝验证 |
| 验证超时 | `timeout` | 用户未在时限内完成验证 |
| 服务异常 | `cannot_verify` | 客户端自身异常，无法执行验证 |

**重要**：
- 每个验证请求**必须且只能**返回一次响应
- 不应重复发送相同验证请求的响应
- 超时后发送的响应应标记为最终状态

---

### 4.1 黑名单管理

#### 4.1.1 完整黑名单列表推送

**触发时机**：初始连接时或客户端请求时

```json
{
  "type": "blacklist_full",
  "messageId": "550e8400-e29b-41d4-a716-446655440000",
  "data": {
    "list": [
      {
        "id": "019d9fbb-e479-7f6b-a587-5348a1b23706",
        "qq": "123456789",
        "reason": "违规行为",
        "created_at": [2021, 5, 20, 12, 33, 19, 0]
      },
      // 更多黑名单条目
    ]
  }
}
```

#### 4.1.2 新增黑名单条目推送

**触发时机**：有新的黑名单条目添加时

```json
{
  "type": "blacklist_add",
  "messageId": "550e8400-e29b-41d4-a716-446655440000",
  "data": {
    "id": "019d9fbb-e479-7f6b-a587-5348a1b23707",
    "qq": "987654321",
    "reason": "恶意攻击",
    "created_at": [2021, 5, 20, 12, 33, 20, 0]
  }
}
```

#### 4.1.3 移除黑名单条目推送

**触发时机**：有黑名单条目被移除时

```json
{
  "type": "blacklist_remove",
  "messageId": "550e8400-e29b-41d4-a716-446655440000",
  "data": {
    "id": "019d9fbb-e479-7f6b-a587-5348a1b23706",
    "qq": "123456789"
  }
}
```

### 4.2 QQ号验证

> **⚠️ 重要提示**：在实现 QQ 号验证之前，请务必阅读 [4.0.1 MessageID 处理规范](#401-messageid-处理规范--关键) 和 [4.0.2 多用户并发处理规范](#402-多用户并发处理规范--关键)，这是验证功能正常工作的基础要求。

#### 4.2.1 验证询问请求

**触发时机**：用户点击生成题目后，服务端在试题生成前向第三方客户端发送验证询问

```json
{
  "type": "qq_verify_check",
  "messageId": "550e8400-e29b-41d4-a716-446655440000",
  "data": {
    "qq": "123456789"
  }
}
```

**字段说明**：
- `qq`：当前用户的QQ号

#### 4.2.2 验证询问响应

**第三方客户端返回是否需要验证**：

```json
{
  "type": "qq_verify_check_response",
  "messageId": "550e8400-e29b-41d4-a716-446655440000",
  "data": {
    "qq": "123456789",
    "need_verify": true
  }
}
```

**字段说明**：
- `need_verify`：`true` 表示需要验证，`false` 表示不需要验证

> **⚠️ 关键**：`messageId` 必须与接收到的 `qq_verify_check` 消息中的 `messageId` 相同，否则服务端无法正确匹配请求！详见 [4.0.1 MessageID 处理规范](#401-messageid-处理规范--关键)

#### 4.2.3 验证请求

**触发时机**：当第三方客户端返回需要验证（`need_verify: true`）后，服务端向第三方客户端发送验证请求

```json
{
  "type": "qq_verify_request",
  "messageId": "550e8400-e29b-41d4-a716-446655440000",
  "data": {
    "qq": "123456789",
    "verify_content": "AbCdEfGhIjKl"
  }
}
```

**字段说明**：
- `qq`：当前用户的QQ号
- `verify_content`：验证内容字符串

#### 4.2.4 验证响应

**第三方客户端返回验证结果**：

```json
{
  "type": "qq_verify_response",
  "messageId": "550e8400-e29b-41d4-a716-446655440000",
  "data": {
    "qq": "123456789",
    "status": "success"
  }
}
```

**字段说明**：
- `status`：验证状态，取值见下方说明

> **⚠️ 关键**：`messageId` 必须与接收到的 `qq_verify_request` 消息中的 `messageId` 相同，否则服务端无法正确匹配请求！详见 [4.0.1 MessageID 处理规范](#401-messageid-处理规范--关键)

**status 字段说明**：
- `success`：验证成功，用户通过验证
- `failed`：验证失败，用户未通过验证
- `timeout`：验证超时，用户未在指定时间内未给出回复，此处时间由第三方 API 客户端把控
- `cannot_verify`：无法验证，第三方客户端无法执行验证

#### 4.2.5 验证配置

**网页后台配置**：

- **验证功能开关**：可在网页后台启用/禁用 QQ 号验证机制
- **验证内容生成规则**：
  - 当启用验证且未配置自定义列表时，系统自动生成12位包含大小写英文字母的随机字符串
  - 支持通过后台配置自定义验证字符串列表，字符串可包含中文、英文字符，单个字符串长度不超过99个字符
- **验证有效期**：支持在后台配置验证的有效天数，超过有效期后需要重新验证
- **白名单机制**：支持配置 QQ 号白名单，白名单内的 QQ 号可跳过验证流程（网页界面列表实现参考黑名单页面）

**验证流程**：

##### 完整流程（前端 → HTTP API 确认验证 → 前端弹窗 → HTTP API 查询状态 → 前端处理 → HTTP 生成试题）

1. **用户点击生成题目按钮**

2. **前端请求验证状态检查 API**：
   - 前端调用 HTTP API 检查当前用户是否需要进行 QQ 号验证
   - 该 API 由第三方客户端提供，用于确认验证需求和返回验证引导信息

3. **API 返回验证检查结果**：
   - **不需要验证**：API 返回 `need_verify: false`，前端直接调用 HTTP `/api/generate` 接口生成试题
   - **需要验证**：API 返回 `need_verify: true`，同时返回引导消息和验证使用的字符串，前端弹出验证窗口显示引导信息和验证字符串

4. **用户完成验证操作**：
   - 用户在第三方客户端完成验证（如发送指定消息到群聊等）
   - 前端显示"等待验证结果"提示和加载动画

5. **用户点击"更新验证状态"按钮**：
   - 前端调用另一个 HTTP API 查询当前用户的认证状态
   - 该 API 返回用户当前的验证状态

6. **前端根据认证状态处理**：
   - **验证成功（success）**：关闭验证窗口，显示"验证成功"提示，调用 HTTP `/api/generate` 生成试题
   - **验证失败（failed）**：关闭验证窗口，提示用户"验证失败，请重新验证"，返回生成题目页面
   - **验证超时（timeout）**：关闭验证窗口，提示用户"验证操作超时，请重新验证"，返回生成题目页面
   - **无法验证（cannot_verify）**：关闭验证窗口，提示用户"服务异常，请坐和放宽，稍后再试"，返回生成题目页面

7. **第三方客户端职责**：
   - 提供验证状态检查 API，返回是否需要验证及验证引导信息
   - 提供验证状态查询 API，返回用户当前验证状态
   - 在用户完成验证后更新验证状态供前端查询
   - 实现验证超时处理机制（建议 2 分钟超时）

#### 4.2.6 常见问题排查

**问题1：验证请求超时，日志显示"No pending verify check request found"**

**症状**：
```
[WARN] No pending verify check request found for messageId: xxx or QQ: xxx
```

**原因**：
- 客户端回复的 `messageId` 与请求中的 `messageId` 不匹配
- 响应延迟超过30秒超时时间

**解决方案**：
1. 检查客户端代码，确保回复时使用请求中的 `messageId`
2. 打印日志对比发送和接收的 `messageId`
3. 确保响应在超时时间内发送

**问题2：多用户同时验证时出现混乱**

**症状**：
- 用户A的验证结果显示给用户B
- 并发验证时部分验证失败

**原因**：
- 客户端没有正确追踪每个验证请求
- 使用全局变量而非Map存储验证上下文

**解决方案**：
1. 使用 Map 结构存储验证上下文，key 为 `messageId`
2. 确保每个验证请求独立处理，不共享状态
3. 参考 [4.0.2 多用户并发处理规范](#402-多用户并发处理规范--关键) 中的示例代码

**问题3：WebSocket TEXT_FULL_WRITING 错误**

**症状**：
```
java.lang.IllegalStateException: The remote endpoint was in state [TEXT_FULL_WRITING]
```

**原因**：
- 并发发送消息导致WebSocket状态冲突
- 发送缓冲区已满

**解决方案**：
1. 客户端应确保消息发送的串行化
2. 避免在同一时刻发送多条消息
3. 实现消息队列，按顺序发送

### 4.3 消息通知

**配置说明**：每项通知支持独立启用/禁用配置

#### 4.3.1 同一QQ号短时间多次提交试题

**配置项**：监控时间窗口（分钟）和提交次数阈值
**网页显示格式**："同一 QQ 号_______分钟内提交_______次试题-关/开"

```json
{
  "type": "notification_submit_frequency",
  "messageId": "550e8400-e29b-41d4-a716-446655440000",
  "data": {
    "qq": "123456789",
    "time_window": 5, // 分钟
    "submit_count": 3,
    "start_time": [2021, 5, 20, 12, 33, 19, 0],
    "end_time": [2021, 5, 20, 12, 33, 20, 0]
  }
}
```

#### 4.3.2 用户登录后台失败

```json
{
  "type": "notification_login_failure",
  "messageId": "550e8400-e29b-41d4-a716-446655440000",
  "data": {
    "username": "user1",
    "password": "password123",
    "fail_time": [2021, 5, 20, 12, 33, 19, 0]
  }
}
```

#### 4.3.3 用户登录后台成功

```json
{
  "type": "notification_login_success",
  "messageId": "550e8400-e29b-41d4-a716-446655440000",
  "data": {
    "username": "user1",
    "qq": "123456789",
    "login_time": [2021, 5, 20, 12, 33, 20, 0],
    "permission_group": "admin"
  }
}
```

#### 4.3.4 用户生成试题后短时间提交

**配置项**：时间阈值（分钟）
**网页显示格式**："用户生成试题后_______分钟内提交-关/开"

```json
{
  "type": "notification_quick_submit",
  "messageId": "550e8400-e29b-41d4-a716-446655440000",
  "data": {
    "qq": "123456789",
    "generate_time": [2021, 5, 20, 12, 33, 15, 0],
    "submit_time": [2021, 5, 20, 12, 33, 20, 0],
    "interval": 5 // 秒
  }
}
```

#### 4.3.5 用户提交试卷

```json
{
  "type": "notification_paper_submit",
  "messageId": "550e8400-e29b-41d4-a716-446655440000",
  "data": {
    "generate_time": [2021, 5, 20, 12, 31, 40, 0],
    "submit_time": [2021, 5, 20, 12, 33, 20, 0],
    "paper_id": "paper_001",
    "qq": "123456789",
    "rating_id": "rating_001",
    "score": 90,
    "max_answer_count": 5,
    "answer_count": 2
  }
}
```

**字段说明**：
- `max_answer_count`：最大答题次数限制，由服务端设置
- `answer_count`：用户当前答题次数，按提交成功计算（即提交成功、注册成功、成绩无效化等情况均计入答题计数）

#### 4.3.6 用户开始考试

```json
{
  "type": "notification_exam_start",
  "messageId": "550e8400-e29b-41d4-a716-446655440000",
  "data": {
    "generate_time": [2021, 5, 20, 12, 31, 40, 0],
    "paper_id": "paper_001",
    "qq": "123456789"
  }
}
```

#### 4.3.7 查询用户历次考试成绩

**触发时机**：第三方客户端主动发送查询请求

##### 4.3.7.1 客户端发送查询请求

```json
{
  "type": "exam_records_query",
  "messageId": "550e8400-e29b-41d4-a716-446655440000",
  "data": {
    "qq": "123456789"
  }
}
```

**字段说明**：
- `qq`：要查询的 QQ 号（必填）

##### 4.3.7.2 服务端返回查询结果

```json
{
  "type": "exam_records_response",
  "messageId": "550e8400-e29b-41d4-a716-446655440000",
  "data": {
    "qq": "123456789",
    "records": [
      {
        "paper_id": "019d9fbb-e479-7f6b-a587-5348a1b23706",
        "score": 90.0,
        "status": "SUBMITTED",
        "generate_time": [2021, 5, 20, 12, 31, 40, 0],
        "submit_time": [2021, 5, 20, 12, 33, 20, 0]
      },
      {
        "paper_id": "019d9fbb-e479-7f6b-a587-5348a1b23707",
        "score": null,
        "status": "EXPIRED",
        "generate_time": [2021, 5, 19, 10, 20, 0, 0],
        "submit_time": null
      }
    ]
  }
}
```

**字段说明**：
- `qq`：查询的 QQ 号
- `records`：考试记录列表，按生成时间倒序排列
- `records[].paper_id`：试卷 ID（UUID 格式）
- `records[].score`：考试成绩，仅已完成提交的记录有值，未完成的记录为 `null`
- `records[].status`：考试状态，取值如下：
  - `ONGOING`：答题中
  - `SUBMITTED`：已提交
  - `MANUAL_INVALIDED`：手动作废
  - `EXPIRED`：已过期
  - `SIGN_UP_COMPLETED`：注册完成
  - `SCORE_INVALIDED`：成绩无效
- `records[].generate_time`：试卷生成时间
- `records[].submit_time`：试卷提交时间，未提交的记录为 `null`

##### 4.3.7.3 错误响应

当查询失败时，服务端返回错误消息：

```json
{
  "type": "error",
  "messageId": "550e8400-e29b-41d4-a716-446655440000",
  "data": "未找到该用户的考试记录"
}
```

## 5. 错误处理

服务端可能发送的错误消息：

```json
{
  "type": "error",
  "messageId": "550e8400-e29b-41d4-a716-446655440000",
  "data": "错误描述"
}
```

常见错误：
- 认证失败
- 无效消息格式
- 权限不足
- 服务器内部错误

## 6. 示例

### 6.1 完整连接认证流程

1. 客户端连接：`{protocol}://example.com:8080/api/websocket/thirdParty/550e8400-e29b-41d4-a716-446655440000`
2. 客户端发送认证消息（包含JWT Token）
3. 服务端发送认证成功结果
4. 服务端推送完整黑名单列表
5. 后续根据事件推送相关通知

### 6.2 QQ号验证流程

1. 服务端发送验证请求
2. 客户端处理验证（可能需要用户交互）
3. 客户端返回验证结果
4. 服务端根据验证结果执行相应操作

## 7. 注意事项

1. 客户端应实现自动重连机制，确保连接稳定性
2. 客户端应实现消息超时处理，特别是QQ号验证的2分钟超时
3. 服务端应支持多机器人同时连接，通过`sid`区分不同机器人
4. 所有消息应采用JSON格式，确保数据结构的一致性
5. 客户端在连接异常断开后应当进行重试，第一次间隔 5 秒后重试，第二次间隔 10 秒后进行重试，第三次间隔 1 分钟后进行重试，后续每间隔 5 分钟进行 1 次重试。客户端也可自行掌握验证时机。