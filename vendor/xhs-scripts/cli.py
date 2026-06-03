#!/opt/homebrew/bin/python3.12
"""统一 CLI 入口，对应 Go MCP 工具的 13 个子命令。

全局选项: --host, --port, --account
输出: JSON（ensure_ascii=False）
退出码: 0=成功, 1=未登录, 2=错误
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

# Windows 控制台默认编码（如 cp1252）不支持中文，强制 UTF-8
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("xhs-cli")
UTC = timezone.utc


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _safe_int(value: object, default: int = 0) -> int:
    if value is None:
        return default
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return default
        digits = "".join(ch for ch in raw if ch.isdigit())
        if not digits:
            return default
        try:
            return int(digits)
        except ValueError:
            return default
    return default


def _sync_to_store_user_db(profile_dict: dict, account: str, fallback_user_id: str = "") -> None:
    """将 user-profile / my-profile 结果同步到统一本地用户库。"""
    basic = profile_dict.get("basicInfo", {}) or {}
    interactions = profile_dict.get("interactions", []) or []
    feeds = profile_dict.get("feeds", []) or []
    if not isinstance(feeds, list):
        feeds = []

    follow_count = 0
    fans_count = 0
    likes_count = 0
    note_count = len(feeds)
    for item in interactions:
        if not isinstance(item, dict):
            continue
        item_type = str(item.get("type", "")).lower()
        item_name = str(item.get("name", "")).lower()
        count = _safe_int(item.get("count", 0))
        if item_type in {"follows", "follow"} or "关注" in item_name:
            follow_count = count
        elif item_type in {"fans", "fan"} or "粉丝" in item_name:
            fans_count = count
        elif item_type in {"likes", "like", "liked"} or "赞" in item_name:
            likes_count = count
        elif "笔记" in item_name:
            note_count = count

    user_id = ""
    if feeds and isinstance(feeds[0], dict):
        user_id = str((feeds[0].get("user", {}) or {}).get("userId", "") or "")
    if not user_id:
        user_id = fallback_user_id or ""
    if not user_id:
        return

    db_path = Path.home() / ".dingclaw" / "store-onboarding" / "data" / "user_profiles.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    now = _now_iso()
    row = (
        "xiaohongshu",
        user_id,
        account or "default",
        str(basic.get("nickname", "") or ""),
        "",
        "",
        str(basic.get("redId", "") or ""),
        "",
        "",
        str(basic.get("desc", "") or ""),
        str(basic.get("ipLocation", "") or ""),
        _safe_int(basic.get("gender", 0)),
        follow_count,
        fans_count,
        likes_count,
        note_count,
        0,
        None,
        "xhs-explore:user-profile",
        json.dumps(profile_dict, ensure_ascii=False),
        now,
        now,
    )
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS user_profiles (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                platform       TEXT NOT NULL,
                user_id        TEXT NOT NULL,
                account        TEXT NOT NULL DEFAULT 'default',
                nickname       TEXT DEFAULT '',
                sec_uid        TEXT DEFAULT '',
                unique_id      TEXT DEFAULT '',
                red_id         TEXT DEFAULT '',
                avatar         TEXT DEFAULT '',
                signature      TEXT DEFAULT '',
                desc           TEXT DEFAULT '',
                ip_location    TEXT DEFAULT '',
                gender         INTEGER DEFAULT 0,
                follows_count  INTEGER DEFAULT 0,
                fans_count     INTEGER DEFAULT 0,
                likes_count    INTEGER DEFAULT 0,
                notes_count    INTEGER DEFAULT 0,
                videos_count   INTEGER DEFAULT 0,
                last_seen_at   INTEGER,
                source         TEXT DEFAULT '',
                raw_json       TEXT DEFAULT '',
                created_at     TEXT NOT NULL,
                updated_at     TEXT NOT NULL,
                UNIQUE(platform, user_id, account)
            )
            """
        )
        conn.execute(
            """
            INSERT INTO user_profiles (
                platform, user_id, account, nickname, sec_uid, unique_id, red_id,
                avatar, signature, desc, ip_location, gender,
                follows_count, fans_count, likes_count, notes_count, videos_count,
                last_seen_at, source, raw_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(platform, user_id, account) DO UPDATE SET
                nickname      = excluded.nickname,
                red_id        = excluded.red_id,
                desc          = excluded.desc,
                ip_location   = excluded.ip_location,
                gender        = excluded.gender,
                follows_count = excluded.follows_count,
                fans_count    = excluded.fans_count,
                likes_count   = excluded.likes_count,
                notes_count   = excluded.notes_count,
                updated_at    = excluded.updated_at,
                raw_json      = excluded.raw_json,
                source        = excluded.source
            """,
            row,
        )
        conn.commit()


def _output(data: dict, exit_code: int = 0) -> None:
    """输出 JSON 并退出。"""
    print(json.dumps(data, ensure_ascii=False, indent=2))
    sys.exit(exit_code)


def _get_user_data_dir(account: str) -> str | None:
    """根据 account 返回 Chrome user-data-dir，None 表示使用 chrome_launcher 默认。

    逻辑：显式 --account 用该账号 profile；未传时用 get_default_account()，
    多账号用户配置 default 后，各入口不传 --account 也能保持 profile 一致。
    """
    from account_manager import _get_profile_dir, get_default_account

    effective = account or get_default_account()
    if not effective:
        return None
    return _get_profile_dir(effective)


def _connect(args: argparse.Namespace, reuse_page: bool = True):
    """连接到 Chrome 并返回 (browser, page)。

    Args:
        args: 命令行参数
        reuse_page: 是否优先复用现有页面（默认 True，避免频繁创建标签页）
    """
    from chrome_launcher import ensure_chrome, has_display
    from xhs.cdp import Browser

    user_data_dir = _get_user_data_dir(args.account or "")
    if not ensure_chrome(
        port=args.port, headless=not has_display(), user_data_dir=user_data_dir
    ):
        _output(
            {"success": False, "error": "无法启动 Chrome，请检查 Chrome 是否已安装"},
            exit_code=2,
        )

    browser = Browser(host=args.host, port=args.port)
    browser.connect()

    # 优先复用现有页面，避免频繁创建标签页
    if reuse_page:
        page = browser.get_existing_page()
        if page:
            return browser, page

    page = browser.new_page()
    return browser, page


def _connect_existing(args: argparse.Namespace):
    """连接到 Chrome 并复用已有页面（用于分步发布的后续步骤）。"""
    from chrome_launcher import ensure_chrome, has_display
    from xhs.cdp import Browser

    user_data_dir = _get_user_data_dir(args.account or "")
    if not ensure_chrome(
        port=args.port, headless=not has_display(), user_data_dir=user_data_dir
    ):
        _output(
            {"success": False, "error": "无法连接到 Chrome"},
            exit_code=2,
        )

    browser = Browser(host=args.host, port=args.port)
    browser.connect()
    page = browser.get_existing_page()
    if not page:
        _output(
            {"success": False, "error": "未找到已打开的页面，请先执行前置步骤"},
            exit_code=2,
        )
    return browser, page


