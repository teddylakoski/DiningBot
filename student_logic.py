"""Student agent behavior: LLM intent recognition, registry matching, A2A purchases and web research."""
from __future__ import annotations
import json
import os
import re
import time
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlparse
from openai import OpenAI
from a2a_wire import send, get_task, task_artifact_data, status_data
from wallet_utils import local_address, balances, send_usdc, USDC, CHAIN_ID

ROOT = Path(__file__).resolve().parent
PROFILE_PATH = ROOT / "profile.json"
INSTRUCTIONS_PATH = ROOT / "agent_instructions.md"
MODEL = os.getenv("OPENAI_MODEL", "gpt-5-mini")
REGISTRY_URL = os.getenv("INSTRUCTOR_REGISTRY_URL", "").strip().rstrip("/")
EXTENSION_URI = "https://classroom.example/a2a/extensions/fort-worth-dining-v1"


def client():
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is missing. Set it as a GitHub Codespaces secret.")
    return OpenAI()


def instruction_text():
    return INSTRUCTIONS_PATH.read_text(encoding="utf-8") if INSTRUCTIONS_PATH.exists() else "Be helpful."


def profile():
    if not PROFILE_PATH.exists():
        return {"name":"My Dining Agent", "specialty":"", "priceCents":None, "description":""}
    return json.loads(PROFILE_PATH.read_text(encoding="utf-8"))


def save_profile(p):
    PROFILE_PATH.write_text(json.dumps(p, indent=2), encoding="utf-8")


def public_url():
    explicit = os.getenv("PUBLIC_A2A_URL", "").strip().rstrip("/")
    if explicit:
        return explicit
    codespace = os.getenv("CODESPACE_NAME", "")
    domain = os.getenv("GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN", "app.github.dev")
    return f"https://{codespace}-8000.{domain}" if codespace else "http://127.0.0.1:8000"


def agent_card():
    p = profile()
    specialist = str(p.get("specialty", "") or "unconfigured")
    description = p.get("description", "") or f"Researches Fort Worth restaurants specializing in {specialist}."
    return {"protocolVersion":"0.3.0", "name":p.get("name") or "Fort Worth Dining Agent",
            "description":description, "url":public_url(), "version":"1.0.0",
            "preferredTransport":"JSONRPC", "capabilities":{
                "streaming":False, "pushNotifications":False,
                "extensions":[{"uri":EXTENSION_URI, "description":"Classroom test-USDC dining service terms on Base Sepolia",
                               "required":False, "params":{
                                   "specialty":p.get("specialty", ""), "priceCents":p.get("priceCents"),
                                   "walletAddress":local_address(),"chainId":CHAIN_ID,
                                   "currency":"USDC", "tokenContract":USDC}}]},
            "defaultInputModes":["text/plain", "application/json"],
            "defaultOutputModes":["text/plain", "application/json"],
            "skills":[{"id":"fort_worth_dining_research","name":f"Fort Worth {specialist} recommendation",
                       "description":f"Web searches restaurants in Fort Worth for {specialist}; provides recommendation, menu prices, hours, reviews and sources after Base Sepolia test USDC payment.",
                       "tags":["Fort Worth","dining",specialist]}]}


