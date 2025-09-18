from playwright.sync_api import sync_playwright

# ==================== 用户配置区 ====================
TARGET_ORDER_ID = "834671103115497"
TARGET_URL = f"https://i.weidian.com/order/detail.php?oid={TARGET_ORDER_ID}"
OUTPUT_PATH = f"screenshots/{TARGET_ORDER_ID}_playwright_sync.png"

MY_COOKIE_STRING = ("__spider__visitorid=f9ce2e7df2397d94; smart_login_type=0; is_login=true; login_type=LOGIN_USER_TYPE_MASTER; login_source=LOGIN_USER_SOURCE_MASTER; uid=1914883825; duid=1914883825; sid=1798256885; wdtoken=18021053; __spider__sessionid=6331d26624bf4ddc; login_token=_EwWqqVIQeOYiTbEo8CpKqNi__wkpX5z49KIO4jvB_4UqxlNgDf5okK3RQFHXNd62L1gJ-SgpOfGnzJ94dyznWjetKa5P_ECApdWJ2Acclo-A-Uvwj-DpnEVm4SvP40yZ2y3Ef2IcN5CCoztA85zIoHuaukJLhN2aRwAf-uVV3rSQpSZZbNEX0-qObdzRM9_7JWIXz5HTzE3zqvUwSyKmPpcoWUWzADxR7fYxi61-jmzzRGfMhw8afkfPC6hnz-u618BvBXDP; v-components/clean-up-advert@private_domain=1642150384; v-components/clean-up-advert@wx_app=1642150384")
# ====================================================

def parse_cookie_string(cookie_string: str) -> list:
    """辅助函数，将Selenium的Cookie字符串转换为Playwright需要的格式"""
    cookies_list = []
    for item in cookie_string.split(';'):
        if '=' in item:
            name, value = item.strip().split('=', 1)
            cookies_list.append({
                'name': name, 'value': value,
                'domain': '.weidian.com', 'path': '/'
            })
    return cookies_list

# sync_playwright() 是一个同步的上下文管理器
with sync_playwright() as p:
    print("--- Playwright 同步API 脚本启动 ---")

    browser = p.chromium.launch(headless=False)

    # 2. 注入Cookie并创建页面
    cookies = parse_cookie_string(MY_COOKIE_STRING)
    context = browser.new_context(storage_state={"cookies": cookies})
    page = context.new_page()

    # 3. 导航到目标页面
    print(f"正在导航到: {TARGET_URL}")
    page.goto(TARGET_URL)
    page.evaluate(f"document.body.style.zoom = 0.4")
    main_container_locator = page.locator('xpath=//*[@id="detail"]')
    page.wait_for_timeout(400)
    main_container_locator.screenshot(path=OUTPUT_PATH)

    print(f"✅ 截图成功！已保存至: {OUTPUT_PATH}")
    print("浏览器将在5秒后关闭...")

    # 5. 为了方便观察，暂停5秒
    page.wait_for_timeout(5000)  # 同步API里的暂停方法

    browser.close()

print("--- 脚本执行完毕 ---")




