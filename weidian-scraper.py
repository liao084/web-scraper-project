# scraper.py
# 最终版 - 基于selenium-wire和JSON解析的全功能爬虫

import json
import os
import time
import io
from typing import List, Dict, Any

import pandas as pd
from seleniumwire import webdriver
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException

# 从我们定义好的common.py中导入OrderData类
from common import OrderData


class WeidianScraper:
    """
    封装了所有微店订单爬取和处理逻辑的主类。
    使用selenium-wire捕获网络请求，直接从JSON获取数据。
    """

    def __init__(self, headless: bool = False):
        """
        初始化浏览器驱动，使用selenium-wire。
        """
        print("正在初始化selenium-wire浏览器驱动...")
        options = webdriver.ChromeOptions()
        options.add_experimental_option('excludeSwitches', ['enable-automation'])
        options.add_experimental_option('useAutomationExtension', False)
        options.add_argument("--start-maximized")

        if headless:
            options.add_argument("--headless")
            options.add_argument("--window-size=1920,1080")

        try:
            service = Service(ChromeDriverManager().install())
            self.driver = webdriver.Chrome(service=service, options=options)
            self.driver.set_page_load_timeout(60)
            self.driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
                "source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
            })
        except Exception as e:
            print(f"初始化WebDriver时发生严重错误: {e}")
            raise
        print("浏览器驱动初始化完成。")

    def login_with_cookie(self, cookie_string: str):
        """
        使用Cookie直接登录。
        """
        print("正在使用Cookie进行登录...")
        self.driver.get("https://weidian.com/")
        time.sleep(2)
        self.driver.delete_all_cookies()
        for cookie_item in cookie_string.split(';'):
            if '=' in cookie_item:
                name, value = cookie_item.strip().split('=', 1)
                self.driver.add_cookie({'name': name, 'value': value, 'domain': '.weidian.com'})
        print("Cookie注入完成。")

    def parse_order_json(self, json_data: Dict[str, Any]) -> List[OrderData]:
        """
        解析从XHR请求中捕获到的订单JSON数据。
        """
        orders = []
        if not json_data or "result" not in json_data or "listRespDTOList" not in json_data["result"]:
            return orders

        for order_dict in json_data["result"]["listRespDTOList"]:
            # 安全地获取字段，如果字段不存在则为None
            sub_order = order_dict.get("sub_orders", [{}])[0]

            order = OrderData(
                order_id=order_dict.get("order_id"),
                order_detail_url=order_dict.get("order_detail_url"),
                order_status=order_dict.get("status_desc"),
                total_price=float(order_dict.get("total_price", 0.0)),
                creation_time=order_dict.get("add_time"),
                payment_time=order_dict.get("pay_time"),
                shipping_time=order_dict.get("express_time"),  # 假设发货时间字段是 express_time
            )
            orders.append(order)
        return orders

    def capture_and_parse_orders(self, clicks_to_perform: int, target_url: str) -> List[OrderData]:
        """
        通过点击“加载更多”并捕获XHR请求来采集所有订单数据。
        """
        self.driver.get(target_url)
        wait = WebDriverWait(self.driver, 10)
        wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, "#app > div.order_item_info > ul > li")))
        print("订单列表首页加载成功。")

        all_orders_data = []

        # 捕获并解析第一页的初始请求
        try:
            initial_request = self.driver.wait_for_request(r'https://thor.weidian.com/apollo/order/list/1.1',
                                                           timeout=10)
            if initial_request and initial_request.response:
                initial_json = json.loads(initial_request.response.body.decode('utf-8'))
                parsed_orders = self.parse_order_json(initial_json)
                all_orders_data.extend(parsed_orders)
                print(f"成功捕获并解析首页 {len(parsed_orders)} 条订单数据。")
        except TimeoutException:
            print("警告：未在首页捕获到初始订单数据请求，将从点击加载后开始。")

        # 增量加载循环
        for i in range(clicks_to_perform):
            try:
                load_more_button = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, ".more_span")))

                # 在点击前清空请求记录，确保我们只捕获最新的请求
                del self.driver.requests

                load_more_button.click()
                print(f"点击了“查看更多订单”... (第 {i + 1} / {clicks_to_perform} 次)")

                # 等待下一次数据请求完成
                request = self.driver.wait_for_request(r'https://thor.weidian.com/apollo/order/list/1.1', timeout=20)

                if request and request.response:
                    response_json = json.loads(request.response.body.decode('utf-8'))
                    parsed_orders = self.parse_order_json(response_json)
                    all_orders_data.extend(parsed_orders)
                    print(f"  > 成功捕获并解析 {len(parsed_orders)} 条新订单。")

            except TimeoutException:
                print("等待数据请求超时，可能所有订单已加载完毕。")
                break
            except Exception as e:
                print(f"在第 {i + 1} 次点击时发生错误: {e}")
                break

        print(f"\n===== 数据采集完成：共获取到 {len(all_orders_data)} 条订单的完整信息。 =====")
        return all_orders_data

    def take_screenshots(self, orders_data: List[OrderData]):
        """
        为每个订单在新标签页中进行截图。
        """
        print("\n===== 开始执行截图任务 =====")
        if not orders_data: return

        original_window = self.driver.current_window_handle
        wait = WebDriverWait(self.driver, 20)

        if not os.path.exists("screenshots"):
            os.makedirs("screenshots")

        for i, order in enumerate(orders_data):
            if not order.order_detail_url:
                continue

            print(f"--- 正在为订单 {order.order_id} 截图 ({i + 1}/{len(orders_data)}) ---")
            try:
                # 在新标签页中打开
                self.driver.switch_to.new_window('tab')
                self.driver.get(order.order_detail_url)

                # 定位核心内容区域并截图 (假设ID为'app')
                main_content_element = wait.until(EC.visibility_of_element_located((By.ID, "app")))

                screenshot_path = os.path.join("screenshots", f"{order.order_id}.png")
                main_content_element.screenshot(screenshot_path)
                order.screenshot_path = screenshot_path  # 将保存路径存回对象
                print(f"  > 截图成功: {screenshot_path}")

                self.driver.close()  # 关闭当前标签页
                self.driver.switch_to.window(original_window)  # 切换回主窗口
                time.sleep(1)  # 短暂休息，防止操作过快

            except Exception as e:
                print(f"  > 为订单 {order.order_id} 截图失败: {e}")
                # 如果出错，同样要确保关闭新窗口并切回主窗口
                if len(self.driver.window_handles) > 1:
                    self.driver.close()
                self.driver.switch_to.window(original_window)
                continue

        print("\n===== 截图任务全部完成 =====")

    def save_to_excel(self, all_orders_data: List[OrderData], filename="微店订单导出.xlsx"):
        """
        将所有数据和嵌入式图片保存到Excel。
        """
        print(f"\n===== 开始将 {len(all_orders_data)} 条数据写入Excel: {filename} =====")
        if not all_orders_data: return

        # 准备DataFrame，只包含您需要的核心字段
        df = pd.DataFrame([{
            '订单号': order.order_id,
            '订单状态': order.order_status,
            '实付金额': order.total_price,
            '下单时间': order.creation_time,
            '付款时间': order.payment_time,
            '发货时间': order.shipping_time,
        } for order in all_orders_data])

        writer = pd.ExcelWriter(filename, engine='xlsxwriter')
        df.to_excel(writer, sheet_name='订单详情', index=False)
        workbook = writer.book
        worksheet = writer.sheets['订单详情']

        # --- 设置列宽和行高，并插入嵌入式图片 ---
        worksheet.write('G1', '订单截图')
        worksheet.set_column('A:F', 22)
        worksheet.set_column('G:G', 45)

        for index, order in enumerate(all_orders_data):
            row_num = index + 2
            worksheet.set_row(row_num - 1, 240)
            if order.screenshot_path and os.path.exists(order.screenshot_path):
                try:
                    with open(order.screenshot_path, 'rb') as f:
                        image_data = f.read()
                    worksheet.insert_image(
                        f'G{row_num}', order.screenshot_path,
                        {'image_data': io.BytesIO(image_data), 'object_position': 2, 'x_scale': 0.5, 'y_scale': 0.5}
                    )
                except Exception as e:
                    print(f"在第 {row_num} 行插入图片时出错: {e}")

        writer.close()
        print(f"===== Excel文件 '{filename}' 写入成功！ =====")

    def run(self, cookie: str, clicks: int):
        """
        执行爬虫的主流程。
        """
        self.login_with_cookie(cookie)
        target_url = "https://weidian.com/user/order/list.php?type=0"  # 从'全部'页面开始

        # 核心流程
        all_data = self.capture_and_parse_orders(clicks, target_url)
        self.take_screenshots(all_data)
        # self.save_to_excel(all_data)

        print("\n🎉🎉🎉 项目执行完毕！ 🎉🎉🎉")


