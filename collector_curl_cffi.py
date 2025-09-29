# -*- coding: utf-8 -*-
"""
collector_v4_final.py (V3.1 - 动态指纹版)

该模块是项目的数据采集核心（生产者），负责以高性能、高匿名的策略从目标API抓取订单数据。

核心架构设计:
- Asynchronous-First: 基于 `asyncio` 构建，实现高并发I/O密集型任务。
- Advanced Anti-Scraping: 采用 `curl_cffi` 替代传统HTTP库，以模拟真实浏览器的TLS/JA3指纹，
  并结合动态指纹池（`BROWSER_FINGERPRINTS`）策略，使得每个请求的客户端特征都难以预测。
- Robust Concurrency Control: 利用 `asyncio.Semaphore` 精确控制并发请求数量，防止因请求过载
  而触发服务端的速率限制。
- Resilient by Design: 内置了基于指数退避思想的自动重试机制，能够优雅地处理可恢复的
  网络错误（`CurlError`），显著提升了在不稳定网络环境下的采集成功率。
- Configuration-Driven: 通过 `.env` 文件将敏感信息（如Cookie、代理凭证）与业务逻辑解耦，
"""

import asyncio
import json
import os
import random
import time
from typing import Optional, List, Dict

# curl_cffi: 项目的基石。它提供了对libcurl的绑定，并实现了对浏览器指纹的模拟（impersonate），
# 这是绕过Cloudflare等高级WAF的关键。
from curl_cffi.requests import AsyncSession
from curl_cffi import CurlError

# dotenv: 用于从 `.env` 文件中加载环境变量，实现了配置与代码的分离。
from dotenv import load_dotenv

# 项目内部模块导入
import database_async
from common import OrderData

# --- 1. 初始化与配置加载 ---
load_dotenv()
print("正在从 .env 文件加载配置...")

# 从环境变量中安全地加载代理配置和身份凭证。
# 这种方式避免了将敏感信息硬编码在代码中。
SMARTPROXY_USERNAME = os.getenv("SMARTPROXY_USERNAME")
SMARTPROXY_PASSWORD = os.getenv("SMARTPROXY_PASSWORD")
SMARTPROXY_ENDPOINT = os.getenv("SMARTPROXY_ENDPOINT")
SMARTPROXY_PORT = os.getenv("SMARTPROXY_PORT")
MY_COOKIE = os.getenv("MY_COOKIE")

# 前置条件检查：确保所有必要的配置都已存在，否则快速失败。
if not all([SMARTPROXY_USERNAME, SMARTPROXY_PASSWORD, SMARTPROXY_ENDPOINT, SMARTPROXY_PORT, MY_COOKIE]):
    raise ValueError("错误：.env 文件中的一个或多个关键配置项缺失！")

# 构建符合 `curl_cffi` 格式的代理URL。
proxy_auth = f"{SMARTPROXY_USERNAME}:{SMARTPROXY_PASSWORD}"
proxy_server = f"{SMARTPROXY_ENDPOINT}:{SMARTPROXY_PORT}"
PROXY_URL = f"http://{proxy_auth}@{proxy_server}"
PROXIES = {"http": PROXY_URL, "https": PROXY_URL}


# ==================== 核心策略与性能调优参数 ====================

# 预计抓取的总页数（从第2页起算）。
PAGES_TO_FETCH = 2999

# 并发请求数。这是一个关键的性能与隐蔽性的权衡点。
# 较低的数值（如5-8）能更好地模拟人类行为，降低被WAF行为分析模块标记的风险。
CONCURRENT_REQUESTS = 6

# 模拟人类操作的随机延迟范围（秒）。
# 在每次成功的请求后引入一个非固定的等待时间，可以打乱请求的规律性，是基础但有效的反爬策略。
POLITE_WAIT_SECONDS_RANGE = (1.0, 3.0)

# --- 动态指纹池 ---
# 这是对抗高级指纹识别反爬系统的核心武器。通过在每次请求时随机选择一个指纹，
# 我们让服务器难以将多个请求关联到同一个自动化客户端。
# 列表中应只包含 curl_cffi 支持的、且较新的浏览器版本。
BROWSER_FINGERPRINTS = [
    "chrome110", "chrome107", "chrome104", "chrome120", "chrome119", "chrome116"
]

# --- 健壮性配置：自动重试 ---
# 每个请求的最大尝试次数。设置为3意味着首次请求失败后，最多再重试2次。
RETRY_COUNT = 3
# 重试前的等待时间（秒）。给予服务器和网络一个缓冲期，避免因连续快速重试而被封禁。
RETRY_DELAY_SECONDS = 3
# =============================================================


