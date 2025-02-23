import requests
import mysql.connector
import re
import time
import pymongo
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
from deep_translator import GoogleTranslator
import telebot
import os
import sys
import random
import json
from dotenv import load_dotenv
import firebase_admin
from firebase_admin import credentials, messaging

load_dotenv()
MONGO_URI = os.getenv("MONGO_URI")
mongo_client = pymongo.MongoClient(MONGO_URI)
db = mongo_client["CurrentAffairs"]
collection = db["ScrapedURLs"]
MYSQL_HOST = os.getenv("MYSQL_HOST")
MYSQL_USER = os.getenv("MYSQL_USER")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD")
MYSQL_DATABASE = os.getenv("MYSQL_DATABASE")
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME")
APP_LINK = os.getenv("APP_LINK")
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

print(f"MYSQL_HOST: {MYSQL_HOST}")
print(f"MYSQL_USER: {MYSQL_USER}")
print(f"MYSQL_PASSWORD: {MYSQL_PASSWORD}")
print(f"MYSQL_DATABASE: {MYSQL_DATABASE}")

class FirebaseNotificationSender:
    def __init__(self, service_account_json=None, topic=None):
        try:
            self.fcm_notification_topic = topic or os.getenv('FCM_NOTIFICATION_TOPIC', 'android_news_app_topic')
            self.app = self._initialize_firebase(service_account_json)
            print(f"Using notification topic: {self.fcm_notification_topic}")
            print("Firebase initialized successfully")
        except Exception as e:
            print(f"Initialization error: {e}")
            sys.exit(1)
    
    def _initialize_firebase(self, service_account_json=None):
        try:
            if service_account_json:
                cred_dict = json.loads(service_account_json)
                cred = credentials.Certificate(cred_dict)
                return firebase_admin.initialize_app(cred)
            service_account_env = os.getenv('FIREBASE_SERVICE_ACCOUNT')
            if service_account_env:
                try:
                    cred_dict = json.loads(service_account_env)
                    cred = credentials.Certificate(cred_dict)
                    return firebase_admin.initialize_app(cred)
                except json.JSONDecodeError:
                    print("Error: FIREBASE_SERVICE_ACCOUNT environment variable contains invalid JSON")
            service_account_path_env = os.getenv('FIREBASE_SERVICE_ACCOUNT_PATH')
            if service_account_path_env:
                path = service_account_path_env if os.path.isabs(service_account_path_env) else os.path.join(SCRIPT_DIR, service_account_path_env)
                if os.path.exists(path):
                    cred = credentials.Certificate(path)
                    return firebase_admin.initialize_app(cred)
                print(f"Warning: Service account file not found at {path}")
            default_path = os.path.join(SCRIPT_DIR, 'service-account.json')
            if os.path.exists(default_path):
                print(f"Using service account at: {default_path}")
                cred = credentials.Certificate(default_path)
                return firebase_admin.initialize_app(cred)
            raise ValueError("No valid Firebase credentials found.")
        except Exception as e:
            print(f"Firebase initialization error: {e}")
            sys.exit(1)
    
    def send_notification(self, title, message, image_url=None, link=None, post_id=0):
        try:
            unique_id = str(random.randint(1000, 9999))
            notification = messaging.Notification(title=title, body=message, image=image_url)
            data = {"id": unique_id, "title": title, "message": message, "post_id": str(post_id), "link": link or ""}
            if image_url:
                data["image"] = image_url
            fcm_message = messaging.Message(notification=notification, data=data, topic=self.fcm_notification_topic)
            response = messaging.send(fcm_message)
            print(f"Notification sent successfully. Message ID: {response}")
            return True, response
        except Exception as e:
            error_msg = f"Failed to send notification: {e}"
            print(error_msg)
            return False, error_msg

