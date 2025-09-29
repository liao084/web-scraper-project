# export_async.py
#
# 负责项目的报告生成阶段。
# 它从数据库中异步读取所有已完成的任务，并使用 pandas 和 xlsxwriter
# 生成最终的、包含订单详情和截图的Excel报告。

import os
import asyncio
import pandas as pd
from typing import List, Dict

# 导入我们自己的异步数据库模块
import database_async

OUTPUT_FILENAME = "微店订单导出_V3_Playwright版.xlsx"


def create_excel_report(orders_data: List[Dict], filename: str):
    """
    根据给定的订单数据字典列表，创建一个格式化的Excel文件。

    该函数是纯数据处理逻辑，与数据的获取方式（同步/异步）解耦。

    Args:
        orders_data: 从数据库获取的、已完成的订单记录列表。
        filename: 输出的Excel文件名。
    """
    if not orders_data:
        print("没有已完成的订单数据可供导出。")
        return

    print(f"--- 正在生成最终的Excel报告: {filename} ---")

    df = pd.DataFrame(orders_data)

    # 对DataFrame进行重排和重命名，以符合最终报告的格式要求
    df = df[[
        'order_id', 'shop_name', 'item_title', 'item_sku_title', 'order_status',
        'sub_order_desc', 'total_price', 'creation_time', 'payment_time',
        'screenshot_path'
    ]]
    df.rename(columns={
        'order_id': '订单号', 'shop_name': '店铺名称', 'item_title': '商品名称', 'item_sku_title': '商品规格',
        'order_status': '订单状态', 'sub_order_desc': '订单退款状态',
        'total_price': '实付金额', 'creation_time': '下单时间',
        'payment_time': '付款时间', 'screenshot_path': '_截图路径'
    }, inplace=True)

    # 使用 xlsxwriter 引擎以获得更丰富的格式化功能
    writer = pd.ExcelWriter(filename,
                            engine='xlsxwriter',
                            datetime_format='yyyy-mm-dd hh:mm:ss')

    df.to_excel(writer, sheet_name='订单详情', index=False)

    # 获取 xlsxwriter 的核心对象以进行深度格式化
    workbook = writer.book
    worksheet = writer.sheets['订单详情']

    # --- 定义单元格格式 ---
    header_format = workbook.add_format({'bold': True, 'valign': 'vcenter', 'align': 'center', 'border': 1})
    cell_format = workbook.add_format({'valign': 'vcenter', 'align': 'left'})
    # 自定义日期格式，使其更符合中文阅读习惯
    date_format = workbook.add_format({
        'num_format': 'm"月"d"日"',
        'valign': 'vcenter',
        'align': 'left'
    })

    # --- 应用格式 ---
    worksheet.set_column('A:A', 25, cell_format)
    worksheet.set_column('B:B', 30, cell_format)
    worksheet.set_column('C:C', 40, cell_format)
    worksheet.set_column('D:F', 20, cell_format)
    worksheet.set_column('G:G', 15, cell_format)
    worksheet.set_column('H:I', 18, date_format)
    worksheet.set_column('J:J', 25, cell_format)
    worksheet.write('K1', '订单截图', header_format)
    worksheet.set_column('K:K', 95)

    # 循环遍历已完成的订单，插入对应的截图
    for index, order in enumerate(orders_data):
        row_num = index + 1
        worksheet.set_row(row_num, 400)
        screenshot_path = order.get('screenshot_path')
        if screenshot_path and os.path.exists(screenshot_path):
            worksheet.insert_image(row_num, 10, screenshot_path, {'object_position': 1})
    writer.close()
    print(f"✅ Excel报告 '{filename}' 已成功生成！")


async def main():
    """
    异步程序的入口点。
    """
    print("--- 开始从数据库导出已完成的订单 ---")

    # 异步调用数据库函数以获取数据
    completed_orders = await database_async.get_completed_orders()

    print(f"发现 {len(completed_orders)} 条已完成的订单记录。")

    # 调用纯同步的报告生成函数
    create_excel_report(completed_orders, OUTPUT_FILENAME)


if __name__ == "__main__":
    asyncio.run(main())