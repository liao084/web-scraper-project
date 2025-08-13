from dataclasses import dataclass
from typing import Optional


@dataclass
class OrderData:
    """
    用于存储从JSON中解析出的单个订单的完整信息。
    假设一个订单只包含一个商品。
    所有字段都设为可选，以增强程序的健-健壮性。
    """
    # 核心ID和URL
    order_id: Optional[str] = None
    order_detail_url: Optional[str] = None

    # 状态和金额
    order_status: Optional[str] = None
    total_price: Optional[float] = None

    # 时间信息
    creation_time: Optional[str] = None
    payment_time: Optional[str] = None
    shipping_time: Optional[str] = None  # 发货时间

    # 店铺信息
    shop_name: Optional[str] = None

    # --- 商品信息 (直接作为主类属性) ---
    item_title: Optional[str] = None
    item_sku: Optional[str] = None  # 商品规格，例如 "黑色; 42码"
    item_price: Optional[float] = None  # 商品单价
    item_quantity: Optional[int] = None  # 商品数量 (虽然总是一个，但保留此字段是好习惯)
    item_img_url: Optional[str] = None  # 商品主图的URL

    # 截图在本地的保存路径
    screenshot_path: Optional[str] = None