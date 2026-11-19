import { DatabaseSync } from "node:sqlite";
import { deserialize, serialize } from "node:v8";

// Journal fixture riêng. Dữ liệu có thể khôi phục chỉ gồm checkpoint/record đã ký.
export function authorityJournal(filename) {
  const db = new DatabaseSync(filename);
  db.exec(`PRAGMA synchronous=FULL;
    CREATE TABLE IF NOT EXISTS directory_head (sequence INTEGER PRIMARY KEY, snapshot BLOB NOT NULL);`);
  const head = db.prepare("SELECT snapshot FROM directory_head ORDER BY sequence DESC LIMIT 1");
  const links = db.prepare("SELECT snapshot FROM directory_head WHERE sequence>? AND sequence<? ORDER BY sequence");
  const append = db.prepare(`INSERT INTO directory_head
    SELECT ?,? WHERE (SELECT COALESCE(MAX(sequence),0)+1 FROM directory_head)=?`);
  return {
    head: () => {
      const row = head.get();
      return row && deserialize(Buffer.from(row.snapshot));
    },
    links: (after, before) => links.all(after, before).map(({ snapshot }) => deserialize(Buffer.from(snapshot)).checkpoint),
    append(snapshot) {
      const sequence = snapshot.checkpoint.sequence;
      if (append.run(sequence, serialize(snapshot), sequence).changes !== 1) throw new Error("Concurrent authority publication");
    },
    close: () => db.close(),
  };
}
