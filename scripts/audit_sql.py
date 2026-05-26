#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
qiq-audit-sql: DB 规范自动检查脚本

用法:
    python audit_sql.py <path> [path...] [--strict] [--format md|json] [-o out.md]

支持:
    - .sql 文件
    - 源码文件（.go/.py/.js/.ts/.java/.kt/.rs/.cpp/.c/.cc/.h/.php/.rb/.scala）
      会从字符串字面量中提取嵌入 SQL（识别含 CREATE/ALTER/SELECT/INSERT/UPDATE/DELETE 关键字的字符串）

输出:
    Markdown 格式的违规报告（默认 stdout，或 -o 输出到文件）。

退出码:
    0 = 通过（无 MUST 违规；--strict 模式下要求无任何违规）
    1 = 存在 MUST 违规（或 --strict 模式下存在任何违规）
    2 = 输入参数错误
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

# -------------------- 数据结构 --------------------

LEVEL_MUST = "MUST"
LEVEL_RECOMMEND = "RECOMMEND"


@dataclass
class Finding:
    rule_id: str
    level: str  # MUST / RECOMMEND
    title: str
    message: str
    file: str
    line: int = 0
    snippet: str = ""

    def to_dict(self):
        return {
            "rule_id": self.rule_id,
            "level": self.level,
            "title": self.title,
            "message": self.message,
            "file": self.file,
            "line": self.line,
            "snippet": self.snippet,
        }


@dataclass
class SqlBlock:
    """从源文件中提取出的一条/一段 SQL 内容。"""
    text: str
    file: str
    start_line: int  # 原始文件中的起始行号

    def line_of_offset(self, offset: int) -> int:
        return self.start_line + self.text[:offset].count("\n")


# -------------------- 保留字（精简集，覆盖最常见） --------------------
# 来源：MySQL 8.0 reserved words 主要集合 + 常见关键字。完整集太大，列高频。
RESERVED_WORDS = {
    "accessible", "add", "all", "alter", "analyze", "and", "as", "asc", "asensitive",
    "before", "between", "bigint", "binary", "blob", "both", "by",
    "call", "cascade", "case", "change", "char", "character", "check", "collate",
    "column", "condition", "constraint", "continue", "convert", "create", "cross",
    "cube", "cume_dist", "current_date", "current_time", "current_timestamp", "current_user",
    "cursor",
    "database", "databases", "day_hour", "day_microsecond", "day_minute", "day_second",
    "dec", "decimal", "declare", "default", "delayed", "delete", "dense_rank", "desc",
    "describe", "deterministic", "distinct", "distinctrow", "div", "double", "drop", "dual",
    "each", "else", "elseif", "empty", "enclosed", "escaped", "except", "exists", "exit",
    "explain",
    "false", "fetch", "first_value", "float", "float4", "float8", "for", "force", "foreign",
    "from", "fulltext", "function",
    "generated", "get", "grant", "group", "grouping", "groups",
    "having", "high_priority", "hour_microsecond", "hour_minute", "hour_second",
    "if", "ignore", "in", "index", "infile", "inner", "inout", "insensitive", "insert",
    "int", "int1", "int2", "int3", "int4", "int8", "integer", "intersect", "interval", "into",
    "io_after_gtids", "io_before_gtids", "is", "iterate",
    "join", "json_table",
    "key", "keys", "kill",
    "lag", "last_value", "lateral", "lead", "leading", "leave", "left", "like", "limit",
    "linear", "lines", "load", "localtime", "localtimestamp", "lock", "long", "longblob",
    "longtext", "loop", "low_priority",
    "master_bind", "master_ssl_verify_server_cert", "match", "maxvalue", "mediumblob",
    "mediumint", "mediumtext", "middleint", "minute_microsecond", "minute_second", "mod",
    "modifies",
    "natural", "not", "no_write_to_binlog", "nth_value", "ntile", "null", "numeric",
    "of", "on", "optimize", "optimizer_costs", "option", "optionally", "or", "order", "out",
    "outer", "outfile", "over",
    "partition", "percent_rank", "precision", "primary", "procedure", "purge",
    "range", "rank", "read", "reads", "read_write", "real", "recursive", "references",
    "regexp", "release", "rename", "repeat", "replace", "require", "resignal", "restrict",
    "return", "revoke", "right", "rlike", "row", "rows", "row_number",
    "schema", "schemas", "second_microsecond", "select", "sensitive", "separator", "set",
    "show", "signal", "smallint", "spatial", "specific", "sql", "sqlexception", "sqlstate",
    "sqlwarning", "sql_big_result", "sql_calc_found_rows", "sql_small_result", "ssl",
    "starting", "stored", "straight_join", "system",
    "table", "tables", "terminated", "then", "tinyblob", "tinyint", "tinytext", "to",
    "trailing", "trigger", "true",
    "undo", "union", "unique", "unlock", "unsigned", "update", "usage", "use", "using",
    "utc_date", "utc_time", "utc_timestamp",
    "values", "varbinary", "varchar", "varcharacter", "varying", "virtual",
    "when", "where", "while", "window", "with", "write",
    "xor",
    "year_month",
    "zerofill",
}

# -------------------- 工具函数 --------------------

SOURCE_EXTS = {
    ".go", ".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".kt", ".rs",
    ".cpp", ".cc", ".cxx", ".c", ".h", ".hpp", ".php", ".rb", ".scala",
}

SQL_KEYWORDS_FOR_DETECT = re.compile(
    r"\b(SELECT|INSERT|UPDATE|DELETE|CREATE|ALTER|DROP|TRUNCATE|REPLACE|CALL)\b",
    re.IGNORECASE,
)


