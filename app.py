from flask import Flask, request, jsonify, render_template
import subprocess
import json
import requests
import os
import logging
import re
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Set up logging
logging.basicConfig(level=logging.INFO, 
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__, template_folder='.')

UPLOAD_FOLDER = "uploads"
# Make sure uploads folder exists
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Groq API credentials
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_API_ENDPOINT = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "llama3-8b-8192"  

@app.route('/')
def home():
    return render_template('index.html')

def clean_text(text):
    """Clean up text to reduce token count."""
    # Replace multiple newlines with single newline
    text = re.sub(r'\n\s*\n', '\n', text)
    # Remove excessive spaces
    text = re.sub(r' +', ' ', text)
    # Remove redundant punctuation 
    text = re.sub(r'\.{3,}', '...', text)
    # Strip leading/trailing whitespace
    return text.strip()

def summarize_with_groq(text, chapter_title):
    """Send text to Groq API for summarization."""
    try:
        logger.info(f"Summarizing using Groq API: {chapter_title}")
        
        # Clean and optimize the text
        text = clean_text(text)
        
        # Calculate approximate token count (rough estimate: 4 chars ≈ 1 token)
        estimated_tokens = len(text) // 4
        logger.info(f"Estimated token count: {estimated_tokens}")
        
        # If text is too long, truncate it to fit within limits
        # Llama3-8b-8192 has a context window of about 8192 tokens, but we need room for the prompt and output
        max_input_tokens = 5000  # Allow buffer for prompt and output
        
        if estimated_tokens > max_input_tokens:
            logger.warning(f"Text too long ({estimated_tokens} est. tokens), truncating to ~{max_input_tokens} tokens")
            # Truncate text to approximately max_input_tokens
            text = text[:max_input_tokens * 4]
            logger.info(f"Truncated text to {len(text)} characters")
        
        headers = {
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json"
        }
        
        # Prepare the prompt for the API
        prompt = f"""This is a chapter of a Wattpad story. Read the entire chapter carefully and summarize it in a story format.

        IMPORTANT: Pay special attention to character names, places, and key terms exactly as they appear in the original text. Do not substitute or change any proper nouns. Maintain all character relationships and dynamics exactly as presented.

        Ensure the summary is a rich, immersive retelling that mirrors the original narrative while maintaining its tone, style, and pacing in a seamless flow.

        The summary must be approximately 1000-1500 words long, preserving the authenticity of the original chapter.

        Do not introduce any new storylines, subplots, or additional details that are not in the original text.

        Output only the summary—no introductory or concluding remarks, no explanations about word count, and no analysis.

        Chapter Title: {chapter_title}

        Chapter Content:
        {text}
        """
        
        payload = {
            "model": GROQ_MODEL,
            "messages": [
                {"role": "system", "content": "You are a helpful assistant that provides high-quality summaries of fiction content."},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.7,
            "max_tokens": 1000
        }
        
        logger.info("Sending request to Groq API")
        response = requests.post(GROQ_API_ENDPOINT, headers=headers, json=payload, timeout=60)
        
        if response.status_code != 200:
            logger.error(f"Groq API error: {response.status_code} - {response.text}")
            return None, f"Groq API error: {response.status_code}"
        
        result = response.json()
        summary = result["choices"][0]["message"]["content"]
        
        logger.info(f"Successfully received summary from Groq API, length: {len(summary)} characters")
        return summary, None
        
    except Exception as e:
        logger.exception(f"Error in summarize_with_groq: {str(e)}")
        return None, f"Failed to summarize: {str(e)}"
    
@app.route('/summarize', methods=['POST'])
def summarize_text():
    """Send text file content to Groq API and return the summary."""
    try:
        data = request.json
        filename = data.get("filename", "")
        
        logger.info(f"Summarizing file: {filename}")

        file_path = os.path.join(UPLOAD_FOLDER, filename)
        if not filename or not os.path.exists(file_path):
            logger.error(f"File not found: {file_path}")
            return jsonify({"error": f"File not found: {filename}"}), 400

        with open(file_path, "r", encoding="utf-8") as file:
            content = file.read()
            logger.info(f"Read file content, length: {len(content)} characters")
            
        # Extract the chapter title (first line of the file)
        lines = content.split('\n')
        chapter_title = lines[0].strip()
        
        # The rest is the text content
        text = '\n'.join(lines[1:]).strip()
            
        # Call Groq API for summarization
        summary, error = summarize_with_groq(text, chapter_title)
        
        if error:
            return jsonify({"error": error}), 500
            
        if not summary:
            logger.error("No summary generated from API")
            return jsonify({"error": "No summary generated from API"}), 500
            
        logger.info(f"Generated summary of length: {len(summary)} characters")
        
        # Format the summary to make it more narrative-like
        formatted_summary = summary.replace("\n\n", "<br><br>")
        
        return jsonify({"summary": formatted_summary, "file_path": file_path})
        
    except Exception as e:
        logger.exception(f"Error in summarize_text: {str(e)}")
        return jsonify({"error": f"Failed to summarize: {str(e)}"}), 500

@app.route('/scrape', methods=['POST'])
def scrape():
    try:
        data = request.json
        url = data.get('url', '')

        if not url:
            logger.error("No URL provided")
            return jsonify({"error": "No URL provided"}), 400

        logger.info(f"Scraping URL: {url}")
        
        # Run the scraping script with the URL
        result = subprocess.run(
            ["python3", "scrape_wattpad.py", url], 
            stdout=subprocess.PIPE, 
            stderr=subprocess.PIPE, 
            text=True,
            timeout=300
        )

        # Log the output of the scraping script
        logger.info(f"Scraping script stdout: {result.stdout}")
        if result.stderr:
            logger.warning(f"Scraping script stderr: {result.stderr}")

        if result.returncode != 0:
            logger.error(f"Scraping script failed with return code {result.returncode}")
            return jsonify({
                "error": "Scraping script failed", 
                "details": result.stderr
            }), 500

        # Parse the JSON output from the scraping script
        try:
            scrape_output = json.loads(result.stdout.strip()) if result.stdout.strip() else {}
            
            if "error" in scrape_output:
                logger.error(f"Error from scraping script: {scrape_output['error']}")
                return jsonify({"error": scrape_output["error"]}), 500
                
            chapter_title = scrape_output.get("title", "Untitled Chapter")
            filename = scrape_output.get("filename", "")

            if not filename:
                logger.error("No filename returned from scraping script")
                return jsonify({"error": "Failed to save file - no filename returned"}), 500

            logger.info(f"Successfully scraped chapter: {chapter_title}")
            
            # Get the full file path
            file_path = os.path.join(UPLOAD_FOLDER, filename)
            
            # Call the summarization endpoint
            summary_response = requests.post(
                f"http://{request.host}/summarize",
                json={"filename": filename},
                timeout=300  # Longer timeout for API inference
            )
            
            if summary_response.status_code != 200:
                logger.error(f"Summarization failed: {summary_response.status_code} - {summary_response.text}")
                return jsonify({
                    "error": "Summarization failed", 
                    "details": summary_response.text
                }), 500

            summary_data = summary_response.json()
            
            if "error" in summary_data:
                logger.error(f"Error in summary data: {summary_data['error']}")
                return jsonify({
                    "error": "Summarization error", 
                    "details": summary_data["error"]
                }), 500

            # Now that we have the summary, delete the file
            try:
                if os.path.exists(file_path):
                    os.remove(file_path)
                    logger.info(f"Successfully deleted file: {file_path}")
                else:
                    logger.warning(f"File not found for deletion: {file_path}")
            except Exception as del_err:
                logger.warning(f"Failed to delete file {file_path}: {str(del_err)}")
                # Continue anyway - non-fatal error

            logger.info("Successfully generated summary")
            return jsonify({
                "message": "Scraping and summarization complete!",
                "title": chapter_title,
                "summary": summary_data.get("summary", "Summary not available")
            })

        except json.JSONDecodeError as e:
            logger.exception(f"JSON parsing error: {str(e)}")
            return jsonify({
                "error": "JSON parsing error", 
                "details": str(e),
                "raw_output": result.stdout
            }), 500
            
    except Exception as e:
        logger.exception(f"Unexpected error in scrape: {str(e)}")
        return jsonify({"error": f"An unexpected error occurred: {str(e)}"}), 500

if __name__ == '__main__':
    port = int(os.getenv("PORT", 8080))
    app.run(debug=False, host='0.0.0.0', port=port)