def _headless_fallback(args: argparse.Namespace) -> None:
    """Headless 模式未登录时的处理：有桌面降级到有窗口模式，无桌面直接报错提示。"""
    from chrome_launcher import has_display, restart_chrome

    if has_display():
        logger.info("Headless 模式未登录，切换到有窗口模式...")
        restart_chrome(
            port=args.port,
            headless=False,
            user_data_dir=_get_user_data_dir(args.account or ""),
        )
        _output(
            {
                "success": False,
                "error": "未登录",
                "action": "switched_to_headed",
                "message": "已切换到有窗口模式，请在浏览器中扫码登录",
            },
            exit_code=1,
        )
    else:
        _output(
            {
                "success": False,
                "error": "未登录",
                "action": "login_required",
                "message": "无界面环境下请先运行 send-code --phone <手机号> 完成登录",
            },
            exit_code=1,
        )


def _get_storage(args: argparse.Namespace):
    """获取 XHSStorage 实例（lazy import，避免在不需要存储的命令中引入开销）。"""
    from xhs.storage import XHSStorage

    return XHSStorage(account=args.account or "default")


# ========== 子命令实现 ==========


def cmd_check_login(args: argparse.Namespace) -> None:
    """检查登录状态。"""
    from xhs.login import check_login_status

    browser, page = _connect(args)
    try:
        logged_in = check_login_status(page)
        if logged_in:
            _output({"logged_in": True}, exit_code=0)
        else:
            from chrome_launcher import has_display

            method = "qrcode" if has_display() else "phone"
            hint = (
                "请运行 login（二维码）完成登录"
                if method == "qrcode"
                else "请运行 send-code --phone <手机号>（手机验证码）完成登录"
            )
            _output(
                {"logged_in": False, "login_method": method, "hint": hint}, exit_code=1
            )
    finally:
        browser.close_page(page)
        browser.close()


def cmd_login(args: argparse.Namespace) -> None:
    """获取登录二维码，输出后退出。用户扫码后执行 check-scan-status 检查状态。

    不阻塞等待扫码，以便 agent 可将二维码展示给用户；完成后由 check-scan-status 检查。
    """
    from xhs.login import fetch_qrcode, save_qrcode_to_file

    browser = None
    try:
        browser, page = _connect(args)
        src, already = fetch_qrcode(page)
        if already:
            _output({"logged_in": True, "message": "已登录"})

        qrcode_path = save_qrcode_to_file(src)
        _output(
            {
                "success": True,
                "qrcode_path": qrcode_path,
                "message": "请使用小红书 App 或微信扫描二维码。扫码完成后请告知，将执行 check-scan-status 检查页面状态",
                "next_step": "用户扫码后执行 check-scan-status",
            }
        )
    finally:
        if browser:
            # 仅断开连接，不关闭 tab，供 check-scan-status 复用
            browser.close()


def cmd_check_scan_status(args: argparse.Namespace) -> None:
    """检查扫码后的页面状态。用户告知已完成扫码后执行。"""
    from xhs.login import check_scan_status

    browser = None
    try:
        browser, page = _connect_existing(args)
        result = check_scan_status(page)
        if result.get("logged_in"):
            _output(result, 0)
        elif result.get("need_verify_code"):
            _output({**result, "success": True}, 0)
        else:
            _output(result, 0)
    except Exception as e:
        logger.error("检查页面状态失败: %s", e, exc_info=True)
        _output({"success": False, "error": str(e)}, 2)
    finally:
        if browser:
            browser.close()


def cmd_phone_login(args: argparse.Namespace) -> None:
    """手机号+验证码登录（适用于无界面服务器）。"""
    from xhs.login import send_phone_code, submit_phone_code

    browser, page = _connect(args)
    try:
        sent = send_phone_code(page, args.phone)
        if not sent:
            _output({"logged_in": True, "message": "已登录，无需重新登录"})
            return

        # 输出提示，等待用户在终端输入验证码
        print(
            json.dumps(
                {
                    "status": "code_sent",
                    "message": f"验证码已发送至 {args.phone[:3]}****{args.phone[-4:]}",
                },
                ensure_ascii=False,
            ),
            flush=True,
        )

        # 从 --code 参数或交互式 stdin 读取验证码
        if args.code:
            code = args.code.strip()
        else:
            try:
                code = input("请输入验证码: ").strip()
            except EOFError:
                _output({"success": False, "error": "未收到验证码输入"}, exit_code=2)
                return

        if not code:
            _output({"success": False, "error": "验证码不能为空"}, exit_code=2)
            return

        success = submit_phone_code(page, code)
        _output(
            {
                "logged_in": success,
                "message": "登录成功" if success else "验证码错误或超时",
            },
            exit_code=0 if success else 2,
        )
    finally:
        browser.close_page(page)
        browser.close()


def cmd_send_code(args: argparse.Namespace) -> None:
    """分步登录第一步：填写手机号并发送验证码，保持页面不关闭。"""
    from chrome_launcher import has_display, restart_chrome
    from xhs.errors import RateLimitError
    from xhs.login import send_phone_code

    for attempt in range(2):
        browser, page = _connect(args)
        try:
            sent = send_phone_code(page, args.phone)
            if not sent:
                _output({"logged_in": True, "message": "已登录，无需重新登录"})
                return

            _output(
                {
                    "status": "code_sent",
                    "message": f"验证码已发送至 {args.phone[:3]}****{args.phone[-4:]}，请运行 verify-code --code <验证码>",
                }
            )
        except RateLimitError:
            browser.close()
            if attempt == 0:
                logger.info("请求频率限制，重启 Chrome 后重试...")
                restart_chrome(
                    port=args.port,
                    headless=not has_display(),
                    user_data_dir=_get_user_data_dir(args.account or ""),
                )
                continue
            _output(
                {"success": False, "error": "请求太频繁，重启后仍失败，请稍后再试"},
                exit_code=2,
            )
        else:
            # 只断开控制连接，不关闭页面——tab 保持打开，verify-code 继续复用
            browser.close()
            return


def cmd_verify_code(args: argparse.Namespace) -> None:
    """分步登录第二步：在已有页面上填写验证码并提交。"""
    from xhs.login import submit_phone_code

    browser, page = _connect_existing(args)
    try:
        success = submit_phone_code(page, args.code)
        _output(
            {
                "logged_in": success,
                "message": "登录成功" if success else "验证码错误或超时",
            },
            exit_code=0 if success else 2,
        )
    finally:
        browser.close_page(page)
        browser.close()


