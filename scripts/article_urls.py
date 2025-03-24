#!/usr/bin/env python3

import os
import re
import csv
import sys
import time
import argparse
import requests
from pathlib import Path
from urllib.parse import urlparse


def setup_argparse():
    """Set up command line arguments."""
    parser = argparse.ArgumentParser(description="Get article URLs from Wayback Machine archives")
    parser.add_argument("host", help="Host URL to fetch (comma-separated for multiple hosts)")
    parser.add_argument("-y", "--year", default="2024", help="Year to fetch in YYYY format (default: 2024)")
    parser.add_argument("--no-filter", action="store_true", help="Disable URL filtering")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing CSV file")
    parser.add_argument("-P", "--path", help="Absolute path for output file")
    parser.add_argument("-o", "--output", default="articles.csv", help="Output filename")
    parser.add_argument("-l", "--limit", type=int, default=10000, 
                       help="Maximum number of results per host (default: 10000)")
    parser.add_argument("-r", "--retries", type=int, default=5,
                       help="Number of retry attempts for API requests (default: 5)")
    parser.add_argument("--timeout", type=int, default=60,
                       help="Timeout for API requests in seconds (default: 60)")
    
    return parser.parse_args()


def get_archived_urls(host, year, limit=10000, max_retries=5, timeout=60):
    """Use the Wayback CDX API to get archived URLs for a host and year."""
    # Clean host - remove protocol if present
    clean_host = host
    if clean_host.startswith(('http://', 'https://')):
        clean_host = re.sub(r'^https?://', '', clean_host)
    
    print(f"Fetching archived URLs for {clean_host} from year {year}...")
    
    # CDX API endpoint
    cdx_url = "https://web.archive.org/cdx/search/cdx"
    
    # Parameters for the CDX request
    params = {
        'url': clean_host,         # The host to search for
        'matchType': 'domain',     # Match the entire domain
        'output': 'json',          # Output in JSON format
        'fl': 'original,timestamp', # Return original URL and timestamp
        'filter': ['!statuscode:404', 'mimetype:text/html'],  # Multiple filters
        'collapse': 'urlkey',      # Remove duplicates
        'limit': limit,            # Maximum results
        'from': f"{year}0101",     # Start date (YYYYMMDD)
        'to': f"{year}1231"        # End date (YYYYMMDD)
    }
    
    # Retry logic for API requests with exponential backoff
    for attempt in range(max_retries):
        try:
            print(f"Request attempt {attempt + 1}/{max_retries}...")
            response = requests.get(cdx_url, params=params, timeout=timeout)
            
            if response.status_code == 200:
                break
                
            print(f"Error: Failed to fetch archives. Status code: {response.status_code}")
            if attempt < max_retries - 1:
                wait_time = 5 * (2 ** attempt)  # Exponential backoff
                print(f"Retrying in {wait_time} seconds...")
                time.sleep(wait_time)
        except requests.exceptions.Timeout:
            print(f"Request timed out on attempt {attempt + 1}")
            if attempt < max_retries - 1:
                wait_time = 5 * (2 ** attempt)
                print(f"Retrying in {wait_time} seconds...")
                time.sleep(wait_time)
        except requests.exceptions.RequestException as e:
            print(f"Request error: {e}")
            if attempt < max_retries - 1:
                wait_time = 5 * (2 ** attempt)
                print(f"Retrying in {wait_time} seconds...")
                time.sleep(wait_time)
    else:
        # All retries failed
        print(f"Failed to fetch archives after {max_retries} attempts.")
        return [], [], clean_host
    
    try:
        # First row is column headers
        results = response.json()
        if not results or len(results) <= 1:
            print(f"No archived URLs found for {clean_host} in {year}")
            return [], [], clean_host
        
        # Skip the header row [0] and extract URLs from the result
        # Each row contains [original_url, timestamp]
        original_urls = []
        archive_urls = []
        for row in results[1:]:
            original_url = row[0]
            timestamp = row[1]
            
            # Remove protocol from original URL if present
            clean_original = original_url
            if clean_original.startswith(('http://', 'https://')):
                clean_original = re.sub(r'^https?://', '', clean_original)
            
            # Construct the archive URL without double protocol
            archive_url = f"https://web.archive.org/web/{timestamp}/{clean_original}"
            
            original_urls.append(original_url)
            archive_urls.append(archive_url)
        
        print(f"Found {len(original_urls)} archived URLs for {clean_host}")
        return original_urls, archive_urls, clean_host
    
    except Exception as e:
        print(f"Error parsing CDX API response: {e}")
        return [], [], clean_host


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
                     re.search(r'/ro/news/\d{4}/\d{2}/\d{2}/$', check_url) or \
                     re.search(r'/(jurnalul-|popcorn-show-)[^/]*/?$', check_url):
                    pass_host_filters = False
                    
            # Filters for nokta.md
            elif 'nokta.md' in host:
                if '/page/' in check_url or '/cdn-cgi/' in check_url:
                    pass_host_filters = False
                    
            # Filter for md.kp.media
            elif 'md.kp.media' in host:
                if '/online/news/' not in check_url and not re.search(r'/daily/\d+/\d+/$', check_url):
                    pass_host_filters = False
                    
            # Filter for evedomosti.md
            elif 'evedomosti.md' in host:
                if '/news/' not in check_url:
                    pass_host_filters = False
                    
            # Filter for gagauzinfo.md
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


