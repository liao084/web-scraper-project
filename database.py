# database.py
import sqlite3
from typing import List, Optional, Tuple, Dict

# 定义数据库文件的路径，所有其他脚本都会引用这个变量
DB_PATH = "tasks.db"


def initialize_database():
    """
    初始化数据库。如果数据库文件或表不存在，则创建它们。
    这是整个流程开始前必须调用的函数。
    """
    # conn 会自动创建 tasks.db 文件（如果不存在）
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # 创建 'orders' 表
    # 使用 'IF NOT EXISTS' 确保重复运行不会报错
    cursor.execute('''
                   CREATE TABLE IF NOT EXISTS orders
                   (
                       id
                       INTEGER
                       PRIMARY
                       KEY
                       AUTOINCREMENT,
                       order_id
                       TEXT
                       NOT
                       NULL
                       UNIQUE,
                       item_title
                       TEXT,
                       item_sku_title
                       TEXT,
                       order_status
                       TEXT,
                       sub_order_desc
                       TEXT, -- 【新增】用于存储“退款完成”等状态
                       total_price
                       TEXT,
                       creation_time
                       TEXT,
                       payment_time
                       TEXT,
                       shipping_time
                       TEXT,
                       order_detail_url
                       TEXT,
                       screenshot_path
                       TEXT,
                       status
                       TEXT
                       NOT
                       NULL
                   )
                   ''')
    # status 的可能值: 'pending', 'running', 'completed', 'failed'

    conn.commit()  # 提交更改
    conn.close()  # 关闭连接


def insert_orders(orders_data: List[Dict]):
    """
    批量将采集到的订单数据插入数据库。
    利用 'OR IGNORE' 关键字，如果订单号(order_id)已存在，则自动跳过，不会插入重复数据。
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    insert_query = '''
                   INSERT \
                   OR IGNORE INTO orders (
                order_id, item_title, item_sku_title, order_status, sub_order_desc,
                total_price, creation_time, payment_time, shipping_time, order_detail_url, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending') \
                   '''

    # 将字典列表转换为元组列表，以匹配SQL查询的占位符
    data_to_insert = [
        (
            o.get("order_id"), o.get("item_title"), o.get("item_sku_title"),
            o.get("order_status"), o.get("sub_order_desc"),  # <-- 新增
            o.get("total_price"), o.get("creation_time"),
            o.get("payment_time"), o.get("shipping_time"), o.get("order_detail_url")
        ) for o in orders_data
    ]

    cursor.executemany(insert_query, data_to_insert)
    conn.commit()
    inserted_count = cursor.rowcount
    conn.close()
    return inserted_count


def fetch_pending_task() -> Optional[Tuple]:
    """
    【为多线程设计】从数据库中获取一个'pending'状态的任务，并立即将其状态更新为'running'。
    这是一个原子操作，以防止多个线程抢到同一个任务。
    返回一个包含任务所有信息的元组，如果没有待处理任务则返回 None。
    """
    # 使用 with 语句可以确保连接在操作结束后自动关闭，即使发生错误
    with sqlite3.connect(DB_PATH, isolation_level='EXCLUSIVE', timeout=10) as conn:
        cursor = conn.cursor()

        # 开启一个排他锁事务，保证在这一系列操作完成前，其他线程不能访问数据库
        cursor.execute("BEGIN EXCLUSIVE")
        try:
            cursor.execute("SELECT * FROM orders WHERE status = 'pending' LIMIT 1")
            task = cursor.fetchone()

            if task:
                task_id = task[0]  # 主键 id
                cursor.execute("UPDATE orders SET status = 'running' WHERE id = ?", (task_id,))
                conn.commit()
                return task
            else:
                conn.commit()  # 即使没找到，也要提交事务来释放锁
                return None
        except Exception as e:
            conn.rollback()  # 如果出错，回滚所有更改
            print(f"[DB Error] 获取任务失败: {e}")
            return None


def update_task_status_from_queue(result: Dict):
    """
    根据来自结果队列的信息，更新数据库中任务的状态。
    """
    task_id = result.get('task_id')
    status = result.get('status')
    screenshot_path = result.get('screenshot_path')
    error_message = result.get('error')

    with sqlite3.connect(DB_PATH, timeout=10) as conn:
        cursor = conn.cursor()
        if status == 'completed':
            cursor.execute(
                "UPDATE orders SET status = ?, screenshot_path = ? WHERE id = ?",
                (status, screenshot_path, task_id)
            )
        elif status == 'failed':
            # 可以在这里记录更详细的错误信息，如果数据库结构支持的话
            cursor.execute(
                "UPDATE orders SET status = ? WHERE id = ?",
                ('failed', task_id)
            )
        conn.commit()


def get_completed_orders() -> List[Dict]:
    """
    获取所有状态为 'completed' 的订单，用于最终生成Excel报告。
    """
    with sqlite3.connect(DB_PATH, timeout=10) as conn:
        conn.row_factory = sqlite3.Row  # 让查询结果可以像字典一样通过列名访问
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM orders WHERE status = 'completed' ORDER BY creation_time DESC")
        rows = cursor.fetchall()

        # 将 sqlite3.Row 对象转换为标准的字典列表
        completed_orders = [dict(row) for row in rows]
        return completed_orders