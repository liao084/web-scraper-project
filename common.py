# common.py
from dataclasses import dataclass
from typing import Optional

@dataclass
class OrderData:
    """
    用于存储单个订单的核心信息，以生成最终的Excel报告。
    """
    # 核心ID
    order_id: str

    # --- 新增：商品信息 ---
    item_title: Optional[str] = None      # 商品名称
    item_sku_title: Optional[str] = None  # 商品规格

    # 订单状态与金额
    order_status: Optional[str] = None
    total_price: Optional[str] = None     # 实付金额 (保持为字符串)

    # 时间信息
    creation_time: Optional[str] = None
    payment_time: Optional[str] = None
    shipping_time: Optional[str] = None   # 发货时间 (如果JSON提供就记录)

    # --- 辅助字段 ---
    order_detail_url: Optional[str] = None # 用于截图的详情页URL
    screenshot_path: Optional[str] = None  # 截图在本地的保存路径