def cmd_delete_cookies(args: argparse.Namespace) -> None:
    """退出登录（页面 UI 点击退出）并删除 cookies 文件。"""
    from xhs.cookies import delete_cookies, get_cookies_file_path
    from xhs.login import logout

    # 先通过浏览器 UI 退出登录
    browser, page = _connect(args)
    try:
        logged_out = logout(page)
    finally:
        browser.close_page(page)
        browser.close()

    # 再删除本地 cookies 文件
    path = get_cookies_file_path(args.account)
    delete_cookies(path)

    msg = "已退出登录并删除 cookies" if logged_out else "未登录，已删除 cookies 文件"
    _output({"success": True, "message": msg, "cookies_path": path})


def cmd_close_browser(args: argparse.Namespace) -> None:
    """关闭当前浏览器 tab 并断开 CDP 连接，释放 agent 侧资源。Chrome 进程仍会保留。完成用户请求后应调用此命令收尾。"""
    from chrome_launcher import ensure_chrome, has_display
    from xhs.cdp import Browser

    user_data_dir = _get_user_data_dir(args.account or "")
    if not ensure_chrome(
        port=args.port, headless=not has_display(), user_data_dir=user_data_dir
    ):
        _output(
            {"success": False, "error": "Chrome 未启动"},
            exit_code=2,
        )

    browser = Browser(host=args.host, port=args.port)
    browser.connect()
    page = browser.get_existing_page()
    if page:
        browser.close_page(page)
    browser.close()
    _output({"success": True, "message": "已关闭浏览器 tab"})


def cmd_list_feeds(args: argparse.Namespace) -> None:
    """获取首页 Feed 列表。"""
    from xhs.feeds import list_feeds

    browser, page = _connect(args)
    try:
        feeds = list_feeds(page)
        try:
            _get_storage(args).upsert_notes_from_feeds(feeds)
        except Exception as e:
            print(f"[storage] 写入失败: {e}", file=sys.stderr)
        _output({"feeds": [f.to_dict() for f in feeds], "count": len(feeds)})
    finally:
        # 不关闭 tab，保留供下次 get_existing_page() 复用
        browser.close()


def cmd_search_feeds(args: argparse.Namespace) -> None:
    """搜索 Feeds。"""
    from xhs.search import search_feeds
    from xhs.types import FilterOption

    filter_opt = FilterOption(
        sort_by=args.sort_by or "",
        note_type=args.note_type or "",
        publish_time=args.publish_time or "",
        search_scope=args.search_scope or "",
        location=args.location or "",
    )

    browser, page = _connect(args)
    try:
        feeds = search_feeds(page, args.keyword, filter_opt)
        try:
            _get_storage(args).upsert_notes_from_feeds(feeds, keyword=args.keyword)
        except Exception as e:
            print(f"[storage] 写入失败: {e}", file=sys.stderr)
        _output({"feeds": [f.to_dict() for f in feeds], "count": len(feeds)})
    finally:
        # 不关闭 tab，保留供下次 get_existing_page() 复用
        browser.close()


def cmd_get_feed_detail(args: argparse.Namespace) -> None:
    """获取 Feed 详情。"""
    from xhs.feed_detail import get_feed_detail
    from xhs.types import CommentLoadConfig

    config = CommentLoadConfig(
        click_more_replies=args.click_more_replies,
        max_replies_threshold=args.max_replies_threshold,
        max_comment_items=args.max_comment_items,
        scroll_speed=args.scroll_speed,
    )

    browser, page = _connect(args)
    try:
        detail = get_feed_detail(
            page,
            args.feed_id,
            args.xsec_token,
            load_all_comments=args.load_all_comments,
            config=config,
        )
        try:
            storage = _get_storage(args)
            storage.upsert_note(detail.note)
            storage.upsert_comments(detail.comments.list_, detail.note.note_id)
        except Exception as e:
            print(f"[storage] 写入失败: {e}", file=sys.stderr)
        _output(detail.to_dict())
    finally:
        # 不关闭 tab，保留供下次 get_existing_page() 复用，避免每次新建窗口
        browser.close()


def cmd_user_profile(args: argparse.Namespace) -> None:
    """获取用户主页。"""
    from xhs.user_profile import get_user_profile

    browser, page = _connect(args)
    try:
        profile = get_user_profile(page, args.user_id, args.xsec_token)
        output = profile.to_dict()
        try:
            _sync_to_store_user_db(
                output,
                args.account or "default",
                fallback_user_id=args.user_id or "",
            )
        except Exception as e:
            print(f"[store-user-db] 同步失败: {e}", file=sys.stderr)
        _output(output)
    finally:
        # 不关闭 tab，保留供下次 get_existing_page() 复用
        browser.close()


def cmd_my_profile(args: argparse.Namespace) -> None:
    """获取当前登录账号的主页（无需 user_id / xsec_token）。"""
    from xhs.user_profile import get_my_profile

    browser, page = _connect(args)
    try:
        profile = get_my_profile(page)
        output = profile.to_dict()
        try:
            storage = _get_storage(args)
            storage.upsert_notes_from_feeds(profile.feeds)
            if profile.feeds:
                my_author_id = profile.feeds[0].note_card.user.user_id
                storage.mark_notes_mine([f.id for f in profile.feeds])
                storage.set_my_identity(my_author_id)
                storage.mark_comments_mine(my_author_id)
        except Exception as e:
            print(f"[storage] 写入失败: {e}", file=sys.stderr)
        try:
            _sync_to_store_user_db(output, args.account or "default")
        except Exception as e:
            print(f"[store-user-db] 同步失败: {e}", file=sys.stderr)
        _output(output)
    finally:
        # 不关闭 tab，保留供下次 get_existing_page() 复用
        browser.close()


def _extract_and_upsert_after_comment(page, feed_id: str, args: argparse.Namespace) -> None:
    """评论/回复成功后，从当前页面提取最新数据并更新本地数据库。"""
    import time

    from xhs.errors import NoFeedDetailError
    from xhs.feed_detail import _extract_feed_detail

    time.sleep(1.5)  # 等待页面 state 更新
    try:
        detail = _extract_feed_detail(page, feed_id)
        storage = _get_storage(args)
        storage.upsert_note(detail.note)
        storage.upsert_comments(detail.comments.list_, detail.note.note_id)
    except NoFeedDetailError:
        logger.debug("评论后提取详情失败，跳过数据库更新")
    except Exception as e:
        print(f"[storage] 评论后更新数据库失败: {e}", file=sys.stderr)


