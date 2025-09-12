# export.py
# Phase 3: 报告生成器 (日期格式修正版)

import os
import pandas as pd
from typing import List, Dict

import database

OUTPUT_FILENAME = "微店订单导出_V2.xlsx"


def create_excel_report(orders_data: List[Dict], filename: str):
    if not orders_data:
        print("没有已完成的订单数据可供导出。")
        return

    print(f"--- 正在生成最终的Excel报告: {filename} ---")

    df = pd.DataFrame(orders_data)

    # 【核心修正-步骤1】
    # 我们不再在这里使用 pd.to_datetime。
    # 我们将保持日期为字符串格式，让xlsxwriter在写入时进行转换和格式化。
    # 这样可以给予xlsxwriter最大的控制权。

    df = df[[
        'order_id', 'item_title', 'item_sku_title', 'order_status',
        'sub_order_desc', 'total_price', 'creation_time', 'payment_time',
        'screenshot_path'
    ]]
    df.rename(columns={
        'order_id': '订单号', 'item_title': '商品名称', 'item_sku_title': '商品规格',
        'order_status': '订单状态', 'sub_order_desc': '订单退款状态',
        'total_price': '实付金额', 'creation_time': '下单时间',
        'payment_time': '付款时间', 'screenshot_path': '_截图路径'
    }, inplace=True)

    # 【核心修正-步骤2】
    # 在创建ExcelWriter时，我们要特别指定datetime_format，
    # 告诉pandas不要为日期应用它自己的默认格式。
    writer = pd.ExcelWriter(filename,
                            engine='xlsxwriter',
                            datetime_format='yyyy-mm-dd hh:mm:ss')  # 提供一个基础格式

    df.to_excel(writer, sheet_name='订单详情', index=False)

    workbook = writer.book
    worksheet = writer.sheets['订单详情']

    header_format = workbook.add_format({'bold': True, 'valign': 'vcenter', 'align': 'center', 'border': 1})
    cell_format = workbook.add_format({'valign': 'vcenter', 'align': 'left'})

    # 【核心修正-步骤3】
    # 我们创建的自定义日期格式现在会覆盖掉之前datetime_format设置的基础格式。
    date_format = workbook.add_format({
        'num_format': 'm"月"d"日"',
        'valign': 'vcenter',
        'align': 'left'
    })

    for col_num, value in enumerate(df.columns.values):
        worksheet.write(0, col_num, value, header_format)

    # 调整列宽
    worksheet.set_column('A:A', 25, cell_format)
    worksheet.set_column('B:B', 40, cell_format)
    worksheet.set_column('C:E', 20, cell_format)
    worksheet.set_column('F:F', 15, cell_format)
    worksheet.set_column('I:I', 25, cell_format)
    worksheet.write('J1', '订单截图', header_format)
    worksheet.set_column('J:J', 95)

    # 【核心修正-步骤4】
    # 现在将我们的自定义日期格式应用到指定的列，这将覆盖默认格式。
    worksheet.set_column('G:H', 18, date_format)

    # 插入图片部分保持不变
    for index, order in enumerate(orders_data):
        row_num = index + 1
        worksheet.set_row(row_num, 400)
        screenshot_path = order.get('screenshot_path')
        if screenshot_path and os.path.exists(screenshot_path):
            worksheet.insert_image(row_num, 9, screenshot_path, {'object_position': 1})

    writer.close()
    print(f"✅ Excel报告 '{filename}' 已成功生成！")


def main():
    print("--- 开始从数据库导出已完成的订单 ---")
    completed_orders = database.get_completed_orders()
    print(f"发现 {len(completed_orders)} 条已完成的订单记录。")
    create_excel_report(completed_orders, OUTPUT_FILENAME)


if __name__ == "__main__":
    main()