import asyncio
from playwright.async_api import async_playwright, Page ,Browser# 我们可能需要Page的类型注解
from typing import List, Dict # 用于类型注解，让代码更清晰
import time

target_url = "https://book.douban.com/top250"
MAX_CONCURRENT_TASKS = 4


async def scrape_single_page(browser: Browser, url: str, page_num: int) -> List[Dict]:
    print(f"  [TASK-{page_num}] 开始采集页面 {url}")

    context = await browser.new_context()
    page = await context.new_page()
    scraped_data = []

    await page.goto(url,timeout = 30000)
    await page.wait_for_selector("xpath=//div[@id='content']//table")
    book_items_locator = page.locator("xpath=//div[@id='content']//table")
    book_counts = await book_items_locator.count()

    print(f"\n------该页面有{book_counts}本书------")

    for i in range(0, book_counts):
        book_item = book_items_locator.nth(i)
        title_locator = book_item.locator("xpath=.//div[@class='pl2']/a")
        title = await title_locator.inner_text()

        info_locator = book_item.locator("xpath=.//p[@class='pl']")
        info_text = await info_locator.inner_text()
        info_parts = info_text.split("/")

        try:
            author = info_parts[0].strip()
            publisher = info_parts[1].strip() if len(info_parts) > 1 else "N/A"
            pub_date = info_parts[2].strip() if len(info_parts) > 2 else "N/A"
            price = info_parts[3].strip() if len(info_parts) > 3 else "N/A"
        except IndexError:
            author = "信息格式特殊"
            publisher, pub_date, price = "N/A", "N/A", "N/A"

        rating_nums_locator = book_item.locator("xpath=.//span[@class='rating_nums']")
        rating_nums = await rating_nums_locator.inner_text()

        book_quote_locator = book_item.locator("xpath=.//span[@class='inq']")
        book_quote = await book_quote_locator.inner_text()

        book_data = {
            "title": title,
            "author": author,
            "publisher": publisher,
            "pub_date": pub_date,
            "price": price,
            "rating_nums": rating_nums,
            "book_quote": book_quote,
            "page_num": page_num
        }
        scraped_data.append(book_data)

        print(f"已采集{book_data['title']}")

    await context.close()
    print(f"  [Task-{page_num}] 上下文已关闭，资源已释放。")
    return scraped_data

async def main():
    all_books_data = []
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_TASKS)


    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)

        tasks = []
        for i in range(10):
            page_num = i + 1
            start_index = i * 25
            url = f"https://book.douban.com/top250?start={start_index}"

            tasks.append(scrape_with_semaphore(semaphore, browser, url, page_num))

        print(f"--- 准备并发采集10个页面，并发度: {MAX_CONCURRENT_TASKS} ---")
        results_from_all_pages = await asyncio.gather(*tasks)

        for page_result in results_from_all_pages:
            all_books_data.extend(page_result)

        await browser.close()

    print(f"\n\n==================== 所有页面并发采集完毕 ====================")
    print(f"总计采集到 {len(all_books_data)} 本书的信息。")

async def scrape_with_semaphore(semaphore, *args, **kwargs):
    """一个包装器，用于在执行主任务前获取信号量"""
    async with semaphore:
        return await scrape_single_page(*args, **kwargs)

if __name__ == "__main__":
    start_time = time.time()
    asyncio.run(main())
    end_time = time.time()
    print(f"\n---程序总耗时{end_time-start_time:.2f}s---")
    # for i, book_data in enumerate(all_books_data):
    #     # 【打印修正】使用正确的 f-string 语法
    #     print(f"\n--- 第{i + 1}本书 ---")
    #     print(f"书名: {book_data['title']}")
    #     print(f"作者: {book_data['author']}")
    #     print(f"出版社: {book_data['publisher']}")
    #     print(f"出版日期: {book_data['pub_date']}")
    #     print(f"价格: {book_data['price']}")
    #     print(f"豆瓣评分: {book_data['rating_nums']}")
    #     print(f"名著引言: {book_data['book_quote']}")


