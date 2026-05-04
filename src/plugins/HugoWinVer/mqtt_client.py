import paho.mqtt.client as mqtt
import ssl
import json
import time
import logging
import random

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

# ========== 核心配置 ==========
BROKER = "iot-broker-mis.seewo.com"
PORT = 8883
DEVICE_ID = "1226264878715764736"  # ✅ 您的设备ID
CLIENT_ID = DEVICE_ID
USERNAME = f"{DEVICE_ID}_68764AB3AE54417DD1BAC785376168F4"
PASSWORD = "BE68555584DACEAF58633FCC1F4F71E1"

# ========== 主题配置 ==========
# 订阅主题（使用 + 通配符）
SUBSCRIBE_TOPICS = [
    f"/sys/1_76f4349916d/{DEVICE_ID}/rpc/request/+",
    f"/sys/1_76f4349916d/{DEVICE_ID}/up/response/+"
]

# 发布主题 - 根据您提供的格式替换设备ID
# 原示例: /sys/1_76f4349916d/1266166986950455296/up/request/9
#PUBLISH_TOPIC = f"/sys/1_76f4349916d/{DEVICE_ID}/up/request/10"  # ✅ 已替换设备ID 1266166986950455296
PUBLISH_TOPIC = f"/sys/1_76f4349916d/1266166986950455296/up/request/11"

# 状态标记
reply_received = False
received_payload = None

# ========== 回调函数 ==========
def on_connect(client, userdata, flags, rc):
    """连接成功回调"""
    if rc == 0:
        logger.info("✅ MQTT 连接成功！")
        # 订阅主题
        for topic in SUBSCRIBE_TOPICS:
            result, mid = client.subscribe(topic, qos=0)
            if result == mqtt.MQTT_ERR_SUCCESS:
                logger.info(f"📬 订阅请求已发送: {topic}")
            else:
                logger.error(f"❌ 订阅失败: {topic}, 错误码: {result}")
    else:
        conn_errors = {
            1: "错误的协议版本", 2: "无效的客户端标识", 3: "服务器不可用",
            4: "用户名或密码错误", 5: "未授权"
        }
        logger.error(f"❌ 连接失败: {conn_errors.get(rc, f'未知错误码 {rc}')}")

def on_message(client, userdata, msg):
    """收到消息回调"""
    global reply_received, received_payload
    logger.info(f"📨 收到消息 - 主题: {msg.topic}")
    try:
        payload = json.loads(msg.payload.decode('utf-8'))
        logger.info(f"📄 内容:\n{json.dumps(payload, indent=2, ensure_ascii=False)}")
        received_payload = payload
        reply_received = True
    except json.JSONDecodeError:
        logger.warning(f"⚠️  非JSON消息: {msg.payload.decode('utf-8', errors='ignore')}")
        reply_received = True
    except Exception as e:
        logger.error(f"❌ 处理消息异常: {e}")

def on_subscribe(client, userdata, mid, granted_qos):
    """订阅确认回调"""
    logger.info(f"✅ 订阅确认，QoS: {granted_qos}")

def on_disconnect(client, userdata, rc):
    """断开连接回调"""
    logger.warning(f"⚠️  连接断开，返回码: {rc}")

def on_publish(client, userdata, mid):
    """消息发布成功回调"""
    logger.info(f"✅ 消息发布成功，mid: {mid}")

def parse_response(response: dict):
    """解析响应，返回版本号或错误信息"""
    code = response.get('code')
    if str(code) in ("200", "0", "000000"):
        data = response.get('data', {})
        version = data.get('latestVersion')
        if not version and isinstance(data.get('attrs'), dict):
            version = data['attrs'].get('latestVersion')

        if version:
            return {"success": True, "data": {"latestVersion": version, "updateTime": data.get('updateTime', '未知')}}
        return {"success": False, "error": "响应中未找到版本号"}
    else:
        msg = response.get('msg', response.get('message', '未知错误'))
        return {"success": False, "error": f"平台返回错误({code}): {msg}"}