def cmd_post_comment(args: argparse.Namespace) -> None:
    """发表评论。"""
    from xhs.comment import post_comment

    browser, page = _connect(args)
    try:
        post_comment(page, args.feed_id, args.xsec_token, args.content)
        _extract_and_upsert_after_comment(page, args.feed_id, args)
        _output({"success": True, "message": "评论发送成功"})
    finally:
        browser.close_page(page)
        browser.close()


def cmd_reply_comment(args: argparse.Namespace) -> None:
    """回复评论。"""
    from xhs.comment import reply_comment

    browser, page = _connect(args)
    try:
        reply_comment(
            page,
            args.feed_id,
            args.xsec_token,
            args.content,
            comment_id=args.comment_id or "",
            user_id=args.user_id or "",
        )
        _extract_and_upsert_after_comment(page, args.feed_id, args)
        _output({"success": True, "message": "回复成功"})
    finally:
        browser.close_page(page)
        browser.close()


def cmd_like_feed(args: argparse.Namespace) -> None:
    """点赞/取消点赞。"""
    from xhs.like_favorite import like_feed, unlike_feed

    browser, page = _connect(args)
    try:
        if args.unlike:
            result = unlike_feed(page, args.feed_id, args.xsec_token)
        else:
            result = like_feed(page, args.feed_id, args.xsec_token)
        _output(result.to_dict())
    finally:
        browser.close_page(page)
        browser.close()


def cmd_favorite_feed(args: argparse.Namespace) -> None:
    """收藏/取消收藏。"""
    from xhs.like_favorite import favorite_feed, unfavorite_feed

    browser, page = _connect(args)
    try:
        if args.unfavorite:
            result = unfavorite_feed(page, args.feed_id, args.xsec_token)
        else:
            result = favorite_feed(page, args.feed_id, args.xsec_token)
        _output(result.to_dict())
    finally:
        browser.close_page(page)
        browser.close()


def cmd_publish(args: argparse.Namespace) -> None:
    """发布图文内容。"""
    from image_downloader import process_images
    from xhs.login import check_login_status
    from xhs.publish import publish_image_content
    from xhs.types import PublishImageContent

    # 读取标题和正文
    with open(args.title_file, encoding="utf-8") as f:
        title = f.read().strip()
    with open(args.content_file, encoding="utf-8") as f:
        content = f.read().strip()

    # 处理图片
    image_paths = process_images(args.images) if args.images else []
    if not image_paths:
        _output({"success": False, "error": "没有有效的图片"}, exit_code=2)

    browser, page = _connect(args)
    try:
        # headless 模式登录检查 + 自动降级
        headless = getattr(args, "headless", False)
        if headless and not check_login_status(page):
            browser.close_page(page)
            browser.close()
            _headless_fallback(args)
            return

        publish_image_content(
            page,
            PublishImageContent(
                title=title,
                content=content,
                tags=args.tags or [],
                image_paths=image_paths,
                schedule_time=args.schedule_at,
                is_original=args.original,
                visibility=args.visibility or "",
            ),
        )
        _output(
            {
                "success": True,
                "title": title,
                "images": len(image_paths),
                "status": "发布完成",
            }
        )
    finally:
        browser.close_page(page)
        browser.close()


def cmd_fill_publish(args: argparse.Namespace) -> None:
    """只填写图文表单，不发布。"""
    from image_downloader import process_images
    from xhs.publish import fill_publish_form
    from xhs.types import PublishImageContent

    with open(args.title_file, encoding="utf-8") as f:
        title = f.read().strip()
    with open(args.content_file, encoding="utf-8") as f:
        content = f.read().strip()

    image_paths = process_images(args.images) if args.images else []
    if not image_paths:
        _output({"success": False, "error": "没有有效的图片"}, exit_code=2)

    browser, page = _connect(args)
    try:
        fill_publish_form(
            page,
            PublishImageContent(
                title=title,
                content=content,
                tags=args.tags or [],
                image_paths=image_paths,
                schedule_time=args.schedule_at,
                is_original=args.original,
                visibility=args.visibility or "",
            ),
        )
        _output(
            {
                "success": True,
                "title": title,
                "images": len(image_paths),
                "status": "表单已填写，等待确认发布",
            }
        )
    finally:
        # 不关闭页面，让用户在浏览器中预览
        browser.close()


def cmd_fill_publish_video(args: argparse.Namespace) -> None:
    """只填写视频表单，不发布。"""
    from xhs.publish_video import fill_publish_video_form
    from xhs.types import PublishVideoContent

    with open(args.title_file, encoding="utf-8") as f:
        title = f.read().strip()
    with open(args.content_file, encoding="utf-8") as f:
        content = f.read().strip()

    browser, page = _connect(args)
    try:
        fill_publish_video_form(
            page,
            PublishVideoContent(
                title=title,
                content=content,
                tags=args.tags or [],
                video_path=args.video,
                schedule_time=args.schedule_at,
                visibility=args.visibility or "",
            ),
        )
        _output(
            {
                "success": True,
                "title": title,
                "video": args.video,
                "status": "视频表单已填写，等待确认发布",
            }
        )
    finally:
        # 不关闭页面，让用户在浏览器中预览
        browser.close()


def cmd_click_publish(args: argparse.Namespace) -> None:
    """点击发布按钮（在用户确认后调用）。复用已有的发布页 tab。"""
    from xhs.publish import click_publish_button

    browser, page = _connect_existing(args)
    try:
        click_publish_button(page)
        _output({"success": True, "status": "发布完成"})
    finally:
        browser.close_page(page)
        browser.close()


def cmd_save_draft(args: argparse.Namespace) -> None:
    """保存为草稿（取消发布时调用）。"""
    from xhs.publish import save_as_draft

    browser, page = _connect_existing(args)
    try:
        save_as_draft(page)
        _output({"success": True, "status": "内容已保存到草稿箱"})
    finally:
        browser.close_page(page)
        browser.close()


def cmd_long_article(args: argparse.Namespace) -> None:
    """长文模式：填写内容 + 一键排版，返回模板列表。"""
    from xhs.publish_long_article import publish_long_article

    with open(args.title_file, encoding="utf-8") as f:
        title = f.read().strip()
    with open(args.content_file, encoding="utf-8") as f:
        content = f.read().strip()

    browser, page = _connect(args)
    try:
        template_names = publish_long_article(
            page,
            title=title,
            content=content,
            image_paths=args.images,
        )
        _output(
            {
                "success": True,
                "templates": template_names,
                "status": "长文已填写，请选择模板",
            }
        )
    finally:
        # 不关闭页面，后续 select-template / next-step 需要复用
        browser.close()


def cmd_select_template(args: argparse.Namespace) -> None:
    """选择排版模板。复用已有的长文编辑页 tab。"""
    from xhs.publish_long_article import select_template

    browser, page = _connect_existing(args)
    try:
        selected = select_template(page, args.name)
        if selected:
            _output({"success": True, "template": args.name, "status": "模板已选择"})
        else:
            _output(
                {"success": False, "error": f"未找到模板: {args.name}"},
                exit_code=2,
            )
    finally:
        # 不关闭页面，后续 next-step 需要复用
        browser.close()


