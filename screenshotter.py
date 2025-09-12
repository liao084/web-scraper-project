# screenshotter.py (V2.1 - 终极稳定版)
# 职责：从数据库读取任务，使用【动态再生的WebDriver池】和多线程并行截图，并将结果安全地写回数据库。

import os
import io
import time
import queue
import threading
from typing import Optional

from PIL import Image, ImageChops
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# 导入我们自己的模块
import database

# ==================== 用户配置区 ====================
# 并发设置 (建议从保守值开始，如 4)
WORKER_THREADS = 4
MAX_DRIVERS_IN_POOL = 4

# 【新增】WebDriver实例生命周期管理
# 每个浏览器实例最多截图 N 次后就会被销毁重建，这是保证长期稳定性的关键
DRIVER_MAX_USE_COUNT = 50

# 截图重试设置
MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 5

# 截图精加工设置
TARGET_WIDTH = 640

# 登录Cookie (非常重要！)
MY_COOKIE = ("__spider__visitorid=f9ce2e7df2397d94; smart_login_type=0; is_login=true; login_type=LOGIN_USER_TYPE_MASTER; login_source=LOGIN_USER_SOURCE_MASTER; uid=1914883825; duid=1914883825; sid=1798256885; __spider__sessionid=6331d26624bf4ddc; wdtoken=18021053; login_token=_EwWqqVIQZ9VKaPUruqau8kzyu4eUegvgO8pDg8Q0oz7Odq671TksX_plNoFGpsP6x04OuRqqEHMvHnIZcSE8gmUVGkr6pzQeAAw_an3pRhWxhS_JqVpZzjLeqqpYaHFSWVE3Neoh7r1NXiysF2dKSrSjA_ExsEv7o6t1YbYfrlzmjfzfZBcU_qzEU_p_FqKI9yDI3QxMbb2Ona2i-S5KsqMX7_TzwS0QgIEV3QWUrlZGrOHiEr7ZqOqZ0g_vfghKLvgpbepB")
# ====================================================

# 【修改】池中现在存放的是 (driver, use_count) 元组
driver_pool = queue.Queue(maxsize=MAX_DRIVERS_IN_POOL)
results_queue = queue.Queue()


def _trim_image(image: Image.Image) -> Image.Image:
    """辅助函数，用于自动裁剪图片的空白边缘"""
    bg = Image.new(image.mode, image.size, image.getpixel((0, 0)))
    diff = ImageChops.difference(image, bg)
    diff = ImageChops.add(diff, diff, 2.0, -100)
    bbox = diff.getbbox()
    if bbox:
        return image.crop(bbox)
    return image


def take_single_screenshot(driver: webdriver.Chrome, detail_url: str, order_id: str) -> str:
    """
    使用给定的WebDriver实例，为单个订单截图并返回图片路径。
    """
    driver.get(detail_url)

    main_container_xpath = '//*[@id="detail"]'
    wait = WebDriverWait(driver, 20)
    main_container = wait.until(EC.visibility_of_element_located((By.XPATH, main_container_xpath)))

    driver.execute_script("document.body.style.zoom='40%'")
    time.sleep(1.5)

    base_screenshot_png = main_container.screenshot_as_png
    base_image = Image.open(io.BytesIO(base_screenshot_png))

    final_image = base_image.crop((0, 0, TARGET_WIDTH, base_image.height))
    final_image = _trim_image(final_image)

    if not os.path.exists("screenshots"):
        os.makedirs("screenshots")
    screenshot_path = os.path.join("screenshots", f"{order_id}.png")
    final_image.save(screenshot_path)

    return screenshot_path


def create_new_driver_instance(instance_num: str = "new"):
    """【新增】一个专门用于创建全新、干净的WebDriver实例的函数。"""
    print(f"  > [Instance Manager] 正在创建实例 [{instance_num}]...")
    try:
        options = webdriver.ChromeOptions()
        options.add_argument("--headless")  # 正式运行时开启无头模式
        options.add_argument("--disable-gpu")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--no-sandbox")
        # 【新增的稳定性选项】
        options.add_argument("--disable-extensions")
        options.add_argument("--disable-infobars")
        options.add_argument("--start-maximized")
        options.add_argument("--disable-browser-side-navigation")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_experimental_option('excludeSwitches', ['enable-automation'])

        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)

        driver.get("https://weidian.com/")
        time.sleep(1)
        driver.delete_all_cookies()
        for cookie_item in MY_COOKIE.split(';'):
            if '=' in cookie_item:
                name, value = cookie_item.strip().split('=', 1)
                driver.add_cookie({'name': name, 'value': value, 'domain': '.weidian.com'})

        print(f"  > [Instance Manager] 实例 [{instance_num}] 创建并登录成功。")
        return driver
    except Exception as e:
        print(f"  > ❌ [Instance Manager] 创建实例 [{instance_num}] 失败: {e}")
        return None


