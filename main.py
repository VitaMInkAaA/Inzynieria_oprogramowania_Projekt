import os
from psycopg2 import pool
from google import genai
from dotenv import load_dotenv
from datetime import datetime
import cuid
from email.message import EmailMessage
import smtplib
import traceback


# Load environment variables
load_dotenv()

# Retrieve API key and database URL
GEMINI_TOKEN = os.getenv("GEMINI_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
EMAIL = os.getenv("EMAIL")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
L_EMAIL = os.getenv("L_EMAIL")
Y_EMAIL = os.getenv("Y_EMAIL")

# Initialize connection pool for PostgreSQL (NeonDB)
connection_pool = pool.SimpleConnectionPool(
    1, 10,  # Min and max connections in the pool
    dsn=DATABASE_URL  # Ensure it handles SSL settings properly
)

TOPICS_FILE = "topics.txt"
USED_TOPICS_FILE = "used_topics.txt"

def list_tables():
    """
    Fetches and returns all available tables in the PostgreSQL database.
    """
    conn = connection_pool.getconn()
    cur = conn.cursor()

    cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public';")
    tables = [table[0] for table in cur.fetchall()]

    cur.close()
    connection_pool.putconn(conn)
    
    print("Available Tables in Database:", tables)
    return tables

def get_table_columns(table_name):
    """
    Fetches and returns all available columns for a given table.
    """
    conn = connection_pool.getconn()
    cur = conn.cursor()

    cur.execute(f"""
        SELECT column_name FROM information_schema.columns
        WHERE table_name = %s;
    """, (table_name,))

    columns = [col[0] for col in cur.fetchall()]

    cur.close()
    connection_pool.putconn(conn)

    print(f"Available Columns in Table '{table_name}':", columns)
    return columns

def get_unused_topic():
    """
    Reads the topics.txt file and finds an unused topic.
    """
    # Read all topics
    with open(TOPICS_FILE, "r", encoding="utf-8") as f:
        all_topics = [line.strip() for line in f.readlines() if line.strip()]

    # Read used topics
    if os.path.exists(USED_TOPICS_FILE):
        with open(USED_TOPICS_FILE, "r", encoding="utf-8") as f:
            used_topics = set(line.strip() for line in f.readlines())
    else:
        used_topics = set()

    # Find the first unused topic
    for topic in all_topics:
        if topic not in used_topics:
            return topic

    return None  # No unused topics left

def mark_topic_as_used(topic):
    """
    Appends a topic to the used_topics.txt file to track it.
    """
    with open(USED_TOPICS_FILE, "a", encoding="utf-8") as f:
        f.write(topic + "\n")

def generate_blog_post(topic):
    """
    Generates a blog post using Google Gemini AI.
    Returns a tuple containing (slug, date, title, content).
    """
    client = genai.Client(api_key=GEMINI_TOKEN)
    response = client.models.generate_content(
        model="gemini-2.0-pro-exp-02-05",
        contents=f"""
        Stwórz zoptymalizowany pod kątem SEO artykuł blogowy w formacie Markdown.
        Zwróć wynik w formacie:
        
        slug-url(bez słowa markdown, z minusami zamiast spacji, zgodny z składnią path URL) | {datetime.now().date()} | Tytuł artykułu | Treść artykułu (bez nagłówka tytułowego)
        
        Temat artykułu: {topic}
        
        Wytyczne SEO:
        - Długość: 1500-2500 słów
        - Hierarchia nagłówków markdown
        - Słowa kluczowe wplecione naturalnie
        - Struktura dla Featured Snippets
        - Czytelność UX: krótkie akapity, listy punktowane, wyróżnienia
        - Styl: Profesjonalny, ale angażujący
        """
    )

    # Extracting response text
    generated_text = response.text.strip()[3:]
    
    # Splitting data using "|"
    extracted_data = generated_text.split("|")
    
    if len(extracted_data) < 4:
        raise ValueError("Unexpected response format from Gemini AI")

    slug = extracted_data[0].strip()
    date = extracted_data[1].strip()
    title = extracted_data[2].strip()
    content = extracted_data[3].strip()

    return slug, date, title, content

def insert_blog_post(table_name, columns, slug, title, content):
    """
    Inserts the generated blog post into the specified table.
    """
    conn = connection_pool.getconn()
    cur = conn.cursor()

    # Quote the table name to handle case-sensitivity
    table_name = f'"{table_name}"'

    required_fields = ["id", "slug", "title", "date", "content", "createdAt", "updatedAt"]
    available_fields = [col for col in required_fields if col in columns]

    quoted_columns = [f'"{col}"' for col in available_fields]

    insert_query = f"""
        INSERT INTO {table_name} ({', '.join(quoted_columns)})
        VALUES ({', '.join(['%s'] * len(available_fields))})
        RETURNING id;
    """

    generated_id = cuid.cuid()

    values = {
        "id": generated_id,
        "slug": slug,
        "title": title,
        "date": datetime.now().date(),
        "content": content,
        "createdAt": datetime.now(),
        "updatedAt": datetime.now()
    }

    insert_values = [values[col] for col in available_fields]

    cur.execute(insert_query, insert_values)
    post_id = cur.fetchone()[0]

    conn.commit()
    cur.close()
    connection_pool.putconn(conn)

    print(f"Blog post successfully inserted into '{table_name}' with ID: {post_id}")
    return post_id

def generate_and_post_blog():
    """
    Selects an unused topic, generates a blog post, and uploads it to the database.
    """
    topic = get_unused_topic()

    if not topic:
        print("No more unused topics available. Exiting script.")
        return

    tables = list_tables()
    if not tables:
        print("No tables found in the database!")
        return

    target_table = "post" if "post" in tables else tables[0]

    print(f"Using table: {target_table}")

    columns = get_table_columns(target_table)

    slug, date, title, content = generate_blog_post(topic)
    insert_blog_post(target_table, columns, slug, title, content)

    mark_topic_as_used(topic)
    print(f"Topic '{topic}' marked as used.")

def Send_Mail(receiver, subject, text, html=False):
    """
    Sends an email with plain text or HTML content.
    """
    msg = EmailMessage()
    if html:
        msg.set_content(text, subtype='html')
    else:
        msg.set_content(text)

    msg['Subject'] = subject
    msg['From'] = str(EMAIL)
    msg['To'] = receiver

    server = smtplib.SMTP_SSL('ssl0.ovh.net', 465)
    server.login(str(EMAIL), str(EMAIL_PASSWORD))
    server.send_message(msg)
    server.quit()

# Execute script
if __name__ == "__main__":
    try:
        #raise ValueError("This is a test error! Something went wrong in the blog generation process.")
        generate_and_post_blog()
    except Exception as e:
        error_type = type(e).__name__
        error_message = str(e)
        error_traceback = traceback.format_exc()

        # Email formatting in HTML with syntax highlighting
        error_html = f"""
        <html>
        <head>
            <style>
                body {{
                    font-family: 'Arial', sans-serif;
                    background-color: #f4f4f4;
                    padding: 20px;
                }}
                .container {{
                    max-width: 800px;
                    background: #fff;
                    padding: 20px;
                    border-radius: 5px;
                    box-shadow: 0px 0px 10px rgba(0,0,0,0.1);
                }}
                h2 {{
                    color: #d9534f;
                }}
                .error-details {{
                    background: #282c34;
                    color: #abb2bf;
                    padding: 15px;
                    border-radius: 5px;
                    font-family: monospace;
                    white-space: pre-wrap;
                }}
                .timestamp {{
                    color: #5bc0de;
                    font-weight: bold;
                }}
            </style>
        </head>
        <body>
            <div class="container">
                <h2>Blog Publish Error</h2>
                <p><strong>Date:</strong> <span class="timestamp">{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</span></p>
                <p><strong>Error Type:</strong> {error_type}</p>
                <p><strong>Message:</strong> {error_message}</p>
                <p><strong>Traceback:</strong></p>
                <div class="error-details">{error_traceback}</div>
            </div>
        </body>
        </html>
        """

        # Send error email
        Send_Mail(str(L_EMAIL), "Blog Publish Error", error_html, html=True)
        Send_Mail(str(Y_EMAIL), "Blog Publish Error", error_html, html=True)
