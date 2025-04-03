from playwright.sync_api import sync_playwright
import re
import sys
import json
import os
import logging
import time
import traceback

# Set up logging
logging.basicConfig(level=logging.INFO, 
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Define the uploads directory
UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)  # Ensure the folder exists

def sanitize_filename(title):
    """Remove invalid filename characters and trim excessive spaces."""
    sanitized = re.sub(r'[\\/:*?"<>|]', '', title).strip()
    return sanitized[:50]  # Limit filename length to avoid issues

def run(playwright, chapter_link):
    browser = None
    context = None
    
    try:
        logger.info(f"Starting scraping for URL: {chapter_link}")
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1280, "height": 800})
        page = context.new_page()
        page.set_default_timeout(60000)  # 60 seconds timeout - reduced from 120

        if not chapter_link:
            logger.error("No URL provided")
            print(json.dumps({"error": "No URL provided!"}))
            return

        if not chapter_link.startswith(('http://', 'https://')):
            chapter_link = 'https://' + chapter_link
        
        if 'wattpad.com' not in chapter_link:
            logger.error("Not a Wattpad URL")
            print(json.dumps({"error": "Please enter a valid Wattpad URL"}))
            return

        logger.info(f"Navigating to: {chapter_link}")
        try:
            # Attempt to navigate with a shorter timeout first
            page.goto(chapter_link, timeout=30000, wait_until="domcontentloaded")
            logger.info("Page loaded (domcontentloaded)")
        except Exception as e:
            logger.warning(f"Initial page load failed: {str(e)}, trying with longer timeout")
            # If that fails, try again with a different wait strategy
            page.goto(chapter_link, timeout=45000, wait_until="load")
            logger.info("Page loaded (load event)")
        
        # Wait a bit for any JavaScript to initialize
        page.wait_for_timeout(3000)
        logger.info("Waited for page initialization")
        
        # Try multiple selectors for title elements
        title_selectors = [
            'h1',
            'h1.h5',
            'h2.font-semibold',
            'h1[data-part-title]',
            '.story-parts-title h1',
            '.story-info__title',
            '.part-title',
            '.part-header__title'
        ]
        
        chapter_title = "Untitled Chapter"
        for selector in title_selectors:
            try:
                logger.info(f"Trying title selector: {selector}")
                title_element = page.query_selector(selector)
                if title_element:
                    potential_title = title_element.text_content().strip()
                    if potential_title and potential_title.lower() != "browse" and len(potential_title) > 3:
                        chapter_title = potential_title
                        logger.info(f"Found title with selector {selector}: {chapter_title}")
                        break
            except Exception as e:
                logger.warning(f"Error with title selector {selector}: {str(e)}")
        
        safe_title = sanitize_filename(chapter_title)
        logger.info(f"Using chapter title: {chapter_title}")
        
        # Scroll down the page to ensure all content is loaded
        logger.info("Scrolling through page to load all content...")
        
        # Get the initial height of the page
        initial_height = page.evaluate('document.body.scrollHeight')
        
        # Scroll down in increments to trigger content loading
        last_height = 0
        current_height = initial_height
        max_scroll_attempts = 15  # Reduced from 30 to prevent too much time spent scrolling
        scroll_count = 0
        
        for _ in range(max_scroll_attempts):
            scroll_count += 1
            # Scroll to the bottom of the currently loaded content
            page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
            
            # Wait for any new content to load
            page.wait_for_timeout(500)  # Reduced from 1000ms to 500ms
            
            # Check if we've reached the end (if the height hasn't changed)
            last_height = current_height
            current_height = page.evaluate('document.body.scrollHeight')
            
            logger.info(f"Scroll {scroll_count}: height {current_height} (change: {current_height - last_height})")
            
            if current_height == last_height:
                # If height hasn't changed, wait one more time and check again
                page.wait_for_timeout(1000)
                new_height = page.evaluate('document.body.scrollHeight')
                if new_height == current_height:
                    logger.info("No height change after waiting, ending scroll")
                    break
                current_height = new_height
        
        logger.info(f"Scrolling complete. Page height changed from {initial_height} to {current_height}")
        
        # Try different selectors for paragraph content
        paragraph_selector_options = [
            'pre >> p',
            '.page-content p',
            '.story-parts__part p',
            '.page-read p',
            '.reader-text p',
            '[data-page-number] p',
            '[role="article"] p',
            '.panel-reading p'
        ]
        
        paragraphs = []
        for selector in paragraph_selector_options:
            logger.info(f"Trying paragraph selector: {selector}")
            try:
                paragraph_elements = page.query_selector_all(selector)
                
                # Process paragraphs from this selector
                selector_paragraphs = []
                for p in paragraph_elements:
                    content = p.text_content().strip()
                    if content:
                        # Remove '+' at the end of paragraphs if present
                        if content.endswith('+'):
                            content = content[:-1].strip()
                        selector_paragraphs.append(content)
                
                # If we found a good number of paragraphs, use this selector's results
                if len(selector_paragraphs) > 5:  # Assuming a chapter has at least 5 paragraphs
                    paragraphs = selector_paragraphs
                    logger.info(f"Using selector {selector}, found {len(paragraphs)} paragraphs")
                    break
            except Exception as e:
                logger.warning(f"Error with paragraph selector {selector}: {str(e)}")
        
        if not paragraphs:
            # Last resort: try to get text from all visible paragraph-like elements
            logger.info("Trying generic selector for paragraphs")
            try:
                all_paragraphs = page.query_selector_all('p, .p')
                for p in all_paragraphs:
                    content = p.text_content().strip()
                    if content and len(content) > 20:  # Only include substantial paragraphs
                        if content.endswith('+'):
                            content = content[:-1].strip()
                        paragraphs.append(content)
            except Exception as e:
                logger.warning(f"Error with generic paragraph selector: {str(e)}")
        
        if not paragraphs:
            logger.error("No content found on the page")
            print(json.dumps({"error": "Could not extract content from this Wattpad page."}))
            return
        
        logger.info(f"Extracted {len(paragraphs)} paragraphs")
        
        # JOIN WITH SINGLE NEWLINE INSTEAD OF DOUBLE NEWLINE TO SAVE SPACE
        chapter_text = "\n".join(paragraphs)  # Use single instead of double newline separator
        
        # Use the chapter name as the filename
        filename = f"{safe_title}.txt"
        file_path = os.path.join(UPLOAD_FOLDER, filename)
        
        logger.info(f"Saving content to file: {file_path}")
        with open(file_path, 'w', encoding="utf-8") as file:
            file.write(f"{chapter_title}\n\n")  # Write chapter title first
            file.write(chapter_text)
        
        # Ensure we flush the output before exiting
        result = json.dumps({"title": chapter_title, "filename": filename})
        logger.info(f"Returning result: {result}")
        print(result)
        sys.stdout.flush()

    except Exception as e:
        logger.exception(f"Error during scraping: {str(e)}")
        error_details = {"error": f"Scraping error: {str(e)}", "traceback": traceback.format_exc()}
        print(json.dumps(error_details))
        sys.stdout.flush()
    finally:
        try:
            if context:
                context.close()
            if browser:
                browser.close()
            logger.info("Browser resources cleaned up")
        except Exception as cleanup_error:
            logger.error(f"Error during cleanup: {str(cleanup_error)}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(json.dumps({"error": "No URL provided!"}))
        sys.stdout.flush()
        sys.exit(1)

    chapter_link = sys.argv[1]
    logger.info(f"Starting scrape_wattpad.py with URL: {chapter_link}")

    try:
        with sync_playwright() as playwright:
            run(playwright, chapter_link)
    except Exception as e:
        logger.exception(f"Unhandled exception: {str(e)}")
        error_details = {"error": f"Unhandled exception: {str(e)}", "traceback": traceback.format_exc()}
        print(json.dumps(error_details))
        sys.stdout.flush()
        sys.exit(1)     