# ========== 主函数 ==========
def main():
    global reply_received, received_payload

    # 创建客户端 (MQTT 3.1.1)
    client = mqtt.Client(
        client_id=CLIENT_ID,
        clean_session=False,  # ✅ 关闭 Clean Session
        protocol=mqtt.MQTTv311
    )

    # ✅ 关闭自动重连
    client.reconnect_delay_set(min_delay=120, max_delay=120)
    client._auto_reconnect = False

    # 设置回调
    client.on_connect = on_connect
    client.on_message = on_message
    client.on_subscribe = on_subscribe
    client.on_disconnect = on_disconnect
    client.on_publish = on_publish

    # 设置认证
    client.username_pw_set(USERNAME, PASSWORD)

    # ✅ 配置 MQTTS + 禁用SSL验证（测试环境）
    client.tls_set(
        ca_certs=None,
        certfile=None,
        keyfile=None,
        cert_reqs=ssl.CERT_NONE,
        tls_version=ssl.PROTOCOL_TLS_CLIENT
    )
    client.tls_insecure_set(True)  # ✅ 禁用主机名验证

    try:
        # 连接
        logger.info(f"🔌 正在连接 {BROKER}:{PORT} (MQTTS)...")
        client.connect(BROKER, port=PORT, keepalive=60)
        client.loop_start()

        TraceID = ''.join(random.choices('0123456789abcdef', k=16))

        # 消息内容
        MESSAGE = {
            "method": "thing.property.get",
            "params": {
                "attrs": ["latestVersion"]
            },
            "traceId": TraceID,
            "version": "1.2.6"
        }

        # 等待连接和订阅完成
        time.sleep(3)

        if client.is_connected():
            # 发送消息
            payload_str = json.dumps(MESSAGE, ensure_ascii=False)
            logger.info(f"📤 发送消息到: {PUBLISH_TOPIC}")
            logger.info(f"📦 内容: {payload_str}")

            result = client.publish(
                topic=PUBLISH_TOPIC,
                payload=payload_str,
                qos=0
            )

            if result.rc == mqtt.MQTT_ERR_SUCCESS:
                logger.info("✅ 消息已进入发送队列")
            else:
                logger.error(f"❌ 发送失败，错误码: {result.rc}")
                return {"success": False, "error": f"发送失败: {result.rc}"}

            # 等待回复
            logger.info("⏳ 等待服务器回复 (最多30秒)...")
            timeout = 30
            start = time.time()

            while not reply_received and (time.time() - start) < timeout:
                time.sleep(0.3)

            # 输出结果 - 使用新的解析逻辑
            if reply_received and received_payload:
                parse_result = parse_response(received_payload)
                if parse_result["success"]:
                    print("\n" + "="*60)
                    print("🎉 成功收到回复！")
                    print(json.dumps(received_payload, indent=2, ensure_ascii=False))
                    print("="*60)
                    return parse_result
                else:
                    print("\n" + "="*60)
                    print(f"❌ 解析失败: {parse_result['error']}")
                    print(json.dumps(received_payload, indent=2, ensure_ascii=False))
                    print("="*60)
                    return parse_result
            elif reply_received and not received_payload:
                print("\n" + "="*60)
                print("🎉 收到回复，但无法解析为JSON")
                print("="*60)
                return {"success": False, "error": "收到回复，但无法解析为JSON"}
            else:
                print("\n" + "="*60)
                print("⏰ 等待超时，未收到回复")
                print("💡 请检查:")
                print("   1. 发布主题是否正确")
                print("   2. 设备是否已激活/授权")
                print("   3. 平台是否支持 thing.property.get 方法")
                print("="*60)
                return {"success": False, "error": "等待超时"}
        else:
            logger.error("❌ 客户端未连接成功")
            return {"success": False, "error": "客户端未连接成功"}

    except ssl.SSLError as e:
        logger.error(f"🔐 SSL/TLS 错误: {e}")
        return {"success": False, "error": f"SSL/TLS错误: {e}"}
    except Exception as e:
        logger.error(f"❌ 运行时异常: {type(e).__name__}: {e}")
        return {"success": False, "error": f"{type(e).__name__}: {e}"}
    finally:
        logger.info("🔚 正在清理资源...")
        client.loop_stop()
        client.disconnect()
        time.sleep(1)

if __name__ == "__main__":
    last_version = main()
    logger.info(f"🎯 返回结果: {last_version}")
    if last_version and last_version.get("success"):
        logger.info(f"✅ latestVersion: {last_version['data']['latestVersion']}")
