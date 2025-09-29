# common.py (更新版)
from dataclasses import dataclass, asdict
from typing import Optional

@dataclass
class OrderData:
    order_id: str
    shop_name: Optional[str] = None
    item_title: Optional[str] = None
    item_sku_title: Optional[str] = None
    order_status: Optional[str] = None
    sub_order_desc: Optional[str] = None # 【新增】订单退款状态
    total_price: Optional[str] = None
    creation_time: Optional[str] = None
    payment_time: Optional[str] = None
    shipping_time: Optional[str] = None
    order_detail_url: Optional[str] = None

    def to_dict(self):
        return asdict(self)