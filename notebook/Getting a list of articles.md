
Before scraping anything we need to know what to scrape.

## Manual inspect element method

I found that an easy way to do this was by pulling the URLs directly from the [[Wayback Machine]]’s site maps. For any given host it has archives for, the Wayback Machine provides a site map, which charts all the archived webpages for that host by year.

![[sitemap_gagauznews_1600x1200@2x.png|The 2024 sitemap for https://gagauznews.com/. https://web.archive.org/web/sitemap/https://gagauznews.com/]]

Simply by using inspect element in **Developer Tools**, it’s possible to copy the `svg` element that creates the chart. From there its only a matter of using a regular expression to match the `href` URLs.

![[Screenshot 2025-03-18_150303@2x.png]]

## Using the Wayback Machine API

- [[article_urls.py]]
- [Wayback CDX server API docs](https://archive.org/developers/wayback-cdx-server.html).

### Usage

```shell
python article_urls.py [options] hosts
```

e.g.

```shell
python article_urls.py gagauznews.com,gagauzinfo.md,jurnaltv.md,md.kp.media,nokta.md,evedomosti.md
```

### Options

The options are as follows:

| Flag                  | Description                                                                                                                                                                                                                                                               |
| --------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `-y, --year YYYY`     | Year to fetch in YYYY format, e.g. 2024 (default). Will set from and to parameters in the CDX request to {year}0101 and {year}1231 respectively.                                                                                                                          |
| `-p, --path PATH`     | Absolute path for the outputted file. By default, it outputs to the root directory in [articles.csv](vscode-file://vscode-app/c:/Users/gavri/AppData/Local/Programs/Microsoft%20VS%20Code%20Insiders/resources/app/out/vs/code/electron-sandbox/workbench/workbench.html) |
| `-o, --output NAME`   | Specify a different output file name. By default, this is articles.csv                                                                                                                                                                                                    |
| `-l, --limit VALUE`   | Maximum number of results per host, e.g. 10000 (default)                                                                                                                                                                                                                  |
| `-r, --retries VALUE` | Number of retry attempts for API requests, e.g. 5 (default)                                                                                                                                                                                                               |
| `--timeout VALUE`     | Timeout for API requests in seconds, e.g. 60 (default)                                                                                                                                                                                                                    |
| `--no-filter`         | Disables URL filtering.                                                                                                                                                                                                                                                   |
| `--overwrite`         | Overwrites the existing CSV file when outputting. By default, the script only adds any new URLs as rows if the file already exists.                                                                                                                                       |

### Filtering URLs

- If URL doesn’t end with a slash (`/`), append one.
- Exclude URLs which don’t contain the relevant host. 
- Blacklist URLs containing certain segments.

```python
# Ensure URLs end with a slash for consistency when checking patterns
check_url = url
if not check_url.endswith('/'):
	check_url += '/'
            
# Include only URLs that contain the host
if host not in url:
	excluded_count += 1
	continue
            
# Exclude blacklisted segments
blacklisted = False
blacklist_segments = [
	'/tag/', '/author/', '/category/', '/podcast/', 
	'/program-category/', '/project/', '/daily/', '/all-news/'
]
```

#### Host-specific filters

| Host(s)          | Rule                                                                                                                                                           |
| ---------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `gagauznews.com` | Include only URLs which end in `.html/`                                                                                                                        |
| `jurnaltv.md`    | Include only URLs which contain `/news/`                                                                                                                       |
| `jurnaltv.md`    | Exclude URLs which end in `/ro/news/YYYY/`, `/ro/news/<YYYY>/<MM>/`, or `/ro/news/<YYYY>/<MM>/<DD>/` (where YYYY, MM, and DD of course represent date digits). |
| `jurnaltv.md`    | Exclude URLs whose path begins `jurnalul-`  or `popcorn-show-`                                                                                                 |
| `nokta.md`       | Exclude URLs which contain `/page/`.                                                                                                                           |
| `nokta.md`       | Exclude URLs which contain `/cdn-cgi/`                                                                                                                         |
| `md.kp.media`    | Include only URLs which contain `/online/news/` or end in `/daily/<any digits/<anydigits>/`                                                                    |
| `evedomosti.md`  | Include only URLs which contain `/news/`                                                                                                                       |
| `gagauzinfo.md`  | Include only URLs which contain `/news/` and at least one hyphen (`-`)                                                                                         |

## Appendix

### filter_urls(urls, archive_urls, host, no_filter=False)

The entire filter function

```python
def filter_urls(urls, archive_urls, host, no_filter=False):
    """Filter URLs based on the defined rules."""
    if no_filter:
        print("Skipping URL filtering as requested.")
        return urls, archive_urls
    
    filtered_urls = []
    filtered_archive_urls = []
    excluded_count = 0
    
    # Process URLs
    for i, url in enumerate(urls):
        try:
            # Ensure URLs end with a slash for consistency when checking patterns
            check_url = url
            if not check_url.endswith('/'):
                check_url += '/'
            
            # General filters - include only URLs that contain the host
            if host not in url:
                excluded_count += 1
                continue
            
            # Exclude blacklisted segments
            blacklisted = False
            blacklist_segments = [
                '/tag/', '/author/', '/category/', '/podcast/', 
                '/program-category/', '/project/', '/daily/', '/all-news/'
            ]
            
            for segment in blacklist_segments:
                if segment in check_url:
                    blacklisted = True
                    break
            
            if blacklisted:
                excluded_count += 1
                continue
            
            # Host-specific filters
            pass_host_filters = True
            
            # Filter for gagauznews.com
            if 'gagauznews.com' in host and not check_url.endswith('.html/'):
                pass_host_filters = False
                
            # Filters for jurnaltv.md
            elif 'jurnaltv.md' in host:
                if '/news/' not in check_url:
                    pass_host_filters = False
                elif re.search(r'/ro/news/\d{4}/$', check_url) or \
                     re.search(r'/ro/news/\d{4}/\d{2}/$', check_url) or \
                     re.search(r'/ro/news/\d{4}/\d{2}/\d{2}/$', check_url):
                    pass_host_filters = False
                    
            # Filters for nokta.md
            elif 'nokta.md' in host:
                if '/page/' in check_url or '/cdn-cgi/' in check_url:
                    pass_host_filters = False
                    
            # Filters for md.kp.media
            elif 'md.kp.media' in host:
                if '/online/news/' not in check_url and not re.search(r'/daily/\d+/\d+/$', check_url):
                    pass_host_filters = False
                    
            # Filters for evedomosti.md
            elif 'evedomosti.md' in host:
                if '/news/' not in check_url:
                    pass_host_filters = False
                    
            # Filters for gagauzinfo.md
            elif 'gagauzinfo.md' in host:
                if '/news/' not in check_url or '-' not in check_url:
                    pass_host_filters = False
            
            if not pass_host_filters:
                excluded_count += 1
                continue
            
            filtered_urls.append(url)
            filtered_archive_urls.append(archive_urls[i])
        
        except Exception as e:
            print(f"Error filtering URL {url}: {e}")
            excluded_count += 1
            continue
    
    print(f"Excluded {excluded_count} URLs based on filtering rules.")
    return filtered_urls, filtered_archive_urls
```