def cmd_next_step(args: argparse.Namespace) -> None:
    """点击下一步 + 填写发布页描述。复用已有的长文编辑页 tab。"""
    from xhs.publish_long_article import click_next_and_fill_description

    with open(args.content_file, encoding="utf-8") as f:
        description = f.read().strip()

    browser, page = _connect_existing(args)
    try:
        click_next_and_fill_description(page, description)
        _output({"success": True, "status": "已进入发布页，等待确认发布"})
    finally:
        # 不关闭页面，等待 click-publish
        browser.close()


def cmd_publish_video(args: argparse.Namespace) -> None:
    """发布视频内容。"""
    from xhs.login import check_login_status
    from xhs.publish_video import publish_video_content
    from xhs.types import PublishVideoContent

    with open(args.title_file, encoding="utf-8") as f:
        title = f.read().strip()
    with open(args.content_file, encoding="utf-8") as f:
        content = f.read().strip()

    browser, page = _connect(args)
    try:
        # headless 模式登录检查 + 自动降级
        headless = getattr(args, "headless", False)
        if headless and not check_login_status(page):
            browser.close_page(page)
            browser.close()
            _headless_fallback(args)
            return

        publish_video_content(
            page,
            PublishVideoContent(
                title=title,
                content=content,
                tags=args.tags or [],
                video_path=args.video,
                schedule_time=args.schedule_at,
                visibility=args.visibility or "",
            ),
        )
        _output(
            {"success": True, "title": title, "video": args.video, "status": "发布完成"}
        )
    finally:
        browser.close_page(page)
        browser.close()


# ========== 本地查询子命令（无需 Chrome）==========


def cmd_query_notes(args: argparse.Namespace) -> None:
    """查询本地缓存帖子数据库。"""
    storage = _get_storage(args)
    if args.note_id:
        note = storage.get_note(args.note_id)
        _output({"note": note, "found": note is not None})
        return
    notes = storage.query_notes(
        mine_only=args.mine,
        keyword=args.keyword or None,
        limit=args.limit,
        offset=args.offset,
    )
    _output({"notes": notes, "count": len(notes)})


def cmd_query_comments(args: argparse.Namespace) -> None:
    """查询本地缓存评论数据库。"""
    storage = _get_storage(args)
    comments = storage.query_comments(
        note_id=args.note_id or None,
        mine_only=args.mine,
        limit=args.limit,
        offset=args.offset,
        author_id=args.author_id or None,
        keyword=args.keyword or None,
    )
    _output({"comments": comments, "count": len(comments)})


def cmd_query_users(args: argparse.Namespace) -> None:
    """查询本地缓存用户数据库。"""
    storage = _get_storage(args)
    if args.user_id:
        user = storage.query_user(args.user_id)
        _output({"user": user, "found": user is not None})
        return
    users = storage.query_users(
        intent_type=args.intent_type or None,
        keyword=args.keyword or None,
        limit=args.limit,
        offset=args.offset,
    )
    _output({"users": users, "count": len(users)})


def cmd_query_comment_authors(args: argparse.Namespace) -> None:
    """按帖子聚合评论用户，用于画像分析。"""
    storage = _get_storage(args)
    authors = storage.query_comment_authors(note_id=args.note_id, limit=args.limit)
    _output({"authors": authors, "note_id": args.note_id, "count": len(authors)})


def cmd_update_comment_reply(args: argparse.Namespace) -> None:
    """回复成功后增量更新数据库（无需浏览器）。"""
    storage = _get_storage(args)
    storage.add_reply_to_parent(
        parent_id=args.parent_id,
        new_comment_id=args.comment_id,
        note_id=args.note_id,
        is_mine=args.mine,
        content=args.content or "",
        author_id=args.author_id or "",
        author_name=args.author_name or "",
    )
    _output({"success": True, "message": "已更新父评论的回复信息"})


def cmd_search_local(args: argparse.Namespace) -> None:
    """在本地数据库全文 LIKE 检索帖子或评论。"""
    storage = _get_storage(args)
    results = storage.search_local(args.query, target=args.target, limit=args.limit)
    _output(
        {
            "results": results,
            "query": args.query,
            "target": args.target,
            "count": len(results),
        }
    )


def cmd_trend_analysis(args: argparse.Namespace) -> None:
    """分析某关键词下竞品帖子的互动趋势。"""
    storage = _get_storage(args)
    result = storage.trend_analysis(args.keyword, args.days)
    _output(result)


# ========== 素材管理子命令（无需 Chrome）==========


def cmd_material_check(args: argparse.Namespace) -> None:
    """检查素材管理依赖安装状态。"""
    from material.config import check_dependencies, get_missing_dependencies

    deps = check_dependencies()
    missing = get_missing_dependencies()
    result = {
        "dependencies": deps,
        "all_installed": len(missing) == 0,
    }
    if missing:
        result["missing"] = missing
        result["install_command"] = f"uv pip install {' '.join(missing)}"
        result["message"] = f"缺少依赖: {', '.join(missing)}，请先安装"
    else:
        result["message"] = "所有依赖已安装"
    _output(result)


def cmd_material_config(args: argparse.Namespace) -> None:
    """查看或更新素材管理配置。"""
    from material.config import get_material_config, update_material_config

    updates = {}
    if args.api_key is not None:
        updates["API_KEY"] = args.api_key
    if args.model_name is not None:
        updates["MODEL_NAME"] = args.model_name
    if args.base_url is not None:
        updates["BASE_URL"] = args.base_url
    if args.embedding_model_name is not None:
        updates["EMBEDDING_MODEL_NAME"] = args.embedding_model_name
    if args.top_n is not None:
        updates["TOP_N"] = args.top_n

    if updates:
        try:
            config = update_material_config(**updates)
            message = "配置已更新"
            if "API_KEY" in updates or "MODEL_NAME" in updates:
                message += "。注意：请确保所配置的大模型支持多模态（能识别理解图片和视频），如 gpt-4o、qwen-vl 等，纯文本模型无法生成图片描述"
            _output({"status": "ok", "config": config, "message": message})
        except ValueError as e:
            _output({"status": "error", "error": str(e)}, exit_code=2)
    else:
        config = get_material_config()
        # 隐藏 API_KEY 的中间部分
        display_config = dict(config)
        api_key = display_config.get("API_KEY", "")
        if api_key and len(api_key) > 8:
            display_config["API_KEY"] = api_key[:4] + "****" + api_key[-4:]
        _output({"config": display_config})


