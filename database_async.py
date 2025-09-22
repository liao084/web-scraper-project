# database_async.py
#
# 负责项目所有与数据库相关的异步操作。
# 使用 aiosqlite 库，为上层应用提供数据持久化、任务调度和状态管理接口。

import aiosqlite
from typing import List, Optional, Tuple, Dict

DB_PATH = "tasks.db"


async def initialize_database():
    """
    初始化数据库。如果表不存在，则创建 `orders` 表。

    `orders` 表采用 (order_id, sub_order_desc) 的联合唯一约束，
    旨在精确记录每个订单的每一次状态流转，同时自动防止完全重复的数据插入。
    """
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('''
                         CREATE TABLE IF NOT EXISTS orders
                         (
                             id INTEGER PRIMARY KEY AUTOINCREMENT,
                             order_id TEXT NOT NULL,
                             item_title TEXT,
                             item_sku_title TEXT,
                             order_status TEXT,
                             sub_order_desc TEXT,
                             total_price TEXT,
                             creation_time TEXT,
                             payment_time TEXT,
                             shipping_time TEXT,
                             order_detail_url TEXT,
                             screenshot_path TEXT,
                             status TEXT NOT NULL,
                             UNIQUE(order_id, sub_order_desc)
                         )
                         ''')
        await db.commit()


async def insert_orders(orders_data: List[Dict]) -> int:
    """
    将一批订单数据批量插入数据库。

    利用联合唯一约束，`INSERT OR IGNORE` 会自动跳过已存在的 (order_id, sub_order_desc) 组合，
    只插入新的订单状态记录。

    Args:
        orders_data: 包含多个订单信息字典的列表。

    Returns:
        成功插入数据库的新记录条数。
    """
    async with aiosqlite.connect(DB_PATH) as db:
        # 在执行前后通过比较 aiosqlite.Connection.total_changes，
        # 可以精确计算出本次 executemany 操作实际插入的行数。
        changes_before = db.total_changes

        insert_query = '''
                       INSERT OR IGNORE INTO orders (order_id, item_title, item_sku_title, order_status, sub_order_desc,
                                           total_price, creation_time, payment_time, shipping_time, order_detail_url,
                                           status)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')
                       '''

        data_to_insert = [
            (
                o.get("order_id"), o.get("item_title"), o.get("item_sku_title"),
                o.get("order_status"), o.get("sub_order_desc"),
                o.get("total_price"), o.get("creation_time"),
                o.get("payment_time"), o.get("shipping_time"), o.get("order_detail_url")
            ) for o in orders_data
        ]

        await db.executemany(insert_query, data_to_insert)
        await db.commit()

        changes_after = db.total_changes
        return changes_after - changes_before


async def fetch_pending_task() -> Optional[Tuple]:
    """
    以原子操作的方式，从数据库中获取一个待处理（'pending'）的任务。

    获取任务后，会立即将其状态更新为 'running'，以防止其他并发的 worker 获取到
    同一个任务。使用了 `EXCLUSIVE` 锁来保证操作的原子性。

    Returns:
        一个包含任务所有字段的元组，如果无待处理任务则返回 None。
    """

    try:
        async with aiosqlite.connect(DB_PATH, isolation_level='EXCLUSIVE', timeout=10) as db:
            cursor = await db.execute("SELECT * FROM orders WHERE status = 'pending' LIMIT 1")
            task = await cursor.fetchone()
            await cursor.close()
            if task:
                task_id = task[0]
                await db.execute("UPDATE orders SET status = 'running' WHERE id = ?", (task_id,))
                await db.commit()
                return task
            else:
                return None
    except aiosqlite.Error as e:
        print(f"[DB Error] 获取异步任务失败: {e}")
        return None


async def update_task_status_from_queue(result: Dict):
    """
    根据处理结果，更新数据库中特定任务的状态。

    Args:
        result: 一个字典，必须包含 'task_id' 和 'status'。
                若 status 为 'completed'，则还应包含 'screenshot_path'。
    """
    task_id = result.get('task_id')
    status = result.get('status')
    screenshot_path = result.get('screenshot_path')

    async with aiosqlite.connect(DB_PATH, timeout=10) as db:
        if status == 'completed':
            await db.execute(
                "UPDATE orders SET status = ?, screenshot_path = ? WHERE id = ?",
                (status, screenshot_path, task_id)
            )
        elif status == 'failed':
            await db.execute(
                "UPDATE orders SET status = ? WHERE id = ?",
                ('failed', task_id)
            )
        await db.commit()


async def get_completed_orders() -> List[Dict]:
    """
    从数据库中获取所有已完成 ('completed') 的订单记录。

    Returns:
        一个包含所有已完成订单的字典列表，按创建时间降序排列。
    """
    async with aiosqlite.connect(DB_PATH, timeout=10) as db:
        # 使用 aiosqlite.Row 作为 row_factory，使得查询结果可以像字典一样通过列名访问。
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM orders WHERE status = 'completed' ORDER BY creation_time DESC")
        rows = await cursor.fetchall()
        await cursor.close()

        # 将 aiosqlite.Row 对象列表转换为标准的字典列表
        completed_orders = [dict(row) for row in rows]
        return completed_orders