def get_urls_to_scrape():
    today = datetime.today()
    first_day_of_month = today.replace(day=1)
    urls = []
    for i in range((today - first_day_of_month).days + 1):
        date = first_day_of_month + timedelta(days=i)
        formatted_date = date.strftime('%Y-%m-%d')
        url = f"https://www.indiabix.com/current-affairs/{formatted_date}/"
        if not collection.find_one({"url": url}):
            urls.append(url)
    return urls

def create_mysql_connection():
    try:
        conn = mysql.connector.connect(
            host=MYSQL_HOST,
            user=MYSQL_USER,
            password=MYSQL_PASSWORD,
            database=MYSQL_DATABASE
        )
        print("✅ MySQL connection established successfully")
        return conn
    except mysql.connector.Error as err:
        print(f"❌ MySQL Connection Error: {err}")
        return None

def extract_date_from_url(url):
    date_match = re.search(r'(\d{4}-\d{2}-\d{2})', url)
    if date_match:
        extracted_date = datetime.strptime(date_match.group(0), '%Y-%m-%d')
        return extracted_date.strftime('%d %B %Y'), extracted_date.strftime('%Y-%m-%d')
    return datetime.today().strftime('%d %B %Y'), datetime.today().strftime('%Y-%m-%d')

def scrape_current_affairs_content(url):
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
    attempt = 0
    while attempt < retries:
        try:
            return GoogleTranslator(source='auto', target='gu').translate(text)
        except Exception as e:
            attempt += 1
            print(f"⚠️ Translation attempt {attempt}/{retries} failed: {e}")
            if attempt < retries:
                print(f"⏳ Retrying in {delay} seconds...")
                time.sleep(delay)
            else:
                print("❌ Translation failed after multiple attempts. Returning original text.")
                return text

