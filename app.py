import os
import json
from datetime import datetime
from functools import wraps
import calendar
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from flask_mysqldb import MySQL
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv
import requests

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "change-this-secret-key")

app.config["MYSQL_HOST"] = os.getenv("MYSQL_HOST", "localhost")
app.config["MYSQL_USER"] = os.getenv("MYSQL_USER", "root")
app.config["MYSQL_PASSWORD"] = os.getenv("MYSQL_PASSWORD", "")
app.config["MYSQL_DB"] = os.getenv("MYSQL_DB", "daytone_ai")
app.config["MYSQL_PORT"] = int(os.getenv("MYSQL_PORT", "3306"))
app.config["MYSQL_CURSORCLASS"] = "DictCursor"

mysql = MySQL(app)

MOODS = [
    {"name": "Very Low", "emoji": "😢", "score": 1},
    {"name": "Sad", "emoji": "😔", "score": 2},
    {"name": "Neutral", "emoji": "😐", "score": 3},
    {"name": "Okay", "emoji": "🙂", "score": 4},
    {"name": "Good", "emoji": "😊", "score": 5},
    {"name": "Happy", "emoji": "😄", "score": 6},
    {"name": "Excellent", "emoji": "🤩", "score": 7},
]

def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped
def calculate_streak(user_id):
    cursor = mysql.connection.cursor()

    cursor.execute("""
        SELECT DISTINCT DATE(created_at) AS entry_date
        FROM mood_entries
        WHERE user_id = %s
        ORDER BY entry_date DESC
    """, (user_id,))

    rows = cursor.fetchall()
    cursor.close()

    if not rows:
        return 0, 0

    dates = [row["entry_date"] for row in rows]

    today = datetime.now().date()

    current_streak = 0

    if dates[0] == today:
        current_streak = 1

        for i in range(1, len(dates)):
            if dates[i] == dates[i - 1] - timedelta(days=1):
                current_streak += 1
            else:
                break

    longest_streak = 1
    temp_streak = 1

    for i in range(1, len(dates)):
        if dates[i] == dates[i - 1] - timedelta(days=1):
            temp_streak += 1
        else:
            temp_streak = 1

        longest_streak = max(longest_streak, temp_streak)

    return current_streak, longest_streak
def get_user():
    if "user_id" not in session:
        return None
    cur = mysql.connection.cursor()
    cur.execute("SELECT id, name, email FROM users WHERE id=%s", (session["user_id"],))
    user = cur.fetchone()
    cur.close()
    return user

def get_ai_analysis(journal, mood_name, mood_score):
    api_key = os.getenv("GEMINI_API_KEY")

    if not api_key:
        return {
            "stress_level": max(1, min(10, 10 - mood_score)),
            "summary": "AI analysis is not configured yet. Your entry has been saved successfully.",
            "factors": ["AI API key has not been added to the .env file."],
            "suggestions": [
                "Take a few slow, comfortable breaths.",
                "Give yourself a short break and do one manageable task.",
                "Talk to someone you trust if you feel you need support."
            ],
            "note": "Add GEMINI_API_KEY to .env to enable Gemini analysis."
        }

    prompt = f"""
You are DayTone AI, a mental wellness self-reflection assistant.

This is NOT a medical diagnosis system.
Do not diagnose disorders, prescribe medication, or make clinical claims.

Analyze the user's journal and selected mood.

Return ONLY valid JSON with exactly these keys:

stress_level: integer from 1 to 10
summary: short, empathetic summary
factors: array of 2 to 5 short factors that may be contributing
suggestions: array of 4 to 6 practical, safe wellness suggestions
note: one short supportive note

Selected mood: {mood_name}
Mood score: {mood_score}/7

Journal:
{journal}

If the journal indicates possible immediate danger or self-harm,
do not investigate or give harmful instructions.

Instead, encourage contacting a trusted person and appropriate
emergency or professional support.

Keep the response supportive and non-judgmental.
"""

    # Try these models in order.
    models = [
        "gemini-3.5-flash",
        "gemini-3.5-flash-lite",
        "gemini-2.5-flash"
    ]

    for model in models:

        url = (
            f"https://generativelanguage.googleapis.com/"
            f"v1beta/models/{model}:generateContent"
        )

        # Retry temporary server/rate-limit errors
        for attempt in range(3):

            try:
                print(f"Trying Gemini model: {model} (attempt {attempt + 1}/3)")

                response = requests.post(
                    url,
                    params={"key": api_key},
                    json={
                        "contents": [
                            {
                                "parts": [
                                    {
                                        "text": prompt
                                    }
                                ]
                            }
                        ]
                    },
                    timeout=45
                )

                print("Gemini HTTP status:", response.status_code)

                # Temporary server/rate-limit problem
                if response.status_code in [429, 500, 502, 503, 504]:

                    print(
                        f"Gemini temporary error "
                        f"{response.status_code} with {model}"
                    )

                    if attempt < 2:
                        import time
                        time.sleep(2 ** attempt)
                        continue

                    # Try next model
                    break

                # Other HTTP errors
                response.raise_for_status()

                data = response.json()

                candidates = data.get("candidates", [])

                if not candidates:
                    print("Gemini returned no candidates.")
                    break

                text = (
                    candidates[0]
                    .get("content", {})
                    .get("parts", [{}])[0]
                    .get("text", "")
                    .strip()
                )

                if not text:
                    print("Gemini returned empty text.")
                    break

                # Remove Markdown JSON fences if Gemini adds them
                if text.startswith("```"):
                    text = text.replace("```json", "")
                    text = text.replace("```", "")
                    text = text.strip()

                result = json.loads(text)

                # Validate / normalize result
                result["stress_level"] = max(
                    1,
                    min(
                        10,
                        int(result.get("stress_level", 5))
                    )
                )

                result["factors"] = result.get("factors", [])
                result["suggestions"] = result.get("suggestions", [])

                result["summary"] = result.get(
                    "summary",
                    "Your entry was analyzed."
                )

                result["note"] = result.get(
                    "note",
                    "Take things one step at a time."
                )

                print(f"Gemini analysis successful using {model}")

                return result

            except requests.exceptions.Timeout:
                print(f"Gemini timeout with {model}")

                if attempt < 2:
                    import time
                    time.sleep(2 ** attempt)
                    continue

                break

            except requests.exceptions.RequestException as exc:
                print(f"Gemini request error with {model}: {exc}")
                break

            except json.JSONDecodeError as exc:
                print("Gemini returned invalid JSON:", exc)
                print("Gemini response:", text)
                break

            except Exception as exc:
                print("Unexpected Gemini error:", exc)
                break

    # All Gemini models failed
    print("All Gemini models failed. Using local fallback.")

    return {
        "stress_level": max(
            1,
            min(10, 10 - mood_score)
        ),

        "summary": (
            "Your journal was saved, but AI analysis "
            "could not be completed right now."
        ),

        "factors": [
            "The AI service is temporarily unavailable."
        ],

        "suggestions": [
            "Take a short break.",
            "Try slow breathing for a few minutes.",
            "Write down one small thing you can control today.",
            "Reach out to someone you trust if you need support."
        ],

        "note": (
            "Your journal has been saved safely. "
            "Please try the AI analysis again later."
        )
    }
