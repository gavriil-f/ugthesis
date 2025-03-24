## Todo

- [] Double check if clean_text() is redundant
- [] Check whether clean_text(), format_text_improvements() and extract_content() can be combined into one. Seems kinda inefficient right now idk.
- [] Create config
- Check beautifulSoup capabilities. Maybe I'm doing too much on my own? e.g. converting `<strong>` elements. Look at markdownify (?)
- Double check the list building part, i.e. `elif p.name.startswith('h')`. What is this doing again.
- If keeping format_text_improvements() rename it to lint or something and add the ability to config individual linting processes/rules.
- Add a fallback to the current gagauznews description extraction? Right now its just using the first h3 it finds but this doesn't seem robust.
- Double check that the leading paragraph handling for gagauznewss doesn't apply to all h3s within the content, just the first h3 if it is the first paragraph within content.
- Maybe set publication names and languages per host as variables at the beginning / config—rather than in each indiviudal procesor—for configurability.
- I think the content fallback for evedomosti is exactly the same 
- I think im ensuring there are no line breaks twice in save_markdown. Check.
- Fix CSV data output - or use a separate script for this.
- Fix the fact that lists should have an empty line before and after

Move the evedomsti line breaker fixer into the dedicated evedemosti processor (currently in `save_markdown()`)

## Notes

Not sure if this is redundant as it is

```python
content_copy = BeautifulSoup(str(content_elem), 'html.parser')
```

### Config

#### Blacklisted selectors

```json
## decompose() from beautifulSoup is used to remove these elements from the content
unwanted_selectors = [
    'script', 'style', 'iframe', 'noscript',
    '.social-share', '.share-buttons', '.comments', '#comments', 
    '.related-posts', '.info-item', '.article-description',
    '.sharedaddy', '.jp-relatedposts'
]
```



