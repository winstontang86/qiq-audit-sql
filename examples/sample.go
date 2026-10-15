package repo

import (
	"database/sql"
	"fmt"
)

// 故意写得不规范的 Go 代码：嵌入的 SQL 字符串会被检测出来

func badQueries(db *sql.DB) {
	// 缺 WHERE
	_, _ = db.Exec("DELETE FROM orders")

	// SELECT * + 全模糊
	_, _ = db.Query(`SELECT * FROM users WHERE name LIKE '%abc%'`)

	// 三表以上 JOIN（4 张表）
	_, _ = db.Query(`
        SELECT u.id, o.id, p.id, c.id
        FROM users u
        JOIN orders o ON o.uid = u.id
        JOIN products p ON p.oid = o.id
        JOIN categories c ON c.pid = p.id
        WHERE u.id = ?
    `)

	// INSERT 缺字段名
	_, _ = db.Exec("INSERT INTO orders VALUES (1, 2, 3)")

	// 真正的存储过程调用（含参数括号）仍需命中规则 2.11
	_, _ = db.Exec("CALL archive_orders(?)")
}

func goodQueries(db *sql.DB) {
	_, _ = db.Query("SELECT id, name FROM users WHERE id = ? LIMIT 1")
}

// 以下字符串里的 call 只是英文单词，不是存储过程调用，不应命中规则 2.11（回归用例）。
func errorMessages(err error) error {
	return fmt.Errorf("call buddyone token: %w", err)
}
