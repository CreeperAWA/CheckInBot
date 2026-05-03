import nonebot
from nonebot import on_command
from nonebot.adapters.onebot.v11 import MessageSegment, GroupMessageEvent
from nonebot.plugin import PluginMetadata
from nonebot.log import logger
from nonebot.exception import FinishedException

import asyncio
import time
import json
import os
from datetime import datetime, timedelta
from threading import Thread
from pathlib import Path

from .mqtt_client import main as seewo_query

__plugin_meta__ = PluginMetadata(
    name="希沃管家版本查询",
    description="通过 IoT 平台查询最新希沃管家 Windows 版本号",
    usage="发送 /HugoWinVer 进行查询",
    type="application",
    supported_adapters={"~onebot.v11"},
)

# 配置
CHECK_INTERVAL_MINUTES = 60  # 检查间隔（分钟），可修改
DATA_FILE = Path(__file__).parent / "version_data.json"  # 数据存储文件

# 全局变量
check_task = None
last_check_time = None
current_version = None
is_first_check = True  # 标记是否首次启动检查

class VersionData:
    """版本数据管理类"""
    
    def __init__(self, data_file):
        self.data_file = data_file
        self.data = {
            "last_check_time": None,  # 上次检查时间（ISO格式）
            "current_version": None,   # 当前已知版本
            "last_update_time": None   # 上次更新时间
        }
        self.load()
    
    def load(self):
        """加载本地数据"""
        if self.data_file.exists():
            try:
                with open(self.data_file, 'r', encoding='utf-8') as f:
                    loaded_data = json.load(f)
                    self.data.update(loaded_data)
                    logger.info(f"已加载版本数据: 当前版本={self.data['current_version']}, 上次检查={self.data['last_check_time']}")
            except Exception as e:
                logger.error(f"加载版本数据失败: {e}")
        else:
            logger.info("未找到版本数据文件，将创建新文件")
    
    def save(self):
        """保存数据到本地"""
        try:
            self.data_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.data_file, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
            logger.debug("版本数据已保存")
        except Exception as e:
            logger.error(f"保存版本数据失败: {e}")
    
    def update_check_time(self):
        """更新检查时间"""
        self.data["last_check_time"] = datetime.now().isoformat()
        self.save()
    
    def update_version(self, new_version):
        """更新版本号"""
        old_version = self.data["current_version"]
        self.data["current_version"] = new_version
        self.data["last_update_time"] = datetime.now().isoformat()
        self.save()
        return old_version
    
    def get_last_check_time(self):
        """获取上次检查时间"""
        if self.data["last_check_time"]:
            return datetime.fromisoformat(self.data["last_check_time"])
        return None
    
    def get_current_version(self):
        """获取当前保存的版本"""
        return self.data["current_version"]
    
    def should_check(self):
        """判断是否需要检查（基于时间间隔）"""
        last_check = self.get_last_check_time()
        if last_check is None:
            return True
        time_diff = datetime.now() - last_check
        return time_diff.total_seconds() >= CHECK_INTERVAL_MINUTES * 60

# 全局数据实例
version_data = VersionData(DATA_FILE)

async def check_version_and_notify(bot, is_auto_check=False):
    """
    检查版本并发送通知
    is_auto_check: 是否为自动检查（True: 自动检查, False: 手动触发）
    返回: (success, version, is_updated)
    """
    global current_version
    
    try:
        # 执行查询
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, seewo_query)
        
        if result.get("success"):
            new_version = result["data"]["latestVersion"]
            old_version = version_data.get_current_version()
            
            # 更新检查时间
            version_data.update_check_time()
            
            # 判断是否有更新
            is_updated = False
            if old_version is None:
                # 首次获取版本
                version_data.update_version(new_version)
                logger.info(f"首次获取到版本: {new_version}")
            if new_version != old_version:
                # 发现新版本
                version_data.update_version(new_version)
                is_updated = True
                logger.info(f"发现新版本! 旧版本: {old_version} -> 新版本: {new_version}")
                
                # 如果是自动检查且有更新，发送通知
                if is_auto_check and bot:
                    await send_update_notification(bot, old_version, new_version)
            else:
                logger.debug(f"版本无变化: {new_version}")
            
            return True, new_version, is_updated
        else:
            error_msg = result.get("error", "未知错误")
            logger.error(f"版本检查失败: {error_msg}")
            return False, None, False
            
    except Exception as e:
        logger.exception(f"版本检查异常")
        return False, None, False

async def send_update_notification(bot, old_version, new_version):
    """发送更新通知到所有群组"""
    try:
        # 获取所有群组列表
        # group_list = await bot.get_group_list()
        group_list = [116575829, 640265417]
        
        notification_msg = (
            f"== 希沃管家Windows版本更新通知 ==\n"
            f"旧版本: {old_version}\n"
            f"新版本: {new_version}\n"
            f"发送 /HugoWinVer 可查询最新版本"
        )
        
        for group in group_list:
            #group_id = group["group_id"] # 用bot.get_group_list()时使用
            group_id = group
            try:
                await bot.send_group_msg(group_id=group_id, message=notification_msg)
                logger.info(f"已向群组 {group_id} 发送更新通知")
                await asyncio.sleep(0.5)  # 避免风控
            except Exception as e:
                logger.error(f"向群组 {group_id} 发送通知失败: {e}")
                
    except Exception as e:
        logger.error(f"发送更新通知失败: {e}")

