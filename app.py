#!/usr/bin/env python3
"""
Jira Auto Assigner — Flask Web App

Usage:
    cp .env.example .env          # fill in your values
    export $(cat .env | xargs)
    python app.py
    Open http://localhost:5000
"""

import json
import os
import requests
from flask import Flask, jsonify, render_template, request

app = Flask(__name__)

JIRA_BASE_URL     = os.environ.get("JIRA_BASE_URL", "https://your-jira-instance.atlassian.net")
JIRA_EMAIL        = os.environ.get("JIRA_EMAIL", "")
JIRA_USER_DISPLAY = os.environ.get("JIRA_USER_DISPLAY", "auto-assigner")
MAPPINGS_FILE     = os.path.join(os.path.dirname(__file__), "mappings.json")


# ── Auth ──────────────────────────────────────────────────────────────────────

def get_headers():
    token = os.environ.get("JIRA_TOKEN")
    if not token:
        raise EnvironmentError("JIRA_TOKEN environment variable is not set")
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


# ── Jira fetch ────────────────────────────────────────────────────────────────

def fetch_issue(issue_key):
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    url = f"{JIRA_BASE_URL}/rest/api/2/issue/{issue_key}?expand=names"
    try:
        resp = requests.get(url, headers=get_headers(), timeout=15, verify=False)
    except requests.exceptions.ConnectionError as e:
        raise ConnectionError(f"Cannot reach Jira: {e}")

    if resp.status_code == 401:
        resp = requests.get(
            url,
            auth=(JIRA_EMAIL, os.environ.get("JIRA_TOKEN", "")),
            timeout=15,
            verify=False,
        )

    if resp.status_code == 404:
        raise ValueError(f"Ticket '{issue_key}' not found")

    resp.raise_for_status()
    return resp.json()


# ── Field helpers ─────────────────────────────────────────────────────────────

def _extract_value(val):
    if isinstance(val, dict):
        return val.get("value") or val.get("name") or val.get("displayName") or ""
    if isinstance(val, list):
        parts = [
            (v.get("value") or v.get("name") or v.get("displayName") or "")
            if isinstance(v, dict) else str(v)
            for v in val
        ]
        return " ".join(p for p in parts if p)
    return str(val) if val else ""


def find_custom_field(fields, names, *keywords):
    kw = [k.lower() for k in keywords]
    for field_key, display_name in names.items():
        if all(k in display_name.lower() for k in kw):
            val = fields.get(field_key)
            if val is not None:
                return _extract_value(val)
    return ""


# ── Ticket parsing ────────────────────────────────────────────────────────────

def parse_ticket(data):
    fields = data.get("fields", {})
    names  = data.get("names", {})

    components = [c.get("name", "") for c in fields.get("components", [])]
    labels     = fields.get("labels", [])

    return {
        "key":           data.get("key", ""),
        "summary":       fields.get("summary", ""),
        "description":   fields.get("description") or "",
        "status":        (fields.get("status") or {}).get("name", "N/A"),
        "priority":      (fields.get("priority") or {}).get("name", "N/A"),
        "issue_type":    (fields.get("issuetype") or {}).get("name", "N/A"),
        "assignee":      (fields.get("assignee") or {}).get("displayName", "Unassigned"),
        "reporter":      (fields.get("reporter") or {}).get("displayName", "N/A"),
        "created":       (fields.get("created") or "")[:10],
        "updated":       (fields.get("updated") or "")[:10],
        "components":    components,
        "labels":        labels,
        "tech_domain":   find_custom_field(fields, names, "tech", "domain"),
        "fix_versions":  [v.get("name", "") for v in fields.get("fixVersions", [])],
        "epic_link":     find_custom_field(fields, names, "epic", "link") or find_custom_field(fields, names, "epic", "name"),
        "sprint":        find_custom_field(fields, names, "sprint"),
        "story_points":  find_custom_field(fields, names, "story", "point"),
        "project":       (fields.get("project") or {}).get("key", ""),
        "sub_type":      find_custom_field(fields, names, "sub", "type") or find_custom_field(fields, names, "subtype"),
        "is_acceptance": False,
    }


# ── Mapping / matching ────────────────────────────────────────────────────────

def load_mappings():
    if not os.path.exists(MAPPINGS_FILE):
        return []
    with open(MAPPINGS_FILE) as f:
        return json.load(f).get("mappings", [])


