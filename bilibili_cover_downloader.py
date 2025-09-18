from playwright.sync_api import Playwright, sync_playwright
import os
target_url = "https://www.bilibili.com"

def handle_response(response):
    try:

        url = response.url
        is_home_common_cover = "home-common-cover" in url
        if is_home_common_cover:
            print(f"发现疑似封面图片url：{url}")
            image_bytes = response.body()
            # filename = url.split("/")[-1].split("@")[0]
            filename = f"{hash(url)}.jpg"
            os.makedirs("bilibili_images",exist_ok=True)
            save_path = os.path.join("bilibili_images", filename)

            with open(save_path, "wb") as f:
                f.write(image_bytes)
            print(f"图片已经成功下载至{save_path}")
    except Exception as e:
        print(f"下载{url}图片是出现错误，错误为{e}")

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    page = browser.new_page()
    page.on("response",handle_response)
    page.goto(target_url)
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(10000)
    browser.close()