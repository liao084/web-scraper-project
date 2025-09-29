# collector_async.py
#
# 负责项目的数据采集阶段（生产者）。
# 它使用 Playwright 的事件监听机制，在后台自动捕获订单列表页的API请求，
# 解析后将订单数据异步存入数据库。

import asyncio
import json
import gzip
import time
from typing import List, Dict

from playwright.async_api import async_playwright, Response

# 导入项目内部的异步数据库模块和数据模型
import database_async
from common import OrderData

# ==================== 用户配置区 ====================
MY_COOKIE = (
    "wdtoken=b700990a; __spider__visitorid=b32bd2948c71ccba; __spider__sessionid=f07f9182f8d35056; login_token=_EwWqqVIQFrYy3oczxQdlxhC841fICvtvder0hnWvKHxii8dqKfX_5hQ_qijjh9Z5F3qD6sVVRHnXidbTYuhip1zKRmbuq1EgRZ66YXW8ZxZyWGsaBh13ADEkhXCYdq6rPNPg3nYJ56bpMwEWYLyuD4AuBQSq85SG2wXlJg80anK3ivJxI8x4oA8Nl-qbbXJG9rzgZna0jHjvRsJI1JylimZYBO-2qCYaz8qZSqnQ0x5UXSwL9REV8CMIwMG4dMQyRgekSXp-; is_login=true; login_type=LOGIN_USER_TYPE_MASTER; login_source=LOGIN_USER_SOURCE_MASTER; uid=1914883825; duid=1914883825; sid=1798256885; smart_login_type=0")
CLICKS_TO_PERFORM = 2999
TARGET_URL = "https://weidian.com/user/order/list.php?type=0"
# ====================================================