def strip_sql_comments(sql: str) -> str:
    """删除 SQL 注释：-- ... 单行、/* */ 多行、# 单行（hash 注释）。
    保留长度，便于行号计算 → 改用占位空格替换。
    """
    out = []
    i = 0
    n = len(sql)
    while i < n:
        ch = sql[i]
        nxt = sql[i + 1] if i + 1 < n else ""
        # 单引号字符串
        if ch == "'":
            j = i + 1
            while j < n:
                if sql[j] == "\\" and j + 1 < n:
                    j += 2
                    continue
                if sql[j] == "'":
                    if j + 1 < n and sql[j + 1] == "'":  # 连续两个单引号转义
                        j += 2
                        continue
                    j += 1
                    break
                j += 1
            out.append(sql[i:j])
            i = j
            continue
        # 双引号字符串
        if ch == '"':
            j = i + 1
            while j < n:
                if sql[j] == "\\" and j + 1 < n:
                    j += 2
                    continue
                if sql[j] == '"':
                    j += 1
                    break
                j += 1
            out.append(sql[i:j])
            i = j
            continue
        # 反引号标识符
        if ch == "`":
            j = i + 1
            while j < n and sql[j] != "`":
                j += 1
            j = min(j + 1, n)
            out.append(sql[i:j])
            i = j
            continue
        # /* */ 注释
        if ch == "/" and nxt == "*":
            j = sql.find("*/", i + 2)
            if j == -1:
                j = n
            else:
                j += 2
            # 保留换行
            out.append("".join("\n" if c == "\n" else " " for c in sql[i:j]))
            i = j
            continue
        # -- 单行注释
        if ch == "-" and nxt == "-":
            j = sql.find("\n", i)
            if j == -1:
                j = n
            out.append(" " * (j - i))
            i = j
            continue
        # # 单行注释（MySQL 支持）
        if ch == "#":
            j = sql.find("\n", i)
            if j == -1:
                j = n
            out.append(" " * (j - i))
            i = j
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def split_statements(sql: str) -> list[tuple[int, str]]:
    """按分号拆分语句，跳过字符串内的分号。返回 [(offset, statement_text), ...]。"""
    stmts: list[tuple[int, str]] = []
    n = len(sql)
    i = 0
    start = 0
    while i < n:
        ch = sql[i]
        if ch in ("'", '"'):
            quote = ch
            j = i + 1
            while j < n:
                if sql[j] == "\\" and j + 1 < n:
                    j += 2
                    continue
                if sql[j] == quote:
                    if j + 1 < n and sql[j + 1] == quote:
                        j += 2
                        continue
                    j += 1
                    break
                j += 1
            i = j
            continue
        if ch == "`":
            j = i + 1
            while j < n and sql[j] != "`":
                j += 1
            i = min(j + 1, n)
            continue
        if ch == ";":
            stmt = sql[start:i].strip()
            if stmt:
                stmts.append((start, stmt))
            i += 1
            start = i
            continue
        i += 1
    tail = sql[start:].strip()
    if tail:
        stmts.append((start, tail))
    return stmts


def extract_sql_blocks_from_source(src: str, file: str) -> list[SqlBlock]:
    """从源代码字符串字面量中提取可能的 SQL 块。"""
    blocks: list[SqlBlock] = []
    n = len(src)
    i = 0
    while i < n:
        ch = src[i]
        # 反引号（Go/JS template / 多行字符串）
        if ch == "`":
            j = i + 1
            while j < n and src[j] != "`":
                j += 1
            content = src[i + 1: j]
            if SQL_KEYWORDS_FOR_DETECT.search(content):
                start_line = src[:i].count("\n") + 1
                blocks.append(SqlBlock(content, file, start_line))
            i = j + 1
            continue
        # 三引号字符串（Python/Scala）
        if ch in ('"', "'") and src[i:i + 3] in ('"""', "'''"):
            quote = src[i:i + 3]
            j = src.find(quote, i + 3)
            if j == -1:
                j = n
            content = src[i + 3: j]
            if SQL_KEYWORDS_FOR_DETECT.search(content):
                start_line = src[:i].count("\n") + 1
                blocks.append(SqlBlock(content, file, start_line))
            i = j + 3
            continue
        # 单/双引号字符串
        if ch in ('"', "'"):
            quote = ch
            j = i + 1
            while j < n:
                if src[j] == "\\" and j + 1 < n:
                    j += 2
                    continue
                if src[j] == quote:
                    break
                if src[j] == "\n":
                    # 大多数语言单/双引号不允许换行，遇到换行就放弃
                    break
                j += 1
            content = src[i + 1: j]
            if SQL_KEYWORDS_FOR_DETECT.search(content):
                start_line = src[:i].count("\n") + 1
                blocks.append(SqlBlock(content, file, start_line))
            i = j + 1
            continue
        i += 1
    return blocks


# -------------------- 检查器 --------------------

# CREATE TABLE 的整体匹配
RE_CREATE_TABLE = re.compile(
    r"\bCREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[`\"]?(\w+)[`\"]?\s*\((.*?)\)\s*(ENGINE\s*=\s*\w+|DEFAULT\s+CHARSET|CHARACTER\s+SET|/\*.*?\*/|;|$)?",
    re.IGNORECASE | re.DOTALL,
)

RE_CREATE_DATABASE = re.compile(
    r"\bCREATE\s+(?:DATABASE|SCHEMA)\s+(?:IF\s+NOT\s+EXISTS\s+)?[`\"]?(\w+)[`\"]?(.*?)(?:;|$)",
    re.IGNORECASE | re.DOTALL,
)


def _strip_inline_parens(s: str) -> str:
    """把 column 行内的小括号(如 varchar(64)、decimal(10,2))内容去掉，便于按逗号拆列。"""
    out = []
    depth = 0
    for c in s:
        if c == "(":
            depth += 1
            continue
        if c == ")":
            depth = max(depth - 1, 0)
            continue
        if depth == 0:
            out.append(c)
    return "".join(out)


def split_columns_block(body: str) -> list[str]:
    """把 CREATE TABLE 括号内的体按顶层逗号拆开。"""
    items: list[str] = []
    depth = 0
    cur = []
    in_q = None
    i = 0
    n = len(body)
    while i < n:
        ch = body[i]
        if in_q:
            cur.append(ch)
            if ch == "\\" and i + 1 < n:
                cur.append(body[i + 1])
                i += 2
                continue
            if ch == in_q:
                in_q = None
            i += 1
            continue
        if ch in ("'", '"', "`"):
            in_q = ch
            cur.append(ch)
            i += 1
            continue
        if ch == "(":
            depth += 1
            cur.append(ch)
            i += 1
            continue
        if ch == ")":
            depth -= 1
            cur.append(ch)
            i += 1
            continue
        if ch == "," and depth == 0:
            items.append("".join(cur).strip())
            cur = []
            i += 1
            continue
        cur.append(ch)
        i += 1
    if cur:
        item = "".join(cur).strip()
        if item:
            items.append(item)
    return items


