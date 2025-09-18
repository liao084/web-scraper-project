from playwright.sync_api import sync_playwright
import time
target_url = "https://book.douban.com/top250"

def handle_response(response):
    url = response.url
    # if url == target_url:
    pass

def scrape_info_and_print(num:int):
    page.wait_for_selector('xpath=//div[@id="content"]//table')
    book_items_locator = page.locator('xpath=//*[@id="content"]//table')
    book_counts = book_items_locator.count()
    print(f"该页面共有{book_counts}本书")

    for i in range(book_counts):
        book_item = book_items_locator.nth(i)
        title_locator = book_item.locator("xpath=.//div[@class='pl2']//a")
        title = title_locator.inner_text()

        info_locator = book_item.locator("xpath=.//p[@class='pl']")
        info_text = info_locator.inner_text()
        info_parts = info_text.split("/")

        try:
            author = info_parts[0].strip()
            publisher = info_parts[1].strip() if len(info_parts) > 1 else "N/A"
            pub_date = info_parts[2].strip() if len(info_parts) > 2 else "N/A"
            price = info_parts[3].strip() if len(info_parts) > 3 else "N/A"
        except IndexError:
            author = "信息格式特殊"
            publisher, pub_date, price = "N/A", "N/A", "N/A"

        # 提取评分
        rating_nums_locator = book_item.locator("xpath=.//span[@class='rating_nums']")
        rating_nums = rating_nums_locator.inner_text()

        # 提取引言
        book_quote_locator = book_item.locator("xpath=.//span[@class='inq']")
        book_quote = book_quote_locator.inner_text()

        # 打印抓取结果
        print(f"\n----第{i + 1+(num-1)*25}本书----")
        print(f"      书名：{title}")
        print(f"      作者：{author}")
        print(f"      出版社：{publisher}")
        print(f"      出版日期：{pub_date}")
        print(f"      价格：{price}")
        print(f"      豆瓣评分：{rating_nums}")
        print(f"      名著引言：{book_quote}")
start_time = time.time()
with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    page = browser.new_page()
    # page.on("response",handle_response)
    page.goto(target_url)

    for i in range(1,11):
        print(f"-----正在抓去第{i}页书单-----\n")
        scrape_info_and_print(i)

        if i < 10:
            next_page_button = page.locator("xpath=//*[@id='content']//span[@class='next']/a")
            next_page_button.click()

# print("-----第一页提取完毕-----")
    end_time = time.time()
    print(f"程序总耗时{end_time - start_time:.2f}s")
    page.wait_for_timeout(10000)
    browser.close()