# --- 主入口 (Main Entry Point) ---
if __name__ == "__main__":
    # ==================== 用户配置区 ====================
    # 1. 预估一个足够大的点击次数，以加载所有您需要的订单
    CLICKS_TO_PERFORM = 1

    # 2. 在这里粘贴您从浏览器获取的、最新的Cookie字符串
    MY_COOKIE = ("wdtoken=53da40f0; __spider__visitorid=f9ce2e7df2397d94; smart_login_type=0; v-components/clean-up-advert@private_domain=1736676582; v-components/clean-up-advert@wx_app=1736676582; token=; isLogin=; loginUserType=; loginUserSource=; WD_b_id=; WD_b_wduss=; WD_b_country=; WD_b_tele=; WD_s_id=; WD_s_tele=; WD_s_wduss=; WD_seller=; hold=; cn_merchant=; hi_dxh=; visitor_id=d3ab461c-0422-4912-a2e3-da55fd55693b; is_login=true; login_type=LOGIN_USER_TYPE_MASTER; login_source=LOGIN_USER_SOURCE_MASTER; uid=1914883825; duid=1914883825; sid=1798256885; __spider__sessionid=2daceef675922809; login_token=_EwWqqVIQTfS25Z1aeG1c3tUeSQg9EB8OW4VosAkuvlgy6ogm5Io2HWETPd4RV6ke79RGwQ4385m6xSvbSD9QqiZCr_egNQN1IkLI-iohpX1TIQxeHYmmDadvlqfB6o_GJm60vIAqmAkEyg1kVt59DzTtFSCRREra_oHZlwIKroh-FUZMdOgGeQDstqH4BpL2wD-y6H1F5NzS2tp-hgK0G9KBBaoNyNjLDEvG5-9y0Z0fSssKHgstA_RlyJFqpqMOggPT7ASJ")
    # ====================================================

    scraper = WeidianScraper()
    try:
        if "PASTE_YOUR_LATEST_COOKIE" in MY_COOKIE:
            raise Exception("请在脚本中配置您的最新Cookie！")
        scraper.run(MY_COOKIE, CLICKS_TO_PERFORM)
    except Exception as e:
        print(f"程序执行时遇到致命错误: {e}")
    finally:
        print("程序运行结束，按回车键退出...")
        input()
        scraper.driver.quit()