# -------------------- 各项检查实现 --------------------

class Auditor:
    def __init__(self):
        self.findings: list[Finding] = []

    def add(self, f: Finding):
        self.findings.append(f)

    # === 入口 ===
    def audit_block(self, block: SqlBlock):
        cleaned = strip_sql_comments(block.text)
        for stmt_offset, stmt in split_statements(cleaned):
            line = block.line_of_offset(stmt_offset)
            self._audit_statement(stmt, block.file, line)

    def _audit_statement(self, stmt: str, file: str, line: int):
        s = stmt.strip()
        upper_head = s.upper().lstrip("(").lstrip()
        # 分类
        if re.match(r"CREATE\s+(DATABASE|SCHEMA)\b", upper_head):
            self._check_create_database(s, file, line)
        elif re.match(r"CREATE\s+TABLE\b", upper_head):
            self._check_create_table(s, file, line)
        elif re.match(r"ALTER\s+TABLE\b", upper_head):
            self._check_alter_table(s, file, line)
        elif re.match(r"DROP\s+TABLE\b", upper_head):
            self.add(Finding(
                "2.2", LEVEL_MUST, "禁止 DROP TABLE",
                "禁止用 SQL 命令直接删表，需走表下线流程。",
                file, line, _short(s)))
        elif re.match(r"DROP\s+(DATABASE|SCHEMA)\b", upper_head):
            self.add(Finding(
                "2.1", LEVEL_MUST, "禁止 DROP DATABASE",
                "禁止用 SQL 命令直接删库，需走数据库下线流程。",
                file, line, _short(s)))
        elif re.match(r"CREATE\s+(DEFINER\s*=\s*\S+\s+)?(PROCEDURE|FUNCTION)\b", upper_head):
            self.add(Finding(
                "2.11", LEVEL_MUST, "禁止存储过程/函数",
                "禁止使用存储过程/函数（难调试、难扩展、不可移植）。",
                file, line, _short(s)))
        elif re.match(r"CALL\s+\w", upper_head):
            self.add(Finding(
                "2.11", LEVEL_MUST, "禁止 CALL 存储过程",
                "禁止调用存储过程。",
                file, line, _short(s)))
        elif re.match(r"INSERT\s+(IGNORE\s+)?INTO\b", upper_head):
            self._check_insert(s, file, line)
        elif re.match(r"REPLACE\s+INTO\b", upper_head):
            self._check_insert(s, file, line)
        elif re.match(r"UPDATE\b", upper_head):
            self._check_update_delete(s, file, line, kind="UPDATE")
            self._check_dml_common(s, file, line)
        elif re.match(r"DELETE\b", upper_head):
            self._check_update_delete(s, file, line, kind="DELETE")
            self._check_dml_common(s, file, line)
        elif re.match(r"SELECT\b", upper_head):
            self._check_select(s, file, line)
            self._check_dml_common(s, file, line)

    # === DDL: CREATE DATABASE ===
    def _check_create_database(self, s: str, file: str, line: int):
        m = RE_CREATE_DATABASE.search(s)
        if not m:
            return
        opts = m.group(2) or ""
        opts_upper = opts.upper()
        # 1.1.3 必须指定字符集
        cs_match = re.search(r"(?:CHARACTER\s+SET|CHARSET)\s*=?\s*([\w]+)", opts, re.IGNORECASE)
        if not cs_match:
            self.add(Finding(
                "1.1.3", LEVEL_MUST, "建库必须指定字符集",
                "CREATE DATABASE 必须显式 CHARACTER SET / CHARSET，且只能为 utf8 或 utf8mb4（推荐 utf8mb4）。",
                file, line, _short(s)))
        else:
            cs = cs_match.group(1).lower()
            if cs not in ("utf8", "utf8mb4", "utf8mb3"):
                self.add(Finding(
                    "1.1.3", LEVEL_MUST, "字符集只能为 utf8 / utf8mb4",
                    f"当前字符集 `{cs}`，必须改为 utf8 或 utf8mb4（推荐 utf8mb4）。",
                    file, line, _short(s)))

    # === DDL: CREATE TABLE ===
    def _check_create_table(self, s: str, file: str, line: int):
        # 提取表名 + 括号体
        m = re.search(r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[`\"]?(\w+)[`\"]?\s*\(", s, re.IGNORECASE)
        if not m:
            return
        tbl = m.group(1)
        body_start = s.index("(", m.end() - 1)
        # 找匹配的右括号
        depth = 0
        i = body_start
        in_q = None
        end = -1
        while i < len(s):
            ch = s[i]
            if in_q:
                if ch == "\\" and i + 1 < len(s):
                    i += 2
                    continue
                if ch == in_q:
                    in_q = None
                i += 1
                continue
            if ch in ("'", '"', "`"):
                in_q = ch
                i += 1
                continue
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    end = i
                    break
            i += 1
        if end == -1:
            return
        body = s[body_start + 1: end]
        tail = s[end + 1:]  # ENGINE / CHARSET / COMMENT 等

        # 1.1.1 表名保留字
        self._check_reserved_identifier(tbl, "表名", file, line, s)
        # 1.2.1 表名命名
        self._check_lower_snake(tbl, "表名", file, line, s)
        # 1.2.4 长度
        if len(tbl) > 32:
            self.add(Finding(
                "1.2.4", LEVEL_RECOMMEND, "表名长度过长",
                f"表名 `{tbl}` 长度 {len(tbl)} > 32 字符。",
                file, line, _short(s)))

        # 解析列与约束
        items = split_columns_block(body)
        columns: list[dict] = []
        primary_keys: list[str] = []
        unique_keys: list[tuple[str, list[str]]] = []
        normal_keys: list[tuple[str, list[str]]] = []
        has_foreign_key = False
        has_inline_pk = False
        inline_pk_col: str | None = None
        inline_pk_unsigned = False
        inline_pk_type = ""

        for raw in items:
            item = raw.strip().rstrip(",").strip()
            if not item:
                continue
            head_upper = item.upper()
            if head_upper.startswith("PRIMARY KEY"):
                cols_match = re.search(r"PRIMARY\s+KEY\s*\(([^)]+)\)", item, re.IGNORECASE)
                if cols_match:
                    primary_keys.extend(_split_idx_cols(cols_match.group(1)))
                continue
            if head_upper.startswith(("UNIQUE KEY", "UNIQUE INDEX", "UNIQUE (")):
                m2 = re.search(r"UNIQUE\s+(?:KEY|INDEX)?\s*[`\"]?(\w*)[`\"]?\s*\(([^)]+)\)", item, re.IGNORECASE)
                if m2:
                    name = m2.group(1) or ""
                    cols = _split_idx_cols(m2.group(2))
                    unique_keys.append((name, cols))
                continue
            if head_upper.startswith(("KEY ", "INDEX ", "KEY(", "INDEX(")):
                m2 = re.search(r"(?:KEY|INDEX)\s+[`\"]?(\w+)[`\"]?\s*\(([^)]+)\)", item, re.IGNORECASE)
                if m2:
                    normal_keys.append((m2.group(1), _split_idx_cols(m2.group(2))))
                continue
            if head_upper.startswith(("CONSTRAINT", "FOREIGN KEY")):
                if "FOREIGN KEY" in head_upper or "REFERENCES" in head_upper:
                    has_foreign_key = True
                # 当一个 CONSTRAINT 子句包含 PRIMARY KEY / UNIQUE 时也要识别
                if "PRIMARY KEY" in head_upper:
                    cols_match = re.search(r"PRIMARY\s+KEY\s*\(([^)]+)\)", item, re.IGNORECASE)
                    if cols_match:
                        primary_keys.extend(_split_idx_cols(cols_match.group(1)))
                if "UNIQUE" in head_upper:
                    m2 = re.search(r"UNIQUE\s+(?:KEY|INDEX)?\s*[`\"]?(\w*)[`\"]?\s*\(([^)]+)\)", item, re.IGNORECASE)
                    if m2:
                        unique_keys.append((m2.group(1) or "", _split_idx_cols(m2.group(2))))
                continue
            if head_upper.startswith(("FULLTEXT", "SPATIAL")):
                continue
            # 普通列定义
            col = _parse_column(item)
            if col is None:
                continue
            columns.append(col)
            if col.get("inline_primary"):
                has_inline_pk = True
                inline_pk_col = col["name"]
                inline_pk_unsigned = col.get("unsigned", False)
                inline_pk_type = col.get("type", "")

        # 1.1.17 禁止外键
        if has_foreign_key:
            self.add(Finding(
                "1.1.17", LEVEL_MUST, "禁止外键",
                "禁止使用 FOREIGN KEY / REFERENCES 外键约束。",
                file, line, _short(s)))

        # 1.1.9 必须显式声明主键
        if not has_inline_pk and not primary_keys:
            self.add(Finding(
                "1.1.9", LEVEL_MUST, "必须显式声明主键",
                "CREATE TABLE 必须显式声明 PRIMARY KEY，不允许省略。",
                file, line, _short(s)))

        # 1.1.10 主键 bigint unsigned
        pk_cols_for_type_check: list[dict] = []
        if has_inline_pk and inline_pk_col:
            pk_cols_for_type_check.extend([c for c in columns if c["name"] == inline_pk_col])
        if primary_keys:
            for pkc in primary_keys:
                pk_cols_for_type_check.extend([c for c in columns if c["name"].lower() == pkc.lower()])
        for c in pk_cols_for_type_check:
            t = c.get("type", "").lower()
            if "bigint" not in t:
                self.add(Finding(
                    "1.1.10", LEVEL_MUST, "主键必须为 bigint",
                    f"主键列 `{c['name']}` 类型为 `{c.get('type', '')}`，应为 bigint（推荐 unsigned）。",
                    file, line, _short(s)))
            elif not c.get("unsigned"):
                self.add(Finding(
                    "1.1.10", LEVEL_RECOMMEND, "主键建议 bigint unsigned",
                    f"主键列 `{c['name']}` 建议加 unsigned。",
                    file, line, _short(s)))

        # 1.1.11 索引列 NOT NULL
        all_index_cols: list[str] = []
        all_index_cols.extend(primary_keys)
        if has_inline_pk and inline_pk_col:
            all_index_cols.append(inline_pk_col)
        for _, cols in unique_keys:
            all_index_cols.extend(cols)
        for _, cols in normal_keys:
            all_index_cols.extend(cols)
        col_by_name = {c["name"].lower(): c for c in columns}
        seen_idx_col = set()
        for raw_idx_col in all_index_cols:
            ic = raw_idx_col.lower()
            if ic in seen_idx_col:
                continue
            seen_idx_col.add(ic)
            c = col_by_name.get(ic)
            if c and not c.get("not_null"):
                self.add(Finding(
                    "1.1.11", LEVEL_MUST, "索引列必须 NOT NULL",
                    f"索引列 `{c['name']}` 没有 NOT NULL 约束。",
                    file, line, _short(s)))

        # 1.2.2 索引命名
        if has_inline_pk:
            pass  # 内联主键不需命名
        for name, cols in unique_keys:
            if name and not name.startswith("uk_"):
                self.add(Finding(
                    "1.2.2", LEVEL_RECOMMEND, "唯一索引命名应以 uk_ 开头",
                    f"索引 `{name}` 建议改为 `uk_<字段名>`。",
                    file, line, _short(s)))
        for name, cols in normal_keys:
            if name and not name.startswith("idx_"):
                self.add(Finding(
                    "1.2.2", LEVEL_RECOMMEND, "普通索引命名应以 idx_ 开头",
                    f"索引 `{name}` 建议改为 `idx_<字段名>`。",
                    file, line, _short(s)))

        # 1.3.5 varchar 索引必须指定前缀长度
        for kind, idx_list in (("UNIQUE", unique_keys), ("INDEX", normal_keys)):
            for name, cols in idx_list:
                for raw_col in cols:
                    base, prefix_len = _parse_idx_col(raw_col)
                    c = col_by_name.get(base.lower())
                    if c and c.get("type", "").lower().startswith("varchar") and prefix_len is None:
                        self.add(Finding(
                            "1.3.5", LEVEL_RECOMMEND, "varchar 索引未指定前缀长度",
                            f"{kind} `{name or '(匿名)'}` 中 varchar 列 `{base}` 未指定索引前缀长度。",
                            file, line, _short(s)))

        # 列级检查
        col_names_lower = [c["name"].lower() for c in columns]
        time_cols: list[dict] = []
        for c in columns:
            cname = c["name"]
            ctype_full = c.get("type", "")
            ctype = ctype_full.lower()
            # 1.1.1 字段名保留字
            self._check_reserved_identifier(cname, "字段名", file, line, s)
            # 1.2.1 命名
            self._check_lower_snake(cname, "字段名", file, line, s)
            # 1.2.4 长度
            if len(cname) > 32:
                self.add(Finding(
                    "1.2.4", LEVEL_RECOMMEND, "字段名长度过长",
                    f"字段 `{cname}` 长度 {len(cname)} > 32 字符。",
                    file, line, _short(s)))
            # 1.1.7 禁止 float / double
            if re.match(r"\b(float|double|real)\b", ctype):
                self.add(Finding(
                    "1.1.7", LEVEL_MUST, "禁止 float / double",
                    f"字段 `{cname}` 使用了 `{ctype_full}`，小数请使用 decimal。",
                    file, line, _short(s)))
            # 1.1.15 禁止 enum
            if ctype.startswith("enum"):
                self.add(Finding(
                    "1.1.15", LEVEL_MUST, "禁止 ENUM",
                    f"字段 `{cname}` 使用了 ENUM 类型，建议改为 tinyint/smallint/char。",
                    file, line, _short(s)))
            # 1.3.3 不建议 TEXT/BLOB
            if re.match(r"\b(tinytext|text|mediumtext|longtext|tinyblob|blob|mediumblob|longblob)\b", ctype):
                self.add(Finding(
                    "1.3.3", LEVEL_RECOMMEND, "不建议使用 TEXT/BLOB",
                    f"字段 `{cname}` 类型 `{ctype_full}`，建议拆到独立表用主键关联。",
                    file, line, _short(s)))
            # 1.1.20 字段必须有 COMMENT
            if not c.get("comment"):
                self.add(Finding(
                    "1.1.20", LEVEL_MUST, "字段必须带 COMMENT",
                    f"字段 `{cname}` 缺少 COMMENT 注释。",
                    file, line, _short(s)))
            # 1.1.13 NOT NULL 推荐带 DEFAULT
            if c.get("not_null") and not c.get("has_default") \
                    and not c.get("auto_increment") \
                    and not re.match(r"\b(text|blob|mediumtext|longtext|tinytext|mediumblob|longblob|tinyblob|json)\b", ctype):
                self.add(Finding(
                    "1.1.13", LEVEL_RECOMMEND, "NOT NULL 列建议带默认值",
                    f"字段 `{cname}` 是 NOT NULL，建议添加 DEFAULT。",
                    file, line, _short(s)))
            # 1.1.14 timestamp/datetime 建议有默认值
            if re.match(r"\b(timestamp|datetime)\b", ctype) and not c.get("has_default"):
                self.add(Finding(
                    "1.1.14", LEVEL_RECOMMEND, "时间类型列建议有默认值",
                    f"字段 `{cname}` 类型 `{ctype_full}` 建议添加 DEFAULT。",
                    file, line, _short(s)))
                time_cols.append(c)
            # 1.2.5 时间字段命名后缀
            if re.match(r"\b(timestamp|datetime)\b", ctype):
                if not (cname.endswith("_at") or cname.endswith("_time")):
                    self.add(Finding(
                        "1.2.5", LEVEL_RECOMMEND, "时间戳字段命名建议以 _at 结尾",
                        f"字段 `{cname}` 是时间戳/时间类型，建议命名以 `_at` 结尾。",
                        file, line, _short(s)))
            if re.match(r"\bdate\b", ctype):
                if not cname.endswith("_date"):
                    self.add(Finding(
                        "1.2.5", LEVEL_RECOMMEND, "日期字段命名建议以 _date 结尾",
                        f"字段 `{cname}` 类型 date，建议命名以 `_date` 结尾。",
                        file, line, _short(s)))

        # 1.1.18 表字段数 < 99
        if len(columns) >= 99:
            self.add(Finding(
                "1.1.18", LEVEL_RECOMMEND, "表字段数过多",
                f"表 `{tbl}` 字段数 {len(columns)} >= 99，建议拆表。",
                file, line, _short(s)))

        # 1.1.19 必备字段 id / create_at / update_at
        for required in ("id", "create_at", "update_at"):
            if required not in col_names_lower:
                self.add(Finding(
                    "1.1.19", LEVEL_RECOMMEND, "缺失必备字段",
                    f"表 `{tbl}` 缺少必备字段 `{required}`。",
                    file, line, _short(s)))

        # 表级 ENGINE / CHARSET / COLLATE / COMMENT 检查
        tail_upper = tail.upper()
        # 1.1.2 InnoDB
        m_eng = re.search(r"ENGINE\s*=\s*(\w+)", tail, re.IGNORECASE)
        if m_eng:
            eng = m_eng.group(1).lower()
            if eng != "innodb":
                self.add(Finding(
                    "1.1.2", LEVEL_RECOMMEND, "存储引擎建议 InnoDB",
                    f"表 `{tbl}` ENGINE=`{eng}`，默认建议 InnoDB；有事务必须 InnoDB。",
                    file, line, _short(s)))
        # 1.1.4 字符集推荐 utf8mb4
        m_cs = re.search(r"(?:DEFAULT\s+)?(?:CHARACTER\s+SET|CHARSET)\s*=?\s*([\w]+)", tail, re.IGNORECASE)
        if m_cs:
            cs = m_cs.group(1).lower()
            if cs not in ("utf8mb4", "utf8", "utf8mb3"):
                self.add(Finding(
                    "1.1.4", LEVEL_RECOMMEND, "字符集建议 utf8mb4",
                    f"表 `{tbl}` 字符集 `{cs}`，建议 utf8mb4（必要时 utf8）。",
                    file, line, _short(s)))
        # 1.1.6 COLLATE 不要 _bin
        m_co = re.search(r"COLLATE\s*=?\s*([\w]+)", tail, re.IGNORECASE)
        if m_co and m_co.group(1).lower().endswith("_bin"):
            self.add(Finding(
                "1.1.6", LEVEL_RECOMMEND, "字符序避免 *_bin",
                f"表 `{tbl}` COLLATE=`{m_co.group(1)}`，大小写敏感排序规则不推荐。",
                file, line, _short(s)))
        # 1.1.20 表必须有 COMMENT
        if "COMMENT" not in tail_upper:
            self.add(Finding(
                "1.1.20", LEVEL_MUST, "表必须带 COMMENT",
                f"表 `{tbl}` 缺少表级 COMMENT 注释。",
                file, line, _short(s)))

    # === DDL: ALTER TABLE ===
    def _check_alter_table(self, s: str, file: str, line: int):
        upper = s.upper()
        # 2.4 禁止删列
        if re.search(r"\bDROP\s+COLUMN\b", upper):
            self.add(Finding(
                "2.4", LEVEL_MUST, "禁止删除列",
                "ALTER TABLE ... DROP COLUMN 不被允许。",
                file, line, _short(s)))

    # === DML ===
    def _check_insert(self, s: str, file: str, line: int):
        # 2.5 INSERT 必须显式字段名
        m = re.search(
            r"\b(?:INSERT|REPLACE)\s+(?:IGNORE\s+|LOW_PRIORITY\s+|DELAYED\s+|HIGH_PRIORITY\s+)?INTO\s+[`\"]?\w+[`\"]?\s*([^V])",
            s, re.IGNORECASE)
        # 简单的判定方法：查找 INTO <table> 后紧跟 VALUES 或 SELECT，而没有括号字段列表
        m2 = re.search(
            r"\bINTO\s+[`\"]?\w+[`\"]?\s*(\([^)]*\))?\s*(VALUES|SELECT|SET|VALUE)",
            s, re.IGNORECASE)
        if m2 and m2.group(1) is None and m2.group(2).upper() in ("VALUES", "VALUE", "SELECT"):
            self.add(Finding(
                "2.5", LEVEL_MUST, "INSERT 必须显式列出字段名",
                "INSERT/REPLACE 语句必须在表名后显式列出字段名。",
                file, line, _short(s)))

    def _check_update_delete(self, s: str, file: str, line: int, kind: str):
        # 2.6 UPDATE/DELETE 必须 WHERE
        upper = s.upper()
        # DELETE FROM tbl 且无 WHERE
        if not re.search(r"\bWHERE\b", upper):
            self.add(Finding(
                "2.6", LEVEL_MUST, f"{kind} 必须带 WHERE",
                f"{kind} 语句必须带 WHERE 条件，避免误操作与全表扫描。",
                file, line, _short(s)))

    def _check_select(self, s: str, file: str, line: int):
        upper = s.upper()
        # 2.6 SELECT 不带 WHERE 也告警（推荐级，避免误伤聚合查询？这里按 MUST 维持原文）
        # 文档原话："禁止 select 不带 where" → MUST
        # 但 SELECT 1 / SELECT NOW() / SELECT FROM DUAL 这类不需要 WHERE，做精细化判断
        if re.search(r"\bFROM\b", upper) and not re.search(r"\bWHERE\b", upper):
            # 排除 INFORMATION_SCHEMA / DUAL / system tables
            if not re.search(r"\bFROM\s+(DUAL|INFORMATION_SCHEMA\b|MYSQL\.\w+)", upper):
                self.add(Finding(
                    "2.6", LEVEL_MUST, "SELECT 不带 WHERE",
                    "SELECT 语句没有 WHERE 条件，可能导致全表扫描，请补全条件或用 LIMIT 控制。",
                    file, line, _short(s)))

        # 2.8 SELECT *
        if re.search(r"SELECT\s+\*", upper) and not re.search(r"COUNT\s*\(\s*\*\s*\)", upper) \
                and not re.search(r"EXISTS\s*\(\s*SELECT\s+\*", upper):
            # 避免误报子查询里 EXISTS(SELECT * ...)，但 EXISTS 内部 SELECT * 是惯用法，跳过
            self.add(Finding(
                "2.8", LEVEL_RECOMMEND, "避免 SELECT *",
                "建议明确指定 SELECT 字段，避免 SELECT *。",
                file, line, _short(s)))

        # 2.16 count(列名)/count(1) 提示
        for m in re.finditer(r"\bCOUNT\s*\(\s*([^)]*?)\s*\)", upper):
            arg = m.group(1).strip()
            if arg in ("*",):
                continue
            if arg in ("1",) or re.match(r"^[`\"\w.]+$", arg):
                self.add(Finding(
                    "2.16", LEVEL_RECOMMEND, "建议使用 count(*)",
                    f"COUNT({arg}) 建议改为 COUNT(*)（标准统计行数语法）。",
                    file, line, _short(s)))
                break

    # === DML 通用检查 ===
    def _check_dml_common(self, s: str, file: str, line: int):
        upper = s.upper()

        # 2.10 三表以上 JOIN
        join_count = len(re.findall(r"\b(?:INNER|LEFT|RIGHT|CROSS|FULL|OUTER)?\s*JOIN\b", upper))
        if join_count >= 3:  # 主表 + 3 个 JOIN = 4 张表 > 3，触发；按文档"超过三个表禁止 join"
            tables = 1 + join_count
            if tables > 3:
                self.add(Finding(
                    "2.10", LEVEL_MUST, "JOIN 表数量超过 3",
                    f"该语句涉及 {tables} 张表的 JOIN，超过 3 张表禁止 JOIN。",
                    file, line, _short(s)))

        # 2.13 全/左模糊
        for m in re.finditer(r"\bLIKE\s+(['\"])(%[^'\"]*)\1", s, re.IGNORECASE):
            pattern = m.group(2)
            self.add(Finding(
                "2.13", LEVEL_RECOMMEND, "避免左模糊/全模糊",
                f"LIKE `{pattern}` 以 `%` 开头会导致索引失效。",
                file, line, _short(s)))

        # 2.14 IN(...) 元素 > 200
        for m in re.finditer(r"\bIN\s*\(([^()]*)\)", s, re.IGNORECASE):
            inside = m.group(1)
            # 排除子查询 IN (SELECT ...)
            if re.match(r"\s*SELECT\b", inside, re.IGNORECASE):
                continue
            # 粗略数元素
            n_items = len([x for x in inside.split(",") if x.strip()])
            if n_items > 200:
                self.add(Finding(
                    "2.14", LEVEL_RECOMMEND, "IN 列表过长",
                    f"IN(...) 中元素 {n_items} 个，建议控制在 200 以内。",
                    file, line, _short(s)))

        # 2.18 ORDER BY RAND()
        if re.search(r"ORDER\s+BY\s+RAND\s*\(", upper):
            self.add(Finding(
                "2.18", LEVEL_RECOMMEND, "禁止 ORDER BY RAND()",
                "ORDER BY RAND() 性能很差，建议改用其他随机方案。",
                file, line, _short(s)))

        # 2.9 索引列函数表达式（粗判）：WHERE 中 col 包在函数里
        # 形如 WHERE DATE(col) = ... / UPPER(col) = ...
        m_where = re.search(r"\bWHERE\b(.+?)(?:\bGROUP\s+BY\b|\bORDER\s+BY\b|\bLIMIT\b|$)", upper, re.DOTALL)
        if m_where:
            wclause = m_where.group(1)
            for fn in ("DATE", "UPPER", "LOWER", "SUBSTRING", "LEFT", "RIGHT", "TRIM", "CONCAT", "IFNULL", "DATE_FORMAT", "FROM_UNIXTIME", "UNIX_TIMESTAMP"):
                if re.search(rf"\b{fn}\s*\(\s*[`\"]?\w+[`\"]?\s*[,\)]", wclause):
                    self.add(Finding(
                        "2.9", LEVEL_RECOMMEND, "WHERE 中索引列嵌套函数",
                        f"WHERE 子句中疑似对列使用了 `{fn}(...)`，可能导致索引失效。",
                        file, line, _short(s)))
                    break

        # 2.15 = NULL / <> NULL / != NULL
        if re.search(r"(?:=|<>|!=)\s*NULL\b", upper):
            self.add(Finding(
                "2.15", LEVEL_RECOMMEND, "NULL 比较应使用 IS NULL / ISNULL()",
                "= NULL / <> NULL / != NULL 永远返回 NULL，请使用 IS NULL / IS NOT NULL / ISNULL()。",
                file, line, _short(s)))

    # === 工具：保留字 / 命名 ===
    def _check_reserved_identifier(self, ident: str, kind: str, file: str, line: int, s: str):
        if ident.lower() in RESERVED_WORDS:
            self.add(Finding(
                "1.1.1", LEVEL_MUST, f"{kind}使用了保留字",
                f"{kind} `{ident}` 是 MySQL 保留字，必须改名。",
                file, line, _short(s)))

    def _check_lower_snake(self, ident: str, kind: str, file: str, line: int, s: str):
        # 1.2.1 小写字母+数字+下划线；不以数字开头；不以下划线结尾；两个下划线之间不能仅是数字
        if not re.match(r"^[a-z][a-z0-9_]*$", ident):
            self.add(Finding(
                "1.2.1", LEVEL_MUST, f"{kind}命名不规范",
                f"{kind} `{ident}` 必须使用小写字母+数字+下划线，不能数字开头，不能含大写。",
                file, line, _short(s)))
            return
        if ident.endswith("_"):
            self.add(Finding(
                "1.2.1", LEVEL_MUST, f"{kind}不能以下划线结尾",
                f"{kind} `{ident}` 不能以下划线结尾。",
                file, line, _short(s)))
        if re.search(r"_\d+_", ident):
            self.add(Finding(
                "1.2.1", LEVEL_MUST, f"{kind}两个下划线之间不能仅为数字",
                f"{kind} `{ident}` 中存在 `_<数字>_` 模式，不允许。",
                file, line, _short(s)))


# -------------------- 解析辅助 --------------------

def _split_idx_cols(s: str) -> list[str]:
    parts = []
    for raw in s.split(","):
        x = raw.strip().strip("`\"")
        if x:
            parts.append(x)
    return parts


def _parse_idx_col(raw: str) -> tuple[str, int | None]:
    """解析索引列 `col(20)` → ("col", 20)。"""
    raw = raw.strip().strip("`\"")
    m = re.match(r"^([^\s(]+)(?:\((\d+)\))?", raw)
    if not m:
        return raw, None
    return m.group(1), (int(m.group(2)) if m.group(2) else None)


def _parse_column(item: str) -> dict | None:
    """把一个列定义字符串解析为 dict。"""
    m = re.match(r"^[`\"]?(\w+)[`\"]?\s+([A-Za-z]+)\s*(\([^)]*\))?\s*(.*)$", item.strip(), re.DOTALL)
    if not m:
        return None
    name = m.group(1)
    type_name = m.group(2)
    type_args = m.group(3) or ""
    rest = m.group(4) or ""
    rest_upper = rest.upper()
    full_type = (type_name + type_args).lower()
    not_null = "NOT NULL" in rest_upper
    nullable_explicit = "NULL" in rest_upper and "NOT NULL" not in rest_upper
    has_default = re.search(r"\bDEFAULT\b", rest_upper) is not None
    auto_inc = "AUTO_INCREMENT" in rest_upper
    unsigned = "UNSIGNED" in rest_upper
    inline_primary = "PRIMARY KEY" in rest_upper
    comment_match = re.search(r"COMMENT\s+'((?:[^'\\]|\\.|'')*)'", rest, re.IGNORECASE)
    comment = comment_match.group(1) if comment_match else ""
    return {
        "name": name,
        "type": full_type,
        "type_name": type_name.lower(),
        "not_null": not_null,
        "nullable": nullable_explicit,
        "has_default": has_default,
        "auto_increment": auto_inc,
        "unsigned": unsigned,
        "inline_primary": inline_primary,
        "comment": comment,
    }


def _short(s: str, n: int = 200) -> str:
    s = " ".join(s.split())
    return s if len(s) <= n else s[:n] + "..."


# -------------------- 文件读取 --------------------

def iter_files(paths: list[str]) -> Iterable[Path]:
    for p in paths:
        path = Path(p)
        if path.is_file():
            yield path
        elif path.is_dir():
            for ext in [".sql"] + list(SOURCE_EXTS):
                for f in path.rglob(f"*{ext}"):
                    if any(part in {".git", "node_modules", "vendor", "build", "dist", ".venv", "__pycache__"} for part in f.parts):
                        continue
                    yield f


def read_text(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return p.read_text(encoding="latin-1", errors="replace")


def file_to_blocks(p: Path) -> list[SqlBlock]:
    text = read_text(p)
    if p.suffix.lower() == ".sql":
        return [SqlBlock(text, str(p), 1)]
    if p.suffix.lower() in SOURCE_EXTS:
        return extract_sql_blocks_from_source(text, str(p))
    return []


# -------------------- 报告输出 --------------------

def render_markdown(findings: list[Finding], scanned_files: list[str], strict: bool) -> str:
    must = [f for f in findings if f.level == LEVEL_MUST]
    rec = [f for f in findings if f.level == LEVEL_RECOMMEND]
    lines = []
    lines.append("# DB 规范检查报告（qiq-audit-sql）")
    lines.append("")
    lines.append(f"- 扫描文件数：**{len(scanned_files)}**")
    lines.append(f"- 必须级违规：**{len(must)}**")
    lines.append(f"- 推荐级违规：**{len(rec)}**")
    lines.append(f"- 严格模式：**{'是' if strict else '否'}**")
    lines.append("")
    if not findings:
        lines.append("> ✅ 未发现违规，恭喜通过检查。")
        return "\n".join(lines)

    by_file: dict[str, list[Finding]] = {}
    for f in findings:
        by_file.setdefault(f.file, []).append(f)

    lines.append("## 违规清单")
    lines.append("")
    for file, fs in by_file.items():
        lines.append(f"### `{file}`")
        lines.append("")
        lines.append("| 等级 | 规则 | 行号 | 标题 | 说明 |")
        lines.append("|---|---|---|---|---|")
        # 排序：MUST 优先，再按规则编号
        fs_sorted = sorted(fs, key=lambda x: (0 if x.level == LEVEL_MUST else 1, x.rule_id, x.line))
        for f in fs_sorted:
            level_label = "🛑 必须" if f.level == LEVEL_MUST else "⚠️ 推荐"
            msg = f.message.replace("|", "\\|").replace("\n", " ")
            title = f.title.replace("|", "\\|")
            lines.append(f"| {level_label} | {f.rule_id} | {f.line} | {title} | {msg} |")
        lines.append("")
        # snippet 摘要
        snippets = [f for f in fs_sorted if f.snippet]
        if snippets:
            lines.append("<details><summary>语句片段</summary>")
            lines.append("")
            seen = set()
            for f in snippets:
                key = (f.line, f.snippet)
                if key in seen:
                    continue
                seen.add(key)
                lines.append(f"- L{f.line} (规则 {f.rule_id}): `{f.snippet}`")
            lines.append("")
            lines.append("</details>")
            lines.append("")

    lines.append("## 修复建议")
    lines.append("")
    lines.append("- 🛑 **必须**类违规阻断合流，请优先修复。")
    lines.append("- ⚠️ **推荐**类违规请评估后修复；如确有合理理由保留，请在合流说明中注明。")
    lines.append("- 完整规范见 `references/full-spec.md`，机读 checklist 见 `references/checklist.md`。")
    return "\n".join(lines)


def render_json(findings: list[Finding], scanned_files: list[str], strict: bool) -> str:
    return json.dumps({
        "summary": {
            "scanned_files": len(scanned_files),
            "must": sum(1 for f in findings if f.level == LEVEL_MUST),
            "recommend": sum(1 for f in findings if f.level == LEVEL_RECOMMEND),
            "strict": strict,
        },
        "findings": [f.to_dict() for f in findings],
    }, ensure_ascii=False, indent=2)


# -------------------- main --------------------

def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="DB 规范自动检查")
    parser.add_argument("paths", nargs="+", help="要检查的文件或目录")
    parser.add_argument("--strict", action="store_true", help="严格模式：推荐级违规也阻断退出码")
    parser.add_argument("--format", choices=["md", "json"], default="md", help="报告格式")
    parser.add_argument("-o", "--output", help="输出文件路径（默认 stdout）")
    args = parser.parse_args(argv)

    files = list(iter_files(args.paths))
    if not files:
        print("未找到任何 .sql 或源代码文件。", file=sys.stderr)
        return 2

    auditor = Auditor()
    scanned: list[str] = []
    for p in files:
        scanned.append(str(p))
        for block in file_to_blocks(p):
            auditor.audit_block(block)

    if args.format == "md":
        report = render_markdown(auditor.findings, scanned, args.strict)
    else:
        report = render_json(auditor.findings, scanned, args.strict)

    if args.output:
        Path(args.output).write_text(report, encoding="utf-8")
    else:
        print(report)

    has_must = any(f.level == LEVEL_MUST for f in auditor.findings)
    has_any = bool(auditor.findings)
    if has_must:
        return 1
    if args.strict and has_any:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
