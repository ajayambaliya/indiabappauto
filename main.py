import requests
import mysql.connector
import re
import time
import pymongo
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
from deep_translator import GoogleTranslator
import telebot
import time
import os


# MongoDB Configuration
MONGO_URI = os.getenv("MONGO_URI")
mongo_client = pymongo.MongoClient(MONGO_URI)
db = mongo_client["CurrentAffairs"]
collection = db["ScrapedURLs"]

# MySQL Configuration
MYSQL_HOST = os.getenv("MYSQL_HOST")
MYSQL_USER = os.getenv("MYSQL_USER")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD")
MYSQL_DATABASE = os.getenv("MYSQL_DATABASE")

# Telegram Configuration
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME")
APP_LINK = os.getenv("APP_LINK")

def get_urls_to_scrape():
    """Generate URLs for the current month up to today's date, filtering already scraped URLs from MongoDB."""
    today = datetime.today()
    first_day_of_month = today.replace(day=1)
    
    urls = []
    for i in range((today - first_day_of_month).days + 1):
        date = first_day_of_month + timedelta(days=i)
        formatted_date = date.strftime('%Y-%m-%d')
        url = f"https://www.indiabix.com/current-affairs/{formatted_date}/"
        
        # Check if the URL already exists in MongoDB
        if not collection.find_one({"url": url}):
            urls.append(url)
    
    return urls

def create_mysql_connection():
    """Establish and return a MySQL connection."""
    try:
        return mysql.connector.connect(
            host=MYSQL_HOST,
            user=MYSQL_USER,
            password=MYSQL_PASSWORD,
            database=MYSQL_DATABASE
        )
    except mysql.connector.Error as err:
        print(f"❌ MySQL Connection Error: {err}")
        return None

def extract_date_from_url(url):
    """Extracts the date from the given URL and formats it."""
    date_match = re.search(r'(\d{4}-\d{2}-\d{2})', url)
    if date_match:
        extracted_date = datetime.strptime(date_match.group(0), '%Y-%m-%d')
        return extracted_date.strftime('%d %B %Y'), extracted_date.strftime('%Y-%m-%d')
    return datetime.today().strftime('%d %B %Y'), datetime.today().strftime('%Y-%m-%d')

def scrape_current_affairs_content(url):
    """Scrape content from the URL."""
    try:
        print(f"🔍 Scraping content from: {url}")
        response = requests.get(url, verify=False)
        soup = BeautifulSoup(response.text, 'html.parser')

        question_containers = soup.find_all('div', class_='bix-div-container')
        if not question_containers:
            print(f"⚠️ No content found for {url}, skipping...")
            return None

        questions = []
        for container in question_containers:
            try:
                question_text_div = container.find('div', class_='bix-td-qtxt')
                correct_answer_key = container.find('input', {'class': 'jq-hdnakq'}).get('value', '').strip()
                options = container.find_all('div', class_='bix-td-option-val')
                option_map = {chr(65 + idx): option.text.strip() for idx, option in enumerate(options)}
                correct_answer_text = option_map.get(correct_answer_key, "Unknown")
                explanation_div = container.find('div', class_='bix-ans-description')
                explanation_text = explanation_div.text.strip() if explanation_div else "No explanation available"
                question_text = question_text_div.text.strip() if question_text_div else "No question text"

                questions.append({
                    'question_text': question_text,
                    'correct_answer': correct_answer_text,
                    'explanation': explanation_text,
                    'options': option_map
                })
            except Exception as e:
                print(f"⚠️ Error processing question: {e}")

        return questions
    except Exception as e:
        print(f"❌ Error scraping content from {url}: {e}")
        return None

def translate_to_gujarati(text, retries=3, delay=5):
    """Translate text to Gujarati with retries and fallback."""
    attempt = 0
    while attempt < retries:
        try:
            # Attempt translation
            return GoogleTranslator(source='auto', target='gu').translate(text)
        except Exception as e:
            attempt += 1
            print(f"⚠️ Translation attempt {attempt}/{retries} failed: {e}")
            if attempt < retries:
                print(f"⏳ Retrying in {delay} seconds...")
                time.sleep(delay)  # Wait before retrying
            else:
                print("❌ Translation failed after multiple attempts. Returning original text.")
                return text  # Return original text if all retries fail

