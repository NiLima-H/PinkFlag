# Codex sust cse hackathon

## Team Profile

* **Team Name:** Pink Flag
* **Deployment Platform:** Render (Web Service)

---

# 1. System & Code Architecture

The microservice is built using **FastAPI** to ensure high performance, asynchronous request handling, and compliance with the hackathon timeout requirements. The system follows a **hybrid architecture**, combining deterministic rule-based reasoning with LLM-assisted analysis while enforcing multiple safety guardrails before returning any response.

## Request Flow

```text
                     +----------------------+
                     | Incoming HTTP Request|
                     +----------+-----------+
                                |
               +----------------+----------------+
               |                                 |
               v                                 v
        GET /health                    POST /analyze-ticket
               |                                 |
               |                         Pydantic Schema Validation
               |                                 |
               |                                 v
               |                      Rule-Based Matching Engine
               |                                 |
               |                                 v
               |                         AI Reasoning Layer
               |                                 |
               |                                 v
               |                     Post-Execution Guardrails
               |                                 |
               +-------------------------> JSON Response
```

## Project Structure

```text
queuestorm-investigator/
├── app/
│   ├── main.py                 # FastAPI application entry
│   ├── models.py               # Pydantic request/response schemas
│   ├── services/
│   │   └── investigator.py     # Core investigation logic
│   └── utils/
│       └── safety.py           # Safety rule checks and fixes
├── requirements.txt            # Python dependencies
├── Dockerfile                  # Containerisation
├── .env.example                # Environment variable template
├── README.md                   # This file
├── SUST_Preli_Sample_Cases.json # Public sample cases (provided)
└── validate_samples.py         # Validation script against sample cases
```

---

# 2. Setup & Installation

## Clone the Repository

```bash
git clone https://github.com/NiLima-H/PinkFlag
cd queuestorm-investigator
```

## Create a Virtual Environment

```bash
python -m venv venv
```

### Activate

**Linux / macOS**

```bash
source venv/bin/activate
```

**Windows**

```bash
venv\Scripts\activate
```

## Install Dependencies

```bash
pip install -r requirements.txt
```

## Configure Environment Variables

```bash
cp .env.example .env
```

Update the `.env` file with your API credentials.

---

# 3. Running the Application

Start the server locally:

```bash
uvicorn app.main:app --reload
```

For deployment (Render):

```bash
uvicorn app.main:app --host 0.0.0.0 --port $PORT
use command 'docker compose up --build'
```
---

# 4. AI & Model Usage

The application uses a hybrid approach:

| Component         | Purpose                                                     |
| ----------------- | ----------------------------------------------------------- |
| Rule-Based Engine | Transaction matching, evidence reasoning, validation        |
| External LLM      | Complaint understanding, response generation, summarization |
| Safety Layer      | Removes unsafe outputs and enforces FinTech policies        |

The AI model is **only used for reasoning assistance**. Critical business decisions such as evidence verification, department routing, severity assessment, and safety validation are handled through deterministic logic.

---

# 5. Safety Guardrails

The system includes multiple FinTech safety protections.

## Credential Protection

The service never asks customers to provide:

* PIN
* OTP
* Password
* Secret credentials

Unsafe responses are automatically rewritten before being returned.

---

## Financial Authority Protection

The system never promises:

* Refund approval
* Payment reversal
* Account unblocking
* Fund recovery

Instead, customers are informed that their case will be reviewed through official channels.

---

## Prompt Injection Defense

User input is treated strictly as structured data.

Instructions embedded inside complaints cannot override the application's internal logic or safety rules.

---

# 6. Assumptions & Limitations

## Assumptions

* Transaction timestamps follow ISO-8601 UTC format.
* Relevant transactions exist within the provided transaction history.
* Synthetic data is used for all testing.

## Known Limitations

* Third-party API rate limits may trigger a safe fallback mode.
* Highly ambiguous multilingual slang may require manual review.
* Extremely incomplete transaction histories may result in an `insufficient_data` verdict.

---

# 7. API Endpoints

## Health Check

### Request

```http
GET /health
```

### Response

```json
{
    "status":"ok"
}
```

---

## Analyze Ticket

### Request

```http
POST /analyze-ticket
```

### Sample Request

```json
{
  "ticket_id": "TKT-10023",
  "complaint": "I sent 5000 taka to a wrong number around 2pm today.",
  "language": "en",
  "channel": "in_app_chat",
  "user_type": "customer",
  "campaign_context": "boishakh_bonanza_day_1",
  "transaction_history": [
    {
      "transaction_id": "TXN-9101",
      "timestamp": "2026-04-14T14:08:22Z",
      "type": "transfer",
      "amount": 5000,
      "counterparty": "+8801719876543",
      "status": "completed"
    }
  ]
}
```

---

## Sample Response

```json
{
  "ticket_id": "TKT-10023",
  "relevant_transaction_id": "TXN-9101",
  "evidence_verdict": "consistent",
  "case_type": "wrong_transfer",
  "severity": "high",
  "department": "dispute_resolution",
  "agent_summary": "Customer reports sending 5000 BDT via TXN-9101 to an unintended recipient.",
  "recommended_next_action": "Verify transaction details and follow official dispute procedures.",
  "customer_reply": "We have received your concern and our dispute resolution team is reviewing the transaction. We will update you through official channels.",
  "human_review_required": true,
  "confidence": 0.95,
  "reason_codes": [
    "wrong_transfer",
    "transaction_match"
  ]
}
```

---

# 8. Business Logic Overview

The investigation pipeline performs the following steps:

1. Match the most relevant transaction using transaction ID, amount, type, recipient, and transaction history.
2. Determine the evidence verdict (`consistent`, `inconsistent`, or `insufficient_data`).
3. Classify the complaint into one of the supported case categories.
4. Route the ticket to the correct department.
5. Calculate severity based on complaint type and transaction information.
6. Generate summaries and customer-facing responses.
7. Apply safety validation.
8. Determine whether human review is required.
9. Estimate confidence and generate reasoning codes.

---

# 9. Submission Checklist

* [x] `/health` endpoint implemented
* [x] `/analyze-ticket` endpoint implemented
* [x] Required schema fields returned
* [x] Correct enum values used
* [x] Safety validation implemented
* [x] No OTP/PIN/password requests
* [x] No unauthorized refund or reversal promises
* [x] Environment variables externalized
* [x] `.env.example` included
* [x] No secrets committed
* [x] README provided

---

# 10. License

This project was developed for the **QueueStorm AI FinTech Support Copilot Hackathon** using synthetic data for educational and evaluation purposes.
