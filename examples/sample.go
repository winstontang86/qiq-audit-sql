package repo

import "database/sql"

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
}

func goodQueries(db *sql.DB) {
	_, _ = db.Query("SELECT id, name FROM users WHERE id = ? LIMIT 1")
}
