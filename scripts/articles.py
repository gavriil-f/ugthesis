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

# Default variables
DEFAULT_OUTPUT_DIR = "data/raw/articles"
DEFAULT_CSV_PATH = "data/articles.csv" 
DEFAULT_TIMEOUT = 15 # Integer (seconds)
DEFAULT_RETRIES = 3 # Integer
DEFAULT_DELAY = 5  # Float (seconds)

# Month maps for date scraping + conversion
def get_russian_month(month_text):
    """Get month number from Russian month name (case-insensitive)."""
    RUSSIAN_MONTH_MAP = {
        'янв': '01', 'янва': '01', 'январь': '01', 'январ': '01',
        'фев': '02', 'февр': '02', 'февраль': '02',
        'мар': '03', 'март': '03', 'марта': '03',
        'апр': '04', 'апре': '04', 'апрель': '04',
        'май': '05', 'мая': '05',
        'июн': '06', 'июнь': '06', 'июня': '06',
        'июл': '07', 'июль': '07', 'июля': '07',
        'авг': '08', 'авгу': '08', 'август': '08',
        'сен': '09', 'сент': '09', 'сентябрь': '09',
        'окт': '10', 'октя': '10', 'октябрь': '10',
        'ноя': '11', 'нояб': '11', 'ноябрь': '11',
        'дек': '12', 'дека': '12', 'декабрь': '12',
    }
    
    month_text = month_text.lower()
    return RUSSIAN_MONTH_MAP.get(month_text, '01')

def get_romanian_month(month_text):
    """Get month number from Romanian month name (case-insensitive)."""
    ROMANIAN_MONTH_MAP = {
        'ianuarie': '01', 'februarie': '02', 
        'martie': '03', 'aprilie': '04',
        'mai': '05', 'iunie': '06', 
        'iulie': '07', 'august': '08',
        'septembrie': '09', 'octombrie': '10', 
        'noiembrie': '11', 'decembrie': '12'
    }
    
    month_text = month_text.lower()
    return ROMANIAN_MONTH_MAP.get(month_text, '01')

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
    
    # Retries X number of times
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
    """Extract JSON-LD schema data from the page. Required to get some metadata from particular hosts."""
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
    """Extract metadata from your typical html meta tags."""
    meta_data = {}
    
    for meta in soup.find_all('meta'):
        # Get the meta key (name, property, or http-equiv)
        key = None
        for attr in ['name', 'property', 'http-equiv']:
            if meta.get(attr):
                key = f"{attr}:{meta.get(attr)}"
                break
        # Get meta content - not actually used but potentially useful as a fallback for article content        
        if key and meta.get('content'):
            meta_data[key] = meta.get('content')
            
    return meta_data

def clean_text(text):
    """Clean text by removing extra whitespace and normalizing."""
    if not text:
        return ""
    # Remove all line breaks and normalize multiple spaces into a single space
    return re.sub(r'\s+', ' ', text).strip()

