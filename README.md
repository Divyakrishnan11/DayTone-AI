# DayTone AI

AI-powered mental wellness self-reflection web application.

## Stack
- Frontend: HTML, CSS, JavaScript
- Backend: Python Flask
- Database: MySQL
- AI: Google Gemini API
- Charts: Chart.js

## Features
- User registration and login
- Seven daily mood choices
- Daily journal
- AI-based wellness analysis
- Estimated stress level
- Personalized suggestions
- Mood/stress history
- Analytics dashboard
- Password hashing
- User-specific data access

## Run locally

1. Install Python 3.11+.
2. Install MySQL.
3. Create the database using `database/schema.sql`.
4. Copy `.env.example` to `.env`.
5. Fill in MySQL and Gemini credentials.
6. Install dependencies:

   pip install -r requirements.txt

7. Run:

   python app.py

8. Open http://127.0.0.1:5000

## Important
The AI output is intended for wellness self-reflection, not medical diagnosis.
Do not expose your `.env` file or API keys publicly.
