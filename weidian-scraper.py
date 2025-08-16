# scraper.py
# 最终交付版 - JSON高速采集 + 精准裁剪/格式化截图 + 完美Excel导出
import json
import time
import gzip
import os
import io
from typing import List

import pandas as pd
from PIL import Image, ImageChops
from seleniumwire import webdriver
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException

from common import OrderData


class WeidianScraper:
    """
    封装了所有微店订单爬取和处理逻辑的主类（最终交付版）。
    """

    def __init__(self, headless: bool = False):
        print("正在初始化selenium-wire浏览器驱动...")
        options = webdriver.ChromeOptions()
        options.add_experimental_option('excludeSwitches', ['enable-automation'])
        options.add_argument("--window-size=1200,1080")
        if headless:
            options.add_argument("--headless")
        service = Service(ChromeDriverManager().install())
        self.driver = webdriver.Chrome(service=service, options=options)
        self.wait = WebDriverWait(self.driver, 30)
        print("浏览器驱动初始化完成。")

    def login_with_cookie(self, cookie_string: str):
        print("正在使用Cookie进行登录...")
        self.driver.get("https://weidian.com/")
        time.sleep(2)
        self.driver.delete_all_cookies()
        for cookie_item in cookie_string.split(';'):
            if '=' in cookie_item:
                name, value = cookie_item.strip().split('=', 1)
                self.driver.add_cookie({'name': name, 'value': value, 'domain': '.weidian.com'})
        print("Cookie注入完成。")

    def _parse_response(self, request) -> List[OrderData]:
        # ... _parse_response 函数保持不变 ...
        raw_body = request.response.body
        if 'gzip' in request.response.headers.get('Content-Encoding', ''):
            decompressed_body = gzip.decompress(raw_body)
        else:
            decompressed_body = raw_body
        response_json = json.loads(decompressed_body.decode('utf-8'))
        orders = []
        if "result" in response_json and "listRespDTOList" in response_json["result"]:
            for order_dict in response_json["result"]["listRespDTOList"]:
                final_price_str = order_dict.get("modified_total_price") or order_dict.get("total_price", "0.0")
                sub_order = order_dict.get("sub_orders", [{}])[0]
                order = OrderData(
                    order_id=order_dict.get("order_id"),
                    item_title=sub_order.get("item_title"),
                    item_sku_title=sub_order.get("item_sku_title"),
                    order_status=order_dict.get("status_desc"),
                    total_price=str(final_price_str),
                    creation_time=order_dict.get("add_time"),
                    payment_time=order_dict.get("pay_time"),
                    shipping_time=order_dict.get("express_time"),
                    order_detail_url=order_dict.get("order_detail_url"),
                )
                orders.append(order)
        return orders

    def _trim_image(self, image: Image.Image) -> Image.Image:
        """一个辅助函数，用于自动裁剪图片的空白边缘"""
        bg = Image.new(image.mode, image.size, image.getpixel((0, 0)))
        diff = ImageChops.difference(image, bg)
        diff = ImageChops.add(diff, diff, 2.0, -100)
        bbox = diff.getbbox()
        if bbox:
            return image.crop(bbox)
        return image

    def take_screenshots(self, orders_data: List[OrderData]):
        print(f"\n--- Phase 3: 开始执行截图与精加工任务 ---")
        if not os.path.exists("screenshots"):
            os.makedirs("screenshots")

        main_container_xpath = '//*[@id="detail"]'
        # 根据您的指示，内容区的目标宽度为640px
        TARGET_WIDTH = 640

        for i, order in enumerate(orders_data):
            print(f"  > 正在为订单 {i + 1}/{len(orders_data)} (ID: {order.order_id}) 截图...")
            if not order.order_detail_url:
                print("    - ❌ 缺少详情页URL，跳过。")
                continue

            try:
                self.driver.get(order.order_detail_url)
                main_container = self.wait.until(EC.visibility_of_element_located((By.XPATH, main_container_xpath)))
                self.driver.execute_script("document.body.style.zoom='80%'")
                time.sleep(1.5)  # 增加等待时间确保缩放和渲染完成

                # 1. 截取父容器
                base_screenshot_png = main_container.screenshot_as_png
                base_image = Image.open(io.BytesIO(base_screenshot_png))

                # 2. 精确裁剪左侧和右侧空白
                # 我们假设内容是左对齐的，所以只裁剪右边
                final_image = base_image.crop((0, 0, TARGET_WIDTH, base_image.height))

                # 3. 自动裁剪顶部和底部的空白
                final_image = self._trim_image(final_image)

                # 4. 保存最终处理过的图片
                screenshot_path = os.path.join("screenshots", f"{order.order_id}.png")
                final_image.save(screenshot_path)
                order.screenshot_path = screenshot_path
                print(f"    - ✅ 截图精加工成功: {screenshot_path}")

            except Exception as e:
                print(f"    - ❌ 截图失败: {e}")

    def save_to_excel(self, all_orders_data: List[OrderData], filename="微店订单导出.xlsx"):
        """
        【大道至简版】生成格式统一的Excel报告，将最终适配工作交给WPS。
        """
        print(f"\n--- Phase 4: 开始生成格式统一的Excel报告 ---")
        if not all_orders_data: return

        df = pd.DataFrame([{
            '订单号': order.order_id,
            '商品名称': order.item_title,
            '商品规格': order.item_sku_title,
            '订单状态': order.order_status,
            '实付金额': order.total_price,
            '下单时间': order.creation_time,
            '付款时间': order.payment_time,
        } for order in all_orders_data])

        writer = pd.ExcelWriter(filename, engine='xlsxwriter')
        df.to_excel(writer, sheet_name='订单详情', index=False)
        workbook = writer.book
        worksheet = writer.sheets['订单详情']

        # 1. 创建并应用文本格式
        cell_format = workbook.add_format({'valign': 'vcenter', 'align': 'left'})
        worksheet.set_column('A:G', 22, cell_format)
        worksheet.write('H1', '订单截图')

        # ====================【 最终核心修正 】====================

        # 2. 只设置一个固定的、足够宽的列宽
        worksheet.set_column('H:H', 95)

        # 3. 遍历每一行，只设置一个统一的、足够高的默认行高
        for index, order in enumerate(all_orders_data):
            row_num = index + 1
            worksheet.set_row(row_num, 400)  # 给予一个足够大的初始行高

            if order.screenshot_path and os.path.exists(order.screenshot_path):
                # 插入图片时不再关心尺寸，让它以原始比例放入
                worksheet.insert_image(
                    row_num, 7,  # H列
                    order.screenshot_path,
                    {'object_position': 1}  # 依然保持锚定
                )
        # =============================================================

        writer.close()
        print(f"✅ Excel文件 '{filename}' 写入成功！请打开文件后进行批量转换。")

    def run(self, clicks_to_perform: int):
        # ... run 函数保持不变 ...
        self.login_with_cookie(MY_COOKIE)
        discovered_orders = []
        start_url = "https://weidian.com/user/order/list.php?type=2"
        self.driver.get(start_url)
        try:
            all_tab_xpath = '//*[@id="app"]/div[2]/div[2]/ul/li[1]/span'
            all_tab_button = self.wait.until(EC.element_to_be_clickable((By.XPATH, all_tab_xpath)))
            del self.driver.requests
            all_tab_button.click()
            initial_request = self.wait.until(lambda d: d.wait_for_request(r'tradeview/buyer.order.list'))
            initial_orders = self._parse_response(initial_request)
            discovered_orders.extend(initial_orders)
            for i in range(clicks_to_perform):
                print(f"\n--- 正在加载第 {i + 2} 页... ---")
                button_selector = (By.CSS_SELECTOR, "div.order_add_list .more_span")
                load_more_button = self.wait.until(EC.element_to_be_clickable((button_selector)))
                self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", load_more_button)
                time.sleep(1)
                del self.driver.requests
                self.driver.execute_script("arguments[0].click();", load_more_button)
                next_page_request = self.wait.until(lambda d: d.wait_for_request(r'tradeview/buyer.order.list/1.1'))
                next_page_orders = self._parse_response(next_page_request)
                discovered_orders.extend(next_page_orders)
        except TimeoutException:
            print(f"\n✅ 所有订单页面已加载完毕。")
        print(f"\n--- 快速发现阶段完成，共找到 {len(discovered_orders)} 条订单记录。---")

        self.take_screenshots(discovered_orders)
        self.save_to_excel(discovered_orders)
        print("\n🎉🎉🎉 项目执行完毕！ 🎉🎉🎉")


