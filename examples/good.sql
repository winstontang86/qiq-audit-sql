-- 一个相对规范的建表示例

CREATE DATABASE good_db CHARACTER SET utf8mb4;

CREATE TABLE order_item (
    id           bigint unsigned NOT NULL AUTO_INCREMENT COMMENT '主键 ID',
    order_id     bigint unsigned NOT NULL DEFAULT 0      COMMENT '订单 ID',
    sku_code     varchar(64)     NOT NULL DEFAULT ''     COMMENT 'SKU 编码',
    item_name    varchar(128)    NOT NULL DEFAULT ''     COMMENT '商品名称',
    quantity     int unsigned    NOT NULL DEFAULT 0      COMMENT '商品数量',
    price        decimal(12, 2)  NOT NULL DEFAULT 0.00   COMMENT '单价（元）',
    is_gift      tinyint unsigned NOT NULL DEFAULT 0     COMMENT '是否赠品：1=是，0=否',
    create_at    datetime        NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    update_at    datetime        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    PRIMARY KEY (id),
    UNIQUE KEY uk_order_sku (order_id, sku_code),
    KEY idx_create_at (create_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci COMMENT='订单明细';

-- 规范的 DML
SELECT id, item_name, price FROM order_item WHERE order_id = 1001 LIMIT 100;
INSERT INTO order_item (order_id, sku_code, item_name, quantity, price)
    VALUES (1001, 'SKU-1', '商品 A', 2, 19.90);
UPDATE order_item SET quantity = quantity + 1 WHERE id = 1;
DELETE FROM order_item WHERE id = 1;
SELECT count(*) FROM order_item WHERE order_id = 1;
