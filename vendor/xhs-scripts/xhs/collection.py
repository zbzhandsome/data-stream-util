"""XHS 数据采集结果的统一 Schema。

XHSCollection 是 xhs-collect → ai-table → analysis-report 管道的标准数据契约。
所有下游 skill 均以此格式作为唯一输入，不关心数据来源（搜索 or 个人主页）。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class CollectionItemAuthor:
    user_id: str = ""
    nickname: str = ""

    def to_dict(self) -> dict:
        return {"userId": self.user_id, "nickname": self.nickname}


@dataclass
class CollectionItemInteract:
    liked_count: str = ""
    collected_count: str = ""
    comment_count: str = ""
    shared_count: str = ""

    def to_dict(self) -> dict:
        return {
            "likedCount": self.liked_count,
            "collectedCount": self.collected_count,
            "commentCount": self.comment_count,
            "sharedCount": self.shared_count,
        }


@dataclass
class CollectionItem:
    """单篇笔记的统一数据结构。

    基础字段（Feed 卡片即可获得，enrich=False 时填充）：
        id, xsec_token, title, type, author, interact, cover_url, url

    增强字段（需要 enrich-details 时填充，enrich=False 时为零值）：
        desc, publish_time, ip_location, image_count
    """

    # 基础字段
    id: str = ""
    xsec_token: str = ""
    title: str = ""
    type: str = ""  # "normal"（图文）| "video"
    author: CollectionItemAuthor = field(default_factory=CollectionItemAuthor)
    interact: CollectionItemInteract = field(default_factory=CollectionItemInteract)
    cover_url: str = ""
    url: str = ""  # 构造的页面访问链接

    # 增强字段（enrich-details 后填充）
    desc: str = ""
    publish_time: int = 0  # Unix 时间戳（秒），0 表示未获取
    ip_location: str = ""
    image_count: int = 0

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "xsecToken": self.xsec_token,
            "title": self.title,
            "type": self.type,
            "author": self.author.to_dict(),
            "interact": self.interact.to_dict(),
            "coverUrl": self.cover_url,
            "url": self.url,
            "desc": self.desc,
            "publishTime": self.publish_time,
            "ipLocation": self.ip_location,
            "imageCount": self.image_count,
        }

    @classmethod
    def from_feed(cls, feed) -> CollectionItem:
        """从 Feed 对象创建（仅填充基础字段）。"""
        from .urls import make_feed_detail_url

        nc = feed.note_card
        author = CollectionItemAuthor(
            user_id=nc.user.user_id,
            nickname=nc.user.nickname or nc.user.nick_name,
        )
        interact = CollectionItemInteract(
            liked_count=nc.interact_info.liked_count,
            collected_count=nc.interact_info.collected_count,
            comment_count=nc.interact_info.comment_count,
            shared_count=nc.interact_info.shared_count,
        )
        cover = nc.cover.url or nc.cover.url_default
        url = make_feed_detail_url(feed.id, feed.xsec_token) if feed.xsec_token else ""

        return cls(
            id=feed.id,
            xsec_token=feed.xsec_token,
            title=nc.display_title,
            type=nc.type,
            author=author,
            interact=interact,
            cover_url=cover,
            url=url,
        )

    def enrich_from_detail(self, detail) -> None:
        """用 FeedDetailResponse 填充增强字段（in-place 修改）。"""
        self.desc = detail.note.desc
        self.publish_time = detail.note.time
        self.ip_location = detail.note.ip_location
        self.image_count = len(detail.note.image_list)


@dataclass
class XHSCollection:
    """XHS 采集结果集合，下游 skill 的统一输入 schema。

    source 取值：
        "search"    — 来自关键词搜索
        "my_notes"  — 来自当前用户个人主页

    enriched：True 表示 items 已填充 desc / publish_time / ip_location / image_count。
    """

    collection_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    collected_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    )
    source: str = ""  # "search" | "my_notes"
    query: str = ""  # 搜索关键词（my_notes 时为空字符串）
    filters: dict = field(default_factory=dict)
    enriched: bool = False
    total: int = 0
    items: list[CollectionItem] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "collectionId": self.collection_id,
            "collectedAt": self.collected_at,
            "source": self.source,
            "query": self.query,
            "filters": self.filters,
            "enriched": self.enriched,
            "total": self.total,
            "items": [item.to_dict() for item in self.items],
        }

    @classmethod
    def from_feeds(
        cls,
        feeds: list,
        source: str,
        query: str = "",
        filters: dict | None = None,
        enriched: bool = False,
    ) -> XHSCollection:
        """从 Feed 列表快速构建 XHSCollection（基础字段）。"""
        items = [CollectionItem.from_feed(f) for f in feeds]
        return cls(
            source=source,
            query=query,
            filters=filters or {},
            enriched=enriched,
            total=len(items),
            items=items,
        )
