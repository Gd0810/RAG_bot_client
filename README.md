# Organization RAG Chatbot (Django)

A Django web app with a colorful landing page (hero section + gallery) and an
embedded AI chatbot that answers questions about your organization using
**your own uploaded data** — with two retrieval methods and automatic fallback:

1. **Vector method (primary):** uploaded files are chunked, embedded, and
   stored in **ChromaDB**. User questions are answered via semantic search
   over those embeddings.
2. **Page-Index method (fallback):** uploaded files are also stored as
   page-level entries in a plain JSON index (`media/page_index/page_index.json`).
   If the vector search finds nothing relevant, the app automatically falls
   back to fast keyword-based lookup over this JSON file.

Both methods hand their retrieved context to an **NVIDIA NIM** hosted LLM
(free tier, from [build.nvidia.com](https://build.nvidia.com/models)) to
generate the final natural-language answer. **Two models** are configured —
if the first one errors out or times out, the app automatically retries with
the second model.

Any URL that appears in your source data (e.g. `https://yourorg.com/contact/`)
is preserved by the LLM and rendered as a real clickable link in the chat.

---

## 1. Requirements

- Python 3.10+
- Internet access (only needed to install pip packages and to call the NVIDIA API
  — embeddings run 100% locally/offline, no model downloads required)

## 2. Setup

```bash
# 1. Unzip and enter the project
unzip ragbot_project.zip
cd ragbot_project

# 2. Create & activate a virtual environment
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment variables
cp .env.example .env
# now open .env and paste your NVIDIA_API_KEY (see step 3 below)

# 5. Run migrations
python manage.py makemigrations
python manage.py migrate

# 6. Create an admin account
python manage.py createsuperuser

# 7. Run the server
python manage.py runserver
```

Then open:
- **Landing page + chatbot:** http://127.0.0.1:8000/
- **Admin dashboard:** http://127.0.0.1:8000/admin/

On Windows, you can instead double-click `run_local.bat`. It starts Django and
opens the landing page using HTTP. Do not change the address to `https://`;
the Django development server does not provide HTTPS.

## 3. Get your free NVIDIA API key

1. Go to https://build.nvidia.com/models
2. Sign in / sign up (free)
3. Pick any two text-generation / chat models you like — for example
   `nvidia/llama-3.1-nemotron-70b-instruct` and
   `meta/llama-3.1-8b-instruct`. Browse the model catalog for other
   options and copy their exact model IDs.
4. Click **"Get API Key"** on the model page to generate a personal API key.
5. Open `.env` and set:
   ```
   NVIDIA_MODEL_PRIMARY=nvidia/llama-3.1-nemotron-70b-instruct
   NVIDIA_API_KEY_PRIMARY=nvapi-xxxxxx...

   NVIDIA_MODEL_FALLBACK=meta/llama-3.1-8b-instruct
   NVIDIA_API_KEY_FALLBACK=nvapi-yyyyyy...
   ```
   Each model has its own API key field so you can use keys from 2 separate build.nvidia accounts.

If the primary model call ever fails (rate-limited, down, bad response), the
app automatically retries the same question with the fallback model — you
don't need to do anything.

## 4. Add your organization's data

### A. Organization profile (hero section)
Go to **Admin → Organization Profile** and fill in:
- Name, tagline, "about" paragraph
- Hero image / gallery images (optional — clean placeholder images are shown
  automatically if you leave these blank)
- Contact email, website URL
- Theme color (5 light color themes available — teal, indigo, sunset, ocean,
  rose. No dark/black themes, by design.)

### B. Knowledge documents (what the chatbot knows)
Go to **Admin → Knowledge Documents → Add Knowledge Document** and upload
either:
- a **`.txt`** file — free-form text about your organization, services, FAQs,
  policies, contact info, etc.
- a **`.json`** file — structured data (e.g. FAQs, service lists, social
  links). Any shape of JSON is supported; it's automatically flattened into
  readable text before indexing.

As soon as you save, the file is automatically:
1. Chunked and embedded into ChromaDB (vector method), and
2. Split into page-level entries and appended to the shared page-index
   JSON file (fallback method).

You'll see a success/error message in the admin confirming how many chunks
were created. Upload as many documents as you like — everything accumulates
into the same knowledge base. Editing an existing document's file and
re-saving automatically re-indexes it (removing the old entries first).

**Tip:** include real URLs in your text/JSON (e.g. your contact page,
booking page, social links) — the chatbot will surface them as clickable
links whenever they're relevant to a user's question.

## 5. Chat with your assistant

Visit the landing page, scroll to (or click) **"Ask our AI"**, and start
asking questions about your organization. Each answer shows a small caption
indicating whether it was answered via the vector method or the page-index
fallback, plus which model generated it.

---

## How the fallback logic works

```
User question
     │
     ▼
Vector search (ChromaDB, cosine similarity)
     │
     ├── good match found (distance below threshold) ──► use these chunks
     │
     └── no match / all matches too weak
                │
                ▼
        Page-Index fallback (fast keyword search over page_index.json)
                │
                ▼
        Context (from whichever method succeeded) + question
                │
                ▼
        NVIDIA LLM (primary model → fallback model on error)
                │
                ▼
        Answer, with any source URLs turned into clickable links
```

You can tune the vector similarity threshold and how many chunks/pages are
retrieved via `VECTOR_TOP_K`, `VECTOR_DISTANCE_THRESHOLD`, and
`PAGE_INDEX_TOP_K` in `.env`.

## Notes on the embedding model

This project uses a small, fully **offline, deterministic** embedding
function (`orgbot/services/embeddings.py`) instead of downloading a
sentence-transformers/ONNX model from the internet. This means:
- Zero extra downloads, zero heavy ML dependencies (no `torch`), and it
  works identically every time, on any machine, with no internet
  required for embeddings.
- It's a bag-of-words / feature-hashing vectorizer, which works well for
  fact-heavy organizational content (FAQs, contact info, service lists)
  where keyword overlap is a strong relevance signal.

If you later want true semantic embeddings, you can swap in
`sentence-transformers`, an NVIDIA embedding model, or any other embedding
function — only `orgbot/services/embeddings.py` needs to change; the rest
of the RAG pipeline (chunking, storage, fallback logic) stays the same.

## Project structure

```
ragbot_project/
├── manage.py
├── requirements.txt
├── .env.example              # copy to .env and fill in your NVIDIA_API_KEY
├── ragbot/                    # Django project settings/urls
└── orgbot/                    # main app
    ├── models.py               # OrganizationProfile, KnowledgeDocument
    ├── admin.py                # admin + auto-processing on upload
    ├── views.py                # landing page + chat API
    ├── services/
    │   ├── chunking.py          # text/JSON chunking
    │   ├── embeddings.py        # offline hashing embedding function
    │   ├── vector_store.py      # ChromaDB wrapper (method 1)
    │   ├── page_index.py        # JSON keyword fallback (method 2)
    │   ├── ingestion.py         # orchestrates upload -> both stores
    │   ├── llm_client.py        # NVIDIA API, dual-model fallback
    │   ├── rag_engine.py        # vector-first, page-index-fallback logic
    │   └── utils.py             # safe HTML escape + URL linkification
    ├── templates/orgbot/        # landing.html, base.html
    └── static/orgbot/           # style.css, chat.js
```

## Troubleshooting

- **"NVIDIA_API_KEY is not set"** — make sure you copied `.env.example` to
  `.env` and pasted a real key.
- **Both models fail** — double check the exact model ID strings on
  https://build.nvidia.com/models (they're case-sensitive, e.g.
  `meta/llama-3.1-8b-instruct`).
- **Chatbot says it doesn't know something** — upload more `.txt`/`.json`
  documents covering that topic via the admin; the more detail you provide,
  the better the answers.