def screenshot_worker(worker_id: int):
    """
    【修改】截图工人现在会管理WebDriver的生命周期。
    """
    print(f"[Worker-{worker_id}] 已启动。")

    while True:
        task = database.fetch_pending_task()
        if task is None:
            print(f"[Worker-{worker_id}] 未领到新任务，准备退出。")
            break

        task_id, order_id, *_, detail_url, _, _ = task

        driver_with_count = None
        driver = None
        use_count = 0
        retries = 0
        success = False

        while not success and retries < MAX_RETRIES:
            try:
                driver_with_count = driver_pool.get(timeout=300)
                driver, use_count = driver_with_count

                print(
                    f"[Worker-{worker_id}] 正在处理订单 {order_id} (实例使用次数: {use_count + 1}/{DRIVER_MAX_USE_COUNT})...")
                screenshot_path = take_single_screenshot(driver, detail_url, order_id)

                results_queue.put({'task_id': task_id, 'status': 'completed', 'screenshot_path': screenshot_path})
                print(f"  > ✅ [Worker-{worker_id}] 订单 {order_id} 截图成功。")
                success = True
                use_count += 1  # 成功才增加使用次数

            except Exception as e:
                retries += 1
                print(
                    f"  > ❌ [Worker-{worker_id}] 订单 {order_id} 截图失败 (尝试 {retries}/{MAX_RETRIES}): {type(e).__name__}")

                # 当发生严重错误时，主动销毁这个可能出问题的driver
                if "Stacktrace" in str(e) or "crashed" in str(e) or "timed out" in str(e):
                    print(f"  > ⚠️ [Worker-{worker_id}] 检测到严重错误，将销毁当前浏览器实例。")
                    use_count = DRIVER_MAX_USE_COUNT  # 强制使其达到销毁阈值

                if retries < MAX_RETRIES:
                    time.sleep(RETRY_DELAY_SECONDS)
            finally:
                if driver_with_count:
                    # 【核心逻辑】归还或再生
                    if use_count >= DRIVER_MAX_USE_COUNT:
                        print(
                            f"  > [Instance Manager] 实例已达最大使用次数({use_count})，由 Worker-{worker_id} 负责销毁并重建...")
                        try:
                            driver.quit()
                        except Exception as quit_e:
                            print(f"    - 销毁旧实例时出错: {quit_e}")

                        new_driver = create_new_driver_instance(f"Worker-{worker_id}-Regen")
                        if new_driver:
                            driver_pool.put((new_driver, 0))  # 放入全新的实例
                        else:
                            print("    - ❌ 创建新实例失败，池容量暂时减少。")
                    else:
                        # 未达到上限，正常归还
                        driver_pool.put((driver, use_count))

                    driver_with_count = None  # 标记为已处理
                    driver = None

        if not success:
            results_queue.put({'task_id': task_id, 'status': 'failed', 'error': f"超过最大重试次数"})
            print(f"  > ⛔️ [Worker-{worker_id}] 订单 {order_id} 彻底失败。")

    print(f"[Worker-{worker_id}] 已退出。")


def database_writer():
    """
    数据库写入线程的主函数。
    """
    print("[DB Writer] 已启动，等待结果...")
    processed_count = 0
    while True:
        try:
            result = results_queue.get(timeout=300)
            if result is None:  # 收到结束信号
                print("[DB Writer] 收到结束信号，准备退出。")
                break

            database.update_task_status_from_queue(result)
            processed_count += 1
            if processed_count % 20 == 0:
                print(f"[DB Writer] 已处理 {processed_count} 个任务结果。")
        except queue.Empty:
            print("[DB Writer] 长时间未收到新结果，自动退出。")
            break
    print(f"[DB Writer] 共处理了 {processed_count} 个结果，已退出。")


def initialize_driver_pool():
    """在主线程中创建并初始化WebDriver池。"""
    print(f"正在创建 {MAX_DRIVERS_IN_POOL} 个初始浏览器实例放入池中...")
    for i in range(MAX_DRIVERS_IN_POOL):
        driver = create_new_driver_instance(f"Initial-{i + 1}")
        if driver:
            driver_pool.put((driver, 0))


def main():
    start_time = time.time()

    if "在这里粘贴" in MY_COOKIE:
        raise ValueError("请在脚本顶部的配置区填写您最新的有效Cookie！")

    initialize_driver_pool()
    if driver_pool.empty():
        print("❌ WebDriver池为空，无法启动工人线程。程序退出。")
        return

    threads = []

    writer_thread = threading.Thread(target=database_writer)
    writer_thread.start()
    threads.append(writer_thread)

    for i in range(WORKER_THREADS):
        worker = threading.Thread(target=screenshot_worker, args=(i + 1,))
        worker.start()
        threads.append(worker)

    for t in threads:
        if t is not writer_thread:
            t.join()

    print("\n所有截图工人都已完成工作。")

    results_queue.put(None)
    writer_thread.join()
    print("数据库写入者已完成工作。")

    print("正在关闭池中所有剩余的浏览器实例...")
    while not driver_pool.empty():
        try:
            driver, _ = driver_pool.get_nowait()
            driver.quit()
        except queue.Empty:
            break
        except Exception as e:
            print(f"关闭一个driver时出错: {e}")

    end_time = time.time()
    duration = end_time - start_time
    print(f"\n--- 并行截图阶段完成 ---")
    print(f"程序总耗时: {duration:.2f} 秒")


if __name__ == "__main__":
    # 强烈建议在执行大规模任务前，先重启电脑，并清理WDM缓存
    main()