class WeidianCollectorAsync:
    """
    封装了所有与订单采集相关的异步逻辑。
    """

    def __init__(self):
        """
        初始化采集器的状态变量。
        """
        self.total_discovered = 0
        self.total_inserted = 0
        self.active_parsers = set()
        self.new_page_processed = asyncio.Event()

    def _parse_cookie_string(self, cookie_string: str) -> List[Dict]:
        """
        将浏览器Cookie字符串转换为Playwright `context.new_context` 所需的格式。
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

    async def _parse_and_save_orders(self, response: Response):
        """
        一个健壮的响应处理器，负责解析订单数据并将其异步存入数据库。
        该函数被设计为在后台并发执行。
        """
        task = asyncio.current_task()
        self.active_parsers.add(task)
        try:
            raw_body = await response.body()
            # 采用健壮的解压逻辑：优先尝试gzip解压，若失败则假定为纯文本。
            try:
                decompressed_body = gzip.decompress(raw_body)
            except gzip.BadGzipFile:
                decompressed_body = raw_body

            response_json = json.loads(decompressed_body.decode('utf-8'))
            orders_list = []

            # 从JSON数据中提取订单信息，并映射到 OrderData 模型
            if "result" in response_json and "listRespDTOList" in response_json["result"]:
                for order_dict in response_json["result"]["listRespDTOList"]:
                    final_price_str = order_dict.get("modified_total_price") or order_dict.get("total_price", "0.0")
                    sub_order = order_dict.get("sub_orders", [{}])[0]
                    order_data = OrderData(
                        order_id=order_dict.get("order_id"),
                        shop_name=order_dict.get("shop_name"),
                        item_title=sub_order.get("item_title"),
                        item_sku_title=sub_order.get("item_sku_title"),
                        order_status=order_dict.get("status_desc"),
                        sub_order_desc=sub_order.get("sub_order_desc", ""),
                        total_price=str(final_price_str),
                        creation_time=order_dict.get("add_time"),
                        payment_time=order_dict.get("pay_time"),
                        shipping_time=order_dict.get("express_time"),
                        order_detail_url=order_dict.get("order_detail_url"),
                    )
                    orders_list.append(order_data.to_dict())

            if orders_list:
                inserted_count = await database_async.insert_orders(orders_list)
                self.total_discovered += len(orders_list)
                self.total_inserted += inserted_count
                print(f"  > [Handler] ✅ 成功解析，发现 {len(orders_list)} 条订单，新存入 {inserted_count} 条。")

                self.new_page_processed.set()

        except Exception as e:
            print(f"  - ❌ [Handler] 解析或保存订单时发生错误: {e}")
        finally:
            # 确保任务完成后，从活跃集合中移除，用于优雅退出
            self.active_parsers.remove(task)

    async def _handle_response(self, response: Response):
        """
        核心的事件监听器。Playwright会在每次网络响应时调用此函数。
        """
        # 精确过滤我们需要的订单数据API端点
        if 'tradeview/buyer.order.list/1.1' in response.url and response.request.method == 'POST':
            # 使用 asyncio.create_task 将解析和存储操作分派到后台执行，
            # 避免阻塞事件循环，从而可以继续监听其他网络事件。
            asyncio.create_task(self._parse_and_save_orders(response))

    async def run(self, clicks_to_perform: int):
        """
        执行整个采集流程的主函数。
        """
        print(f"\n--- Phase 1 (Async V4.0): 开始高速采集订单数据 ---")
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                storage_state={"cookies": self._parse_cookie_string(MY_COOKIE)}
            )
            page = await context.new_page()
            page.on("response", self._handle_response)

            # 直接导航到目标URL。`wait_until='networkidle'` 确保了页面的
            # 初始网络活动（包括首页订单的XHR请求）有足够时间完成。
            print(f"步骤1: 直接导航到目标页面 -> {TARGET_URL}")
            await page.goto(TARGET_URL, wait_until='networkidle', timeout=60000)

            # 验证首页UI是否成功加载，作为采集流程开始的信号
            print("步骤2: 验证初始订单列表容器是否已加载...")
            try:
                await page.locator('xpath=//*[@id="app"]/div[3]/ul').wait_for(state='visible', timeout=20000)
                print("✅ 首页UI加载成功！")
            except Exception as e:
                print(f"❌ 无法加载初始订单列表，请检查Cookie或网络。错误: {e}")
                await browser.close()
                return

            # 循环模拟点击“加载更多”按钮，以触发后续页面的API请求
            try:
                for i in range(clicks_to_perform):
                    print(f"\n--- 第 {i + 1}/{clicks_to_perform} 次点击 '加载更多' ---")
                    load_more_button = page.locator('xpath=//*[@id="app"]/div[4]/div/div')
                    # await load_more_button.wait_for(state='visible', timeout=15000)

                    # --- START OF MODIFICATION ---

                    # 1. 在点击前，先“放下”信号旗
                    self.new_page_processed.clear()

                    # 2. 执行点击
                    print("  > 正在执行JS强制点击...")
                    await load_more_button.dispatch_event('click')

                    # 3. 等待后台处理器“举起”信号旗
                    # 这意味着新一页的数据已经被成功捕获和处理
                    print("  > 等待新一页数据处理完成...")
                    await self.new_page_processed.wait()
                    print(f"  > ✅ 数据已同步！当前共处理 {self.total_inserted} 条新订单。")

            except Exception as e:
                print(f"\n✅ '加载更多'循环结束。可能已到达末页或超时。原因: {type(e).__name__}")
            finally:
                # 优雅退出：等待所有在后台运行的解析任务完成
                print("\n所有操作完成，等待后台数据处理...")
                await asyncio.sleep(5)
                while self.active_parsers:
                    await asyncio.sleep(0.5)
                await browser.close()
                print("\n--- 浏览器已关闭 ---")

        print(f"\n--- 数据采集阶段完成 ---")
        print(f"总计发现订单: {self.total_discovered} 条")
        print(f"本次新存入数据库: {self.total_inserted} 条")


async def main():
    """
    异步程序的入口点。
    """
    print("正在初始化数据库...")
    await database_async.initialize_database()
    print("数据库初始化完成。")

    collector = WeidianCollectorAsync()
    await collector.run(clicks_to_perform=CLICKS_TO_PERFORM)


if __name__ == "__main__":
    # 使用 time.monotonic() 提供高精度的、不受系统时间影响的计时
    start_time = time.monotonic()
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n程序被用户中断。")
    except Exception as e:
        print(f"程序执行时遇到致命错误: {e}")
    finally:
        end_time = time.monotonic()
        duration = end_time - start_time
        print(f"\n程序总耗时: {duration:.2f} 秒")
        print("采集器运行结束。")