def cmd_material_add_dir(args: argparse.Namespace) -> None:
    """添加素材目录并同步入库。"""
    from material.config import get_missing_dependencies
    from material.sync import add_directory

    missing = get_missing_dependencies()
    if missing:
        _output(
            {
                "status": "error",
                "error": f"缺少依赖: {', '.join(missing)}",
                "install_command": f"uv pip install {' '.join(missing)}",
            },
            exit_code=2,
        )
        return

    result = add_directory(args.directory)
    _output(result)


def cmd_material_remove_dir(args: argparse.Namespace) -> None:
    """移除素材目录。"""
    from material.sync import remove_directory

    result = remove_directory(
        args.directory,
        remove_from_db=not args.keep_db,
    )
    _output(result)


def cmd_material_sync(args: argparse.Namespace) -> None:
    """同步素材库（新增入库 + 清理已删除文件）。"""
    from material.config import get_missing_dependencies
    from material.sync import sync_materials

    missing = get_missing_dependencies()
    if missing:
        _output(
            {
                "status": "error",
                "error": f"缺少依赖: {', '.join(missing)}",
                "install_command": f"uv pip install {' '.join(missing)}",
            },
            exit_code=2,
        )
        return

    result = sync_materials()
    _output(result)


def cmd_material_search(args: argparse.Namespace) -> None:
    """根据文本搜索匹配的素材。"""
    from material.search import search_materials

    result = search_materials(
        query=args.query,
        top_n=getattr(args, "top_n", None),
        media_type=getattr(args, "media_type", None),
    )
    _output(result)


def cmd_material_list(args: argparse.Namespace) -> None:
    """列出所有已入库的素材。"""
    from material.vector import list_materials

    media_type = getattr(args, "media_type", None)
    materials = list_materials(media_type=media_type)
    _output({"materials": materials, "count": len(materials)})


def cmd_material_stats(args: argparse.Namespace) -> None:
    """查看素材库统计信息。"""
    from material.config import get_material_config
    from material.vector import get_material_count

    config = get_material_config()
    stats = get_material_count()
    stats["directories"] = config.get("IMAGE_DIRS", [])
    stats["top_n"] = config.get("TOP_N", 3)
    _output(stats)


def cmd_material_download_model(args: argparse.Namespace) -> None:
    """下载本地 embedding 模型（BAAI/bge-small-zh-v1.5）。"""
    from material.config import (
        LOCAL_EMBEDDING_MODEL_DIR,
        LOCAL_EMBEDDING_MODEL_NAME,
        download_local_embedding_model,
        is_sentence_transformers_installed,
    )

    if not is_sentence_transformers_installed():
        _output(
            {
                "status": "error",
                "error": "sentence-transformers 未安装",
                "install_command": "uv pip install sentence-transformers",
                "message": "请先安装 sentence-transformers: uv pip install sentence-transformers",
            },
            exit_code=2,
        )
        return

    _output(
        {
            "status": "downloading",
            "model_name": LOCAL_EMBEDDING_MODEL_NAME,
            "model_dir": str(LOCAL_EMBEDDING_MODEL_DIR),
            "message": (
                f"正在从 HuggingFace 镜像下载模型 {LOCAL_EMBEDDING_MODEL_NAME}，"
                f"保存到 {LOCAL_EMBEDDING_MODEL_DIR}，首次下载可能需要几分钟..."
            ),
        }
    )

    result = download_local_embedding_model()
    _output(result)