# --- 主入口 (Main Entry Point) ---
if __name__ == "__main__":
    # 1. 在程序开始时记录时间
    start_time = time.time()

    MY_COOKIE = ("__spider__visitorid=2ef09da5a6200925; smart_login_type=0; hi_dxh=; hold=; cn_merchant=; token=; isLogin=; loginUserType=; loginUserSource=; WD_b_id=; WD_b_wduss=; WD_b_country=; WD_b_tele=; WD_s_id=; WD_s_tele=; WD_s_wduss=; WD_seller=; is_login=true; login_type=LOGIN_USER_TYPE_MASTER; login_source=LOGIN_USER_SOURCE_MASTER; uid=1914883825; duid=1914883825; sid=1798256885; wdtoken=58ed060c; __spider__sessionid=2584a22f42a4db8a; login_token=_EwWqqVIQD0u47mFa1wCctnrLcWiA3ZQaBijugH_WeK9ovMUam2aWW1xg1j8s9jLx25qxxOGDQPyK2ZR1QKKtoYFtppFGSj2MXLO9shg_IsiM0vFPNszXRVyLhYcC9yY2V_slrb8-HglH4CsvQRGQUrYBAJeGp7CYAdDL5Bkdvxd_Yj1x0vVr9QEt0Tqgh18433yDSEoGB-y3L5vAKKLVDDcyWDwqlBk1lhddJKxnecFuUx5g6VnlhG0zDoHL7SIlOUPrT3ql; v-components/clean-up-advert@private_domain=1736676582; v-components/clean-up-advert@wx_app=1736676582")  # 请替换为您的有效Cookie
    CLICKS_TO_PERFORM = 10  # 先设置为0，测试10条

    scraper = WeidianScraper()
    try:
        scraper.run(clicks_to_perform=CLICKS_TO_PERFORM)
    except Exception as e:
        print(f"程序执行时遇到致命错误: {e}")
    finally:
        print("程序运行结束，按回车键退出...")

        # 2. 计算并打印总耗时
        end_time = time.time()
        duration = end_time - start_time
        print(f"程序总耗时: {duration:.2f} 秒")

        input()
        scraper.driver.quit()