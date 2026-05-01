"""Welcome message handler for new group members."""
import time
from datetime import datetime
from typing import List, Optional, Tuple, Union

from loguru import logger
from nonebot.adapters.onebot.v11 import Bot

from .config import WelcomeMessageConfig


class WelcomeMessageHandler:
    """Handles welcome message generation and sending for new group members."""

    def __init__(self, config: WelcomeMessageConfig):
        self.config = config

    def is_enabled(self) -> bool:
        """Check if welcome message feature is enabled."""
        return self.config.enabled

    def format_time_array(self, time_array: Optional[Union[List[int], Tuple[int, ...]]]) -> str:
        """Format a time array to human-readable datetime string."""
        if not time_array or not isinstance(time_array, (list, tuple)):
            return "未知"
        try:
            year = time_array[0]
            month = time_array[1]
            day = time_array[2]
            hour = time_array[3]
            minute = time_array[4]
            second = time_array[5] if len(time_array) > 5 else 0
            dt = datetime(year, month, day, hour, minute, second)
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        except (IndexError, TypeError, ValueError) as e:
            logger.error(f"Time array format error: {e}, data: {time_array}")
            return "未知"

    def calculate_duration(self, generate_time_array: Optional[List[int]], submit_time_array: Optional[List[int]]) -> str:
        """Calculate and format duration between generate and submit times."""
        try:
            if not generate_time_array or not submit_time_array:
                return "未知"

            gen_dt = datetime(
                generate_time_array[0],
                generate_time_array[1],
                generate_time_array[2],
                generate_time_array[3],
                generate_time_array[4],
                generate_time_array[5] if len(generate_time_array) > 5 else 0
            )

            sub_dt = datetime(
                submit_time_array[0],
                submit_time_array[1],
                submit_time_array[2],
                submit_time_array[3],
                submit_time_array[4],
                submit_time_array[5] if len(submit_time_array) > 5 else 0
            )

            delta = sub_dt - gen_dt
            total_seconds = int(delta.total_seconds())

            if total_seconds < 0:
                return "未知"

            days = total_seconds // 86400
            remaining_seconds = total_seconds % 86400
            hours = remaining_seconds // 3600
            remaining_seconds = remaining_seconds % 3600
            minutes = remaining_seconds // 60
            seconds = remaining_seconds % 60

            parts = []
            if days > 0:
                parts.append(f"{days}天")
            if hours > 0:
                parts.append(f"{hours}小时")
            if minutes > 0:
                parts.append(f"{minutes}分")
            parts.append(f"{seconds}秒")

            return "".join(parts)
        except (IndexError, TypeError, ValueError) as e:
            logger.error(f"Duration calculation error: {e}")
            return "未知"

    def generate_welcome_message(self, paper_data: dict) -> str:
        """Generate welcome message by replacing variables in template."""
        if not self.is_enabled():
            logger.debug("Welcome message feature is disabled")
            return ""

        generate_time = self.format_time_array(paper_data.get("generate_time"))
        submit_time = self.format_time_array(paper_data.get("submit_time"))
        paper_id = paper_data.get("paper_id", "未知") or "未知"
        score = paper_data.get("score")
        answer_count = paper_data.get("answer_count", "未知")

        if score is not None:
            try:
                score_str = f"{float(score):.1f}"
            except (ValueError, TypeError):
                score_str = "未知"
        else:
            score_str = "未知"

        if answer_count is not None:
            try:
                answer_count_str = str(int(answer_count))
            except (ValueError, TypeError):
                answer_count_str = "未知"
        else:
            answer_count_str = "未知"

        duration = self.calculate_duration(
            paper_data.get("generate_time"),
            paper_data.get("submit_time")
        )

        variables = {
            "generate_time": generate_time,
            "submit_time": submit_time,
            "paper_id": paper_id,
            "score": score_str,
            "answer_count": answer_count_str,
            "duration": duration,
        }

        try:
            message = self.config.template.format(**variables)
            logger.info(f"Generated welcome message for paper {paper_id}")
            return message
        except KeyError as e:
            logger.error(f"Missing variable in template: {e}")
            return ""
        except Exception as e:
            logger.error(f"Error generating welcome message: {e}")
            return ""

    async def send_welcome_message(
        self,
        bot: Bot,
        group_id: int,
        paper_data: dict
    ) -> bool:
        """Send welcome message to group if feature is enabled."""
        if not self.is_enabled():
            return False

        message = self.generate_welcome_message(paper_data)
        if not message:
            return False

        try:
            await bot.send_group_msg(
                group_id=group_id,
                message=message
            )
            logger.info(f"Welcome message sent to group {group_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to send welcome message to group {group_id}: {e}")
            return False
