.

📘 NLP Query Engine for Employee Data
🚀 Overview

This project is a simplified Natural Language Query Engine built with FastAPI.
It allows users to query an employee database and uploaded documents using natural language.

Features:

Automatic schema discovery (no hardcoding of tables)

Simple NL → SQL conversion (heuristics)

Document ingestion (TXT, CSV) with keyword search

Hybrid queries across both database + documents

Caching of repeated queries for speed

Minimal web UI (FastAPI + HTML/JS)

⚙️ Setup Instructions
1. Clone the repo
git clone https://github.com/kubraekram/nlp.git
cd nlp

2. Create virtual environment
python -m venv venv
venv\Scripts\activate    # On Windows
# or
source venv/bin/activate # On Mac/Linux

3. Install dependencies
pip install -r requirements.txt

4. Run the server
python backend/nlp_query_demo.py

5. Open in browser

👉 http://127.0.0.1:8000

🖥️ Usage Demo

Schema Discovery
Schema of the SQLite demo DB is shown on homepage.

Upload Documents
Upload sample files from /sample_data (e.g., resume.txt, resume.csv).

Run Queries
Example queries:

SQL

How many employees do we have?

Average salary by department

Document

Show me resumes mentioning Python

Resumes mentioning Java

Hybrid

Employees with Python skills

Show me employees hired this year

Performance

Run same query twice → second time is faster (cache hit).

📂 Project Structure
nlp/
├── backend/
│   └── nlp_query_demo.py     # FastAPI app
├── sample_data/
│   ├── resume.csv            # Example CSV
│   └── resume.txt            # Example TXT
├── requirements.txt          # Dependencies
└── README.md                 # Documentation

🧪 Testing Checklist

✅ SQL queries

✅ Document queries

✅ Hybrid queries

✅ Cache demonstration

✅ Concurrent access (two tabs)

✅ Error handling (e.g., “Show me John”)

🚧 Known Limitations

NL→SQL uses simple rules, not an LLM

Document search = keyword-based (no semantic embeddings)

SQLite only (but extendable to PostgreSQL/MySQL)

Minimal UI

📹 Loom Demo

👉 [Add your Loom video link here]

👩‍💻 Author

Kubra Ekram