@app.route("/")
def index():
    if "user_id" in session:
        return redirect(url_for("dashboard"))
    return render_template("landing.html")

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if not name or not email or not password:
            flash("Please fill in all fields.", "error")
            return render_template("register.html")

        cur = mysql.connection.cursor()
        cur.execute("SELECT id FROM users WHERE email=%s", (email,))
        if cur.fetchone():
            cur.close()
            flash("An account with this email already exists.", "error")
            return render_template("register.html")

        password_hash = generate_password_hash(password)
        cur.execute(
            "INSERT INTO users (name, email, password_hash) VALUES (%s,%s,%s)",
            (name, email, password_hash)
        )
        mysql.connection.commit()
        cur.close()

        flash("Account created. You can now log in.", "success")
        return redirect(url_for("login"))

    return render_template("register.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        cur = mysql.connection.cursor()
        cur.execute("SELECT id, name, email, password_hash FROM users WHERE email=%s", (email,))
        user = cur.fetchone()
        cur.close()

        if user and check_password_hash(user["password_hash"], password):
            session["user_id"] = user["id"]
            session["user_name"] = user["name"]
            return redirect(url_for("dashboard"))

        flash("Invalid email or password.", "error")

    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))

@app.route("/dashboard")
@login_required
def dashboard():
    user = get_user()
    cur = mysql.connection.cursor()

    cur.execute("""
        SELECT me.mood_name, me.mood_score, me.created_at,
               aa.stress_level, aa.summary
        FROM mood_entries me
        LEFT JOIN ai_analysis aa ON me.analysis_id = aa.id
        WHERE me.user_id=%s
        ORDER BY me.created_at DESC
        LIMIT 7
    """, (session["user_id"],))
    recent = cur.fetchall()

    cur.execute("""
        SELECT me.mood_score, me.mood_name, aa.stress_level, me.created_at
        FROM mood_entries me
        LEFT JOIN ai_analysis aa ON me.analysis_id = aa.id
        WHERE me.user_id=%s
        ORDER BY me.created_at ASC
        LIMIT 30
    """, (session["user_id"],))
    history = cur.fetchall()

    cur.close()

    latest = recent[0] if recent else None

    current_streak, longest_streak = calculate_streak(session["user_id"])

    return render_template(
        "dashboard.html",
        user=user,
        moods=MOODS,
        recent=recent,
        history=history,
        latest=latest,
        current_streak=current_streak,
        longest_streak=longest_streak
    )
