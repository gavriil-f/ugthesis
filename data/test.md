---
cssclasses:
  - table-max
---

```dataview
table without id
	("[[" + file.name + "|" + truncate(title, 48) + "]]") as Title,
	publication as Publication,
	("[[" + truncate(string(published), 10, "") + "]]") as Date
from "data/raw/articles"
limit 25
```
