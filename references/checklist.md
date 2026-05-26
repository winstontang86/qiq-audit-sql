# 检查项 Checklist（机读 + 人工 review 双轨）

> 本表把规范条目按「自动检查 (auto)」与「人工/AI review (manual)」分类。
> - **auto**：`scripts/audit_sql.py` 会自动检查并产出违规清单。
> - **manual**：脚本难以可靠判定，需要由 AI 助手或开发者按 checklist 人工 review。
>
> 本 skill 当前**只检查必须 (MUST) 与推荐 (RECOMMEND) 等级**，可选 (OPTIONAL) 不检查。

## 一、自动检查（auto）

| 编号 | 等级 | 类别 | 检查内容 |
|---|---|---|---|
| 1.1.1 | MUST | DDL | 表名/字段名是否使用 MySQL 保留字 |
| 1.1.3 | MUST | DDL | `CREATE DATABASE` 必须显式指定 `CHARACTER SET`，且只能为 `utf8` 或 `utf8mb4` |
| 1.1.7 | MUST | DDL | 列类型禁止 `float` / `double`（小数用 `decimal`） |
| 1.1.9 | MUST | DDL | `CREATE TABLE` 必须显式声明 `PRIMARY KEY` |
| 1.1.10 | MUST | DDL | 主键列类型应为 `bigint`（推荐 unsigned） |
| 1.1.11 | MUST | DDL | 索引涉及的列必须 `NOT NULL` |
| 1.1.15 | MUST | DDL | 列类型禁止 `ENUM` |
| 1.1.17 | MUST | DDL | `CREATE TABLE` 禁止 `FOREIGN KEY` 或 `REFERENCES` |
| 1.1.20 | MUST | DDL | 表与所有列必须带 `COMMENT` |
| 1.2.1 | MUST | DDL | 表名/字段名只允许小写字母+数字+下划线；不能数字开头；不能以下划线结尾；两个下划线之间不能仅是数字 |
| 2.4 | MUST | DDL | 禁止 `ALTER TABLE ... DROP COLUMN` |
| 2.5 | MUST | DML | `INSERT INTO tbl VALUES (...)` 必须显式列出字段名（即不允许省略字段列表） |
| 2.6 | MUST | DML | `UPDATE` / `DELETE` 必须带 `WHERE`；`SELECT` 不带 `WHERE` 也告警 |
| 2.10 | MUST | DML | 一条 SQL 中的 `JOIN` 表数量不得超过 3 个 |
| 2.11 | MUST | DML | 禁止 `CREATE PROCEDURE` / `CALL` 存储过程 |
| 1.1.2 | RECOMMEND | DDL | 建表语句若指定 `ENGINE=`，应为 `InnoDB`；未指定时不告警 |
| 1.1.4 | RECOMMEND | DDL | 建表 `CHARSET` 推荐 `utf8mb4`（若使用其他字符集告警） |
| 1.1.6 | RECOMMEND | DDL | 字符序不要使用 `*_bin`（大小写敏感） |
| 1.1.13 | RECOMMEND | DDL | `NOT NULL` 列推荐带 `DEFAULT`（无默认值告警） |
| 1.1.14 | RECOMMEND | DDL | `timestamp` / `datetime` 列建议有默认值 |
| 1.1.18 | RECOMMEND | DDL | 表字段数 < 99 |
| 1.1.19 | RECOMMEND | DDL | 表必备字段：`id`、`create_at`、`update_at` |
| 1.2.2 | RECOMMEND | DDL | 索引命名：主键 `pk_`、唯一索引 `uk_`、普通索引 `idx_` |
| 1.2.4 | RECOMMEND | DDL | 库名/表名/列名长度 ≤ 32 字符 |
| 1.2.5 | RECOMMEND | DDL | 时间类列建议命名后缀：时间戳 `_at`、日期 `_date`、月份 `_month` |
| 1.3.3 | RECOMMEND | DDL | `TEXT` / `BLOB` 列出现时告警（建议拆表） |
| 1.3.5 | RECOMMEND | DDL | varchar 字段建索引时必须指定索引长度（前缀长度） |
| 2.3 | RECOMMEND | DDL | 同一文件内对同一表多条 `ALTER` 建议合并 |
| 2.8 | RECOMMEND | DML | `SELECT *` 告警 |
| 2.9 | RECOMMEND | DML | `WHERE` 中索引列嵌套函数（如 `DATE(col)`、`UPPER(col)`）告警 |
| 2.13 | RECOMMEND | DML | `LIKE '%xxx'` / `LIKE '%xxx%'` 告警 |
| 2.14 | RECOMMEND | DML | `IN (...)` 元素数量 ≤ 200 |
| 2.18 | RECOMMEND | DML | 禁止 `ORDER BY RAND()` |
| 2.16 | RECOMMEND | DML | `count(列名)` / `count(1)` 提示改用 `count(*)`（仅提示） |