def clean_and_filter_urls(original_urls, archive_urls, host, no_filter=False):
    """Clean and filter the URLs."""
    if not original_urls:
        return [], []
        
    # Clean urls - remove query strings
    cleaned_urls = []
    cleaned_archive_urls = []
    url_to_archive = {}  # Map original URLs to their wayback machine (archive) URLs
    
    for i, url in enumerate(original_urls):
        try:
            # Parse URL and remove query string
            parsed_url = urlparse(url)
            clean_url = parsed_url.scheme + '://' + parsed_url.netloc + parsed_url.path
            if not clean_url:  # Skip empty URLs
                continue
            cleaned_urls.append(clean_url)
            cleaned_archive_urls.append(archive_urls[i])
            url_to_archive[clean_url] = archive_urls[i]
        except Exception as e:
            print(f"Error cleaning URL {url}: {e}")
            continue
    
    # Remove duplicates while preserving the archive URL
    unique_urls = list(set(cleaned_urls))
    unique_archive_urls = [url_to_archive[url] for url in unique_urls]
    
    print(f"After cleaning and removing duplicates: {len(unique_urls)} unique URLs.")
    
    # Filter URLs
    filtered_urls, filtered_archive_urls = filter_urls(
        unique_urls, unique_archive_urls, host, no_filter
    )
    
    print(f"After filtering: {len(filtered_urls)} URLs remain.")
    return filtered_urls, filtered_archive_urls


def save_to_csv(urls, archive_urls, host, output_path, overwrite):
    """Save URLs to a CSV file with host, archive URL, and original URL."""
    if not urls:
        print(f"No URLs to save for {host}.")
        return
        
    # Ensure the directory exists
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    
    existing_urls = set()
    mode = 'w' if overwrite else 'a+'
    file_exists = os.path.exists(output_path)
    
    # If we're appending and the file exists, read existing URLs
    if file_exists and not overwrite:
        try:
            with open(output_path, 'r', newline='', encoding='utf-8') as f:
                reader = csv.reader(f)
                next(reader, None)  # Skip header
                for row in reader:
                    if len(row) >= 3:
                        existing_urls.add(row[2])
        except Exception as e:
            print(f"Warning: Error reading existing CSV file: {e}")
    
    with open(output_path, mode, newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        
        # Always write header if we're in write mode or if file doesn't exist
        if overwrite or not file_exists:
            writer.writerow(['host', 'archive', 'url'])
        
        new_count = 0
        for i, url in enumerate(urls):
            if url not in existing_urls:
                writer.writerow([host, archive_urls[i], url])
                new_count += 1
                existing_urls.add(url)
    
    print(f"Added {new_count} new URLs to {output_path}")


def process_host(host, args):
    """Process a single host."""
    try:
        # Get archived URLs
        original_urls, archive_urls, clean_host = get_archived_urls(
            host, args.year, args.limit, args.retries, args.timeout
        )
        
        # Clean and filter URLs
        filtered_urls, filtered_archive_urls = clean_and_filter_urls(
            original_urls, archive_urls, clean_host, args.no_filter
        )
        
        if not filtered_urls:
            print(f"No valid URLs found for {host} after filtering.")
            return False
        
        # Determine output path
        if args.path:
            output_dir = args.path
        else:
            # Find the root directory (one level up from script location)
            script_dir = os.path.dirname(os.path.abspath(__file__))
            root_dir = os.path.dirname(script_dir)
            output_dir = os.path.join(root_dir, 'data')
        
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, args.output)
        
        # Save to CSV
        save_to_csv(filtered_urls, filtered_archive_urls, clean_host, output_path, args.overwrite)
        return True
    except Exception as e:
        print(f"Error processing host {host}: {e}")
        return False


def main():
    args = setup_argparse()
    
    # Handle multiple hosts (comma-separated)
    hosts = args.host.split(',')
    
    if len(hosts) > 1:
        print(f"Processing {len(hosts)} hosts: {', '.join(hosts)}")
    
    success_count = 0
    for host in hosts:
        host = host.strip()
        if host:
            print(f"\n{'=' * 50}\nProcessing host: {host}\n{'=' * 50}")
            if process_host(host, args):
                success_count += 1
    
    if len(hosts) > 1:
        print(f"\nCompleted processing {success_count} out of {len(hosts)} hosts successfully.")


if __name__ == "__main__":
    main()