def normalize_history(history, max_items=12):
    """CRITICAL: Converts Gradio 6 messages to plain-text Responses API messages.

    Never forward Gradio content parts with `type: text` to Responses API.
    """
    result = []
    for item in (history or [])[-max_items:]:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        if role not in ("user", "assistant"):
            continue
        content = item.get("content")
        if isinstance(content, str):
            text = content
        elif isinstance(content, list):
            text = "\n".join(p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") in ("text","input_text","output_text") )
        else:
            text = ""
        if text.strip():
            result.append({"role": role, "content": text})
    return result


def _json_response(system, prompt, schema):
    response = client().responses.create(
        model=MODEL,
        instructions=system,
        input=prompt,
        text={"format":{"type":"json_schema","name":"classroom_output","strict":True,"schema":schema}}
    )
    return json.loads(response.output_text)


def route_request(text, history):
    schema = {"type":"object","properties":{
        "action":{"type":"string","enum":["register","buy","chat"]},
        "food":{"type":["string","null"]},
        "priceCents":{"type":["integer","null"]},
        "name":{"type":["string","null"]},
        "description":{"type":["string","null"]}},
        "required":["action","food","priceCents","name","description"],"additionalProperties":False}
    system = ("Classify the latest student's request. register = student edits THEIR agent offering/price/name/description or asks to register the card. "
              "buy = student asks where to find a food or restaurant in Fort Worth; extract and CANONICALIZE the food (e.g. berger, burger -> hamburger; fries -> french fries). "
              "chat = any other question. For register, extract food specialty, integer price IN CENTS, name, description only when explicitly stated; null for unspecified fields. "
              "If asking to register current saved card without changes: register, all nulls. "
              "For buy, food is the normalized requested food item. Return only schema data.")
    context = normalize_history(history, max_items=6)
    prompt = "Recent messages:\n" + json.dumps(context) + "\nLatest request: " + text
    return _json_response(system, prompt, schema)


def list_registry():
    if not REGISTRY_URL:
        raise RuntimeError("INSTRUCTOR_REGISTRY_URL is missing. Set this Codespaces secret to the instructor registry port-8000 URL.")
    task = send(REGISTRY_URL, {"action":"list"})
    data = task_artifact_data(task)
    if data.get("action") != "directory":
        raise RuntimeError("Registry returned an unexpected A2A reply")
    return data.get("agents", [])


def register_service(parsed):
    p = profile()
    food = parsed.get("food")
    if food:
        p["specialty"] = food.strip().lower()
    if parsed.get("name"):
        p["name"] = parsed["name"].strip()
    if parsed.get("description"):
        p["description"] = parsed["description"].strip()
    cents = parsed.get("priceCents")
    if cents is not None:
        if type(cents) is not int or not (1 <= cents <= 100):
            raise ValueError("The service price must be $0.01–$1.00 (1–100 cents).")
        p["priceCents"] = cents
    if not p.get("specialty") or not (isinstance(p.get("priceCents"),int) and 1<=p["priceCents"]<=100):
        raise ValueError("Tell me a food specialty and a price between $0.01 and $1.00, e.g. 'I offer hamburger research for $0.25; register me'.")
    if not p.get("description"):
        p["description"] = f"Researches the best {p['specialty']} in Fort Worth, including menu prices, hours and reviews."
    save_profile(p)
    card = agent_card()
    task = send(REGISTRY_URL, {"action":"register", "card":card})
    reply = task_artifact_data(task)
    if reply.get("action") != "registered":
        raise RuntimeError("Registration did not succeed: " + str(reply))
    return f"Registered **{p['name']}** via A2A. Specialty: **{p['specialty']}**; fee **${p['priceCents']/100:.2f} test USDC**.\n\nMy Base Sepolia wallet is `{local_address()}`. The registry will attempt to fund its ETH gas balance automatically. Fund this same address with test USDC from Circle's Base Sepolia faucet."


def eligible_agents(food, records):
    if not records:
        return []
    # The LLM evaluates *semantic* matches; Python chooses minimum price independently.
    options = [{"url":r["url"], "specialty":r.get("specialty"),"description":r.get("description","")} for r in records]
    schema = {"type":"object","properties":{"matchingUrls":{"type":"array","items":{"type":"string"}}},
              "required":["matchingUrls"],"additionalProperties":False}
    system = ("You are matching a buyer's requested FOOD ITEM to agent offerings. Return ALL agent URLs whose specialty is a clear match, "
              "including synonyms, spelling variations, and singular/plural (berger/burger/hamburger). "
              "Avoid broad generalizations: pizza is not burgers, sushi is not all seafood, pastries is not steak. "
              "Do not consider price. Return only URLs exactly present in the options.")
    answer = _json_response(system, json.dumps({"foodWanted":food,"agents":options}), schema)
    approved = set(answer["matchingUrls"])
    matches = [r for r in records if r["url"] in approved and type(r.get("priceCents")) is int and 1 <= r["priceCents"] <= 100]
    return sorted(matches, key=lambda r:(r["priceCents"],r["name"].lower()))


def purchase(food):
    records = list_registry()
    matches = eligible_agents(food, records)
    if not matches:
        return f"I couldn't find a registered agent specializing in **{food}**. Ask another student to register that specialty."
    seller = matches[0]
    if seller["url"].rstrip("/") == public_url().rstrip("/"):
        # Can't pay self, but still allow if the cheapest candidate happens to be self.
        other = [r for r in matches if r["url"].rstrip("/") != public_url().rstrip("/")]
        if not other:
            return f"The only available {food} provider is this agent itself. Ask another student to offer the service so a real agent-to-agent payment can occur."
        seller = other[0]
    task = send(seller["url"], {"action":"request_recommendation", "food":food, "buyerWallet":local_address()})
    tid, cid = task["id"], task["contextId"]
    if task["status"]["state"] != "input-required":
        raise RuntimeError("Seller did not provide an A2A payment-required quote")
    quote_parts = status_data(task)
    if not quote_parts:
        raise RuntimeError("Missing payment instructions")
    quote = quote_parts[0]
    if quote.get("action") != "payment_required":
        raise RuntimeError("Unexpected payment instructions")
    if (quote.get("priceCents") != seller["priceCents"] or
        quote.get("walletAddress", "").lower() != seller["walletAddress"].lower() or
        quote.get("chainId") != CHAIN_ID or
        quote.get("tokenContract", "").lower() != USDC.lower()):
        raise RuntimeError("Seller quote differs from the registry; refresh registration and try again. No payment was made.")
    price = Decimal(quote["priceCents"]) / 100
    try:
        txhash = send_usdc(quote["walletAddress"], price)
    except Exception as exc:
        raise RuntimeError(f"Payment not sent: {exc}. Check your Base Sepolia test USDC and ETH balances.") from exc
    # If subsequent steps fail, display txhash so student can inspect on explorer.
    try:
        current = send(seller["url"], {"action":"payment_proof","txHash":txhash}, task_id=tid, context_id=cid)
        deadline = time.monotonic()+165
        while current["status"]["state"] not in ("completed","failed","canceled","rejected"):
            if time.monotonic() >= deadline:
                raise TimeoutError("Seller is still researching. The payment has already completed; check with the seller before retrying.")
            time.sleep(3)
            current = get_task(seller["url"], tid)
        if current["status"]["state"] != "completed":
            raise RuntimeError(f"Seller task ended with status {current['status']['state']}")
        data = task_artifact_data(current)
        if not data.get("recommendation"):
            raise RuntimeError("No restaurant recommendation returned")
        result = data["recommendation"]
        return (f"**{food.title()} research — supplied by {seller['name']}**  \n"
                f"Agent specialty: {seller['specialty']} · Service fee: **${price:.2f} test USDC**  \n"
                f"[Base Sepolia payment](https://sepolia.basescan.org/tx/{txhash})\n\n{result}")
    except Exception as exc:
        raise RuntimeError(f"Payment TX: https://sepolia.basescan.org/tx/{txhash}. Follow-up communication failed: {exc}") from exc


def general_chat(message, history):
    r = client().responses.create(model=MODEL,
        instructions=instruction_text()+"\nYou help students operate their A2A restaurant research agent. If user requests setup, guide them to tell you their specialty and fee. Do not claim on-chain payments happened unless code completed them.",
        input=normalize_history(history)+[{"role":"user","content":message}],
        tools=[{"type":"web_search"}])
    return r.output_text or "No response returned."


def handle_chat(user_text, history):
    history = normalize_history(history, max_items=30)
    if not user_text or not user_text.strip():
        return history
    user_text = user_text.strip()
    try:
        request = route_request(user_text, history)
        action = request["action"]
        if action == "register":
            answer = register_service(request)
        elif action == "buy":
            food = request.get("food")
            answer = purchase(food) if food else "Which food item would you like to find in Fort Worth?"
        else:
            answer = general_chat(user_text, history)
    except Exception as exc:
        answer = f"**Unable to complete the request:** {str(exc)}"
    return history + [{"role":"user","content":user_text},{"role":"assistant","content":answer}]


def restaurant_research(food, specialty):
    """Perform actual OpenAI hosted web search, then return text with source URLs when present."""
    prompt = (f"Find the BEST restaurant in Fort Worth, Texas for **{food}** (seller specialty: {specialty}). "
              "Compare plausible local options using current search results. Return one recommended restaurant and explain why. "
              "Include restaurant name, neighborhood or address if verified, menu item price (if found), opening hours (if found), "
              "and a brief review consensus (if available). Include source website URLs. "
              "If price, hours or reviews cannot be verified, say 'not verified' rather than guessing. "
              "Do not invent prices, ratings, reviews or business hours. Use only Fort Worth restaurants.")
    response = client().responses.create(model=MODEL, input=prompt,
                instructions=instruction_text()+"\nYou are the SELLING restaurant researcher. Web search is required; cite sources.",
                tools=[{"type":"web_search"}])
    if not response.output_text:
        raise RuntimeError("OpenAI returned an empty restaurant recommendation")
    source_urls = []
    for out in response.output:
        for part in getattr(out, "content", []) or []:
            for note in getattr(part,"annotations",[]) or []:
                url = getattr(note,"url",None)
                if url and url not in source_urls:
                    source_urls.append(url)
    text = response.output_text
    if source_urls:
        text += "\n\n**Sources:** " + ", ".join(f"[Source {i+1}]({url})" for i,url in enumerate(source_urls[:8]))
    return text