## 二、人工 / AI review（manual）

下列条目难以纯静态判定，需要 AI 辅助 review，由 SKILL.md 引导按条过：

| 编号 | 等级 | 检查要点 |
|---|---|---|
| 1.1.5 | RECOMMEND | 表大小写不敏感（`lower_case_table_names` 配置层面） |
| 1.1.8 | RECOMMEND | 业务上是否本可以用整数替代小数 |
| 1.1.16 | MUST | 索引设计是否走极端（每列单索引 / 全列覆盖） |
| 1.2.3 | RECOMMEND | 「是否」语义字段是否命名为 `is_xxx` 且类型 `tinyint unsigned` |
| 1.3.1 | RECOMMEND | 长度近似相等的字符串是否用 `char` |
| 1.3.2 | RECOMMEND | 时间类型选型是否合适（跨时区场景） |
| 1.3.4 | RECOMMEND | 业务唯一字段是否建了唯一索引 |
| 2.1 | MUST | 是否存在 `DROP DATABASE`（脚本可识别 + review 是否走流程） |
| 2.2 | MUST | 是否存在 `DROP TABLE`（脚本可识别 + review 是否走流程） |
| 2.7 | RECOMMEND | `WHERE` 等号左右字段类型是否一致（需要表结构上下文） |
| 2.15 | RECOMMEND | 是否使用 `ISNULL()` 而非 `= NULL` / `<> NULL`（脚本可粗判） |
| 2.17 | RECOMMEND | 超大分页是否做了延迟关联优化 |
| 3.1 | RECOMMEND | MySQL 版本 ≥ 5.7（推荐 8.0） |
| 3.2 | RECOMMEND | 数据量预估超过 2000 万行需考虑分库分表 |
| 3.3 | RECOMMEND | 启用 `sql_mode` 严格模式 |
| 4.1 | MUST | 跨 AZ 主从、跨 Region 同步 |
| 4.2 | MUST | 重要指标监控告警（连接数/连接使用率/死锁数/磁盘/内存） |
| 5.1 | RECOMMEND | 敏感信息字段加密存储 |
| 5.2 | RECOMMEND | 对接 DB 逻辑层负责 SQL 转义防注入 |
| 5.3 | MUST | Client SDK 初始化显式设置连接超时时间 |
| 6.1 | MUST | 开启审计日志 |
| 6.2 | MUST | RO 组在两个不同可用区 |
| 6.3 | MUST | 主实例开启延时 RO |

## 三、违规级别说明

- **MUST（必须）**：不允许存在违规，发现即应阻断合流；脚本退出码 ≠ 0。
- **RECOMMEND（推荐）**：原则上应遵守，特殊情况可放行但需说明；脚本以告警形式输出，不阻断退出码（可通过 `--strict` 参数把推荐项也提升为阻断）。
- **OPTIONAL（可选）**：本 skill 不检查。