# --- API 接口常量定义 ---
# 将API端点和固定的请求头定义为常量，便于维护和管理。
API_URL = "https://thor.weidian.com/tradeview/buyer.order.list/1.1"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "Origin": "https://weidian.com",
    "Referer": "https://weidian.com/",
}
FIXED_CONTEXT_STR = '{"shopping_center":""}'
# 从完整的Cookie字符串中动态提取 `wdtoken`，确保其与Cookie主体保持同步。
FIXED_WDTOKEN = MY_COOKIE.split('wdtoken=')[1].split(';')[0]

# --- 全局状态变量 ---
# 用于在整个采集周期内累计统计数据。
total_discovered = 0
total_inserted = 0
# 创建一个全局的Semaphore实例，作为并发任务的“交通信号灯”。
SEMAPHORE = asyncio.Semaphore(CONCURRENT_REQUESTS)


def parse_cookie_string_to_dict(cookie_string: str) -> Dict[str, str]:
    """
    将从浏览器复制的原始Cookie字符串解析为 `curl_cffi` 需要的字典格式。

    Args:
        cookie_string: 原始的、以分号分隔的Cookie字符串。

    Returns:
        一个键值对表示的Cookie字典。
    """
    cookie_dict = {}
    for item in cookie_string.split(';'):
        item = item.strip()
        if '=' in item:
            name, value = item.split('=', 1)
            cookie_dict[name] = value
    return cookie_dict


def parse_and_prepare_orders(response_json: dict) -> List[Dict]:
    """
    一个纯函数，负责从API响应的JSON中解析、清洗和格式化订单数据。

    该函数具有良好的健壮性，能够处理响应中数据字段缺失或为None的情况。

    Args:
        response_json: API返回的JSON数据，已通过 `response.json()` 转换。

    Returns:
        一个包含多个订单数据字典的列表，可以直接用于数据库插入。
    """
    orders_list = []
    result_data = response_json.get("result")
    if result_data and "listRespDTOList" in result_data:
        order_dict_list = result_data["listRespDTOList"]
        if order_dict_list is None:
            return []  # 如果API返回null，视为空列表，防止`TypeError`。
        for order_dict in order_dict_list:
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
    return orders_list


async def fetch_page(session: AsyncSession, page_no: int, first_order_id: Optional[str] = None) -> Optional[List[Dict]]:
    """
    核心的并发工作单元（Worker）。

    该函数负责获取单页的订单数据，并封装了所有核心的采集策略：
    并发控制、动态指纹、自动重试、数据解析和存储。

    Args:
        session: 复用的 `AsyncSession` 实例，用于保持TCP连接和会话状态。
        page_no: 需要抓取的订单页码。
        first_order_id: 用于分页的关键锚定ID，从第二页开始必须提供。

    Returns:
        成功时返回从API获取的订单列表，若已达末页则返回空列表。
        在所有重试均失败后，返回 `None`。
    """
    global total_discovered, total_inserted

    # `async with SEMAPHORE` 是一个优雅的并发控制模式。
    # 当池中（由CONCURRENT_REQUESTS定义）的许可全部被占用时，协程会在此处异步等待，
    # 直到有其他协程执行完毕并释放许可。
    async with SEMAPHORE:
        # 构造请求载荷（Payload）。
        param_dict = {
            "type": "0", "from": "h5", "page_no": page_no, "page_size": 10,
            "v_seller_id": "",
        }
        if first_order_id:
            param_dict["statusOrderId"] = first_order_id
        param_str = json.dumps(param_dict, separators=(',', ':'))
        form_data = {"param": param_str, "context": FIXED_CONTEXT_STR, "wdtoken": FIXED_WDTOKEN}

        # --- 健壮性核心：自动重试循环 ---
        for attempt in range(RETRY_COUNT):
            try:
                # --- 反爬核心：动态选择指纹 ---
                # 在每次请求（包括重试）前，都从指纹池中随机选择一个新的身份。
                fingerprint = random.choice(BROWSER_FINGERPRINTS)

                if attempt > 0:
                    print(f"  > [重试 {attempt}/{RETRY_COUNT}] 正在再次尝试第 {page_no} 页 (使用新指纹: {fingerprint})...")

                response = await session.post(
                    API_URL,
                    data=form_data,
                    impersonate=fingerprint,  # 应用随机选择的浏览器指纹
                    proxies=PROXIES,          # 通过配置好的住宅代理发出请求
                    timeout=40.0              # 为代理网络设置一个较为宽裕的超时时间
                )
                # 检查HTTP状态码，如果是非2xx的码（如403, 500），将抛出异常。
                response.raise_for_status()
                response_json = response.json()

                orders_to_insert = parse_and_prepare_orders(response_json)

                if not orders_to_insert:
                    print(f"  - 第 {page_no} 页没有发现订单数据，可能已达末页。")
                    return []  # 正常到达末页，返回空列表。

                # 将数据异步写入数据库，并更新全局统计。
                inserted_count = await database_async.insert_orders(orders_to_insert)
                total_discovered += len(orders_to_insert)
                total_inserted += inserted_count
                print(f"  ✅ 第 {page_no} 页 (使用 {fingerprint}): 发现 {len(orders_to_insert)} 条，新存入 {inserted_count} 条。")

                # --- 反爬核心：模拟人类行为的随机等待 ---
                await asyncio.sleep(random.uniform(*POLITE_WAIT_SECONDS_RANGE))

                # 任务成功完成，立即退出重试循环并返回结果。
                return response_json.get("result", {}).get("listRespDTOList", [])

            except CurlError as e:
                # 精确捕获由 `curl_cffi` 抛出的底层网络异常（如超时、连接重置、协议错误）。
                # 这些是典型的瞬态错误，非常适合重试。
                print(f"  - ⚠️ 第 {page_no} 页网络错误 (尝试 {attempt + 1}/{RETRY_COUNT}): {e}")
                if attempt < RETRY_COUNT - 1:
                    await asyncio.sleep(RETRY_DELAY_SECONDS)  # 等待后进入下一次重试
                else:
                    print(f"  ❌ 第 {page_no} 页在多次重试后仍失败。")
                    return None  # 所有重试机会用尽，宣告失败。
            except Exception as e:
                # 捕获其他所有意料之外的异常（如JSON解析失败、键错误等）。
                # 这些通常是程序逻辑或API结构变更导致的，重试无法解决，应直接失败。
                print(f"  ❌ 第 {page_no} 页处理时遇到致命错误: {type(e).__name__} - {e}")
                return None
        return None  # 理论上不会执行到这里，但作为代码的防御性保障。


