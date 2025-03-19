
Options

| Flag                | Description                                                      |
| ------------------- | ---------------------------------------------------------------- |
| `-i, --input PATH`  | Input CSV file path (default: data/articles.csv)                 |
| `-o, --output PATH` | Output directory for markdown files (default: data/raw/articles) |
| `--timeout`         | Request timeout in seconds (default: 15)                         |
| `--retries INTEGER` | Maximum number of retries for failed requests (default: 3)       |
| `--delay VALUE`     | Delay between requests in seconds (default: 5)                   |
| `--force`           | Force re-scraping of articles even if they already exist         |
| `--limit INTEGER`   | Limit the number of articles to scrape                           |
| `--host HOST`       | Limit scraping to a specific host                                |


## Scraping filters and rules

Globally,

1. For all outputted articles value of
	1. site = clean host
	2. archive = web archive url  (archiv)
	3. url = original url
2. Remove from content `['script', 'style', 'iframe', 'noscript']`. Also blacklist `['.social-share', '.share-buttons', '.comments', '#comments', '.related-posts', '.info-item', '.article-description']`
3. Join each paragraph (in the content only) with a new line in between
4. Empty line between frontmatter and beginning of content
5. Append `"> "` at the start of blockquote paragraphs.
6. File name for markdown article = `host_last-segment-of-url`
7. Title, description, site, and urls should be enclosed in double apostrophes in the frontmatter
8. Remove any `h1` from content
9. Remove line breaks in title and description properties

### gagauznews.com

| Target      | Rule                                                                                                          |
| ----------- | ------------------------------------------------------------------------------------------------------------- |
| title       | title. Remove ‘`– Новости Гагаузии \| Gagauznews.com`’.                                                       |
| published   | published                                                                                                     |
| publication | `"[[Gagauznews]]"`                                                                                            |
| author      | author                                                                                                        |
| language    | `ru`                                                                                                          |
| section     | articleSection in schema                                                                                      |
| description | description                                                                                                   |
| keywords    | keywords in schema                                                                                            |
| content     | From `.single-body.entry-content`. (1) Remove any headings beginning with ‘Поделиться’ and any content below. |

### gagauzinfo.md

| Target      | Rule                                                                                                                                                  |
| ----------- | ----------------------------------------------------------------------------------------------------------------------------------------------------- |
| title       | title                                                                                                                                                 |
| published   | Take the first`.info-item.info-time`. This then needs to be converted from DD MMM YYYY, HH:mm (in Russian) to ISO. See below.                         |
| publication | `"[[Gagauzinfo]]"`                                                                                                                                    |
| author      | null                                                                                                                                                  |
| language    | `ru`                                                                                                                                                  |
| section     | Directory immediately following `/news/` in the URL, e.g. picks out ‘politics’ as the section in`http://gagauzinfo.md/news/politics/irina-vlah-o-...` |
| description | If there exists  `.content-news > .block-content > h3`, then the text of this. Otherwise null.                                                        |
| keywords    | null                                                                                                                                                  |
| content     | `.content-news`. Convert the h3 with class=”article-title” to a bolded paragraph.                                                                     |

```python
# Convert date in format "08 АВГ 2024" to YYYY-MM-DD
month_map = {
	'ЯНВ': '01', 'ЯНВА': '01', 'ЯНВАРЬ': '01', 'ЯНВАР': '01',
	'ФЕВ': '02', 'ФЕВР': '02', 'ФЕВРАЛЬ': '02',
	'МАР': '03', 'МАРТ': '03', 'МАРТА': '03',
	'АПР': '04', 'АПРЕ': '04', 'АПРЕЛЬ': '04',
	'МАЙ': '05', 'МАЯ': '05',
	'ИЮН': '06', 'ИЮНЬ': '06', 'ИЮНЯ': '06',
	'ИЮЛ': '07', 'ИЮЛЬ': '07', 'ИЮЛЯ': '07',
	'АВГ': '08', 'АВГУ': '08', 'АВГУСТ': '08',
	'СЕН': '09', 'СЕНТ': '09', 'СЕНТЯБРЬ': '09',
	'ОКТ': '10', 'ОКТЯ': '10', 'ОКТЯБРЬ': '10',
	'НОЯ': '11', 'НОЯБ': '11', 'НОЯБРЬ': '11',
	'ДЕК': '12', 'ДЕКА': '12', 'ДЕКАБРЬ': '12',
}
```

### jurnaltv.md

| Target      | Rule                                                                                                                                                                                                                                                                                          |
| ----------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| title       | title. Remove " \| JurnalTV.md" from the end of title                                                                                                                                                                                                                                         |
| published   | From first `.product-comment`. This then needs to be converted from DD MMMM YYYY, HH:mm (in Romanian) to ISO. See below.                                                                                                                                                                      |
| publication | `"[[Jurnal TV]]"`                                                                                                                                                                                                                                                                             |
| author      | `null`                                                                                                                                                                                                                                                                                        |
| language    | `ro`                                                                                                                                                                                                                                                                                          |
| section     | Find the first element which contains `href="/category/{str}"`. The string = the section.                                                                                                                                                                                                     |
| description | description                                                                                                                                                                                                                                                                                   |
| keywords    | null                                                                                                                                                                                                                                                                                          |
| content     | Only use the element with class .mb-3.pb-1.text-white (but not .lead) as the article content. Prepend to this the text of the element class="mb-3 pb-1 text-white lead" . This leading paragraph should also be bold.<br><br>If no content found using the above, fallback to `.article-body` |


```python
# Dictionary for Romanian month names to numbers
month_map = {
	'ianuarie': '01', 'februarie': '02', 
	'martie': '03', 'aprilie': '04',
	'mai': '05', 'iunie': '06', 
	'iulie': '07', 'august': '08',
	'septembrie': '09', 'octombrie': '10', 
	'noiembrie': '11', 'decembrie': '12'
}
```

### md.kp.media

| Target      | Rule                                                                                                                    |
| ----------- | ----------------------------------------------------------------------------------------------------------------------- |
| title       | title                                                                                                                   |
| published   | published                                                                                                               |
| publication | `"[[KP Media Moldova]]"`                                                                                                |
| author      | author (remove any ‘\|’ and trailing whitespaces). Convert to title case (ie upper case first letter, rest lower case). |
| language    | `ru`                                                                                                                    |
| section     | meta:property:article:section                                                                                           |
| description | description                                                                                                             |
| keywords    | schema keywords                                                                                                         |
| content     | `.content-body`                                                                                                         |

### nokta.md

| Target      | Rule                    |
| ----------- | ----------------------- |
| title       | title                   |
| published   | published               |
| publication | `"[[Nokta]]"`           |
| author      | author                  |
| language    | `ro`                    |
| section     | schema articleSection   |
| description | description             |
| keywords    | schema keywords         |
| content     | `.single-post__content` |

### evedomosti.md

| Target      | Rule                                                                                    |
| ----------- | --------------------------------------------------------------------------------------- |
| title       | title                                                                                   |
| published   | From`class="date float-left”`. Convert from `DD.MM.YYYY, HH:mm` to `YYYY-MM-DD[T]HH:mm` |
| publication | `"[[Moldavskie Vedomosti]]"`                                                            |
| author      | author                                                                                  |
| language    | `ru`                                                                                    |
| section     | Text of h1 element in a `.category-heading` element.                                    |
| description | description                                                                             |
| keywords    | null                                                                                    |
| content     | `.article-content`                                                                      |


