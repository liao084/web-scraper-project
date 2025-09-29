# screenshotter_async.py
#
# 负责项目的并行截图阶段（消费者）。
# 它从数据库中获取待处理任务，使用Playwright的BrowserContext池
# 和asyncio的并发模型，高速并行截图，并将结果安全地写回数据库。

import asyncio
import os
import io
import time
from typing import List, Dict

from PIL import Image, ImageChops
from playwright.async_api import async_playwright, Browser, Page

# dotenv: 用于从 `.env` 文件中加载环境变量，实现了配置与代码的分离。
from dotenv import load_dotenv

import database_async

# ==================== 用户配置区 ====================
load_dotenv()
print("正在从 .env 文件加载配置...")

MY_COOKIE = os.getenv("MY_COOKIE")

# 并发worker数量，建议根据CPU核心数和内存大小进行调整
WORKER_COUNT = 6

# --- 截图与裁剪核心参数 ---
# 设置一个比最终截图宽的虚拟浏览器视口，为缩放后的居中内容提供留白
VIEWPORT_WIDTH = 1200
VIEWPORT_HEIGHT = 1000

# 定义我们最终想要的截图尺寸
FINAL_WIDTH = 640
FINAL_HEIGHT = 960

# 根据上述参数，自动计算Pillow裁剪框的精确坐标
# 逻辑：(视口宽度 - 最终宽度) / 2 = 单侧留白宽度
CROP_LEFT = (VIEWPORT_WIDTH - FINAL_WIDTH) // 2
CROP_UPPER = 0
CROP_RIGHT = CROP_LEFT + FINAL_WIDTH
CROP_LOWER = CROP_UPPER + FINAL_HEIGHT
CROP_BOX = (CROP_LEFT, CROP_UPPER, CROP_RIGHT, CROP_LOWER)


# ====================================================


def _parse_cookie_string(cookie_string: str) -> List[Dict]:
    """
    将浏览器Cookie字符串转换为Playwright `storage_state` 所需的格式。
    """
    cookies_list = []
    for item in cookie_string.split(';'):
        if '=' in item:
            name, value = item.strip().split('=', 1)
            cookies_list.append({
                'name': name, 'value': value,
                'domain': '.weidian.com', 'path': '/'
            })
    return cookies_list


def _trim_image(image: Image.Image) -> Image.Image:
    """
    使用Pillow智能裁剪图片的空白边缘，以获得像素级完美的成品。
    """
    bg = Image.new(image.mode, image.size, image.getpixel((0, 0)))
    diff = ImageChops.difference(image, bg)
    diff = ImageChops.add(diff, diff, 2.0, -100)
    bbox = diff.getbbox()
    if bbox:
        return image.crop(bbox)
    return image


async def take_screenshot_and_crop(page: Page, order_id: str) -> str:
    """
    执行一次高效且稳定的截图和裁剪操作。
    """
    # 步骤1: 执行全局缩放，以在有限的视口内展示更多页面内容
    await page.evaluate("document.body.style.zoom='40%'")

    # 步骤2: 等待一个在所有订单状态下都必然存在的关键元素加载完成。
    # 这是比固定延时更可靠的智能等待，确保了页面在缩放后已稳定。
    await page.locator("xpath=//*[@id='detail']//div[@class='order_information_wrap']").wait_for(state='visible',
                                                                                                 timeout=20000)

    # 步骤3: 对整个可视区域(Viewport)进行截图
    screenshot_bytes = await page.screenshot()

    # 步骤4: 使用Pillow进行精确的、基于坐标的裁剪
    base_image = Image.open(io.BytesIO(screenshot_bytes))
    cropped_image = base_image.crop(CROP_BOX)

    # 步骤5: 对裁剪后的图片进行最终的边缘空白修剪
    final_image = _trim_image(cropped_image)

    # 步骤6: 保存最终成品
    os.makedirs("screenshots", exist_ok=True)
    screenshot_path = os.path.join("screenshots", f"{order_id}.png")
    final_image.save(screenshot_path)

    return screenshot_path


async def screenshot_worker(worker_id: int, browser: Browser, storage_state: dict):
    """
    截图工人协程。它会不断从数据库获取任务，直到没有任务为止。
    每个worker在一个独立的、干净的BrowserContext中工作，以实现完全隔离。
    """
    print(f"[Worker-{worker_id}] 已启动。")
    while True:
        task = await database_async.fetch_pending_task()
        if task is None:
            print(f"[Worker-{worker_id}] 未领到新任务，准备退出。")
            break

        task_id, order_id, *_, detail_url, _, _ = task
        context = None
        try:
            # 创建一个全新的、轻量级的浏览器上下文，并注入登录状态和视口大小
            context = await browser.new_context(
                storage_state=storage_state,
                viewport={'width': VIEWPORT_WIDTH, 'height': VIEWPORT_HEIGHT}
            )
            page = await context.new_page()

            print(f"[Worker-{worker_id}] 正在处理订单 {order_id}...")
            # 使用 'networkidle' 确保页面网络活动基本静默，这是主要的稳定保障
            await page.goto(detail_url, wait_until='networkidle', timeout=30000)

            screenshot_path = await take_screenshot_and_crop(page, order_id)

            result = {'task_id': task_id, 'status': 'completed', 'screenshot_path': screenshot_path}
            await database_async.update_task_status_from_queue(result)
            print(f"  > ✅ [Worker-{worker_id}] 订单 {order_id} 截图成功。")
        except Exception as e:
            result = {'task_id': task_id, 'status': 'failed', 'error': str(e)}
            await database_async.update_task_status_from_queue(result)
            print(f"  > ❌ [Worker-{worker_id}] 订单 {order_id} 截图失败: {type(e).__name__}")
        finally:
            # 无论成功与否，都确保浏览器上下文被干净地关闭，防止资源泄露
            if context:
                await context.close()


async def main():
    """
    异步程序的入口点。
    """
    start_time = time.monotonic()
    await database_async.initialize_database()
    async with async_playwright() as p:
        print("正在启动浏览器...")
        browser = await p.chromium.launch(headless=True)
        cookies = _parse_cookie_string(MY_COOKIE)
        storage_state = {"cookies": cookies}
        print("浏览器启动完成。")
        print(f"--- 准备启动 {WORKER_COUNT} 个并发截图工人 ---")

        # 创建一组并发的worker任务
        workers = [
            asyncio.create_task(screenshot_worker(i + 1, browser, storage_state))
            for i in range(WORKER_COUNT)
        ]

        # 使用 asyncio.gather 等待所有worker完成它们的工作
        await asyncio.gather(*workers)
        await browser.close()

    end_time = time.monotonic()
    duration = end_time - start_time
    print(f"\n--- 并行截图阶段完成 ---")
    print(f"程序总耗时: {duration:.2f} 秒")


if __name__ == "__main__":
    asyncio.run(main())