# ========== 参数解析 ==========
def build_parser() -> argparse.ArgumentParser:
    """构建 CLI 参数解析器。"""
    parser = argparse.ArgumentParser(
        prog="xhs-cli",
        description="小红书自动化 CLI",
    )

    # 全局选项
    parser.add_argument(
        "--host", default="127.0.0.1", help="Chrome 调试主机 (default: 127.0.0.1)"
    )
    parser.add_argument(
        "--port", type=int, default=9222, help="Chrome 调试端口 (default: 9222)"
    )
    parser.add_argument("--account", default="", help="账号名称")

    subparsers = parser.add_subparsers(dest="command", required=True)

    # check-login
    sub = subparsers.add_parser("check-login", help="检查登录状态")
    sub.set_defaults(func=cmd_check_login)

    # login（分步：输出二维码后退出，用户扫码后执行 check-scan-status）
    sub = subparsers.add_parser(
        "login",
        help="获取登录二维码，输出后退出，用户扫码后执行 check-scan-status",
    )
    sub.set_defaults(func=cmd_login)

    sub = subparsers.add_parser(
        "check-scan-status",
        help="检查扫码后的页面状态，用户告知已完成扫码后执行",
    )
    sub.set_defaults(func=cmd_check_scan_status)

    # phone-login（单命令交互式）
    sub = subparsers.add_parser(
        "phone-login", help="手机号+验证码登录（交互式，适合本地终端）"
    )
    sub.add_argument(
        "--phone", required=True, help="手机号（不含国家码，如 13800138000）"
    )
    sub.add_argument("--code", default="", help="短信验证码（省略则交互式输入）")
    sub.set_defaults(func=cmd_phone_login)

    # send-code（分步登录第一步）
    sub = subparsers.add_parser(
        "send-code", help="分步登录第一步：发送手机验证码，保持页面不关闭"
    )
    sub.add_argument("--phone", required=True, help="手机号（不含国家码）")
    sub.set_defaults(func=cmd_send_code)

    # verify-code（分步登录第二步）
    sub = subparsers.add_parser(
        "verify-code", help="分步登录第二步：填写验证码并完成登录"
    )
    sub.add_argument("--code", required=True, help="收到的短信验证码")
    sub.set_defaults(func=cmd_verify_code)

    # delete-cookies
    sub = subparsers.add_parser("delete-cookies", help="删除 cookies")
    sub.set_defaults(func=cmd_delete_cookies)

    # close-browser
    sub = subparsers.add_parser("close-browser", help="关闭浏览器 tab，完成请求后收尾")
    sub.set_defaults(func=cmd_close_browser)

    # list-feeds
    sub = subparsers.add_parser("list-feeds", help="获取首页 Feed 列表")
    sub.set_defaults(func=cmd_list_feeds)

    # search-feeds
    sub = subparsers.add_parser("search-feeds", help="搜索 Feeds")
    sub.add_argument("--keyword", required=True, help="搜索关键词")
    sub.add_argument("--sort-by", help="排序: 综合|最新|最多点赞|最多评论|最多收藏")
    sub.add_argument("--note-type", help="类型: 不限|视频|图文")
    sub.add_argument("--publish-time", help="时间: 不限|一天内|一周内|半年内")
    sub.add_argument("--search-scope", help="范围: 不限|已看过|未看过|已关注")
    sub.add_argument("--location", help="位置: 不限|同城|附近")
    sub.set_defaults(func=cmd_search_feeds)

    # get-feed-detail
    sub = subparsers.add_parser("get-feed-detail", help="获取 Feed 详情")
    sub.add_argument("--feed-id", required=True, help="Feed ID")
    sub.add_argument("--xsec-token", required=True, help="xsec_token")
    sub.add_argument("--load-all-comments", action="store_true", help="加载全部评论")
    sub.add_argument(
        "--click-more-replies", action="store_true", help="点击展开更多回复"
    )
    sub.add_argument(
        "--max-replies-threshold", type=int, default=10, help="展开回复数阈值"
    )
    sub.add_argument(
        "--max-comment-items", type=int, default=0, help="最大评论数 (0=不限)"
    )
    sub.add_argument(
        "--scroll-speed", default="normal", help="滚动速度: slow|normal|fast"
    )
    sub.set_defaults(func=cmd_get_feed_detail)

    # user-profile
    sub = subparsers.add_parser("user-profile", help="获取用户主页")
    sub.add_argument("--user-id", required=True, help="用户 ID")
    sub.add_argument("--xsec-token", required=True, help="xsec_token")
    sub.set_defaults(func=cmd_user_profile)

    # my-profile
    sub = subparsers.add_parser(
        "my-profile", help="获取当前登录账号的主页（无需 user_id / xsec_token）"
    )
    sub.set_defaults(func=cmd_my_profile)

    # post-comment
    sub = subparsers.add_parser("post-comment", help="发表评论")
    sub.add_argument("--feed-id", required=True, help="Feed ID")
    sub.add_argument("--xsec-token", required=True, help="xsec_token")
    sub.add_argument("--content", required=True, help="评论内容")
    sub.set_defaults(func=cmd_post_comment)

    # reply-comment
    sub = subparsers.add_parser("reply-comment", help="回复评论")
    sub.add_argument("--feed-id", required=True, help="Feed ID")
    sub.add_argument("--xsec-token", required=True, help="xsec_token")
    sub.add_argument("--content", required=True, help="回复内容")
    sub.add_argument("--comment-id", help="目标评论 ID")
    sub.add_argument("--user-id", help="目标用户 ID")
    sub.set_defaults(func=cmd_reply_comment)

    # like-feed
    sub = subparsers.add_parser("like-feed", help="点赞")
    sub.add_argument("--feed-id", required=True, help="Feed ID")
    sub.add_argument("--xsec-token", required=True, help="xsec_token")
    sub.add_argument("--unlike", action="store_true", help="取消点赞")
    sub.set_defaults(func=cmd_like_feed)

    # favorite-feed
    sub = subparsers.add_parser("favorite-feed", help="收藏")
    sub.add_argument("--feed-id", required=True, help="Feed ID")
    sub.add_argument("--xsec-token", required=True, help="xsec_token")
    sub.add_argument("--unfavorite", action="store_true", help="取消收藏")
    sub.set_defaults(func=cmd_favorite_feed)

    # publish
    sub = subparsers.add_parser("publish", help="发布图文")
    sub.add_argument("--title-file", required=True, help="标题文件路径")
    sub.add_argument("--content-file", required=True, help="正文文件路径")
    sub.add_argument("--images", nargs="+", required=True, help="图片路径/URL")
    sub.add_argument("--tags", nargs="*", help="标签")
    sub.add_argument("--schedule-at", help="定时发布 (ISO8601)")
    sub.add_argument("--original", action="store_true", help="声明原创")
    sub.add_argument("--visibility", help="可见范围")
    sub.add_argument(
        "--headless", action="store_true", help="无头模式（未登录自动降级）"
    )
    sub.set_defaults(func=cmd_publish)

    # publish-video
    sub = subparsers.add_parser("publish-video", help="发布视频")
    sub.add_argument("--title-file", required=True, help="标题文件路径")
    sub.add_argument("--content-file", required=True, help="正文文件路径")
    sub.add_argument("--video", required=True, help="视频文件路径")
    sub.add_argument("--tags", nargs="*", help="标签")
    sub.add_argument("--schedule-at", help="定时发布 (ISO8601)")
    sub.add_argument("--visibility", help="可见范围")
    sub.add_argument(
        "--headless", action="store_true", help="无头模式（未登录自动降级）"
    )
    sub.set_defaults(func=cmd_publish_video)

    # fill-publish（只填写图文表单，不发布）
    sub = subparsers.add_parser("fill-publish", help="填写图文表单（不发布）")
    sub.add_argument("--title-file", required=True, help="标题文件路径")
    sub.add_argument("--content-file", required=True, help="正文文件路径")
    sub.add_argument("--images", nargs="+", required=True, help="图片路径/URL")
    sub.add_argument("--tags", nargs="*", help="标签")
    sub.add_argument("--schedule-at", help="定时发布 (ISO8601)")
    sub.add_argument("--original", action="store_true", help="声明原创")
    sub.add_argument("--visibility", help="可见范围")
    sub.set_defaults(func=cmd_fill_publish)

    # fill-publish-video（只填写视频表单，不发布）
    sub = subparsers.add_parser("fill-publish-video", help="填写视频表单（不发布）")
    sub.add_argument("--title-file", required=True, help="标题文件路径")
    sub.add_argument("--content-file", required=True, help="正文文件路径")
    sub.add_argument("--video", required=True, help="视频文件路径")
    sub.add_argument("--tags", nargs="*", help="标签")
    sub.add_argument("--schedule-at", help="定时发布 (ISO8601)")
    sub.add_argument("--visibility", help="可见范围")
    sub.set_defaults(func=cmd_fill_publish_video)

    # click-publish（点击发布按钮）
    sub = subparsers.add_parser("click-publish", help="点击发布按钮")
    sub.set_defaults(func=cmd_click_publish)

    # long-article（长文模式）
    sub = subparsers.add_parser("long-article", help="长文模式：填写 + 一键排版")
    sub.add_argument("--title-file", required=True, help="标题文件路径")
    sub.add_argument("--content-file", required=True, help="正文文件路径")
    sub.add_argument("--images", nargs="*", help="可选图片路径")
    sub.set_defaults(func=cmd_long_article)

    # select-template（选择模板）
    sub = subparsers.add_parser("select-template", help="选择排版模板")
    sub.add_argument("--name", required=True, help="模板名称")
    sub.set_defaults(func=cmd_select_template)

    # next-step（下一步 + 填写描述）
    sub = subparsers.add_parser("next-step", help="点击下一步 + 填写描述")
    sub.add_argument("--content-file", required=True, help="描述内容文件路径")
    sub.set_defaults(func=cmd_next_step)

    # save-draft（保存草稿）
    sub = subparsers.add_parser("save-draft", help="保存为草稿（取消发布时使用）")
    sub.set_defaults(func=cmd_save_draft)

    # ========== 素材管理命令（无需 Chrome）==========

    # material-check
    sub = subparsers.add_parser("material-check", help="检查素材管理依赖安装状态")
    sub.set_defaults(func=cmd_material_check)

    # material-config
    sub = subparsers.add_parser("material-config", help="查看或更新素材管理配置")
    sub.add_argument("--api-key", help="大模型 API 密钥")
    sub.add_argument(
        "--model-name",
        help="大模型名称（必须支持多模态，如 gpt-4o、qwen-vl，用于生成图片描述）",
    )
    sub.add_argument("--base-url", help="大模型 API 地址")
    sub.add_argument(
        "--embedding-model-name",
        help="Embedding 模型名称（用于向量化，默认 text-embedding-v3）",
    )
    sub.add_argument("--top-n", type=int, help="搜索返回的素材数量")
    sub.set_defaults(func=cmd_material_config)

    # material-add-dir
    sub = subparsers.add_parser("material-add-dir", help="添加素材目录并同步入库")
    sub.add_argument("--directory", required=True, help="素材目录路径（绝对路径）")
    sub.set_defaults(func=cmd_material_add_dir)

    # material-remove-dir
    sub = subparsers.add_parser("material-remove-dir", help="移除素材目录")
    sub.add_argument("--directory", required=True, help="要移除的目录路径")
    sub.add_argument("--keep-db", action="store_true", help="保留数据库中的素材记录")
    sub.set_defaults(func=cmd_material_remove_dir)

    # material-sync
    sub = subparsers.add_parser(
        "material-sync", help="同步素材库（新增入库 + 清理已删除文件）"
    )
    sub.set_defaults(func=cmd_material_sync)

    # material-search
    sub = subparsers.add_parser("material-search", help="根据文本搜索匹配的素材")
    sub.add_argument("--query", required=True, help="搜索文本")
    sub.add_argument("--top-n", type=int, help="返回数量（默认使用配置中的 TOP_N）")
    sub.add_argument("--media-type", choices=["image", "video"], help="过滤素材类型")
    sub.set_defaults(func=cmd_material_search)

    # material-list
    sub = subparsers.add_parser("material-list", help="列出所有已入库的素材")
    sub.add_argument("--media-type", choices=["image", "video"], help="过滤素材类型")
    sub.set_defaults(func=cmd_material_list)

    # material-stats
    sub = subparsers.add_parser("material-stats", help="查看素材库统计信息")
    sub.set_defaults(func=cmd_material_stats)

    # material-download-model
    sub = subparsers.add_parser(
        "material-download-model",
        help="下载本地 embedding 模型（BAAI/bge-small-zh-v1.5）",
    )
    sub.set_defaults(func=cmd_material_download_model)

    # ========== 本地查询命令（无需 Chrome）==========

    # query-notes
    sub = subparsers.add_parser("query-notes", help="查询本地缓存帖子")
    sub.add_argument("--note-id", help="按帖子 ID 查询单条详情")
    sub.add_argument("--mine", action="store_true", help="只看我的帖子")
    sub.add_argument("--keyword", help="关键词（匹配 title/desc/搜索词）")
    sub.add_argument("--limit", type=int, default=20, help="返回条数 (default: 20)")
    sub.add_argument("--offset", type=int, default=0, help="偏移量 (default: 0)")
    sub.set_defaults(func=cmd_query_notes)

    # query-comments
    sub = subparsers.add_parser("query-comments", help="查询本地缓存评论")
    sub.add_argument("--note-id", help="按帖子 ID 过滤")
    sub.add_argument("--author-id", help="按评论作者 ID 过滤")
    sub.add_argument("--keyword", help="按评论内容关键词过滤")
    sub.add_argument("--mine", action="store_true", help="只看我的评论/回复")
    sub.add_argument("--limit", type=int, default=20, help="返回条数 (default: 20)")
    sub.add_argument("--offset", type=int, default=0, help="偏移量 (default: 0)")
    sub.set_defaults(func=cmd_query_comments)

    # query-users
    sub = subparsers.add_parser("query-users", help="查询本地缓存用户画像")
    sub.add_argument("--user-id", help="按用户 ID 查询单个用户")
    sub.add_argument("--intent-type", help="按意向类型过滤（购买型/咨询型等）")
    sub.add_argument("--keyword", help="按昵称/地域/简介关键词过滤")
    sub.add_argument("--limit", type=int, default=20, help="返回条数 (default: 20)")
    sub.add_argument("--offset", type=int, default=0, help="偏移量 (default: 0)")
    sub.set_defaults(func=cmd_query_users)

    # query-comment-authors
    sub = subparsers.add_parser("query-comment-authors", help="按帖子聚合评论用户")
    sub.add_argument("--note-id", required=True, help="帖子 ID")
    sub.add_argument("--limit", type=int, default=50, help="返回条数 (default: 50)")
    sub.set_defaults(func=cmd_query_comment_authors)

    # update-comment-reply
    sub = subparsers.add_parser(
        "update-comment-reply",
        help="回复成功后增量更新数据库（无需浏览器）",
    )
    sub.add_argument("--parent-id", required=True, help="父评论 ID")
    sub.add_argument("--comment-id", required=True, help="新回复的评论 ID")
    sub.add_argument("--note-id", required=True, help="所属帖子 ID")
    sub.add_argument("--mine", action="store_true", help="新回复是否为自己所发")
    sub.add_argument("--content", help="回复内容（可选，占位用）")
    sub.add_argument("--author-id", help="回复作者 ID（可选）")
    sub.add_argument("--author-name", help="回复作者昵称（可选）")
    sub.set_defaults(func=cmd_update_comment_reply)

    # search-local
    sub = subparsers.add_parser("search-local", help="在本地数据库全文检索")
    sub.add_argument("--query", required=True, help="检索词")
    sub.add_argument(
        "--target", default="notes", choices=["notes", "comments"], help="检索目标"
    )
    sub.add_argument("--limit", type=int, default=10, help="返回条数 (default: 10)")
    sub.set_defaults(func=cmd_search_local)

    # trend-analysis
    sub = subparsers.add_parser("trend-analysis", help="分析关键词竞品互动趋势")
    sub.add_argument("--keyword", required=True, help="关键词")
    sub.add_argument("--days", type=int, default=30, help="分析最近 N 天 (default: 30)")
    sub.set_defaults(func=cmd_trend_analysis)

    return parser


def main() -> None:
    """CLI 入口。"""
    parser = build_parser()
    args = parser.parse_args()

    try:
        args.func(args)
    except Exception as e:
        logger.error("执行失败: %s", e, exc_info=True)
        _output({"success": False, "error": str(e)}, exit_code=2)


if __name__ == "__main__":
    main()
