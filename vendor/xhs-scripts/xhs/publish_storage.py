"""发布内容数据持久化模块。

提供发布数据的提取、解析和本地存储功能。
"""

from __future__ import annotations

import contextlib
import datetime
import json
import logging
import os
from filelock import FileLock
import re
import threading
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class PublishData:
    """发布内容数据结构。"""

    id: str = field(default="")
    gmt_create: str = field(default="")
    gmt_modified: str = field(default="")
    uid: int = 0
    content: str = field(default="")
    publish_time: int = 0
    detail_url: str = field(default="")
    user_inputs: str = "[]"
    chat_list: str = "[]"
    title: str = field(default="")
    platform: str = "xiaohongshu"
    content_type: str | None = None
    topic_list: list[str] = field(default_factory=list)
    like_count: int = 0
    comment_count: int = 0
    collect_count: int = 0
    share_count: int = 0
    location: dict[str, float] | None = None
    address: str = field(default="")
    doc_id: str = field(default="")

    def to_dict(self) -> dict[str, Any]:
        """转换为 camelCase 字典格式，用于 JSON 序列化。"""
        return {
            "id": self.id,
            "gmtCreate": self.gmt_create,
            "gmtModified": self.gmt_modified,
            "uid": self.uid,
            "content": self.content,
            "publishTime": self.publish_time,
            "detailUrl": self.detail_url,
            "userInputs": self.user_inputs,
            "chatList": self.chat_list,
            "title": self.title,
            "platform": self.platform,
            "contentType": self.content_type,
            "topicList": self.topic_list,
            "likeCount": self.like_count,
            "commentCount": self.comment_count,
            "collectCount": self.collect_count,
            "shareCount": self.share_count,
            "location": self.location,
            "address": self.address,
            "docId": self.doc_id,
        }


# 存储根目录
STORAGE_DIR = os.path.expanduser("~/.dingclaw/xhs/publishContent")
PUBLISH_API_URL = "web_api/sns/v2/note"


def extract_request_data(
    request_data: dict[str, Any] | None,
) -> tuple[str, str, str | None]:
    """从请求对象中提取标题、正文和类型。

    Args:
        request_data: CDP 捕获的请求数据

    Returns:
        (title, desc, type) 标题、正文、类型
    """
    if not request_data:
        return "", "", None

    post_data = request_data.get("postData", "")
    if not post_data:
        return "", "", None

    try:
        data = json.loads(post_data)
    except json.JSONDecodeError:
        logger.warning("请求体不是有效的 JSON 格式")
        return "", "", None

    # 从 postData 中提取 title、desc、type
    # 实际请求体结构：
    # { "common": { "type": "video", "title": "xxx", "desc": "xxx", ... }, "video_info": {...} }
    # 也兼容其他可能的格式：
    # - 嵌套在 note 字段中：{"note": {"title": "xxx", "desc": "xxx", "type": "image"}}
    # - 直接字段：{"title": "xxx", "desc": "xxx", "type": "image"}
    common = data.get("common")
    if common and isinstance(common, dict):
        title = common.get("title", "")
        desc = common.get("desc", "")
        content_type = common.get("type")
        return title, desc, content_type

    note = data.get("note", data)
    title = note.get("title", "")
    desc = note.get("desc", "")
    content_type = note.get("type")

    return title, desc, content_type


def extract_response_data(response_data: dict[str, Any] | None) -> tuple[str, str]:
    """从响应对象中提取笔记 ID 和分享链接。

    Args:
        response_data: CDP 捕获的响应数据

    Returns:
        (doc_id, share_link) 笔记 ID、分享链接
    """
    if not response_data:
        return "", ""

    body = response_data.get("body", "")
    if not body:
        return "", ""

    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        logger.warning("响应体不是有效的 JSON 格式: %s", body[:100])
        return "", ""

    # 从响应中提取 id 和 share_link
    # 响应格式：{"success": true, "data": {"id": "xxx", ...}, "share_link": "xxx"}
    res_data = data.get("data", {})
    doc_id = res_data.get("id", "")
    share_link = data.get("share_link", "")

    return doc_id, share_link


def parse_topics(content: str) -> list[str]:
    """从正文中解析话题标签。

    提取以 # 开始到空格或字符串末尾的内容。

    Args:
        content: 笔记正文

    Returns:
        话题列表，如 ["美食", "北京"]
    """
    if not content:
        return []

    # 匹配 #开头到下一个空格或字符串末尾
    # 例如：#美食 #北京 的小吃 -> ["美食", "北京"]
    pattern = r"#(\S+)?"
    topics = re.findall(pattern, content)
    # 去重并保持顺序
    seen = set()
    result = []
    for topic in topics:
        if topic not in seen:
            seen.add(topic)
            result.append(topic)
    return result


