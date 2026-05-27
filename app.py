import os
import json
from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
from anthropic import Anthropic
from datetime import datetime, timedelta

app = Flask(__name__)
CORS(app, origins=["https://louvrlabs.com", "http://localhost:*"])

anthropic = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

META_API_VERSION = "v21.0"
META_BASE = f"https://graph.facebook.com/{META_API_VERSION}"

CREATIVE_FIELDS = "name,status,effective_status,created_time,updated_time"
INSIGHT_FIELDS = "ad_id,ad_name,impressions,clicks,spend,ctr,cpm,cpp,reach,frequency,actions,action_values,cost_per_action_type"
INSIGHT_PERIOD = "last_7d"


def get_meta_ads(account_id, token):
    """Pull ads + insights from Meta Ads API."""
    
    # Normalize account ID
    if not account_id.startswith("act_"):
        account_id = f"act_{account_id}"

    # 1. Get active ads
    ads_url = f"{META_BASE}/{account_id}/ads"
    ads_resp = requests.get(ads_url, params={
        "access_token": token,
        "fields": f"{CREATIVE_FIELDS},creative{{thumbnail_url,effective_instagram_story_id,object_story_spec}}",
        "effective_status": json.dumps(["ACTIVE", "PAUSED"]),
        "limit": 20
    })

    if ads_resp.status_code != 200:
        error = ads_resp.json().get("error", {})
        return None, f"Meta API error: {error.get('message', ads_resp.text)}"

    ads_data = ads_resp.json().get("data", [])
    if not ads_data:
        return None, "NO_ADS"

    # 2. Get insights for each ad
    insights_url = f"{META_BASE}/{account_id}/insights"
    insights_resp = requests.get(insights_url, params={
        "access_token": token,
        "fields": INSIGHT_FIELDS,
        "date_preset": INSIGHT_PERIOD,
        "level": "ad",
        "limit": 50
    })

    insights_by_ad = {}
    if insights_resp.status_code == 200:
        for row in insights_resp.json().get("data", []):
            insights_by_ad[row["ad_id"]] = row

    # 3. Merge ads + insights
    creatives = []
    for ad in ads_data:
        ad_id = ad["id"]
        ins = insights_by_ad.get(ad_id, {})

        spend = float(ins.get("spend", 0))
        clicks = int(ins.get("clicks", 0))
        impressions = int(ins.get("impressions", 0))
        reach = int(ins.get("reach", 0))
        frequency = float(ins.get("frequency", 0))
        ctr = float(ins.get("ctr", 0))
        cpm = float(ins.get("cpm", 0))

        # Calculate ROAS from action_values
        roas = 0
        purchase_value = 0
        for av in ins.get("action_values", []):
            if av.get("action_type") == "offsite_conversion.fb_pixel_purchase":
                purchase_value = float(av.get("value", 0))
        if spend > 0 and purchase_value > 0:
            roas = round(purchase_value / spend, 2)

        # Get purchases
        purchases = 0
        for action in ins.get("actions", []):
            if action.get("action_type") == "offsite_conversion.fb_pixel_purchase":
                purchases = int(action.get("value", 0))

        creatives.append({
            "id": ad_id,
            "name": ad.get("name", "Unnamed ad"),
            "status": ad.get("effective_status", "UNKNOWN"),
            "thumbnail": ad.get("creative", {}).get("thumbnail_url", ""),
            "spend": spend,
            "impressions": impressions,
            "reach": reach,
            "clicks": clicks,
            "ctr": round(ctr, 2),
            "cpm": round(cpm, 2),
            "frequency": round(frequency, 2),
            "roas": roas,
            "purchases": purchases,
            "purchase_value": round(purchase_value, 2),
            "has_data": spend > 0
        })

    # Sort by ROAS descending, then by spend
    creatives.sort(key=lambda x: (x["roas"], x["spend"]), reverse=True)

    # Add rank
    for i, c in enumerate(creatives):
        c["rank"] = i + 1

    return creatives, None


def analyze_with_claude(creatives, account_id):
    """Send creative data to Claude for analysis."""

    # Build a clean summary for Claude
    summary_lines = []
    for c in creatives:
        line = (
            f"#{c['rank']} {c['name']} | "
            f"ROAS: {c['roas']}x | CTR: {c['ctr']}% | "
            f"Spend: €{c['spend']} | CPM: €{c['cpm']} | "
            f"Frequency: {c['frequency']} | Status: {c['status']}"
        )
        summary_lines.append(line)

    total_spend = sum(c["spend"] for c in creatives)
    total_purchases = sum(c["purchases"] for c in creatives)
    avg_roas = round(sum(c["roas"] for c in creatives if c["roas"] > 0) / max(len([c for c in creatives if c["roas"] > 0]), 1), 2)

    prompt = f"""You are a Meta Ads performance analyst. Analyze this ad account data and return a JSON response.

Account: {account_id}
Week: {datetime.now().strftime('%d %B %Y')}
Total spend: €{total_spend:.2f}
Average ROAS: {avg_roas}x
Total purchases: {total_purchases}

Creatives ranked by performance:
{chr(10).join(summary_lines)}

Return ONLY valid JSON with this exact structure:
{{
  "summary": "2-3 sentence executive summary of account performance",
  "overall_roas": {avg_roas},
  "total_spend": {total_spend:.2f},
  "week_label": "{datetime.now().strftime('Week of %d %b')}",
  "creatives": [
    {{
      "rank": 1,
      "id": "ad_id_here",
      "why_performing": "1-2 sentences explaining why this ad performs as it does",
      "action": "Scale +20%" ,
      "action_type": "scale"
    }}
  ],
  "actions": [
    {{
      "priority": "high",
      "title": "Action title",
      "detail": "Specific step-by-step instruction",
      "why": "Data-backed reason"
    }}
  ],
  "insights": [
    {{
      "type": "creative",
      "title": "Insight title",
      "body": "2-3 sentence insight"
    }}
  ]
}}

For action_type use: "scale", "hold", "refresh", "pause", "test"
For insight type use: "creative", "audience", "budget", "format"
Provide exactly 3 actions and 3-4 insights. Be specific with numbers from the data."""

    message = anthropic.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}]
    )

    raw = message.content[0].text.strip()
    # Strip markdown fences if present
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip()

    return json.loads(raw)


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "service": "louvr-performance-api"})