def format_html_content(questions, formatted_date):
    html_content = f"""
    <div style="text-align: center; font-size: 26px; font-weight: 700; margin: 25px auto; padding: 15px; max-width: 900px; 
                background: linear-gradient(135deg, #6b48ff, #00ddeb); color: white; border-radius: 15px; 
                box-shadow: 0 6px 12px rgba(0,0,0,0.2); position: relative; overflow: hidden;">
        <span style="position: relative; z-index: 1;">📅 {formatted_date}</span>
        <div style="position: absolute; top: 0; left: 0; width: 100%; height: 100%; background: rgba(255,255,255,0.1); 
                    transform: skew(-20deg); z-index: 0;"></div>
    </div>
    <style>
        @import url(https://fonts.googleapis.com/css2?family=Hind+Vadodara:wght@400;600;700&display=swap');
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{ font-family: 'Poppins', sans-serif; line-height: 1.8; color: #2c3e50; background: #f0f4f8; 
                background-image: url('data:image/svg+xml,%3Csvg width="20" height="20" viewBox="0 0 20 20" xmlns="http://www.w3.org/2000/svg"%3E%3Cg fill="%239C92AC" fill-opacity="0.1"%3E%3Cpath d="M10 0a10 10 0 110 20 10 10 0 010-20zm0 2a8 8 0 100 16 8 8 0 000-16z"/%3E%3C/g%3E%3C/svg%3E'); }}
        .qa-container {{ max-width: 900px; margin: 0 auto 50px; padding: 25px; }}
        .title-header {{ text-align: center; margin-bottom: 40px; padding: 25px; background: linear-gradient(45deg, #ff6b6b, #4ecdc4); 
                         color: white; border-radius: 20px; box-shadow: 0 8px 16px rgba(0,0,0,0.15); position: relative; 
                         overflow: hidden; animation: glow 2s infinite alternate; }}
        .title-header h2 {{ font-size: 32px; font-weight: 700; text-transform: uppercase; letter-spacing: 2px; }}
        .title-header p {{ font-size: 20px; font-weight: 600; opacity: 0.9; }}
        .question-box {{ background: white; border-radius: 20px; box-shadow: 0 10px 20px rgba(0,0,0,0.1); margin-bottom: 35px; 
                        padding: 30px; transition: transform 0.3s ease, box-shadow 0.3s ease; border: 2px solid #dfe6e9; 
                        position: relative; overflow: hidden; }}
        .question-box:hover {{ transform: translateY(-5px); box-shadow: 0 15px 30px rgba(0,0,0,0.2); }}
        .question-box::before {{ content: ''; position: absolute; top: -50%; left: -50%; width: 200%; height: 200%; 
                                background: radial-gradient(circle, rgba(107, 72, 255, 0.1), transparent); transform: rotate(45deg); z-index: 0; }}
        .question-header {{ color: #6b48ff; font-size: 24px; font-weight: 700; margin-bottom: 20px; position: relative; z-index: 1; 
                          background: rgba(255,255,255,0.8); padding: 10px; border-radius: 10px; }}
        .option-box {{ padding: 15px; margin: 10px 0; background: #f7f9fc; border-radius: 12px; transition: all 0.3s ease; 
                      border-left: 4px solid #6b48ff; font-weight: 500; position: relative; z-index: 1; }}
        .option-box:hover {{ background: #e9ecef; transform: scale(1.02); }}
        .correct-answer {{ background: linear-gradient(90deg, #00ddeb, #6b48ff); color: white; padding: 15px; margin: 15px 0; 
                         border-radius: 12px; font-weight: 600; position: relative; z-index: 1; animation: pulse 1.5s infinite; }}
        .correct-answer strong {{ color: white; display: block; margin-bottom: 8px; font-size: 18px; }}
        .explanation-box {{ background: #fef9e7; padding: 20px; margin: 15px 0; border-radius: 12px; border-left: 4px solid #f1c40f; 
                          position: relative; z-index: 1; }}
        .explanation-box strong {{ color: #e67e22; display: block; margin-bottom: 10px; font-size: 16px; }}
        @keyframes glow {{ 0% {{ box-shadow: 0 8px 16px rgba(0,0,0,0.15); }} 100% {{ box-shadow: 0 8px 24px rgba(255,107,107,0.4); }} }}
        @keyframes pulse {{ 0% {{ transform: scale(1); }} 50% {{ transform: scale(1.03); }} 100% {{ transform: scale(1); }} }}
        @media (max-width: 600px) {{ 
            .qa-container {{ padding: 15px; }}
            .question-box {{ padding: 20px; }}
            .question-header {{ font-size: 20px; }}
            .title-header h2 {{ font-size: 26px; }}
            .title-header p {{ font-size: 16px; }}
        }}
        .footer {{ text-align: center; padding: 25px; color: #7f8c8d; font-size: 16px; margin-top: 30px; 
                  background: linear-gradient(135deg, #dfe6e9, #ecf0f1); border-radius: 15px; box-shadow: 0 4px 8px rgba(0,0,0,0.1); }}
    </style>
    <div class="qa-container">
    """
    total_questions = len(questions)
    html_content += f"""
    <div class="title-header">
        <h2>📚 ગુજરાતી કરંટ અફેર્સ</h2>
        <p>કુલ પ્રશ્નો: {total_questions}</p>
    </div>
    """
    for idx, question in enumerate(questions, 1):
        translated_question = translate_to_gujarati(question['question_text'])
        translated_answer = translate_to_gujarati(question['correct_answer'])
        translated_explanation = translate_to_gujarati(question['explanation'])
        html_content += f"""
        <div class="question-box">
            <div class="question-header">📝 પ્રશ્ન {idx}</div>
            <div style="margin-bottom: 20px; font-size: 18px; line-height: 1.8; font-weight: 500; position: relative; z-index: 1;">{translated_question}</div>
            <div style="margin: 25px 0;">
        """
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
    html_content += """
        <div class="footer">
            આભાર! આશા રાખીએ છીએ કે આ પ્રશ્નો તમારા જ્ઞાનમાં વધારો કરશે! 🌟
        </div>
    </div>
    """
    return html_content

