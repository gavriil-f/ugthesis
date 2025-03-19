#!/usr/bin/env python3

import os
import csv
import re
import json
import yaml
import requests
import logging
from datetime import datetime
from bs4 import BeautifulSoup
from urllib.parse import urlparse
import argparse
from pathlib import Path
import time
from slugify import slugify
import random
import shutil  # Add shutil for test directory operations

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Set up defaults
DEFAULT_OUTPUT_DIR = "data/raw/articles"
DEFAULT_CSV_PATH = "data/articles.csv"
DEFAULT_TIMEOUT = 15
DEFAULT_RETRIES = 3
DEFAULT_DELAY = 5  # Delay between requests in seconds

# Month maps for date conversion
RUSSIAN_MONTH_MAP = {
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

ROMANIAN_MONTH_MAP = {
    'ianuarie': '01', 'februarie': '02', 
    'martie': '03', 'aprilie': '04',
    'mai': '05', 'iunie': '06', 
    'iulie': '07', 'august': '08',
    'septembrie': '09', 'octombrie': '10', 
    'noiembrie': '11', 'decembrie': '12'
}

def setup_argparse():
    """Set up command line arguments."""
    parser = argparse.ArgumentParser(description="Scrape article content and metadata from Wayback Machine archives")
    parser.add_argument("-i", "--input", default=DEFAULT_CSV_PATH, help=f"Input CSV file path (default: {DEFAULT_CSV_PATH})")
    parser.add_argument("-o", "--output", default=DEFAULT_OUTPUT_DIR, help=f"Output directory for markdown files (default: {DEFAULT_OUTPUT_DIR})")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, help=f"Request timeout in seconds (default: {DEFAULT_TIMEOUT})")
    parser.add_argument("--retries", type=int, default=DEFAULT_RETRIES, help=f"Maximum number of retries for failed requests (default: {DEFAULT_RETRIES})")
    parser.add_argument("--delay", type=float, default=DEFAULT_DELAY, help=f"Delay between requests in seconds (default: {DEFAULT_DELAY})")
    parser.add_argument("--force", action="store_true", help="Force re-scraping of articles even if they already exist")
    parser.add_argument("--limit", type=int, help="Limit the number of articles to scrape")
    parser.add_argument("--host", help="Limit scraping to a specific host")
    parser.add_argument("--test", nargs='?', const=3, type=int, help="Run in test mode with N samples per host (default: 3)")
    return parser.parse_args()

def read_csv(csv_path):
    """Read the CSV file and return a list of dictionaries."""
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.reader(f)
        rows = list(reader)
    
    # Handle headers
    if not rows:
        return []
    
    # Check if CSV has headers
    if rows[0][0] == 'host' and rows[0][1] == 'archive' and rows[0][2] == 'url':
        headers = rows[0]
        data = rows[1:]
    else:
        # Use default headers if not present
        headers = ['host', 'archive', 'url']
        data = rows
    
    return [dict(zip(headers, row)) for row in data]