@app.route("/journal", methods=["GET", "POST"])
@login_required
def journal():
    if request.method == "POST":
        mood_score = int(request.form.get("mood_score", 0))
        journal_text = request.form.get("journal", "").strip()
        mood = next((m for m in MOODS if m["score"] == mood_score), None)

        if not mood:
            flash("Please select a mood.", "error")
            return redirect(url_for("journal"))
        if len(journal_text) < 10:
            flash("Please write a little more about your day.", "error")
            return redirect(url_for("journal"))

        analysis = get_ai_analysis(journal_text, mood["name"], mood_score)

        cur = mysql.connection.cursor()
        cur.execute(
            "INSERT INTO journals (user_id, journal_text) VALUES (%s,%s)",
            (session["user_id"], journal_text)
        )
        journal_id = cur.lastrowid

        cur.execute("""
            INSERT INTO ai_analysis
            (journal_id, stress_level, summary, factors_json, suggestions_json, note)
            VALUES (%s,%s,%s,%s,%s,%s)
        """, (
            journal_id,
            analysis["stress_level"],
            analysis["summary"],
            json.dumps(analysis["factors"]),
            json.dumps(analysis["suggestions"]),
            analysis["note"]
        ))
        analysis_id = cur.lastrowid

        cur.execute("""
            INSERT INTO mood_entries
            (user_id, mood_name, mood_score, journal_id, analysis_id)
            VALUES (%s,%s,%s,%s,%s)
        """, (
            session["user_id"],
            mood["name"],
            mood_score,
            journal_id,
            analysis_id
        ))

        mysql.connection.commit()
        cur.close()

        session["latest_analysis_id"] = analysis_id
        return redirect(url_for("analysis", analysis_id=analysis_id))

    return render_template("journal.html", moods=MOODS)

@app.route("/analysis/<int:analysis_id>")
@login_required
def analysis(analysis_id):
    cur = mysql.connection.cursor()
    cur.execute("""
        SELECT aa.*, j.journal_text, me.mood_name, me.mood_score
        FROM ai_analysis aa
        JOIN journals j ON aa.journal_id=j.id
        JOIN mood_entries me ON me.analysis_id=aa.id
        WHERE aa.id=%s AND j.user_id=%s
    """, (analysis_id, session["user_id"]))
    result = cur.fetchone()
    cur.close()

    if not result:
        return redirect(url_for("dashboard"))

    result["factors"] = json.loads(result["factors_json"] or "[]")
    result["suggestions"] = json.loads(result["suggestions_json"] or "[]")
    return render_template("analysis.html", result=result)

@app.route("/analytics")
@login_required
def analytics():
    cur = mysql.connection.cursor()
    cur.execute("""
        SELECT mood_name, mood_score, created_at,
               (SELECT stress_level FROM ai_analysis WHERE id=me.analysis_id) AS stress_level
        FROM mood_entries me
        WHERE user_id=%s
        ORDER BY created_at ASC
        LIMIT 90
    """, (session["user_id"],))
    rows = cur.fetchall()
    cur.close()
    return render_template("analytics.html", rows=rows)

@app.route("/api/health")
def health():
    try:
        cur = mysql.connection.cursor()
        cur.execute("SELECT 1")
        cur.fetchone()
        cur.close()
        return jsonify({"status": "ok", "database": "connected"})
    except Exception:
        return jsonify({"status": "error", "database": "not connected"}), 500
@app.route("/calendar")
@login_required
def calendar_view():
    now = datetime.now()

    year = request.args.get("year", default=now.year, type=int)
    month = request.args.get("month", default=now.month, type=int)

    cal = calendar.Calendar(firstweekday=0)
    calendar_weeks = cal.monthdayscalendar(year, month)

    if month == 1:
        prev_month = 12
        prev_year = year - 1
    else:
        prev_month = month - 1
        prev_year = year

    if month == 12:
        next_month = 1
        next_year = year + 1
    else:
        next_month = month + 1
        next_year = year

    month_name = calendar.month_name[month]

    user_id = session["user_id"]

    cursor = mysql.connection.cursor()

    cursor.execute("""
        SELECT
            DAY(me.created_at) AS day,
            me.mood_name,
            me.mood_score,
            CASE me.mood_name
                WHEN 'Very Low' THEN '😢'
                WHEN 'Sad' THEN '😔'
                WHEN 'Neutral' THEN '😐'
                WHEN 'Okay' THEN '🙂'
                WHEN 'Good' THEN '😊'
                WHEN 'Happy' THEN '😄'
                WHEN 'Excellent' THEN '🤩'
                ELSE '🙂'
            END AS mood_emoji,
            aa.stress_level
        FROM mood_entries me
        LEFT JOIN ai_analysis aa
            ON me.analysis_id = aa.id
        WHERE me.user_id = %s
        AND YEAR(me.created_at) = %s
        AND MONTH(me.created_at) = %s
        ORDER BY me.created_at
    """, (user_id, year, month))

    rows = cursor.fetchall()
    cursor.close()

    mood_entries = {}

    for row in rows:
        mood_entries[row["day"]] = {
            "mood_name": row["mood_name"],
            "mood_score": row["mood_score"],
            "mood_emoji": row["mood_emoji"],
            "stress_level": row["stress_level"]
        }

    return render_template(
        "calendar.html",
        calendar_weeks=calendar_weeks,
        mood_entries=mood_entries,
        month_name=month_name,
        year=year,
        prev_month=prev_month,
        prev_year=prev_year,
        next_month=next_month,
        next_year=next_year
    )


if __name__ == "__main__":
    app.run(debug=True)