async def periodic_check(bot):
    """定时检查任务"""
    global is_first_check
    
    # 启动时立即检查一次（如果超过间隔时间或首次启动）
    if version_data.should_check() or is_first_check:
        logger.info("执行启动检查...")
        await check_version_and_notify(bot, is_auto_check=True)
        is_first_check = False
    else:
        last_check = version_data.get_last_check_time()
        logger.info(f"距离上次检查未满{CHECK_INTERVAL_MINUTES}分钟，跳过启动检查。上次检查: {last_check}")
    
    # 进入循环定时检查
    while True:
        try:
            # 等待指定时间
            await asyncio.sleep(CHECK_INTERVAL_MINUTES * 60)
            
            logger.info(f"执行定时版本检查 (间隔: {CHECK_INTERVAL_MINUTES}分钟)")
            await check_version_and_notify(bot, is_auto_check=True)
            
        except asyncio.CancelledError:
            logger.info("定时检查任务已取消")
            break
        except Exception as e:
            logger.exception(f"定时检查任务出错")
            # 继续运行，不中断任务

# NoneBot 启动时的处理
@nonebot.get_driver().on_bot_connect
async def start_periodic_check():
    """在机器人启动时启动定时检查任务"""
    global check_task
    
    if check_task and not check_task.done():
        return
    
    # 获取 bot 实例（需要等待 bot 连接）
    # 使用延迟获取 bot 的方式
    async def wait_and_start():
        await asyncio.sleep(5)  # 等待 bot 完全启动
        bots = nonebot.get_bots()
        if bots:
            bot = list(bots.values())[0]
            logger.info(f"启动版本定时检查任务 (间隔: {CHECK_INTERVAL_MINUTES}分钟)")
            check_task = asyncio.create_task(periodic_check(bot))
        else:
            logger.warning("未找到可用的 Bot 实例，定时检查任务启动失败")
    
    asyncio.create_task(wait_and_start())

@nonebot.get_driver().on_shutdown
async def stop_periodic_check():
    """在机器人关闭时停止定时检查任务"""
    global check_task
    if check_task and not check_task.done():
        check_task.cancel()
        try:
            await check_task
        except asyncio.CancelledError:
            pass
        logger.info("定时检查任务已停止")

# 命令处理器
hugo_version_cmd = on_command(
    "HugoWinVer",
    aliases={"希沃版本", "管家版本"},
    priority=5,
    block=True,
)

@hugo_version_cmd.handle()
async def handle_hugo_version(event: GroupMessageEvent):
    """手动查询版本命令"""
    # 获取 bot 实例
    bot = nonebot.get_bot()
    
    # 告知用户已开始
    await hugo_version_cmd.send("正在查询Windows版最新希沃管家版本，请稍候...")
    
    try:
        # 手动触发检查（is_auto_check=False，不会发送更新通知）
        success, version, is_updated = await check_version_and_notify(bot, is_auto_check=False)
        
        if success:
            # 如果手动检查发现有更新，静默更新本地存储（不额外通知）
            if is_updated:
                logger.info(f"手动触发发现新版本，已更新本地存储: {version}")
            
            # 回复版本信息（保持不变）
            await hugo_version_cmd.finish(
                MessageSegment.at(event.user_id) + 
                f"\n 希沃管家Windows版最新版本: {version}"
            )
        else:
            await hugo_version_cmd.finish(
                MessageSegment.at(event.user_id) + f"\n❌ 查询失败: {version if version else '未知错误'}"
            )
            
    except FinishedException:
        raise
    except Exception as e:
        logger.exception(f"希沃版本查询运行时异常")
        await hugo_version_cmd.finish(
            MessageSegment.at(event.user_id) + f"\n❌ 异常: {type(e).__name__}: {str(e)}"
        )

# 可选：添加一个管理员命令来修改检查间隔
set_interval_cmd = on_command("设置希沃检查间隔", priority=5, block=True)

@set_interval_cmd.handle()
async def handle_set_interval(event: GroupMessageEvent):
    """设置检查间隔（仅限管理员）"""
    # 这里可以添加管理员权限检查
    try:
        msg = str(event.get_message()).strip()
        # 解析数字
        import re
        match = re.search(r'(\d+)', msg)
        if match:
            minutes = int(match.group(1))
            if 5 <= minutes <= 1440:  # 限制在5分钟到24小时之间
                global CHECK_INTERVAL_MINUTES
                CHECK_INTERVAL_MINUTES = minutes
                await set_interval_cmd.finish(
                    MessageSegment.at(event.user_id) + 
                    f"\n✅ 检查间隔已设置为 {minutes} 分钟"
                )
            else:
                await set_interval_cmd.finish(
                    MessageSegment.at(event.user_id) + 
                    "\n❌ 间隔时间必须在 5-1440 分钟之间"
                )
        else:
            await set_interval_cmd.finish(
                MessageSegment.at(event.user_id) + 
                f"\n当前检查间隔: {CHECK_INTERVAL_MINUTES} 分钟\n使用格式: 设置希沃检查间隔 [分钟数]"
            )
    except Exception as e:
        await set_interval_cmd.finish(f"❌ 设置失败: {e}")