def format_text_improvements(content):
    """Apply additional text formatting improvements."""
    # Add space after semicolons that are followed by text without space. Required for OCD reasons.
    content = re.sub(r'(\w):(\w)', r'\1: \2', content)
    
    return content

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
        
        for elem in content_copy.select(selector):
            elem.decompose()
    
    # Format paragraphss
    paragraphs = []
    processed_texts = set()  # To keep track of processed text to avoid duplication
    in_list = False
    list_items = []
    
    for p in content_copy.find_all(['p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'blockquote', 'ul', 'ol', 'li']):
        # Process any strong elements before getting text
        is_heading = p.name.startswith('h')
        
        # If not a heading, convert any <strong> elements to markdown bold
        if not is_heading:
            for strong in p.find_all('strong'):
                strong_text = strong.get_text().strip()
                if strong_text:
                    # Replace the strong element with markdown bold syntax
                    strong_html = str(strong)
                    p_html = str(p)
                    p_html = p_html.replace(strong_html, f"**{strong_text}**")
                    # Parse the updated HTML back into the paragraph
                    p = BeautifulSoup(p_html, 'html.parser')
        
        text = p.get_text(strip=True)
        if not text:
            continue
            
        if p.name == 'h1':
            # Skip already existing h1 headers entirely so as to avoid duplication when we add title as h1 
            continue
        elif p.name.startswith('h'):
            # If we were building a list, add it now before the header
            if in_list and list_items:
                paragraphs.append("\n".join(list_items))
                list_items = []
                in_list = False
                
            level = int(p.name[1])
            paragraph = f"{'#' * level} {text}"
            if paragraph not in processed_texts:
                paragraphs.append(paragraph)
                processed_texts.add(paragraph)
                processed_texts.add(text)  # Also mark the plain text as processed
        elif p.name == 'blockquote':
            # If we were building a list, add it now before the blockquote
            if in_list and list_items:
                paragraphs.append("\n".join(list_items))
                list_items = []
                in_list = False
                
            # Only add blockquote text in the quote format, don't duplicate as regular paragraph
            paragraph = f"> {text}"
            if paragraph not in processed_texts:
                paragraphs.append(paragraph)
                processed_texts.add(paragraph)
                processed_texts.add(text)  # Also mark the non-quoted version as processed
        elif p.name in ['ul', 'ol']:
            # Handle list containers. Processing their items individually to remove ugly line breaks between list items.
            continue
        elif p.name == 'li':
            # Process list item
            if not in_list:
                in_list = True
                # Add an empty list_items to ensure an empty line before the list
                if paragraphs and not paragraphs[-1].endswith('\n'):
                    paragraphs.append("")
            
            if text and text not in processed_texts:
                list_items.append(f"- {text}")
                processed_texts.add(text)
        else:
            # Regular paragraph
            # If we were building a list, add it now before the new paragraph
            if in_list and list_items:
                paragraphs.append("\n".join(list_items))
                list_items = []
                in_list = False
                # Add an empty line after the list
                paragraphs.append("")
                
            if text not in processed_texts:
                paragraphs.append(text)
                processed_texts.add(text)
    
    # Add any remaining list items
    if in_list and list_items:
        paragraphs.append("\n".join(list_items))
        # Add an empty line after the list
        paragraphs.append("")
    
    # Join all paragraphs and lint
    content = "\n\n".join(paragraphs).replace("\n\n\n\n", "\n\n").replace("\n\n\n", "\n\n")
    content = format_text_improvements(content)
    
    return content

def extract_content_with_fallbacks(soup, selectors, process_func=None):
    """
    Extract content using multiple selector fallbacks.
    
    Args:
        soup: BeautifulSoup object
        selectors: List of CSS selectors to try in order
        process_func: Optional custom processing function for the content element
        
    Returns:
        Processed content string
    """
    content = ""
    content_elem = None
    
    # Try each selector in order until we find content
    for selector in selectors:
        if isinstance(selector, str):
            content_elem = soup.select_one(selector)
        elif callable(selector):
            # Allow for custom element selection logic
            content_elem = selector(soup)
        
        if content_elem:
            break
    
    # If we found a content element, process it
    if content_elem:
        if process_func:
            # Use custom processing function if provided
            content = process_func(content_elem)
        else:
            # Default processing - extract paragraphs
            paragraphs = []
            processed_texts = set()  # Track processed text to avoid duplication
            in_list = False
            list_items = []
            
            # Process heading elements, paragraphs, blockquotes, and lists
            for elem in content_elem.find_all(['p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 
                                               'blockquote', 'ul', 'ol', 'li']):
                text = elem.get_text(strip=True)
                if text and text not in processed_texts:
                    if elem.name == 'blockquote':
                        # If we're in a list, close it before the blockquote
                        if in_list and list_items:
                            paragraphs.append("\n".join(list_items))
                            list_items = []
                            in_list = False
                        
                        paragraph = f"> {text}"
                        paragraphs.append(paragraph)
                        processed_texts.add(text)  # Mark both versions as processed
                        processed_texts.add(paragraph)
                    elif elem.name.startswith('h'):
                        # If we're in a list, close it before the heading
                        if in_list and list_items:
                            paragraphs.append("\n".join(list_items))
                            list_items = []
                            in_list = False
                        
                        level = int(elem.name[1])
                        paragraph = f"{'#' * level} {text}"
                        paragraphs.append(paragraph)
                        processed_texts.add(text)  # Mark both versions as processed
                        processed_texts.add(paragraph)
                    elif elem.name in ['ul', 'ol']:
                        # Start a list container - we'll process its items individually
                        in_list = True
                        # Ensure there's an empty line before the list starts
                        if paragraphs and not paragraphs[-1] == "":
                            paragraphs.append("")
                        continue
                    elif elem.name == 'li':
                        # Process list item
                        if not in_list:
                            in_list = True
                        list_items.append(f"- {text}")
                        processed_texts.add(text)
                    else:
                        # Regular paragraph - if we're in a list, close it
                        if in_list and list_items:
                            paragraphs.append("\n".join(list_items))
                            paragraphs.append("")  # Empty line after list
                            list_items = []
                            in_list = False
                        
                        paragraphs.append(text)
                        processed_texts.add(text)
            
            # Close any remaining list
            if in_list and list_items:
                paragraphs.append("\n".join(list_items))
                paragraphs.append("")  # Empty line after list
            
            # Join all paragraphs with double newlines
            content = "\n\n".join(p for p in paragraphs if p)
    
    # Clean and format the content
    content = clean_content(content) 
    content = format_text_improvements(content)
    
    return content

def process_gagauznews(soup, article_data):
    """Process gagauznews.com articles."""
    # Get basic article data
    meta_data = extract_meta_tags(soup)
    schema_data = extract_schema_data(soup)
    
    # Extract title
    if soup.title:
        title = soup.title.get_text()
        # Clean title
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
    
    # Extract section from the ld+json
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
    
    # Simplified content extraction
    content_elem = soup.select_one('.single-body--content')
    
    if content_elem:
        # Create a more robust approach to extract paragraphs
        paragraphs = []
        in_list = False
        list_items = []
        
        for elem in content_elem.find_all(['p', 'h2', 'h3', 'h4', 'h5', 'h6', 'blockquote', 'ul', 'ol', 'li']):
            text = elem.get_text(strip=True)
            if text:
                if elem.name == 'blockquote':
                    # If we're in a list, close it before the blockquote
                    if in_list and list_items:
                        paragraphs.append("\n".join(list_items))
                        list_items = []
                        in_list = False
                    
                    paragraphs.append(f"> {text}")
                elif elem.name.startswith('h'):
                    # If we're in a list, close it before the heading
                    if in_list and list_items:
                        paragraphs.append("\n".join(list_items))
                        list_items = []
                        in_list = False
                    
                    level = int(elem.name[1])
                    paragraphs.append(f"{'#' * level} {text}")
                elif elem.name in ['ul', 'ol']:
                    # Start a list container - we'll process its items individually
                    in_list = True
                    # Ensure there's an empty line before the list starts
                    if paragraphs and not paragraphs[-1] == "":
                        paragraphs.append("")
                    continue
                elif elem.name == 'li':
                    # Process list item
                    if not in_list:
                        in_list = True
                    list_items.append(f"- {text}")
                else:
                    # Regular paragraph - if we're in a list, close it
                    if in_list and list_items:
                        paragraphs.append("\n".join(list_items))
                        paragraphs.append("")  # Empty line after list
                        list_items = []
                        in_list = False
                    
                    paragraphs.append(text)
        
        # Close any remaining list
        if in_list and list_items:
            paragraphs.append("\n".join(list_items))
            paragraphs.append("")  # Empty line after list
        
        # Join all paragraphs with double newlines
        content = "\n\n".join(paragraphs).replace("\n\n\n\n", "\n\n").replace("\n\n\n", "\n\n")
    else:
        # Fallback to more general extraction
        content = extract_content(soup, 'article')
        if not content:
            content = extract_content(soup, '.entry-content')
    
    # Clean any unwanted content sections
    content = clean_content(content)
    
    # Apply formatting improvements
    content = format_text_improvements(content)
    
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
    # Gagauznews doesn't include this in metadata or schema, 
    # so we have to parse a specific element 
    # (and convert from russian DD MMMM YYYY format)
    date_elem = soup.select_one('.info-item.info-time')
    if date_elem:
        date_text = date_elem.get_text(strip=True)
        try:
            parts = date_text.split()
            if len(parts) >= 3:
                day = parts[0].zfill(2)  # Ensure 2-digit day a la ISO
                month = get_russian_month(parts[1])  # Use the month map
                year = parts[2]
                article_data['published'] = f"{year}-{month}-{day}"
        except Exception as e:
            logging.error(f"Error parsing date '{date_text}': {e}")
    
    # Extract the news section from the URL with a simple regex match
    url_path = urlparse(article_data['url']).path
    news_match = re.search(r'/news/([^/]+)/', url_path)
    if news_match:
        article_data['section'] = news_match.group(1)
    
    # Extract description
    desc_elem = soup.select_one('.content-news > .block-content > h3')
    if desc_elem:
        article_data['description'] = clean_text(desc_elem.get_text())
    
    # Extract content from the .content-news element
    content_elem = soup.select_one('.content-news')
    if content_elem:
        # Get content as paragraphs
        paragraphs = []
        
        # Special handling for the leading paragraph
        # Strip h3 and make bold to be more markdown spec
        h3_title = content_elem.select_one('h3.article-title')
        if h3_title:
            h3_text = h3_title.get_text().strip()
            if h3_text:
                paragraphs.append(f"**{h3_text}**")
        
        # Get all other paragraphs
        for p in content_elem.find_all('p'):
            # Skip if this is inside the h3 we already processed
            if h3_title and h3_title.find(p):
                continue
                
            text = p.get_text().strip()
            if text:
                paragraphs.append(text)
        
        article_data['content'] = "\n\n".join(paragraphs)
    else:
        # Try fallback: use inner text of .content-news > .block-content
        block_content = soup.select_one('.content-news > .block-content')
        if block_content:
            # Get the inner text and split by newlines
            inner_text = block_content.get_text(strip=True)
            # Convert any sequence of whitespace including newlines to a proper paragraph break
            paragraphs = re.split(r'\s*\n\s*', inner_text)
            # Filter out empty paragraphs and join with double newlines
            article_data['content'] = "\n\n".join(p.strip() for p in paragraphs if p.strip())
        else:
            article_data['content'] = ""
    
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
        # Clean title
        title = re.sub(r'\s*\|\s*JurnalTV\.md\s*$', '', title)
        article_data['title'] = clean_text(title)
    
    # Extract published date
    # Same story as with Gagauznews, but in Romanian this time
    date_elem = soup.select_one('.product-comment')
    if date_elem:
        date_text = date_elem.get_text(strip=True)
        try:
            # Try to match DD MMMM YYYY pattern
            match = re.search(r'(\d{1,2})\s+([a-zăîâșț]+)\s+(\d{4})', date_text, re.IGNORECASE)
            if match:
                day = match.group(1).zfill(2)
                month_name = match.group(2)
                month = get_romanian_month(month_name)  # Use the month map
                year = match.group(3)
                article_data['published'] = f"{year}-{month}-{day}"
        except Exception as e:
            logging.error(f"Error parsing date '{date_text}': {e}")
    
    # Extract section from the href which links to /category/<category>/
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
    
    # Custom processing function for JurnalTV content - improved to handle <em> tags
    def process_jurnaltv_content(content_elem):
        paragraphs = []
        processed_texts = set()  # Track processed text to avoid duplication
        
        # Process both lead paragraph and other content elements
        for elem in content_elem.find_all(['p', 'h2', 'h3', 'h4', 'h5', 'h6', 'blockquote', 'ul', 'ol', 'li', 'div.lead']):
            # Special handling for paragraphs with embedded elements like <em>
            if elem.name == 'p' and elem.find('em'):
                # Need to rebuild the paragraph text preserving formatting
                paragraph_text = ""
                for content in elem.contents:
                    if isinstance(content, str):
                        paragraph_text += content.strip()
                    elif content.name == 'em':
                        em_text = content.get_text().strip()
                        if em_text:
                            paragraph_text += f"*{em_text}*"
                
                paragraph_text = paragraph_text.strip()
                if paragraph_text and paragraph_text not in processed_texts:
                    paragraphs.append(paragraph_text)
                    processed_texts.add(paragraph_text)
                continue
            
            text = elem.get_text(strip=True)
            
            # Skip if empty or already processed
            if not text or text in processed_texts:
                continue
                
            processed_texts.add(text)
            
            # Handle based on element type
            if elem.name == 'blockquote':
                paragraph = f"> {text}"
                paragraphs.append(paragraph)
                processed_texts.add(paragraph)  # Mark the formatted version as processed too
            elif elem.name.startswith('h'):
                level = int(elem.name[1])
                paragraph = f"{'#' * level} {text}"
                paragraphs.append(paragraph)
                processed_texts.add(paragraph)  # Mark the formatted version as processed too
            elif elem.name == 'li':
                paragraphs.append(f"- {text}")
            elif 'lead' in elem.get('class', []):
                # Make lead paragraphs bold
                paragraphs.append(f"**{text}**") 
            else:
                paragraphs.append(text)
        
        # Join all paragraphs with double newlines
        return "\n\n".join(p for p in paragraphs if p)
    
    # Define a custom selector function
    def content_selector(soup):
        article_body = soup.select_one('.article-body')
        if article_body:
            return article_body
            
        # Alternative approach with lead and content
        lead_elem = soup.select_one('.mb-3.pb-1.text-white.lead')
        content_elems = soup.select('.mb-3.pb-1.text-white:not(.lead)')
        
        if lead_elem or content_elems:
            wrapper = soup.new_tag('div')
            if lead_elem:
                wrapper.append(lead_elem)
            for elem in content_elems:
                wrapper.append(elem)
            return wrapper
            
        return None
    
    # Extract content with fallbacks
    content = extract_content_with_fallbacks(
        soup,
        [
            content_selector,        # Custom selector combining approaches
            '.mb-7.pb-1'            # Fallback selector
        ],
        process_jurnaltv_content    # Custom processing function
    )
    
    article_data['content'] = content
    
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
        title = soup.title.get_text()
        # Remove " - MD.KP.MEDIA" from the end of title
        title = re.sub(r'\s*-\s*MD\.KP\.MEDIA\s*$', '', title)
        article_data['title'] = clean_text(title)
    
    # Extract published date
    if 'property:article:published_time' in meta_data:
        article_data['published'] = meta_data['property:article:published_time']
    
    # Extract author
    if 'property:article:author' in meta_data:
        author = meta_data['property:article:author']
        # Clean the author name to remove any vertical bar characters
        author = re.sub(r'\s*\|.*', '', author).strip()
        # Convert to title case for consistency (rather than First LAST)
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
    content = ""
    
    # Try find() with data attribute. 
    # Since they don't usually use an html class, we have to search for a specific data attribute
    content_elem = soup.find(attrs={"data-gtm-el": "content-body"})
    if content_elem:
        # Extract text from paragraphs directly
        paragraphs = []
        for p in content_elem.find_all(['p', 'h2', 'h3', 'h4', 'blockquote']):
            text = p.get_text().strip()
            if text:
                if p.name == 'blockquote':
                    paragraphs.append(f"> {text}")
                elif p.name.startswith('h'):
                    level = int(p.name[1])
                    paragraphs.append(f"{'#' * level} {text}")
                else:
                    paragraphs.append(text)
        
        content = "\n\n".join(paragraphs)
    
    # If that fails, get desperate and try a class selector 
    if not content:
        content_elem = soup.select_one('.content-body')
        if content_elem:
            # Extract text from paragraphs
            paragraphs = []
            for p in content_elem.find_all(['p', 'h2', 'h3', 'h4', 'blockquote']):
                text = p.get_text().strip()
                if text:
                    if p.name == 'blockquote':
                        paragraphs.append(f"> {text}")
                    elif p.name.startswith('h'):
                        level = int(p.name[1])
                        paragraphs.append(f"{'#' * level} {text}")
                    else:
                        paragraphs.append(text)
            
            content = "\n\n".join(paragraphs)
    
    article_data['content'] = content
    
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
        title = soup.title.get_text()
        # Remove "- Nokta" or "— Nokta" from the title
        title = re.sub(r'\s*[-—]\s*Nokta\s*$', '', title)
        article_data['title'] = clean_text(title)
    
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
    
    # Custom processing function for Nokta content
    def process_nokta_content(content_elem):
        paragraphs = []
        for elem in content_elem.find_all(['p', 'h2', 'h3', 'h4', 'h5', 'h6', 'blockquote', 'ul', 'ol', 'li']):
            text = elem.get_text(strip=True)
            if text:
                if elem.name == 'blockquote':
                    paragraphs.append(f"> {text}")
                elif elem.name.startswith('h'):
                    level = int(elem.name[1])
                    paragraphs.append(f"{'#' * level} {text}")
                elif elem.name == 'li':
                    paragraphs.append(f"- {text}")
                else:
                    paragraphs.append(text)
        
        content = "\n\n".join(paragraphs)
        
        # Remove lines containing just "nokta" and everything after
        nokta_match = re.search(r'(?m)^\s*nokta\s*$.*', content, re.DOTALL) 
        if nokta_match:
            content = content[:nokta_match.start()].strip()
        
        # Remove lines containing "Читайте также:" and everything after
        related_match = re.search(r'(?m)^\s*Читайте также:\s*$.*', content, re.DOTALL)
        if related_match:
            content = content[:related_match.start()].strip()
            
        return content
    
    # Extract content with fallbacks
    content = extract_content_with_fallbacks(
        soup,
        [
            '.single-post__content',  # Primary selector
            'article.post',          # First fallback
            '.entry-content'         # Second fallback
        ],
        process_nokta_content
    )
    
    article_data['content'] = content
    
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
        title = clean_text(soup.title.get_text())
        # Remove " - Молдавские Ведомости" from the end of title
        title = re.sub(r'\s*-\s*Молдавские Ведомости\s*$', '', title)
        article_data['title'] = title
    
    # Extract published date
    date_elem = soup.select_one('.date.float-left')
    if date_elem:
        date_text = date_elem.get_text(strip=True)
        try:
            # Convert from 'DD.MM.YYYY, HH:mm' format
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
    
    # Custom processing function for Evedomosti content
    def process_evedomosti_content(content_elem):
        paragraphs = []
        processed_texts = set()  # Track processed text to avoid duplication
        
        # Include div elements along with other content elements for evedomosti
        for p in content_elem.find_all(['p', 'div', 'h2', 'h3', 'h4', 'h5', 'h6', 'blockquote', 'ul', 'ol', 'li']):
            # Skip divs that are containers for other content we'll process separately
            if p.name == 'div' and (p.find(['p', 'h2', 'h3', 'h4', 'h5', 'h6', 'blockquote', 'ul', 'ol', 'li']) is not None):
                continue
                
            text = p.get_text(strip=True)
            if text and text not in processed_texts:
                processed_texts.add(text)
                if p.name == 'blockquote':
                    paragraph = f"> {text}"
                    paragraphs.append(paragraph)
                    processed_texts.add(paragraph)  # Also mark the quoted version as processed
                elif p.name.startswith('h'):
                    level = int(p.name[1])
                    paragraph = f"{'#' * level} {text}"
                    paragraphs.append(paragraph)
                    processed_texts.add(paragraph)  # Also mark the headed version as processed
                elif p.name == 'li':
                    paragraphs.append(f"- {text}")
                else:
                    paragraphs.append(text)
        
        content = "\n\n".join(paragraphs)
        
        # Fix line breaks within paragraphs by removing single line breaks
        # But preserve paragraph breaks (double line breaks)
        content = re.sub(r'(?<!\n)\n(?!\n)', ' ', content)
        
        return content
    
    # Extract content with fallbacks
    content = extract_content_with_fallbacks(
        soup,
        [
            '.article-content',               # Primary selector
            '.entry-content > .three-fourth.first',  # New fallback specific to evedomosti
            'article',                        # First general fallback
            '.entry-content'                  # Second general fallback
        ],
        process_evedomosti_content
    )
    
    article_data['content'] = content
    
    # Set publication name
    article_data['publication'] = "Moldavskie Vedomosti"
    
    # Set language
    article_data['language'] = "ru"
    
    return article_data

def clean_content(content):
    """Clean content by removing unwanted sections."""
    # Remove "Читайте также:" and everything after it when it starts a line
    related_match = re.search(r'(?m)^\s*Читайте также:.*$.*', content, re.DOTALL)
    if related_match:
        content = content[:related_match.start()].strip()
    
    # Remove "Читайте по теме:" and everything after it
    related_topic_match = re.search(r'(?m)^\s*Читайте по теме:\s*$.*', content, re.DOTALL)
    if related_topic_match:
        content = content[:related_topic_match.start()].strip()
    
    # Remove "Поделиться" and everything after it (as header, bold, or followed by semicolon)
    share_match = re.search(r'(?m)^\s*(#+\s*|[*_]{2}|\s*)Поделиться(:|[*_]{2}|\s*)$.*', content, re.DOTALL)
    if share_match:
        content = content[:share_match.start()].strip()
    
    # Remove "Еще больше новостей - в Телеграм-канале!" and everything after it
    telegram_match = re.search(r'(?m)^\s*Еще больше новостей - в Телеграм-канале!.*', content, re.DOTALL)
    if telegram_match:
        content = content[:telegram_match.start()].strip()
    
    # Remove "Читайте подробнее" and everything after it
    details_match = re.search(r'(?m)^\s*Читайте подробнее\s*$.*', content, re.DOTALL)
    if details_match:
        content = content[:details_match.start()].strip()
    
    # Remove "Gagauznews — еще больше важных и интересных публикаций в соцсетях:" and everything after it
    gagauznews_socials_match = re.search(r'(?m)^\s*>\s*Gagauznews — еще больше важных и интересных публикаций в соцсетях:\s*$.*', content, re.DOTALL)
    if gagauznews_socials_match:
        content = content[:gagauznews_socials_match.start()].strip()
    
    # Remove "Другие ссылки:" and everything after it
    other_links_match = re.search(r'(?m)^\s*Другие ссылки:\s*$.*', content, re.DOTALL)
    if other_links_match:
        content = content[:other_links_match.start()].strip()
    
    # Remove lines beginning with "Источник:" without removing content after it
    content = re.sub(r'(?m)^\s*Источник:.*$', '', content)
    
    # Remove duplicate blockquotes - look for exact repeated paragraphs where one is a blockquote
    lines = content.split('\n\n')
    cleaned_lines = []
    seen_texts = set()
    
    for line in lines:
        if line.startswith('> '):
            # This is a blockquote - extract the text without the '> ' prefix
            quote_text = line[2:]
            if quote_text in seen_texts:
                # Skip this blockquote as we've already seen this text
                continue
            seen_texts.add(quote_text)
            cleaned_lines.append(line)
        else:
            # This is regular text - add it if we haven't seen it before
            if line not in seen_texts:
                seen_texts.add(line)
                cleaned_lines.append(line)
            # Also check if this is a duplicate of a blockquote (without the '> ' prefix)
            elif not any(f"> {line}" == cleaned_item for cleaned_item in cleaned_lines):
                # If it's not a duplicate of an existing blockquote, keep it
                cleaned_lines.append(line)
    
    # Rejoin the cleaned content
    content = '\n\n'.join(cleaned_lines)
    
    # Fix markdown lists - remove empty lines between list items
    # Split content into lines
    lines = content.split('\n')
    cleaned_lines = []
    i = 0
    while i < len(lines):
        cleaned_lines.append(lines[i])
        # Check if we have a list item followed by an empty line and then another list item
        if (i < len(lines) - 2 and 
            lines[i].strip().startswith('- ') and 
            lines[i+1].strip() == '' and 
            lines[i+2].strip().startswith('- ')):
            # Skip the empty line
            i += 2
        else:
            i += 1
    
    # Rejoin with newlines
    content = '\n'.join(cleaned_lines)
    
    # Clean up any double newlines that might have been created
    content = re.sub(r'\n{3,}', '\n\n', content)
    
    return content

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
    
    # Initialise article data with basic details
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
    
    # Save the scraped article to a markdown file
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
    
    # Insert publication
    publication_name = article_data.get('publication', '')
    frontmatter_data['publication'] = f"[[{publication_name}]]"
    
    # Add published date if available
    if 'published' in article_data and article_data['published']:
        frontmatter_data['published'] = article_data['published']
    
    # Add some extra fields if they exist
    for field in ['author', 'section']:
        if field in article_data and article_data[field]:
            frontmatter_data[field] = article_data[field]
    
    # Format description, removing any line breaks.
    if 'description' in article_data and article_data['description']:
        frontmatter_data['description'] = clean_text(article_data['description'])
    
    # Handle keywords
    if 'keywords' in article_data and article_data['keywords']:
        keywords = article_data['keywords']
        if isinstance(keywords, str):
            frontmatter_data['keywords'] = [f"[[{kw.strip()}]]" for kw in keywords.split(',')]
        else:
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
                width=10000,  # Setting a very wide line width to prevent line wrapping
                sort_keys=False
            )
            f.write(yaml_content)
            f.write('---\n\n')
            
            # Add title as a h1 heading
            f.write(f"# {title}\n\n")
            
            # Process content to remove any remaining h1 tags
            content = article_data.get('content', '')
            # Remove any Markdown h1 headers (lines starting with #)
            content = re.sub(r'(?m)^# .*$\n?', '', content)
            
            # Fix line breaks within paragraphs for evedomosti
            if article_data.get('site') == 'evedomosti.md':
                content = re.sub(r'(?<!\n)\n(?!\n)', ' ', content)
            
            # Clean the content to remove unwanted sections and fix formatting
            content = clean_content(content)
            
            # Final check for duplicate paragraphs where one is a blockquote
            # This ensures no duplication regardless of the order they appear in
            lines = content.split('\n\n')
            final_lines = []
            seen_texts = set()
            
            for line in lines:
                if line.startswith('> '):
                    # This is a blockquote
                    quote_text = line[2:]
                    if quote_text not in seen_texts:
                        seen_texts.add(quote_text)
                        final_lines.append(line)
                else:
                    # Regular text
                    if line not in seen_texts and f"> {line}" not in final_lines:
                        seen_texts.add(line)
                        final_lines.append(line)
            
            content = "\n\n".join(final_lines)
            
            # Apply formatting improvements
            content = format_text_improvements(content)
            
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
        
        # Delete test directory if it already exists for a clean slate
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