def insert_news(connection, news_title, news_description, news_image, news_date):
    query = """
    INSERT INTO tbl_news (cat_id, news_title, news_date, news_description, news_image, 
                         news_status, video_url, video_id, content_type, size, view_count, last_update)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """
    data = (1, news_title, news_date, news_description, news_image, 1, "", "", "Post", "", 0, datetime.now())
    try:
        if not connection or not connection.is_connected():
            print("⚠️ MySQL connection lost or not available, attempting to reconnect...")
            connection = create_mysql_connection()
        if connection and connection.is_connected():
            cursor = connection.cursor()
            cursor.execute(query, data)
            connection.commit()
            news_id = cursor.lastrowid
            cursor.close()
            print(f"✅ Data inserted successfully for {news_title} with ID: {news_id}")
            return news_id
        else:
            print("❌ MySQL connection unavailable after retry")
            return None
    except mysql.connector.Error as err:
        print(f"❌ Error inserting data: {err}")
        return None

def send_telegram_message(date, first_question, total_questions):
    translated_question = translate_to_gujarati(first_question['question_text'])
    translated_answer = translate_to_gujarati(first_question['correct_answer'])
    translated_explanation = translate_to_gujarati(first_question['explanation'])
    remaining_questions = total_questions - 1
    message = f"""
🌟 *{date} – ગુજરાતી કરંટ અફેર્સ* 🌟  
───────────────────────────────────

🎯 *આજનો સ્ટાર પ્રશ્ન:*  

❓ **પ્રશ્ન:**  
   {translated_question}  

✅ **જવાબ:**  
   {translated_answer}  

💡 **સમજૂતી:**  
   {translated_explanation}  

───────────────────────────────────  
📚 *આજના કુલ પ્રશ્નો:* {total_questions}  
🔥 *વધુ {remaining_questions} પ્રશ્નો અમારી ચેનલ પર!*  

🔔 *અપડેટ્સ માટે જોડાઓ:*  
   {CHANNEL_USERNAME}  

#CurrentAffairs #GujaratiGK #LearnWithFun
"""
    bot = telebot.TeleBot(BOT_TOKEN)
    bot.send_message(CHANNEL_USERNAME, message, parse_mode="Markdown")

def send_fcm_notification(sender, date, first_question, total_questions, post_id):
    translated_question = translate_to_gujarati(first_question['question_text'])
    title = f"📅 {date} – ગુજરાતી કરંટ અફેર્સ"
    body = f"❓ પ્રશ્ન: {translated_question[:100]}...\n📚 કુલ પ્રશ્નો: {total_questions}"
    success, response = sender.send_notification(
        title=title,
        message=body,
        post_id=post_id
    )
    return success

def main():
    urls_to_scrape = get_urls_to_scrape()
    if not urls_to_scrape:
        print("✅ No new URLs to scrape today.")
        return

    connection = create_mysql_connection()
    if not connection:
        print("❌ Aborting: Failed to establish initial MySQL connection")
        return

    firebase_sender = FirebaseNotificationSender()

    for url in urls_to_scrape:
        formatted_date, news_date = extract_date_from_url(url)
        questions = scrape_current_affairs_content(url)
        if not questions:
            continue

        html_content = format_html_content(questions, formatted_date)
        news_title = f"{formatted_date} Gujarati Current Affairs"
        image_name = f"{formatted_date}.png"

        news_id = insert_news(connection, news_title, html_content, image_name, news_date)
        if news_id:
            collection.insert_one({"url": url, "date": datetime.now()})
            send_telegram_message(formatted_date, questions[0], len(questions))
            success = send_fcm_notification(firebase_sender, formatted_date, questions[0], len(questions), news_id)
            if not success:
                print(f"⚠️ FCM notification failed for {news_title}")

    if connection and connection.is_connected():
        connection.close()
        print("✅ MySQL connection closed")

if __name__ == "__main__":
    main()
