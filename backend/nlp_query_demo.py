"""
nlp_query_demo.py
Single-file demo of an NLP Query Engine for Employee Data (simplified).

Requirements:
    pip install fastapi uvicorn jinja2 python-multipart aiofiles cachetools

Run:
    python nlp_query_demo.py
Then open: http://127.0.0.1:8000/
"""

import sqlite3
import re
import os
import csv
import uuid
import json
import time
from typing import Dict, Any, List
from fastapi import FastAPI, UploadFile, File, Form
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.requests import Request
from cachetools import LRUCache
import aiofiles
import asyncio

APP_PORT = 8000
DB_FILE = "demo_employees.db"

app = FastAPI()
templates = Jinja2Templates(directory=".")
app.mount("/static", StaticFiles(directory="."), name="static")

INGEST_STATUS: Dict[str, Dict[str, Any]] = {}
QUERY_CACHE = LRUCache(maxsize=200)


# ----------- DEMO DATABASE CREATION -----------
def ensure_demo_db():
    new_db = not os.path.exists(DB_FILE)
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    if new_db:
        cur.executescript("""
        CREATE TABLE employees (
            emp_id INTEGER PRIMARY KEY,
            full_name TEXT,
            dept_id INTEGER,
            position TEXT,
            annual_salary REAL,
            join_date TEXT,
            office_location TEXT
        );
        CREATE TABLE departments (
            dept_id INTEGER PRIMARY KEY,
            dept_name TEXT,
            manager_id INTEGER
        );
        CREATE TABLE documents (
            doc_id TEXT PRIMARY KEY,
            doc_name TEXT,
            content TEXT,
            uploaded_at REAL
        );
        CREATE TABLE doc_index (
            term TEXT,
            doc_id TEXT
        );
        """)
        employees = [
            (1, "Alice Johnson", 1, "Senior Engineer", 120000, "2023-02-15", "NY"),
            (2, "Bob Smith", 1, "Engineer", 90000, "2022-07-10", "NY"),
            (3, "Charlie Lee", 2, "Manager", 130000, "2020-11-01", "SF"),
            (4, "Diana Prince", 3, "Data Scientist", 115000, "2024-01-20", "Remote"),
            (5, "Evan Garcia", 1, "Engineer", 95000, "2021-06-30", "NY"),
        ]
        departments = [
            (1, "Engineering", 3),
            (2, "Product", 3),
            (3, "Data", 4),
        ]
        cur.executemany("INSERT INTO employees VALUES (?,?,?,?,?,?,?)", employees)
        cur.executemany("INSERT INTO departments VALUES (?,?,?)", departments)
        conn.commit()
    conn.close()


def get_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


ensure_demo_db()


# ----------- SCHEMA DISCOVERY -----------
class SchemaDiscovery:
    @staticmethod
    def analyze_database(connection_string: str = DB_FILE) -> dict:
        conn = sqlite3.connect(connection_string)
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';")
        tables = [r[0] for r in cur.fetchall()]
        schema = {}
        for t in tables:
            cur.execute(f"PRAGMA table_info('{t}')")
            cols = [{"name": r[1], "type": r[2]} for r in cur.fetchall()]
            try:
                cur.execute(f"SELECT * FROM {t} LIMIT 3")
                sample = [dict(zip([c[0] for c in cur.description], r)) for r in cur.fetchall()]
            except Exception:
                sample = []
            relationships = []
            for c in cols:
                if c["name"].endswith("_id") and c["name"] != "emp_id":
                    relationships.append({"column": c["name"], "likely_ref_table": c["name"][:-3]})
            schema[t] = {"columns": cols, "sample": sample, "relationships": relationships}
        conn.close()
        return {"tables": schema, "discovered_at": time.time()}


# ----------- DOCUMENT PROCESSOR -----------
def tokenize(text: str) -> List[str]:
    return re.findall(r"[a-zA-Z0-9\+\#\.\-]+", text.lower())


class DocumentProcessor:
    def __init__(self):
        self.conn = get_connection()

    async def process_documents(self, files: List[UploadFile], job_id: str):
        total = len(files)
        INGEST_STATUS[job_id] = {"total": total, "processed": 0, "done": False}
        for file in files:
            filename = file.filename
            contents = await file.read()
            try:
                text = contents.decode("utf-8")
            except:
                text = contents.decode("latin-1", errors="ignore")
            if filename.lower().endswith(".csv"):
                try:
                    text_lines = text.splitlines()
                    reader = csv.DictReader(text_lines)
                    if 'content' in reader.fieldnames:
                        rows = [r['content'] for r in reader if r.get('content')]
                        content = "\n".join(rows)
                    else:
                        content = "\n".join(text_lines)
                except:
                    content = text
            else:
                content = text
            doc_id = str(uuid.uuid4())
            ts = time.time()
            cur = self.conn.cursor()
            cur.execute("INSERT INTO documents VALUES (?,?,?,?)",
                        (doc_id, filename, content, ts))
            for term in set(tokenize(content)):
                cur.execute("INSERT INTO doc_index VALUES (?,?)", (term, doc_id))
            self.conn.commit()
            INGEST_STATUS[job_id]["processed"] += 1
            await asyncio.sleep(0)
        INGEST_STATUS[job_id]["done"] = True

    def search_documents(self, query: str, top_k: int = 5):
        terms = set(tokenize(query))
        if not terms:
            return []
        conn = get_connection()
        cur = conn.cursor()
        placeholders = ",".join(["?"] * len(terms))
        cur.execute(f"SELECT doc_id, COUNT(*) FROM doc_index WHERE term IN ({placeholders}) GROUP BY doc_id ORDER BY COUNT(*) DESC LIMIT ?",
                    (*terms, top_k))
        rows = cur.fetchall()
        results = []
        for doc_id, hits in rows:
            c2 = conn.cursor()
            c2.execute("SELECT doc_name, content FROM documents WHERE doc_id=?", (doc_id,))
            r = c2.fetchone()
            if r:
                snippet = r[1][:150].replace("\n", " ")
                results.append({"doc_id": doc_id, "doc_name": r[0], "snippet": snippet, "score": hits})
        return results


