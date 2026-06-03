"""视频发布，对应 Go xiaohongshu/publish_video.go。"""

from __future__ import annotations

import logging
import os
import time

from .cdp import NetworkCapture, Page, sleep_random
from .errors import PublishError, UploadTimeoutError
from .publish import (
    _click_publish_tab,
    _find_content_element,
    _input_tags,
    _navigate_to_publish_page,
    _set_schedule_publish,
    _set_visibility,
    _validate_tags,
    _validate_title_length,
)
from .publish_storage import (
    build_publish_data,
    extract_request_data,
    extract_response_data,
    save_publish_data,
)
from .selectors import (
    FILE_INPUT,
    PUBLISH_BUTTON,
    TITLE_INPUT,
    UPLOAD_INPUT,
)
from .types import PublishVideoContent

logger = logging.getLogger(__name__)


def publish_video_content(page: Page, content: PublishVideoContent) -> None:
    """发布视频内容（填写表单 + 点击发布）。

    Args:
        page: CDP 页面对象。
        content: 视频发布内容。

    Raises:
        PublishError: 发布失败。
        UploadTimeoutError: 上传/处理超时。
    """
    fill_publish_video_form(page, content)
    click_publish_video_button(page)


def fill_publish_video_form(page: Page, content: PublishVideoContent) -> None:
    """填写视频发布表单，不点击发布按钮。

    Args:
        page: CDP 页面对象。
        content: 视频发布内容。

    Raises:
        PublishError: 填写失败。
        UploadTimeoutError: 上传/处理超时。
    """
    if not content.video_path:
        raise PublishError("视频不能为空")

    # 导航到发布页
    _navigate_to_publish_page(page)

    # 点击"上传视频" TAB
    _click_publish_tab(page, "上传视频")
    sleep_random(1, 3)

    # 上传视频
    _upload_video(page, content.video_path)

    # 填写表单（不点击发布）
    _fill_publish_video_form(
        page,
        content.title,
        content.content,
        content.tags,
        content.schedule_time,
        content.visibility,
    )


def click_publish_video_button(page: Page) -> None:
    """点击视频发布按钮。

    Args:
        page: CDP 页面对象。
    """
    _wait_for_publish_button_clickable(page)

    # 启动网络监听，捕获发布 API 的请求和响应
    with NetworkCapture(page, "web_api/sns/v2/note", timeout=30.0) as capture:
        page.click_element(PUBLISH_BUTTON)
        request_data, response_data = capture.wait_for_capture()

    # 保存发布数据
    if request_data and response_data:
        try:
            title, desc, content_type = extract_request_data(request_data)
            doc_id, detail_url = extract_response_data(response_data)

            if doc_id:
                publish_data = build_publish_data(
                    title=title,
                    desc=desc,
                    content_type=content_type,
                    doc_id=doc_id,
                    detail_url=detail_url,
                )
                if save_publish_data(publish_data):
                    logger.info("视频发布数据已保存: docId=%s, detailUrl=%s", doc_id, detail_url)
                else:
                    logger.warning("视频发布数据保存失败")
            else:
                logger.warning("无法从响应中提取笔记 ID")
        except Exception as e:
            logger.error("处理视频发布数据时出错: %s", e, exc_info=True)
    else:
        logger.warning("未捕获到发布 API 的请求/响应数据")

    sleep_random(3, 5)
    logger.info("视频发布完成")


def _upload_video(page: Page, video_path: str) -> None:
    """上传视频文件。"""
    if not os.path.exists(video_path):
        raise PublishError(f"视频文件不存在: {video_path}")

    # 查找上传输入框
    selector = UPLOAD_INPUT if page.has_element(UPLOAD_INPUT) else FILE_INPUT
    page.set_file_input(selector, [video_path])

    # 等待发布按钮可点击（视频处理完成）
    _wait_for_publish_button_clickable(page)
    logger.info("视频上传/处理完成")



def _wait_for_publish_button_clickable(page: Page) -> None:
    """等待发布按钮可点击（视频处理可能需要较长时间）。"""
    max_wait = 600.0  # 10 分钟
    start = time.monotonic()

    logger.info("开始等待发布按钮可点击(视频)")

    while time.monotonic() - start < max_wait:
        clickable = page.evaluate(
            f"""
            (() => {{
                const btn = document.querySelector({_js_str(PUBLISH_BUTTON)});
                if (!btn) return false;
                const rect = btn.getBoundingClientRect();
                if (rect.width === 0 || rect.height === 0) return false;
                if (btn.disabled) return false;
                if (btn.classList.contains('disabled')) return false;
                return true;
            }})()
            """
        )
        if clickable:
            return
        sleep_random(1, 3)

    raise UploadTimeoutError("等待发布按钮可点击超时(10分钟)")


def _fill_publish_video_form(
    page: Page,
    title: str,
    content: str,
    tags: list[str],
    schedule_time: str | None,
    visibility: str,
) -> None:
    """填写视频表单（不点击发布）。"""
    # 标题校验
    _validate_title_length(title)

    # 标题
    page.input_text(TITLE_INPUT, title)
    sleep_random(1, 3)

    # 正文 + 标签
    content_selector = _find_content_element(page)
    page.input_content_editable(content_selector, content)

    # 回点标题
    sleep_random(1, 3)
    page.click_element(TITLE_INPUT)

    # 标签校验
    if tags:
        _validate_tags(tags)
        _input_tags(page, content_selector, tags)
    sleep_random(1, 3)

    # 定时发布
    if schedule_time:
        _set_schedule_publish(page, schedule_time)

    # 可见范围
    _set_visibility(page, visibility)

    logger.info("视频表单填写完成，等待确认发布")


def _js_str(s: str) -> str:
    """将 Python 字符串转为 JS 字面量。"""
    import json

    return json.dumps(s)
