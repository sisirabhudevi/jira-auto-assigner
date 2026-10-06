# Jira Auto Assigner

A Flask web app that automatically assigns Jira tickets to the right engineer based on keyword matching against a configurable feature → engineer mapping.

## How it works

1. Enter a Jira ticket ID
2. The app fetches the ticket's metadata (summary, description, components, labels, tech domain)
3. Keywords from `mappings.json` are matched against the metadata
4. The best-matching engineer is recommended with a confidence score
5. After reviewing the comment preview, you confirm — the ticket is assigned and a structured comment is posted to Jira explaining the reasoning

## Setup

**1. Install dependencies**
```bash
pip install -r requirements.txt
```

**2. Configure environment variables**
```bash
cp .env.example .env
# Edit .env with your Jira instance URL, email, and API token
export $(cat .env | xargs)
```

To generate a Jira API token: Jira → Profile → Security → API tokens

**3. Configure engineer mappings**

Edit `mappings.json` to define your feature areas and the engineers who own them:
```json
{
  "mappings": [
    {
      "feature": "Authentication & SSO",
      "keywords": ["auth", "SSO", "SAML", "login", "MFA"],
      "engineer": "Jane Smith",
      "jira_username": "jsmith"
    }
  ]
}
```

**4. Run**
```bash
python app.py
```
Open [http://localhost:5000](http://localhost:5000)

## Features

- Keyword-based matching across summary, description, components, labels, and tech domain
- Confidence meter showing match strength
- Keyword highlighting in ticket description
- Comment preview before posting to Jira
- Animated step-by-step assignment flow
- Before/after assignee display on reassignment
- Structured Jira comment with reasoning and keyword analysis table

## File structure

```
app.py              — Flask backend, Jira API integration
mappings.json       — Feature → engineer config (edit this)
requirements.txt    — Python dependencies
templates/
  index.html        — Frontend (HTML + CSS + JS, no build step)
```

## Tech stack

Python · Flask · Jira REST API v2 · Vanilla JS
