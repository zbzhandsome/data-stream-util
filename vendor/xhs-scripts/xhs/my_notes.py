"""获取当前登录用户自己发布的笔记列表。

不需要外部传入 user_id / xsec_token：先从首页 __INITIAL_STATE__ 提取真实 user_id，
再导航到真实主页；若提取失败则扫描页面 DOM 中的个人主页链接作为备选。"""

from __future__ import annotations

import json
import logging
import time

from .cdp import Page
from .types import Feed

logger = logging.getLogger(__name__)

# 从 __INITIAL_STATE__ 提取当前登录用户 ID，尝试多条路径（前端版本差异）
_EXTRACT_MY_USER_ID_JS = """
(() => {
    const state = window.__INITIAL_STATE__;
    if (!state) return "";
    const paths = [
        () => { const v = state.user && state.user.userInfo; return (v && v.value) || (v && v._value) || null; },
        () => state.user && state.user.me,
        () => state.me && state.me.userInfo,
    ];
    for (const fn of paths) {
        try {
            const result = fn();
            if (result && typeof result === "object" && result.userId) {
                return result.userId;
            }
        } catch(e) {}
    }
    return "";
})()
"""

# 从页面 DOM 中查找当前用户的真实主页链接（fallback：__INITIAL_STATE__ 提取失败时使用）
_FIND_PROFILE_LINK_JS = r"""
(() => {
    const links = document.querySelectorAll('a[href*="/user/profile/"]');
    for (const link of links) {
        const href = link.getAttribute('href');
        if (href && /\/user\/profile\/[0-9a-f]{16,}/.test(href)) {
            return href;
        }
    }
    return "";
})()
"""

# 侧边栏头像区域选择器（最终兜底：点击跳转主页）
_SIDEBAR_AVATAR_SELECTOR = ".main-container .user .avatar-wrapper, .main-container .user a.avatar"

# 复用 user_profile.py 中已验证的笔记提取 JS（路径相同）
_EXTRACT_USER_NOTES_JS = """
(() => {
    if (window.__INITIAL_STATE__ &&
        window.__INITIAL_STATE__.user &&
        window.__INITIAL_STATE__.user.notes) {
        const notes = window.__INITIAL_STATE__.user.notes;
        const data = notes.value !== undefined ? notes.value : notes._value;
        if (data) {
            return JSON.stringify(data);
        }
    }
    return "";
})()
"""


def get_my_user_id(page: Page) -> str:
    """获取当前登录用户的 user_id。

    导航到首页让 __INITIAL_STATE__ 完成初始化，然后从中提取用户 ID。

    Raises:
        RuntimeError: 未登录或无法提取 user_id。
    """
    from .urls import HOME_URL

    page.navigate(HOME_URL)
    page.wait_for_load()
    _wait_for_initial_state(page)

    user_id = page.evaluate(_EXTRACT_MY_USER_ID_JS)
    if user_id and isinstance(user_id, str) and user_id.strip():
        return user_id.strip()

    raise RuntimeError("无法从 __INITIAL_STATE__ 提取当前用户 ID，请确认已登录")


def _resolve_my_profile_url(page: Page) -> str:
    """解析当前登录用户真实主页 URL。

    优先从首页 __INITIAL_STATE__ 提取 user_id；失败时扫描页面 DOM
    中含 /user/profile/{hex_id} 格式的链接；均失败则尝试点击侧边栏头像等待跳转。

    Raises:
        RuntimeError: 无法确定个人主页 URL。
    """
    from .urls import HOME_URL

    page.navigate(HOME_URL)
    page.wait_for_load()
    _wait_for_initial_state(page)

    # 1) 从 __INITIAL_STATE__ 提取 user_id
    user_id = page.evaluate(_EXTRACT_MY_USER_ID_JS)
    if user_id and isinstance(user_id, str) and user_id.strip():
        return f"https://www.xiaohongshu.com/user/profile/{user_id.strip()}"

    # 2) 扫描页面 DOM 中的个人主页锚链接
    href = page.evaluate(_FIND_PROFILE_LINK_JS)
    if href and isinstance(href, str) and href.strip():
        h = href.strip()
        return h if h.startswith("http") else f"https://www.xiaohongshu.com{h}"

    # 3) 兜底：点击左下角头像，等待跳转，读取当前 URL
    logger.warning("无法从状态/DOM 提取主页链接，尝试点击侧边栏头像")
    page.click_element(_SIDEBAR_AVATAR_SELECTOR)
    import time as _time
    _time.sleep(2.0)
    current_url: str = page.evaluate("window.location.href") or ""
    if "/user/profile/" in current_url:
        return current_url

    raise RuntimeError(
        "无法确定当前用户的个人主页地址，请确认已登录，"
        "或在浏览器中手动打开小红书个人主页后重试"
    )


def get_my_notes(page: Page) -> list[Feed]:
    """获取当前登录用户自己发布的笔记列表。

    自动解析当前登录用户的真实主页 URL（不依赖 /user/profile/me 重定向），
    无需在外部传入 user_id 或 xsec_token。

    Returns:
        Feed 列表（仅包含笔记卡片字段，不含正文/评论等详情）。

    Raises:
        RuntimeError: 未登录或数据提取失败。
    """
    profile_url = _resolve_my_profile_url(page)
    logger.info("导航到个人主页: %s", profile_url)

    page.navigate(profile_url)
    page.wait_for_load()
    page.wait_dom_stable()
    _wait_for_initial_state(page)

    notes_result = page.evaluate(_EXTRACT_USER_NOTES_JS)
    if not notes_result:
        raise RuntimeError(
            "无法提取个人笔记，请检查是否已登录；"
            "也可尝试手动在浏览器中打开小红书个人主页后重试"
        )

    notes_feeds_raw = json.loads(notes_result)
    feeds: list[Feed] = []
    for feed_group in notes_feeds_raw:
        if isinstance(feed_group, list):
            for f in feed_group:
                feeds.append(Feed.from_dict(f))
        elif isinstance(feed_group, dict):
            feeds.append(Feed.from_dict(feed_group))

    return feeds


def _wait_for_initial_state(page: Page, timeout: float = 10.0) -> None:
    """等待 __INITIAL_STATE__ 就绪。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        ready = page.evaluate("window.__INITIAL_STATE__ !== undefined")
        if ready:
            return
        time.sleep(0.5)
    logger.warning("等待 __INITIAL_STATE__ 超时")