def format_html_content(questions, formatted_date):
    """Format content as HTML with date and responsive design."""
    # First, add the date clearly at the top
    html_content = f"""
    <div style="text-align: center; font-size: 24px; margin: 20px 0; padding: 10px; background-color: #f8f9fa; border-radius: 8px;">
        📅 {formatted_date}
    </div>
    """
    
    # Add CSS styles for the rest of the content
    html_content += """
    <style>
        .qa-container {
            max-width: 800px;
            margin: 0 auto;
            padding: 15px;
            font-family: Arial, sans-serif;
        }
        .question-box {
            background-color: #ffffff;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            margin-bottom: 20px;
            padding: 20px;
        }
        .question-header {
            color: #1a237e;
            font-size: 18px;
            margin-bottom: 15px;
            font-weight: bold;
        }
        .option-box {
            padding: 10px;
            margin: 5px 0;
            background-color: #f8f9fa;
            border-radius: 4px;
        }
        .correct-answer {
            background-color: #e8f5e9;
            color: #2e7d32;
            padding: 10px;
            margin: 10px 0;
            border-radius: 4px;
        }
        .explanation-box {
            background-color: #fff3e0;
            padding: 15px;
            margin: 10px 0;
            border-radius: 4px;
        }
        @media (max-width: 600px) {
            .qa-container {
                padding: 10px;
            }
            .question-box {
                padding: 15px;
            }
        }
    </style>
    <div class="qa-container">
    """

    # Add total questions count
    total_questions = len(questions)
    html_content += f"""
    <div style="text-align: center; margin-bottom: 20px; padding: 10px; background-color: #1a237e; color: white; border-radius: 8px;">
        <h2>📚 ગુજરાતી કરંટ અફેર્સ</h2>
        <p>કુલ પ્રશ્નો: {total_questions}</p>
    </div>
    """

    # Add each question
    for idx, question in enumerate(questions, 1):
        translated_question = translate_to_gujarati(question['question_text'])
        translated_answer = translate_to_gujarati(question['correct_answer'])
        translated_explanation = translate_to_gujarati(question['explanation'])
        
        html_content += f"""
        <div class="question-box">
            <div class="question-header">📝 પ્રશ્ન {idx}</div>
            <div style="margin-bottom: 15px;">{translated_question}</div>
            
            <div style="margin: 15px 0;">
        """
        
        # Add options
        for option_key, option_value in question['options'].items():
            translated_option = translate_to_gujarati(option_value)
            is_correct = option_value == question['correct_answer']
            option_style = 'correct-answer' if is_correct else 'option-box'
            html_content += f"""
                <div class="{option_style}">
                    {option_key}) {translated_option}
                </div>
            """

        html_content += f"""
            </div>
            <div class="correct-answer">
                <strong>✅ સાચો જવાબ:</strong> {translated_answer}
            </div>
            <div class="explanation-box">
                <strong>💡 સમજૂતી:</strong> {translated_explanation}
            </div>
        </div>
        """
        time.sleep(1)

    html_content += "</div>"
    return html_content

def insert_news(connection, news_title, news_description, news_image, news_date):
    """Insert the news data into MySQL."""
    query = """
    INSERT INTO tbl_news (cat_id, news_title, news_date, news_description, news_image, 
                         news_status, video_url, video_id, content_type, size, view_count, last_update)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """

    data = (1, news_title, news_date, news_description, news_image, 10, "", "", "Post", "", 0, datetime.now())

    try:
        connection = create_mysql_connection()
        if connection:
            cursor = connection.cursor()
            cursor.execute(query, data)
            connection.commit()
            cursor.close()
            print(f"✅ Data inserted successfully for {news_title}")
    except mysql.connector.Error as err:
        print(f"❌ Error inserting data: {err}")

def send_telegram_message(date, first_question, total_questions):
    """Send a formatted message to Telegram channel with question count."""
    translated_question = translate_to_gujarati(first_question['question_text'])
    translated_answer = translate_to_gujarati(first_question['correct_answer'])
    translated_explanation = translate_to_gujarati(first_question['explanation'])

    remaining_questions = total_questions - 1

    message = f"""
📅 **{date} – ગુજરાતી કરંટ અફેર્સ** 🇮🇳

🎯 **આજનો મુખ્ય પ્રશ્ન:**

❓ **પ્રશ્ન:** {translated_question}

✅ **જવાબ:** {translated_answer}

💡 **સમજૂતી:** {translated_explanation}

📚 **આજના કુલ પ્રશ્નો:** {total_questions}
🔍 **વધુ {remaining_questions} પ્રશ્નો વાંચવા માટે એપ ડાઉનલોડ કરો!**

📱 **એપ ડાઉનલોડ કરો:** [👉 અહીં ક્લિક કરો]({APP_LINK})

🔔 **અપડેટ્સ માટે અમારી ટેલિગ્રામ ચેનલ જોઈન કરો:**
📢 {CHANNEL_USERNAME}

#CurrentAffairs #GujaratiGK #CompetitiveExams
"""

    bot = telebot.TeleBot(BOT_TOKEN)
    bot.send_message(CHANNEL_USERNAME, message, parse_mode="Markdown")

def main():
    """Main execution function."""
    urls_to_scrape = get_urls_to_scrape()
    if not urls_to_scrape:
        print("✅ No new URLs to scrape today.")
        return

    connection = create_mysql_connection()
    for url in urls_to_scrape:
        formatted_date, news_date = extract_date_from_url(url)
        questions = scrape_current_affairs_content(url)

        if not questions:
            continue

        html_content = format_html_content(questions, formatted_date)
        news_title = f"{formatted_date} Gujarati Current Affairs"
        image_name = f"{formatted_date}.png"

        insert_news(connection, news_title, html_content, image_name, news_date)
        collection.insert_one({"url": url, "date": datetime.now()})
        
        send_telegram_message(formatted_date, questions[0], len(questions))

    if connection:
        connection.close()

if __name__ == "__main__":
    main()