# ----------- QUERY ENGINE -----------
def simple_query_classifier(q: str) -> str:
    ql = q.lower()
    if "document" in ql or "resume" in ql or "skill" in ql:
        return "doc"
    if "employee" in ql or "salary" in ql or "hired" in ql:
        return "sql"
    return "hybrid"


class QueryEngine:
    def __init__(self):
        self.schema = SchemaDiscovery.analyze_database()
        self.doc_processor = DocumentProcessor()

    def process_query(self, q: str) -> dict:
        qtype = simple_query_classifier(q)
        if (q, qtype) in QUERY_CACHE:
            res = QUERY_CACHE[(q, qtype)]
            res["cached"] = True
            return res
        result = {"query": q, "type": qtype, "cached": False}
        try:
            if qtype == "sql":
                sql, params = self._nl_to_sql(q)
                if not sql:
                    result["results"] = {"error": "No SQL generated"}
                else:
                    conn = get_connection()
                    cur = conn.cursor()
                    cur.execute(sql, params)
                    cols = [c[0] for c in cur.description]
                    rows = [dict(zip(cols, r)) for r in cur.fetchall()]
                    result["results"] = rows
            else:
                result["results"] = self.doc_processor.search_documents(q, 5)
        except Exception as e:
            result["results"] = {"error": str(e)}
        QUERY_CACHE[(q, qtype)] = result
        return result

    def _nl_to_sql(self, q: str):
        ql = q.lower()
        if "how many employees" in ql:
            return ("SELECT COUNT(*) as total FROM employees", [])
        if "average salary by department" in ql:
            return ("SELECT d.dept_name, AVG(e.annual_salary) as avg_salary "
                    "FROM employees e JOIN departments d ON e.dept_id=d.dept_id GROUP BY d.dept_name", [])
        if "top" in ql and "highest paid" in ql:
            m = re.search(r"top (\d+)", ql)
            n = int(m.group(1)) if m else 5
            return ("SELECT * FROM employees ORDER BY annual_salary DESC LIMIT ?", [n])
        if "hired this year" in ql:
            year = str(time.localtime().tm_year)
            return ("SELECT * FROM employees WHERE substr(join_date,1,4)=?", [year])
        return ("SELECT * FROM employees LIMIT 10", [])


qe = QueryEngine()


# ----------- API & UI -----------

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    schema = qe.schema
    html = f"""
    <!doctype html>
    <html>
    <head>
      <title>NLP Query Engine Demo</title>
      <style>
        body {{ font-family: Arial, sans-serif; margin: 24px; }}
        .panel {{ border: 1px solid #ddd; padding: 12px; margin-bottom: 16px; border-radius: 8px; }}
        input[type=text], textarea {{ width: 100%; padding: 8px; box-sizing: border-box; }}
        .small {{ font-size:12px; color:#666; }}
      </style>
    </head>
    <body>
      <h2>NLP Query Engine — Simplified Demo</h2>
      <div class="panel">
        <h3>Discovered Schema</h3>
        <pre>{json.dumps(schema, indent=2)}</pre>
      </div>
      <div class="panel">
        <h3>Upload Documents</h3>
        <form id="uploadForm">
          <input id="files" type="file" name="files" multiple />
          <button type="button" onclick="upload()">Upload</button>
        </form>
        <div id="uploadStatus" class="small"></div>
      </div>
      <div class="panel">
        <h3>Query</h3>
        <input id="q" type="text" placeholder='Try: "How many employees do we have?"'/>
        <button onclick="runQuery()">Run</button>
        <div id="metrics" class="small"></div>
        <pre id="result"></pre>
      </div>
      <script>
        async function upload(){{
          const files = document.getElementById('files').files;
          if(!files.length){{alert('Choose files');return;}}
          const fd=new FormData();
          for(let f of files)fd.append('files',f);
          const r=await fetch('/api/upload-documents',{{method:'POST',body:fd}});
          const j=await r.json();
          document.getElementById('uploadStatus').innerText='Job started: '+j.job_id;
        }}
        async function runQuery(){{
          const q=document.getElementById('q').value;
          if(!q){{alert('Enter a query');return;}}
          const r=await fetch('/api/query',{{method:'POST',headers:{{'content-type':'application/json'}},body:JSON.stringify({{query:q}})}});
          const j=await r.json();
          document.getElementById('result').innerText=JSON.stringify(j,null,2);
        }}
      </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html)


@app.post("/api/upload-documents")
async def upload_documents(files: List[UploadFile] = File(...)):
    job_id = str(uuid.uuid4())
    asyncio.create_task(DocumentProcessor().process_documents(files, job_id))
    return {"job_id": job_id}


@app.get("/api/ingest/status")
async def ingest_status(job_id: str):
    return INGEST_STATUS.get(job_id, {"error": "not found"})


@app.post("/api/query")
async def query(payload: Dict[str, Any]):
    q = payload.get("query", "")
    if not q:
        return {"error": "empty query"}
    return qe.process_query(q)


if __name__ == "__main__":
    import uvicorn
    print("Server running at http://127.0.0.1:8000")
    uvicorn.run("nlp_query_demo:app", host="127.0.0.1", port=APP_PORT, reload=False)