def match_engineer(ticket, mappings):
    fields = {
        "summary":     ticket["summary"],
        "description": ticket["description"],
        "tech domain": ticket["tech_domain"],
        "components":  " ".join(ticket["components"]),
        "labels":      " ".join(ticket["labels"]),
    }

    results = []
    for m in mappings:
        keyword_details = []
        for kw in m["keywords"]:
            found_in = [name for name, text in fields.items() if kw.lower() in text.lower()]
            if found_in:
                keyword_details.append({"keyword": kw, "found_in": found_in})

        if not keyword_details:
            continue

        hits = [f'"{d["keyword"]}" in {", ".join(d["found_in"])}' for d in keyword_details]
        reasoning = (
            f'Matched {"; ".join(hits)}. '
            f'This maps to the {m["feature"]} feature area, owned by {m["engineer"]}.'
        )

        results.append({
            "feature":          m["feature"],
            "engineer":         m["engineer"],
            "jira_username":    m.get("jira_username", ""),
            "matched_keywords": [d["keyword"] for d in keyword_details],
            "keyword_details":  keyword_details,
            "match_count":      len(keyword_details),
            "reasoning":        reasoning,
        })

    results.sort(key=lambda r: r["match_count"], reverse=True)
    return results


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/analyze", methods=["POST"])
def analyze():
    body      = request.get_json() or {}
    issue_key = (body.get("ticket_id") or "").strip().upper()

    if not issue_key:
        return jsonify({"error": "Ticket ID is required"}), 400

    try:
        data     = fetch_issue(issue_key)
        ticket   = parse_ticket(data)
        mappings = load_mappings()
        matches  = match_engineer(ticket, mappings)
        best     = matches[0] if matches else {}

        return jsonify({
            "ticket":               ticket,
            "matches":              matches,
            "recommended_engineer": best.get("engineer", ""),
            "jira_username":        best.get("jira_username", ""),
            "matched_feature":      best.get("feature", ""),
            "matched_keywords":     best.get("matched_keywords", []),
            "ticket_url":           f"{JIRA_BASE_URL}/browse/{ticket['key']}",
        })

    except EnvironmentError as e:
        return jsonify({"error": str(e)}), 500
    except ConnectionError as e:
        return jsonify({"error": str(e)}), 503
    except ValueError as e:
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        return jsonify({"error": f"Unexpected error: {e}"}), 500


@app.route("/api/assign", methods=["POST"])
def assign():
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    body            = request.get_json() or {}
    issue_key       = (body.get("ticket_id") or "").strip().upper()
    jira_username   = (body.get("jira_username") or "").strip()
    engineer        = (body.get("engineer") or "").strip()
    feature         = (body.get("feature") or "").strip()
    keyword_details = body.get("keyword_details") or []

    if not issue_key or not jira_username:
        return jsonify({"error": "ticket_id and jira_username are required"}), 400

    try:
        headers = get_headers()

        assign_url = f"{JIRA_BASE_URL}/rest/api/2/issue/{issue_key}/assignee"
        resp = requests.put(assign_url, headers=headers, json={"name": jira_username}, timeout=15, verify=False)
        if resp.status_code == 401:
            resp = requests.put(assign_url, auth=(JIRA_EMAIL, os.environ.get("JIRA_TOKEN", "")),
                                json={"name": jira_username}, timeout=15, verify=False)
        if not resp.ok:
            return jsonify({"error": f"Failed to update assignee: {resp.status_code} — {resp.text}"}), resp.status_code

        comment_url = f"{JIRA_BASE_URL}/rest/api/2/issue/{issue_key}/comment"

        if keyword_details:
            field_map = {}
            for d in keyword_details:
                for f_name in d["found_in"]:
                    field_map.setdefault(f_name, []).append(d["keyword"])

            field_names = list(field_map.keys())
            if len(field_names) == 1:
                fields_str = field_names[0]
            elif len(field_names) == 2:
                fields_str = f"{field_names[0]} and {field_names[1]}"
            else:
                fields_str = ", ".join(field_names[:-1]) + f", and {field_names[-1]}"

            all_kws = list({kw for d in keyword_details for kw in [d["keyword"]]})
            kws_str = " / ".join(f'"{k}"' for k in all_kws)

            reason_paragraph = (
                f"The ticket's {fields_str} consistently reference {feature}-specific terminology ({kws_str}), "
                f"indicating this issue falls within the *{feature}* subsystem. "
                f"Based on the affected component, this has been routed to *{engineer}*, "
                f"the assigned maintainer for this module."
            )
        else:
            reason_paragraph = (
                f"The ticket metadata maps to the *{feature}* subsystem. "
                f"*{engineer}* is the assigned maintainer for this component."
            )

        kw_rows = "\n".join(
            f"| {d['keyword']} | {', '.join(d['found_in'])} |"
            for d in keyword_details
        ) if keyword_details else "| — | — |"

        comment_body = (
            f"*\U0001f916 Jira Auto Assigner*\n"
            f"----\n"
            f"|| \U0001f464 Assigned to || {engineer} ||\n"
            f"|| \U0001f3f7 Feature area || {feature} ||\n"
            f"|| ✅ Status || Auto-assigned ||\n"
            f"\n"
            f"*Reason for assignment*\n"
            f"{reason_paragraph}\n"
            f"\n"
            f"*Keyword Analysis*\n"
            f"|| Keyword || Matched in ||\n"
            f"{kw_rows}\n"
            f"\n"
            f"_(Assigned via Jira Auto Assigner)_"
        )
        requests.post(comment_url, headers=headers, json={"body": comment_body}, timeout=15, verify=False)

        return jsonify({"success": True, "message": f"Assigned to {engineer}."})

    except EnvironmentError as e:
        return jsonify({"error": str(e)}), 500
    except Exception as e:
        return jsonify({"error": f"Unexpected error: {e}"}), 500


@app.route("/api/mappings", methods=["GET"])
def get_mappings():
    return jsonify(load_mappings())


if __name__ == "__main__":
    app.run(debug=True, port=5000)