def map_content_type(content_type: str | None) -> str | None:
    """映射内容类型到标准格式。

    Args:
        content_type: API 返回的类型（normal 或 video）

    Returns:
        textAndImage 或 textAndVideo，无效输入返回 None
    """
    if content_type == "normal":
        return "textAndImage"
    elif content_type == "video":
        return "textAndVideo"
    return None


def get_storage_path() -> str:
    """获取存储根目录路径。"""
    return STORAGE_DIR


def get_date_file_path(date_str: str | None = None) -> str:
    """获取日期对应的文件路径。

    Args:
        date_str: 日期字符串，格式为 YYYYMMDD。如果为 None 则使用当前日期。

    Returns:
        完整的文件路径
    """
    if date_str is None:
        date_str = datetime.datetime.now().strftime("%Y%m%d")

    # 确保目录存在
    os.makedirs(STORAGE_DIR, exist_ok=True)

    return os.path.join(STORAGE_DIR, f"{date_str}.json")


def _read_existing_data(file_path: str) -> list[dict[str, Any]]:
    """读取已存在的数据文件。

    Args:
        file_path: JSON 文件路径

    Returns:
        现有数据数组，如果文件不存在则返回空列表
    """
    if not os.path.exists(file_path):
        return []

    try:
        with open(file_path, encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                return data
            logger.warning("现有数据格式不是数组: %s", file_path)
            return []
    except json.JSONDecodeError as e:
        logger.warning("解析现有数据失败: %s", e)
        return []
    except Exception as e:
        logger.error("读取现有数据失败: %s", e)
        return []


def _write_data(file_path: str, data: list[dict[str, Any]]) -> bool:
    """写入数据到文件（使用文件锁保护，跨平台兼容）。

    Args:
        file_path: JSON 文件路径
        data: 要写入的数据数组

    Returns:
        写入是否成功
    """
    temp_path = f"{file_path}.tmp"
    try:
        lock_path = f"{file_path}.lock"
        with FileLock(lock_path):
            # 临时文件方式确保原子性
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

            # 原子替换原文件
            os.replace(temp_path, file_path)
        return True
    except Exception as e:
        logger.error("写入数据失败: %s", e)
        # 清理临时文件
        with contextlib.suppress(Exception):
            if os.path.exists(temp_path):
                os.remove(temp_path)
        return False


def save_publish_data(publish_data: PublishData) -> bool:
    """保存发布数据。

    将新数据插入到日期文件数组的头部。

    Args:
        publish_data: 发布数据对象

    Returns:
        保存是否成功
    """
    if not publish_data.doc_id:
        logger.warning("笔记 ID 为空，跳过保存")
        return False

    try:
        # 获取文件路径
        file_path = get_date_file_path()

        # 读取现有数据
        existing_data = _read_existing_data(file_path)

        # 生成主键 ID（使用时间戳 + 随机数）
        now_dt = datetime.datetime.now()
        timestamp = int(now_dt.timestamp() * 1000)
        random_suffix = threading.get_ident() % 10000
        publish_data.id = f"{timestamp}{random_suffix:04d}"

        # 设置时间戳
        now_str = now_dt.strftime("%Y-%m-%d %H:%M:%S")
        publish_data.gmt_create = now_str
        publish_data.gmt_modified = now_str
        publish_data.publish_time = timestamp

        # 插入到数组头部
        new_data = [publish_data.to_dict(), *existing_data]

        # 写入文件
        return _write_data(file_path, new_data)

    except Exception as e:
        logger.error("保存发布数据失败: %s", e, exc_info=True)
        return False


def build_publish_data(
    title: str,
    desc: str,
    content_type: str | None,
    doc_id: str,
    detail_url: str,
) -> PublishData:
    """构建发布数据对象。

    Args:
        title: 笔记标题
        desc: 笔记正文
        content_type: 内容类型
        doc_id: 笔记 ID
        detail_url: 详情链接

    Returns:
        PublishData 对象
    """
    return PublishData(
        title=title or "",
        content=desc or "",
        content_type=map_content_type(content_type),
        doc_id=doc_id or "",
        detail_url=detail_url or "",
        topic_list=parse_topics(desc or ""),
        publish_time=int(datetime.datetime.now().timestamp() * 1000),
    )