def write_csv(csv_path, articles):
    """Write the articles data back to the CSV file with any new columns."""
    if not articles:
        return
    
    # Get all unique keys as headers
    headers = set()
    for article in articles:
        headers.update(article.keys())
    
    # Make sure the original columns come first
    ordered_headers = ['host', 'archive', 'url']
    for header in headers:
        if header not in ordered_headers:
            ordered_headers.append(header)
    
    # Create directory if it doesn't exist
    os.makedirs(os.path.dirname(csv_path), exist_ok=True)
    
    with open(csv_path, 'w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=ordered_headers)
        writer.writeheader()
        writer.writerows(articles)

def get_html(url, timeout, max_retries, delay):
    """Fetch HTML content from URL with retry logic."""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    
    for attempt in range(max_retries):
        try:
            current_timeout = timeout * 2 if 'archive.org' in url else timeout
            logging.info(f"Fetching {url} (attempt {attempt+1}/{max_retries})")
            response = requests.get(url, headers=headers, timeout=current_timeout)
            
            if response.status_code == 200:
                return response.text
            else:
                logging.warning(f"Request failed with status code {response.status_code} for {url}")
        except requests.exceptions.Timeout:
            logging.warning(f"Timeout fetching {url}")
        except Exception as e:
            logging.error(f"Error fetching {url}: {e}")
        
        if attempt < max_retries - 1:
            sleep_time = delay * (2 ** attempt)  # Exponential backoff
            logging.info(f"Retrying in {sleep_time} seconds...")
            time.sleep(sleep_time)
    
    logging.error(f"Failed to fetch {url} after {max_retries} attempts")
    return None

def extract_schema_data(soup):
    """Extract JSON-LD schema data from the page."""
    schema_data = {}
    schema_scripts = soup.find_all('script', type='application/ld+json')
    
    for script in schema_scripts:
        if not script.string:
            continue
            
        try:
            data = json.loads(script.string)
            
            # Handle @graph structure
            if '@graph' in data:
                for item in data['@graph']:
                    if isinstance(item, dict) and item.get('@type') == 'Article':
                        schema_data = item
                        break
            # Handle direct Article type
            elif isinstance(data, dict) and data.get('@type') == 'Article':
                schema_data = data
        except json.JSONDecodeError:
            continue
            
    return schema_data

def extract_meta_tags(soup):
    """Extract metadata from meta tags."""
    meta_data = {}
    
    for meta in soup.find_all('meta'):
        # Get the meta key (name, property, or http-equiv)
        key = None
        for attr in ['name', 'property', 'http-equiv']:
            if meta.get(attr):
                key = f"{attr}:{meta.get(attr)}"
                break
                
        if key and meta.get('content'):
            meta_data[key] = meta.get('content')
            
    return meta_data

def clean_text(text):
    """Clean text by removing extra whitespace and normalizing."""
    if not text:
        return ""
    # Remove all line breaks and normalize multiple spaces into a single space
    return re.sub(r'\s+', ' ', text).strip()

def extract_content(soup, selector, clean_content=True):
    """Extract and clean content from the specified selector."""
    content_elem = soup.select_one(selector)
    if not content_elem:
        return ""
        
    # Create a copy to avoid modifying the original
    content_copy = BeautifulSoup(str(content_elem), 'html.parser')
    
    if clean_content:
        # Remove unwanted elements
        unwanted_selectors = [
            'script', 'style', 'iframe', 'noscript',
            '.social-share', '.share-buttons', '.comments', '#comments', 
            '.related-posts', '.info-item', '.article-description',
            '.sharedaddy', '.jp-relatedposts'
        ]
        
        for selector in unwanted_selectors:
            for elem in content_copy.select(selector):
                elem.decompose()
    
    # Format paragraphs
    paragraphs = []
    for p in content_copy.find_all(['p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'blockquote', 'ul', 'ol']):
        text = p.get_text(strip=True)
        if not text:
            continue
            
        if p.name == 'h1':
            # Skip h1 headers entirely as requested
            continue
        elif p.name.startswith('h'):
            level = int(p.name[1])
            paragraphs.append(f"{'#' * level} {text}")
        elif p.name == 'blockquote':
            paragraphs.append(f"> {text}")
        elif p.name in ['ul', 'ol']:
            for li in p.find_all('li'):
                li_text = li.get_text(strip=True)
                if li_text:
                    paragraphs.append(f"* {li_text}")
        else:
            paragraphs.append(text)
            
    return "\n\n".join(paragraphs)

def process_gagauznews(soup, article_data):
    """Process gagauznews.com articles."""
    # Get basic article data
    meta_data = extract_meta_tags(soup)
    schema_data = extract_schema_data(soup)
    
    # Extract title
    if soup.title:
        title = soup.title.get_text()
        # Remove "– Новости Гагаузии | Gagauznews.com"
        title = re.sub(r'\s*–\s*Новости Гагаузии\s*\|\s*Gagauznews\.com', '', title)
        article_data['title'] = clean_text(title)
    
    # Extract published date
    if 'property:article:published_time' in meta_data:
        article_data['published'] = meta_data['property:article:published_time']
    
    # Extract author
    if 'property:article:author' in meta_data:
        article_data['author'] = meta_data['property:article:author']
    else:
        author_elem = soup.select_one('.entry-author__name')
        if author_elem:
            article_data['author'] = clean_text(author_elem.get_text())
    
    # Extract section
    if schema_data and 'articleSection' in schema_data:
        article_data['section'] = schema_data['articleSection']
    
    # Extract description
    if 'name:description' in meta_data:
        article_data['description'] = meta_data['name:description']
    elif 'property:og:description' in meta_data:
        article_data['description'] = meta_data['property:og:description']
    
    # Extract keywords
    if schema_data and 'keywords' in schema_data:
        keywords = schema_data['keywords']
        if isinstance(keywords, str):
            article_data['keywords'] = [k.strip() for k in keywords.split(',')]
        else:
            article_data['keywords'] = keywords
    
    # Extract content
    content_elem = soup.select_one('.single-body.entry-content')
    if content_elem:
        # Process first paragraph with strong element
        first_p = content_elem.find('p')
        paragraphs = []
        
        # Check if first paragraph has a strong element
        if first_p and first_p.find('strong'):
            strong_elem = first_p.find('strong')
            strong_text = strong_elem.get_text().strip()
            
            if strong_text:
                # Add bolded text
                paragraphs.append(f"**{strong_text}** {first_p.get_text().replace(strong_text, '', 1).strip()}")
                
                # Remove first paragraph so it's not processed again
                first_p.decompose()
        
        # Continue with regular content extraction
        content_html = str(content_elem)
        content_soup = BeautifulSoup(content_html, 'html.parser')
        
        # Clean and format content
        formatted_content = extract_content(content_soup, 'body')
        
        # If we processed a first paragraph with strong, prepend it
        if paragraphs:
            formatted_content = paragraphs[0] + "\n\n" + formatted_content
        
        # Remove "Поделиться" and everything after it
        share_match = re.search(r'#+\s*Поделиться.*', formatted_content, re.DOTALL)
        if share_match:
            formatted_content = formatted_content[:share_match.start()].strip()
        
        article_data['content'] = formatted_content
    else:
        # Fallback to regular content extraction
        content = extract_content(soup, '.single-body.entry-content')
        
        # Remove "Поделиться" and everything after it
        share_match = re.search(r'#+\s*Поделиться.*', content, re.DOTALL)
        if share_match:
            content = content[:share_match.start()].strip()
        
        article_data['content'] = content
    
    # Set publication name
    article_data['publication'] = "Gagauznews"
    
    # Set language
    article_data['language'] = "ru"
    
    return article_data

def process_gagauzinfo(soup, article_data):
    """Process gagauzinfo.md articles."""
    # Get basic article data
    meta_data = extract_meta_tags(soup)
    
    # Extract title
    if soup.title:
        article_data['title'] = clean_text(soup.title.get_text())
    
    # Extract published date
    date_elem = soup.select_one('.info-item.info-time')
    if date_elem:
        date_text = date_elem.get_text(strip=True)
        try:
            parts = date_text.split()
            if len(parts) >= 3:
                day = parts[0].zfill(2)  # Ensure 2-digit day
                month_upper = parts[1].upper()
                month = RUSSIAN_MONTH_MAP.get(month_upper, '01')
                year = parts[2]
                article_data['published'] = f"{year}-{month}-{day}"
        except Exception as e:
            logging.error(f"Error parsing date '{date_text}': {e}")
    
    # Extract section from URL
    url_path = urlparse(article_data['url']).path
    news_match = re.search(r'/news/([^/]+)/', url_path)
    if news_match:
        article_data['section'] = news_match.group(1)
    
    # Extract description
    desc_elem = soup.select_one('.content-news > .block-content > h3')
    if desc_elem:
        article_data['description'] = clean_text(desc_elem.get_text())
    
    # Extract content
    content_elem = soup.select_one('.content-news')
    if content_elem:
        # Find the h3 with class article-title
        h3_title = content_elem.select_one('h3.article-title')
        paragraphs = []
        
        # Convert h3.article-title to bolded paragraph
        if h3_title:
            title_text = h3_title.get_text().strip()
            if title_text:
                paragraphs.append(f"**{title_text}**")
                h3_title.decompose()  # Remove h3 so it's not processed again
        
        # Get the rest of the content
        content_html = str(content_elem)
        content_soup = BeautifulSoup(content_html, 'html.parser')
        
        # Extract formatted content
        formatted_content = extract_content(content_soup, 'body')
        
        # Add the bolded h3 paragraph at the beginning if it exists
        if paragraphs:
            formatted_content = paragraphs[0] + "\n\n" + formatted_content
        
        article_data['content'] = formatted_content
    else:
        # Fallback to regular extraction
        article_data['content'] = extract_content(soup, '.content-news')
    
    # Set publication name
    article_data['publication'] = "Gagauzinfo"
    
    # Set language
    article_data['language'] = "ru"
    
    return article_data

def process_jurnaltv(soup, article_data):
    """Process jurnaltv.md articles."""
    # Get basic article data
    meta_data = extract_meta_tags(soup)
    
    # Extract title
    if soup.title:
        title = soup.title.get_text()
        # Remove " | JurnalTV.md" from the end of title
        title = re.sub(r'\s*\|\s*JurnalTV\.md\s*$', '', title)
        article_data['title'] = clean_text(title)
    
    # Extract published date
    date_elem = soup.select_one('.product-comment')
    if date_elem:
        date_text = date_elem.get_text(strip=True)
        try:
            # Try to match DD MMMM YYYY pattern
            match = re.search(r'(\d{1,2})\s+([a-zăîâșț]+)\s+(\d{4})', date_text, re.IGNORECASE)
            if match:
                day = match.group(1).zfill(2)
                month_name = match.group(2).lower()
                month = ROMANIAN_MONTH_MAP.get(month_name, '01')
                year = match.group(3)
                article_data['published'] = f"{year}-{month}-{day}"
        except Exception as e:
            logging.error(f"Error parsing date '{date_text}': {e}")
    
    # Extract section
    category_link = soup.find('a', href=re.compile(r'/category/([^/]+)'))
    if category_link:
        section_match = re.search(r'/category/([^/]+)', category_link['href'])
        if section_match:
            article_data['section'] = section_match.group(1)
    
    # Extract description
    if 'name:description' in meta_data:
        article_data['description'] = meta_data['name:description']
    elif 'property:og:description' in meta_data:
        article_data['description'] = meta_data['property:og:description']
    
    # Extract content - modified approach
    lead_elem = soup.select_one('.mb-3.pb-1.text-white.lead')
    content_elems = soup.select('.mb-3.pb-1.text-white:not(.lead)')
    
    paragraphs = []
    
    # Process lead paragraph
    if lead_elem:
        lead_text = lead_elem.get_text(strip=True)
        if lead_text:
            paragraphs.append(f"**{lead_text}**")
    
    # Process the rest of content elements
    for elem in content_elems:
        text = elem.get_text(strip=True)
        if text:
            paragraphs.append(text)
    
    # Join all paragraphs
    article_data['content'] = "\n\n".join(paragraphs)
    
    # Set publication name
    article_data['publication'] = "JurnalTV"
    
    # Set language
    article_data['language'] = "ro"
    
    return article_data

def process_kp_media(soup, article_data):
    """Process md.kp.media articles."""
    # Get basic article data
    meta_data = extract_meta_tags(soup)
    schema_data = extract_schema_data(soup)
    
    # Extract title
    if soup.title:
        article_data['title'] = clean_text(soup.title.get_text())
    
    # Extract published date
    if 'property:article:published_time' in meta_data:
        article_data['published'] = meta_data['property:article:published_time']
    
    # Extract author
    if 'property:article:author' in meta_data:
        author = meta_data['property:article:author']
        # Clean the author name
        author = re.sub(r'\s*\|.*', '', author).strip()
        # Convert to title case
        author = ' '.join(word.capitalize() for word in author.split())
        article_data['author'] = author
    
    # Extract section
    if 'property:article:section' in meta_data:
        article_data['section'] = meta_data['property:article:section']
    
    # Extract description
    if 'name:description' in meta_data:
        article_data['description'] = meta_data['name:description']
    elif 'property:og:description' in meta_data:
        article_data['description'] = meta_data['property:og:description']
    
    # Extract keywords
    if schema_data and 'keywords' in schema_data:
        keywords = schema_data['keywords']
        if isinstance(keywords, str):
            article_data['keywords'] = [k.strip() for k in keywords.split(',')]
        else:
            article_data['keywords'] = keywords
    elif 'name:keywords' in meta_data:
        article_data['keywords'] = [k.strip() for k in meta_data['name:keywords'].split(',')]
    
    # Extract content
    article_data['content'] = extract_content(soup, '.content-body')
    
    # Set publication name
    article_data['publication'] = "KP Media Moldova"
    
    # Set language
    article_data['language'] = "ru"
    
    return article_data

def process_nokta(soup, article_data):
    """Process nokta.md articles."""
    # Get basic article data
    meta_data = extract_meta_tags(soup)
    schema_data = extract_schema_data(soup)
    
    # Extract title
    if soup.title:
        article_data['title'] = clean_text(soup.title.get_text())
    
    # Extract published date
    if schema_data and 'datePublished' in schema_data:
        article_data['published'] = schema_data['datePublished']
    elif 'property:article:published_time' in meta_data:
        article_data['published'] = meta_data['property:article:published_time']
    
    # Extract author
    if schema_data and 'author' in schema_data:
        if isinstance(schema_data['author'], dict) and 'name' in schema_data['author']:
            article_data['author'] = schema_data['author']['name']
        elif isinstance(schema_data['author'], str):
            article_data['author'] = schema_data['author']
    
    # Extract section
    if schema_data and 'articleSection' in schema_data:
        article_data['section'] = schema_data['articleSection']
    
    # Extract description
    if schema_data and 'description' in schema_data:
        article_data['description'] = schema_data['description']
    elif 'name:description' in meta_data:
        article_data['description'] = meta_data['name:description']
    
    # Extract keywords
    if schema_data and 'keywords' in schema_data:
        keywords = schema_data['keywords']
        if isinstance(keywords, str):
            article_data['keywords'] = [k.strip() for k in keywords.split(',')]
        else:
            article_data['keywords'] = keywords
    
    # Extract content
    article_data['content'] = extract_content(soup, '.single-post__content')
    
    # Set publication name
    article_data['publication'] = "Nokta"
    
    # Set language
    article_data['language'] = "ro"
    
    return article_data

def process_evedomosti(soup, article_data):
    """Process evedomosti.md articles."""
    # Get basic article data
    meta_data = extract_meta_tags(soup)
    
    # Extract title
    if soup.title:
        article_data['title'] = clean_text(soup.title.get_text())
    
    # Extract published date
    date_elem = soup.select_one('.date.float-left')
    if date_elem:
        date_text = date_elem.get_text(strip=True)
        try:
            # Format: "DD.MM.YYYY, HH:mm"
            date_obj = datetime.strptime(date_text, "%d.%m.%Y, %H:%M")
            article_data['published'] = date_obj.strftime("%Y-%m-%dT%H:%M")
        except Exception as e:
            logging.error(f"Error parsing date '{date_text}': {e}")
    
    # Extract section
    section_elem = soup.select_one('.category-heading h1')
    if section_elem:
        article_data['section'] = clean_text(section_elem.get_text())
    
    # Extract description
    if 'name:description' in meta_data:
        article_data['description'] = meta_data['name:description']
    
    # Extract content
    article_data['content'] = extract_content(soup, '.article-content')
    
    # Set publication name
    article_data['publication'] = "Moldavskie Vedomosti"
    
    # Set language
    article_data['language'] = "ru"
    
    return article_data

def process_article(article, args, output_dir):
    """Process a single article: fetch, extract metadata, and save to markdown."""
    host = article['host']
    archive_url = article['archive']
    original_url = article['url']
    
    # Create host-specific subdirectory
    host_dir = os.path.join(output_dir, host)
    os.makedirs(host_dir, exist_ok=True)
    
    # Generate output filename
    path = urlparse(original_url).path
    segments = [s for s in path.split('/') if s]
    last_segment = segments[-1] if segments else 'untitled'
    output_filename = f"{host}_{slugify(last_segment)}.md"
    output_path = os.path.join(host_dir, output_filename)
    
    # Skip if already processed and not forcing
    if os.path.exists(output_path) and not args.force:
        logging.info(f"Skipping {archive_url} - already processed")
        return article
    
    logging.info(f"Processing {archive_url}")
    
    # Fetch HTML content
    html_content = get_html(archive_url, args.timeout, args.retries, args.delay)
    if not html_content:
        article['status'] = 'failed'
        return article
    
    # Parse HTML
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # Initialize article data with basic info
    article_data = {
        'site': host,
        'archive': archive_url,
        'url': original_url,
        'status': 'success'
    }
    
    # Process based on host
    if 'gagauznews.com' in host:
        article_data = process_gagauznews(soup, article_data)
    elif 'gagauzinfo.md' in host:
        article_data = process_gagauzinfo(soup, article_data)
    elif 'jurnaltv.md' in host:
        article_data = process_jurnaltv(soup, article_data)
    elif 'md.kp.media' in host:
        article_data = process_kp_media(soup, article_data)
    elif 'nokta.md' in host:
        article_data = process_nokta(soup, article_data)
    elif 'evedomosti.md' in host:
        article_data = process_evedomosti(soup, article_data)
    else:
        logging.warning(f"No specific parser for {host}, using generic extraction")
        if soup.title:
            article_data['title'] = clean_text(soup.title.get_text())
        article_data['content'] = extract_content(soup, 'body')
    
    # Update the article dict with the extracted data
    for key, value in article_data.items():
        article[key] = value
    
    # Save article to markdown file
    save_markdown(article_data, output_path)
    
    # Add a small delay to avoid overloading the server
    time.sleep(args.delay)
    
    return article

def save_markdown(article_data, output_path):
    """Save article data to a markdown file with YAML frontmatter."""
    # Prepare frontmatter data
    frontmatter_data = {
        'site': article_data.get('site', ''),
        'archive': article_data.get('archive', ''),
        'url': article_data.get('url', ''),
        'language': article_data.get('language', ''),
    }
    
    # Format title - ensure no linebreaks
    title = clean_text(article_data.get('title', 'Untitled'))
    frontmatter_data['title'] = title
    
    # Format publication
    publication_name = article_data.get('publication', '')
    frontmatter_data['publication'] = f"[[{publication_name}]]"
    
    # Add published date if available
    if 'published' in article_data and article_data['published']:
        frontmatter_data['published'] = article_data['published']
    
    # Add optional fields if they exist
    for field in ['author', 'section']:
        if field in article_data and article_data[field]:
            frontmatter_data[field] = article_data[field]
    
    # Handle description separately to ensure no linebreaks
    if 'description' in article_data and article_data['description']:
        frontmatter_data['description'] = clean_text(article_data['description'])
    
    # Handle keywords
    if 'keywords' in article_data and article_data['keywords']:
        keywords = article_data['keywords']
        if isinstance(keywords, str):
            keywords = [kw.strip() for kw in keywords.split(',')]
        frontmatter_data['keywords'] = [f"[[{kw}]]" for kw in keywords]
    
    # Set up custom YAML representer for quoted strings
    class QuotedString(str):
        pass
    
    def represent_quoted_string(dumper, data):
        return dumper.represent_scalar('tag:yaml.org,2002:str', data, style='"')
    
    yaml.add_representer(QuotedString, represent_quoted_string)
    
    # Ensure title, description, site, and URLs are quoted and have no line breaks
    for field in ['title', 'description', 'site', 'archive', 'url']:
        if field in frontmatter_data:
            # Apply clean_text again to ensure no linebreaks
            cleaned_value = clean_text(str(frontmatter_data[field]))
            frontmatter_data[field] = QuotedString(cleaned_value)
    
    # Write to file with explicit YAML flow style for strings
    try:
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write('---\n')
            # Configure YAML dump to not use canonical form and not add line breaks for strings
            yaml_content = yaml.dump(
                frontmatter_data, 
                allow_unicode=True, 
                default_flow_style=False,
                width=10000,  # Set very wide width to prevent line wrapping
                sort_keys=False
            )
            f.write(yaml_content)
            f.write('---\n\n')
            
            # Process content to remove any remaining h1 tags
            content = article_data.get('content', '')
            # Remove any Markdown h1 headers (lines starting with #)
            content = re.sub(r'(?m)^# .*$\n?', '', content)
            f.write(content)
            
        logging.info(f"Saved article to {output_path}")
    except Exception as e:
        logging.error(f"Error saving markdown file: {e}")

def create_test_csv(csv_path, test_csv_path, samples_per_host):
    """Create a test CSV with a random sample of articles from each host."""
    articles = read_csv(csv_path)
    
    if not articles:
        logging.warning(f"No articles found in {csv_path}")
        return []
    
    # Group articles by host
    articles_by_host = {}
    for article in articles:
        host = article['host']
        if host not in articles_by_host:
            articles_by_host[host] = []
        articles_by_host[host].append(article)
    
    # Select random samples for each host
    test_articles = []
    for host, host_articles in articles_by_host.items():
        # Take the minimum of requested samples or available articles
        sample_size = min(samples_per_host, len(host_articles))
        host_samples = random.sample(host_articles, sample_size)
        test_articles.extend(host_samples)
        logging.info(f"Selected {sample_size} articles from {host}")
    
    # Create the test directory if it doesn't exist
    os.makedirs(os.path.dirname(test_csv_path), exist_ok=True)
    
    # Write the test articles to the test CSV
    write_csv(test_csv_path, test_articles)
    logging.info(f"Created test CSV at {test_csv_path} with {len(test_articles)} articles")
    
    return test_articles

def main():
    args = setup_argparse()
    
    # Determine the root directory (parent of the script directory)
    script_dir = Path(__file__).parent
    root_dir = script_dir.parent
    
    # Adjust paths to be relative to root if they're not absolute
    if not os.path.isabs(args.output):
        args.output = os.path.join(root_dir, args.output)
    
    if not os.path.isabs(args.input):
        args.input = os.path.join(root_dir, args.input)
    
    # Handle test mode
    if args.test is not None:
        logging.info(f"Running in test mode with {args.test} samples per host")
        
        # Set up test paths
        test_dir = os.path.join(root_dir, "data", "tests")
        test_csv_path = os.path.join(test_dir, "test_articles.csv")
        args.output = test_dir
        
        # Delete test directory if it exists
        if os.path.exists(test_dir):
            logging.info(f"Deleting existing test directory: {test_dir}")
            shutil.rmtree(test_dir)
        
        # Create test CSV and update input path
        test_articles = create_test_csv(args.input, test_csv_path, args.test)
        args.input = test_csv_path
        
        if not test_articles:
            logging.warning("No test articles to process.")
            return
        
        logging.info(f"Test mode: Using {test_csv_path} as input and {args.output} as output directory")
    
    # Ensure output directory exists
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Read CSV file
    logging.info(f"Reading CSV file: {args.input}")
    articles = read_csv(args.input)
    
    if not articles:
        logging.warning("No articles found in CSV file.")
        return
    
    logging.info(f"Found {len(articles)} articles in CSV file.")
    
    # Filter by host if specified
    if args.host:
        articles = [a for a in articles if a['host'] == args.host]
        logging.info(f"Filtered to {len(articles)} articles for host {args.host}")
    
    # Limit the number of articles if specified
    if args.limit and args.limit > 0:
        articles = articles[:args.limit]
        logging.info(f"Limited to {len(articles)} articles")
    
    # Process articles
    updated_articles = []
    for i, article in enumerate(articles):
        logging.info(f"Processing article {i+1}/{len(articles)}")
        updated_article = process_article(article, args, output_dir)
        updated_articles.append(updated_article)
    
    # Write updated CSV
    write_csv(args.input, updated_articles)
    logging.info(f"Updated CSV file with metadata: {args.input}")
    
    # Count successes and failures
    successes = sum(1 for a in updated_articles if a.get('status') == 'success')
    failures = sum(1 for a in updated_articles if a.get('status') == 'failed')
    skipped = len(updated_articles) - successes - failures
    
    logging.info(f"Processing complete.")
    logging.info(f"Successes: {successes}")
    logging.info(f"Failures: {failures}")
    logging.info(f"Skipped: {skipped}")

if __name__ == "__main__":
    main()