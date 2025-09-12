# collector.py
# Phase 1: 高速数据采集器 (生产者)
# 职责：仅负责通过selenium-wire捕获订单JSON，解析后存入SQLite数据库。

import json
import time
import gzip
from typing import List, Dict

from seleniumwire import webdriver
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException

# 导入我们自己的模块
import database
from common import OrderData


class WeidianCollector:
    """
    一个专门负责采集微店订单数据并将其存入数据库的类。
    """

    def __init__(self, headless: bool = True):
        print("正在初始化selenium-wire浏览器驱动...")
        options = webdriver.ChromeOptions()
        options.add_experimental_option('excludeSwitches', ['enable-automation'])
        options.add_argument("--window-size=1200,800")
        if headless:
            options.add_argument("--headless")
            options.add_argument("--disable-gpu")  # Headless模式下推荐

        # 解决在某些系统上/dev/shm分区过小的问题
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--no-sandbox")

        service = Service(ChromeDriverManager().install())
        self.driver = webdriver.Chrome(service=service, options=options)
        self.wait = WebDriverWait(self.driver, 45)  # 延长等待时间以应对慢速网络
        print("浏览器驱动初始化完成。")

    def login_with_cookie(self, cookie_string: str):
        print("正在使用Cookie进行登录...")
        # 访问一个简单的页面来设置Cookie
        self.driver.get("https://weidian.com/")
        time.sleep(1)
        self.driver.delete_all_cookies()
        for cookie_item in cookie_string.split(';'):
            if '=' in cookie_item:
                name, value = cookie_item.strip().split('=', 1)
                # 确保Cookie的domain是正确的
                self.driver.add_cookie({'name': name, 'value': value, 'domain': '.weidian.com'})
        print("Cookie注入完成。")

    def _parse_response(self, request) -> List[Dict]:
        """
        解析API响应，将其转换为字典列表，准备存入数据库。
        """
        try:
            raw_body = request.response.body
            if 'gzip' in request.response.headers.get('Content-Encoding', ''):
                decompressed_body = gzip.decompress(raw_body)
            else:
                decompressed_body = raw_body

            response_json = json.loads(decompressed_body.decode('utf-8'))

            orders_list = []
            if "result" in response_json and "listRespDTOList" in response_json["result"]:
                for order_dict in response_json["result"]["listRespDTOList"]:
                    final_price_str = order_dict.get("modified_total_price") or order_dict.get("total_price", "0.0")
                    sub_order = order_dict.get("sub_orders", [{}])[0]

                    order_data = OrderData(
                        order_id=order_dict.get("order_id"),
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
        except Exception as e:
            print(f"  - ❌ 解析响应时发生错误: {e}")
            return []

    def run(self, clicks_to_perform: int):
        print("\n--- Phase 1: 开始高速采集订单数据 ---")

        # 1. 初始化数据库
        print("正在初始化数据库...")
        database.initialize_database()
        print("数据库初始化完成。")

        # 2. 登录
        self.login_with_cookie(MY_COOKIE)

        # 3. 访问订单列表页并开始采集
        start_url = "https://weidian.com/user/order/list.php?type=2"
        self.driver.get(start_url)

        total_discovered = 0
        total_inserted = 0

        try:
            # 点击“全部”标签页来触发初始请求
            all_tab_xpath = '//*[@id="app"]/div[2]/div[2]/ul/li[1]/span'
            all_tab_button = self.wait.until(EC.element_to_be_clickable((By.XPATH, all_tab_xpath)))

            del self.driver.requests  # 清空之前的请求记录
            all_tab_button.click()

            print("等待首页订单数据加载...")
            initial_request = self.driver.wait_for_request(r'tradeview/buyer.order.list', timeout=30)
            initial_orders = self._parse_response(initial_request)

            if initial_orders:
                inserted_count = database.insert_orders(initial_orders)
                total_discovered += len(initial_orders)
                total_inserted += inserted_count
                print(f"  > 首页发现 {len(initial_orders)} 条订单，新存入 {inserted_count} 条。")
            else:
                print("  - ⚠️ 首页未发现订单数据，请检查Cookie或页面结构。")

            # 循环点击“加载更多”
            for i in range(clicks_to_perform):
                print(f"\n--- 正在加载第 {i + 2} 页... ---")
                try:
                    button_selector = (By.CSS_SELECTOR, "div.order_add_list .more_span")
                    load_more_button = self.wait.until(EC.element_to_be_clickable(button_selector))

                    # 使用JS点击，更稳定
                    self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", load_more_button)
                    time.sleep(1)  # 等待滚动生效

                    del self.driver.requests
                    self.driver.execute_script("arguments[0].click();", load_more_button)

                    # 等待下一次API请求
                    next_page_request = self.driver.wait_for_request(r'tradeview/buyer.order.list', timeout=30)
                    next_page_orders = self._parse_response(next_page_request)

                    if next_page_orders:
                        inserted_count = database.insert_orders(next_page_orders)
                        total_discovered += len(next_page_orders)
                        total_inserted += inserted_count
                        print(f"  > 本批次发现 {len(next_page_orders)} 条订单，新存入 {inserted_count} 条。")
                    else:
                        print("  - ⚠️ 本批次未发现订单数据，可能已达末页。")
                        break  # 如果API返回空，提前结束

                except TimeoutException:
                    print(f"\n✅ 未找到“加载更多”按钮，或已加载完毕。")
                    break

        except Exception as e:
            print(f"\n❌ 数据采集中途发生严重错误: {e}")

        finally:
            print(f"\n--- 数据采集阶段完成 ---")
            print(f"总计发现订单: {total_discovered} 条")
            print(f"本次新存入数据库: {total_inserted} 条")


# --- 主入口 (Main Entry Point) ---
if __name__ == "__main__":
    start_time = time.time()

    # ==================== 用户配置区 ====================
    MY_COOKIE = ("__spider__visitorid=f9ce2e7df2397d94; smart_login_type=0; is_login=true; login_type=LOGIN_USER_TYPE_MASTER; login_source=LOGIN_USER_SOURCE_MASTER; uid=1914883825; duid=1914883825; sid=1798256885; __spider__sessionid=6331d26624bf4ddc; wdtoken=18021053; login_token=_EwWqqVIQZ9VKaPUruqau8kzyu4eUegvgO8pDg8Q0oz7Odq671TksX_plNoFGpsP6x04OuRqqEHMvHnIZcSE8gmUVGkr6pzQeAAw_an3pRhWxhS_JqVpZzjLeqqpYaHFSWVE3Neoh7r1NXiysF2dKSrSjA_ExsEv7o6t1YbYfrlzmjfzfZBcU_qzEU_p_FqKI9yDI3QxMbb2Ona2i-S5KsqMX7_TzwS0QgIEV3QWUrlZGrOHiEr7ZqOqZ0g_vfghKLvgpbepB")
    CLICKS_TO_PERFORM = 49  # 抓取6页订单 (0=首页, 1=首页+1页, ...)
    # ====================================================

    collector = None
    try:
        if "在这里粘贴" in MY_COOKIE:
            raise ValueError("请在脚本中填写您最新的有效Cookie！")

        collector = WeidianCollector(headless=False)  # 采集阶段建议使用headless模式以提高效率
        collector.run(clicks_to_perform=CLICKS_TO_PERFORM)

    except Exception as e:
        print(f"程序执行时遇到致命错误: {e}")
    finally:
        if collector and collector.driver:
            collector.driver.quit()

        end_time = time.time()
        duration = end_time - start_time
        print(f"\n程序总耗时: {duration:.2f} 秒")
        print("采集器运行结束。")