@app.route("/api/report", methods=["POST"])
def generate_report():
    """
    Main endpoint. Called from account.html when user clicks 'Connect & run report'.
    Body: { "token": "...", "account_id": "..." }
    """
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data provided"}), 400

    token = data.get("token", "").strip()
    account_id = data.get("account_id", "").strip()

    if not token or not account_id:
        return jsonify({"error": "token and account_id are required"}), 400

    # 1. Pull data from Meta
    creatives, error = get_meta_ads(account_id, token)

    if error == "NO_ADS":
        return jsonify({
            "error": "no_ads",
            "message": "No active or paused ads found in this account. Run some campaigns first."
        }), 404

    if error:
        return jsonify({"error": "meta_api_error", "message": error}), 400

    # Filter only ads with spend data
    creatives_with_data = [c for c in creatives if c["has_data"]]
    if not creatives_with_data:
        return jsonify({
            "error": "no_spend_data",
            "message": "Ads found but no spend data in the last 7 days. Make sure campaigns were active this week."
        }), 404

    # 2. Analyze with Claude
    try:
        analysis = analyze_with_claude(creatives_with_data[:8], account_id)
    except Exception as e:
        return jsonify({"error": "claude_error", "message": str(e)}), 500

    # 3. Merge Claude analysis back into creatives
    analysis_by_rank = {c["rank"]: c for c in analysis.get("creatives", [])}
    for creative in creatives_with_data:
        claude_data = analysis_by_rank.get(creative["rank"], {})
        creative["why_performing"] = claude_data.get("why_performing", "")
        creative["action"] = claude_data.get("action", "Review")
        creative["action_type"] = claude_data.get("action_type", "hold")

    return jsonify({
        "ok": True,
        "generated_at": datetime.utcnow().isoformat(),
        "account_id": account_id,
        "summary": analysis.get("summary", ""),
        "overall_roas": analysis.get("overall_roas", 0),
        "total_spend": analysis.get("total_spend", 0),
        "week_label": analysis.get("week_label", ""),
        "creatives": creatives_with_data,
        "actions": analysis.get("actions", []),
        "insights": analysis.get("insights", [])
    })


@app.route("/api/validate-token", methods=["POST"])
def validate_token():
    """Quick check: is this token + account ID valid?"""
    data = request.get_json()
    token = data.get("token", "").strip()
    account_id = data.get("account_id", "").strip()

    if not account_id.startswith("act_"):
        account_id = f"act_{account_id}"

    resp = requests.get(f"{META_BASE}/{account_id}", params={
        "access_token": token,
        "fields": "name,account_status,currency,timezone_name"
    })

    if resp.status_code == 200:
        info = resp.json()
        return jsonify({
            "valid": True,
            "account_name": info.get("name"),
            "currency": info.get("currency"),
            "timezone": info.get("timezone_name"),
            "status": info.get("account_status")
        })
    else:
        error = resp.json().get("error", {})
        return jsonify({
            "valid": False,
            "message": error.get("message", "Invalid token or account ID")
        })


@app.route("/api/create-checkout", methods=["POST"])
def create_checkout():
    """Create a Stripe checkout session for Studio or Pro plan."""
    try:
        import stripe
        stripe.api_key = os.environ.get("STRIPE_SECRET_KEY")

        data = request.get_json()
        plan = data.get("plan", "studio")
        email = data.get("email", "")
        success_url = data.get("success_url", "https://louvrlabs.com/account?checkout=success")
        cancel_url = data.get("cancel_url", "https://louvrlabs.com/onboarding.html")

        price_id = os.environ.get("STRIPE_STUDIO_PRICE") if plan == "studio" else os.environ.get("STRIPE_PRO_PRICE")

        session_params = {
            "mode": "subscription",
            "line_items": [{"price": price_id, "quantity": 1}],
            "success_url": success_url,
            "cancel_url": cancel_url,
            "allow_promotion_codes": True,
        }
        if email:
            session_params["customer_email"] = email

        session = stripe.checkout.Session.create(**session_params)
        return jsonify({"ok": True, "url": session.url})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/webhook", methods=["POST"])
def stripe_webhook():
    """Handle Stripe webhook events."""
    try:
        import stripe
        stripe.api_key = os.environ.get("STRIPE_SECRET_KEY")
        webhook_secret = os.environ.get("STRIPE_WEBHOOK_SECRET", "")

        payload = request.get_data()
        sig_header = request.headers.get("Stripe-Signature", "")

        if webhook_secret:
            try:
                event = stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
            except Exception:
                return jsonify({"error": "Invalid signature"}), 400
        else:
            event = stripe.Event.construct_from(json.loads(payload), stripe.api_key)

        if event["type"] == "checkout.session.completed":
            session = event["data"]["object"]
            customer_email = session.get("customer_email") or session.get("customer_details", {}).get("email")
            plan = "studio"
            # Try to detect plan from amount
            amount = session.get("amount_total", 9900)
            if amount >= 29900:
                plan = "pro"
            print(f"New subscriber: {customer_email} — {plan}")
            # Here you would update Supabase user metadata if needed

        return jsonify({"ok": True})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
