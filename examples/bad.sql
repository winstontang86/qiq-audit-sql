-- 故意写得很差的建表与 DML，覆盖大部分检查项

-- 1. 字符集没指定
CREATE DATABASE my_db_1;

-- 2. 一个糟糕的 CREATE TABLE
CREATE TABLE Orders_2_ (                          -- 表名大写、下划线结尾、_数字_
    Id int PRIMARY KEY,                           -- 主键不是 bigint，且未显式 NOT NULL
    Price double,                                 -- 禁止 double
    Status enum('a','b'),                         -- 禁止 ENUM
    Name varchar(64),                             -- 大写命名 + 缺 NOT NULL + 缺 COMMENT
    UserDesc text,                                -- TEXT 类型告警
    select_col int,                               -- 保留字 select
    create_at datetime,                           -- 缺默认值 + 时间字段ok
    KEY name_idx (Name),                          -- 索引名不以 idx_ 开头 + varchar 索引未指定长度
    UNIQUE KEY uk_status (Status),
    CONSTRAINT fk_user FOREIGN KEY (Id) REFERENCES users(id)  -- 禁止外键
) ENGINE=MyISAM DEFAULT CHARSET=latin1 COLLATE=latin1_bin;     -- 引擎/字符集/字符序都告警，缺表 COMMENT

-- 3. 缺 WHERE 的 DML
DELETE FROM orders;
UPDATE orders SET price = 1;
SELECT * FROM orders;

-- 4. INSERT 不指定字段
INSERT INTO orders VALUES (1, 2, 3);

-- 5. 多表 join + ORDER BY RAND() + 全模糊
SELECT * FROM a
JOIN b ON a.id = b.aid
JOIN c ON c.bid = b.id
JOIN d ON d.cid = c.id
WHERE a.name LIKE '%abc%'
ORDER BY RAND();

-- 6. count(列) + WHERE 函数 + = NULL + IN(超长)
SELECT count(id) FROM orders WHERE DATE(create_at) = '2026-01-01' AND status = NULL;

-- 7. 删表/删库
DROP TABLE orders;
DROP DATABASE my_db_1;

-- 8. 存储过程
CALL my_proc();

-- 9. ALTER DROP COLUMN
ALTER TABLE orders DROP COLUMN price;
