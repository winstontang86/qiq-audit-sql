---
name: qiq-audit-sql
version: 0.1.0
description: 业务后台 DB 规范检查 skill。当用户提交 .sql 文件、含嵌入 SQL 的源代码或 DDL/DML 片段，请求 SQL/DB 规范审核、代码 review、合流/上线门禁检查时使用。覆盖建库建表、库表操作、DB 选型、部署监控、安全、生产管理 6 章中的「必须」与「推荐」级条目，自动产出违规清单与修复建议。
allowed-tools: Read, Write, Edit, Bash, Glob, Grep
agent_created: true
---

# qiq-audit-sql：业务后台 DB 规范检查

## 何时使用

满足任一条件即加载本 skill：

- 用户明确要求「DB 规范检查 / SQL review / 建表 review / 合流门禁 / qiq-audit-sql」
- 用户粘贴或指向 `.sql` 文件、SQL DDL/DML 片段
- 用户提交后台代码（Go/Python/Java/JS/TS/C/C++/PHP/Ruby/Scala/Kotlin/Rust）请求 review，且代码中存在嵌入 SQL
- CI/合流场景：对目录、提交、PR 做 DB 规范门禁

## 检查范围

只检查规范中的 **【必须】** 与 **【推荐】** 条目，**【可选】** 不检查。覆盖 6 章：建库建表、库表操作、DB 选型、部署监控、安全、生产管理。

完整条目见 `references/checklist.md`，规范全文见 `references/full-spec.md`。

## 工作流

### Step 1 —— 确定检查目标

- 单个文件路径（`.sql` 或源代码）→ 直接传给脚本
- 目录路径 → 脚本递归扫描所有 `.sql` 与支持的源代码后缀
- 对话里贴的 SQL 片段 → 用 `Write` 落到 `/tmp/qiq-audit-input.sql` 后再扫描

### Step 2 —— 运行自动化检查

```bash
python3 ${SKILL_DIR}/scripts/audit_sql.py <目标路径...> [选项]
```

常用选项：

- 默认输出 Markdown 报告到 stdout
- `--strict`：把【推荐】级违规也作为阻断条件（合流门禁场景）
- `--format json`：机器可读 JSON
- `-o <file>`：写入文件
- `--diff [REF]`：**行粒度增量模式**。只报告落在 git diff 新增/修改行上的违规。
  - 不带 REF：检查工作区相对 HEAD 的改动（已暂存 + 未暂存 + 未跟踪整文件）。
  - 带 REF：透传给 `git diff <REF>`，例如 `--diff HEAD~1`、`--diff origin/master...HEAD`。
  - 每次执行的中间产物落在 **被检查仓库根目录** 的 `.qiqskills/audit-sql/` 下：`diff.patch`、`changed-lines.json`、`report.{md,json}`。已在 `.gitignore` 中默认忽略。
  - **CI / 合流门禁推荐用法**：`--diff origin/master...HEAD --strict`，只阐断本次 PR 新增的违规。

退出码：`0`=通过；`1`=有【必须】违规（或 `--strict` 下任意违规）；`2`=参数错误。

脚本仅依赖 Python 3 标准库，无第三方依赖。

#### 豁免与项目配置（限制噪声）

- **内联豁免注释**（仅识别 SQL 注释里的指令，不识别宿主语言原生注释）：
  ```sql
  -- audit-sql:disable-file=1.2.1,1.1.20  reason=upstream keycloak schema
  -- audit-sql:disable-next-line=1.2.1    reason=月分表占位符
  CREATE TABLE t_log_YYYYMM (...);
  ```
  多个规则号用逗号隔开；`*` 表示所有规则。
- **项目级配置** `.audit-sql.json`（仓库根目录，脚本会从被检查路径向上查找）：
  ```json
  {
    "column_aliases": {
      "create_at": ["created_at", "gmt_create"],
      "update_at": ["updated_at", "gmt_modified"]
    },
    "table_name_placeholders": ["_YYYYMM", "_YYYYMMDD"],
    "excluded_paths": ["**/keycloak-bridge/**", "**/test/fixture/**"]
  }
  ```
  - `column_aliases`：拓宽 1.1.19 必备字段可接受的命名（在内置默认之上合并，内置已含 `created_at/updated_at/gmt_create/gmt_modified/ctime/mtime`）。
  - `table_name_placeholders`：表名包含该片段时跳过 1.2.1 命名检查。
  - `excluded_paths`：命中路径的违规在报告中被划入「⚪ 上游/历史兼容」分组（**不豁免**，只是分档提示）。如需真豁免请配合 `disable-file`。

### Step 3 —— 解读报告

脚本输出已是结构化 Markdown 报告，以三档分组呈现：

- 🔴 **真违规**：优先修复；必须级阐断合流。
- 🟡 **疑似误报**：命中项目配置的占位符等信号。报表会附「处理提示」一列，提示加 `disable-next-line` 或调整 `.audit-sql.json`。
- ⚪ **上游/历史兼容**：路径命中 `excluded_paths` 或常见上游项目关键字（keycloak/temporal/gitlab…），建议走豁免名单。

表格字段含：等级（🛑必须 / ⚠️推荐）、规则编号、文件、行号、标题、说明。JSON 输出中每条 finding 附 `group` 标签（real / suspect / upstream）。

### Step 4 —— 补充人工 review

`references/checklist.md` 中「人工 / AI review」区列出脚本难以判定、需人工确认的维度，如：

- 索引设计是否走极端（每列单索引 / 全列覆盖）
- 业务唯一字段是否建唯一索引
- 跨时区时间字段选型
- 敏感字段加密
- DB 部署 / 监控 / 审计 / RO 配置
- Client SDK 连接超时配置

若用户的检查范围涉及上述维度，逐项过 checklist 并结合上下文给出建议；否则可跳过本步。

### Step 5 —— 给出修复建议

对每条违规：

- 引用规则编号 + 文件路径 + 行号
- 给出修复后的 SQL 写法
- 【必须】级先修；【推荐】级若保留，需在合流说明中注明原因

## 重要约束

- 只检查【必须】与【推荐】，【可选】条目不出现在报告里。
- 报告统一使用 Markdown 格式。
- 源代码嵌入 SQL 识别后缀：`.go .py .js .ts .jsx .tsx .java .kt .rs .cpp .cc .cxx .c .h .hpp .php .rb .scala`。
- 不直接修改业务代码，只产出报告；除非用户明确要求「自动修复」。
- 报告中的规则编号必须与 `references/full-spec.md` 一一对应。

## 用法示例

```bash
# 检查单个 SQL 文件
python3 scripts/audit_sql.py path/to/migrations/v1.sql

# 检查整个仓库
python3 scripts/audit_sql.py .

# 合流门禁（推荐级也阻断）
python3 scripts/audit_sql.py services/ --strict

# 输出 JSON 供上游工具消费
python3 scripts/audit_sql.py . --format json -o /tmp/audit.json

# 行粒度增量：只检查工作区未提交的改动
python3 scripts/audit_sql.py . --diff

# 行粒度增量：只检查相对某个基线分支的改动（CI 常用）
python3 scripts/audit_sql.py . --diff origin/master...HEAD
```

## 自我回归

修改脚本后执行：

```bash
python3 scripts/audit_sql.py examples/bad.sql     # 期望大量违规、退出码 1
python3 scripts/audit_sql.py examples/good.sql    # 期望 0 个【必须】违规、退出码 0
python3 scripts/audit_sql.py examples/sample.go   # 期望识别 Go 中嵌入 SQL
```