async def main():
    """
    主协程，负责编排整个采集流程。
    """
    print("--- Phase 1 (V4.2.1 - 动态指纹版): 开始高匿并发采集 ---")
    await database_async.initialize_database()

    cookie_dict = parse_cookie_string_to_dict(MY_COOKIE)
    print("✅ Cookie 已成功解析为字典格式。")

    # 使用 `async with` 语句管理 `AsyncSession` 的生命周期，确保资源被正确释放。
    async with AsyncSession(headers=HEADERS, cookies=cookie_dict) as session:
        # 步骤 1: 串行获取第一页。
        # 这是一个关键的引导步骤，因为后续所有页面的并发请求都依赖于从第一页获取的`first_order_id`。
        print("\n--- 正在获取第一页和关键锚定ID ---")
        first_page_orders = await fetch_page(session, page_no=1)

        if first_page_orders is None or not first_page_orders:
            print("❌ 无法获取第一页数据，请检查Cookie、代理或网络。程序退出。")
            return

        first_order_id = first_page_orders[0].get("order_id")
        print(f"✅ 成功获取到锚定订单ID: {first_order_id}")

        # 步骤 2: 创建后续所有页面的并发任务。
        # 我们在这里只创建任务（`create_task`），并不立即执行它们。
        # `asyncio` 的事件循环会在稍后调度这些任务的运行。
        print(f"\n--- 创建 {PAGES_TO_FETCH} 个并发任务 (最大并发数: {CONCURRENT_REQUESTS}) ---")
        tasks = []
        for page in range(2, PAGES_TO_FETCH + 2):
            task = asyncio.create_task(
                fetch_page(session, page_no=page, first_order_id=first_order_id)
            )
            tasks.append(task)

        # 步骤 3: 并发执行所有任务。
        # `asyncio.gather` 会等待列表中的所有任务完成。
        await asyncio.gather(*tasks)

    print("\n--- 数据采集阶段完成 ---")
    print(f"总计发现订单: {total_discovered} 条")
    print(f"本次新存入数据库: {total_inserted} 条")


if __name__ == "__main__":
    # 使用 `time.monotonic()` 来进行性能计时，因为它不受系统时间变化的影响，更精确。
    start_time = time.monotonic()
    try:
        # `asyncio.run()` 是启动和运行顶级异步程序的标准方式。
        asyncio.run(main())
    except Exception as e:
        print(f"程序执行时遇到致命错误: {e}")
    finally:
        # `finally` 块确保无论程序是正常结束还是异常退出，总耗时都会被打印。
        end_time = time.monotonic()
        duration = end_time - start_time
        print(f"\n程序总耗时: {duration:.2f} 秒")