from dataclasses import dataclass
from typing import Optional


@dataclass
class OrderData:
    """
    用于存储单个订单的核心信息，以生成最终的Excel报告。
    所有非必需字段都设为可选，以增强程序的健壮性。
    """
    # 核心ID
    order_id: str  # 订单号，我们假设这个是必填的

    # 订单状态与金额
    order_status: Optional[str] = None
    total_price: Optional[float] = None  # 实付金额

    # 时间信息 (根据订单状态，可能为空)
    creation_time: Optional[str] = None  # 下单时间
    payment_time: Optional[str] = None  # 付款时间
    shipping_time: Optional[str] = None  # 发货时间

    # --- 以下是辅助字段，用于爬虫流程，但不会直接导出到最终Excel的核心列 ---

    # 用于截图的详情页URL
    order_detail_url: Optional[str] = None

    # 截图在本地的临时保存路径
    screenshot_path: Optional[str] = None