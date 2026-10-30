"""Student A2A dining marketplace agent. Gradio 6.30 UI (7860), FastAPI A2A (8000).

OpenAI receives ONLY plain-string role/content chat history, not Gradio 6 content parts.
"""
from __future__ import annotations
import threading
from concurrent.futures import ThreadPoolExecutor
import gradio as gr
import uvicorn
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from a2a_wire import data_parts, task_record, result_envelope, error_envelope, new_id
from student_logic import (agent_card, handle_chat, list_registry, profile, restaurant_research,
                           public_url, normalize_history)
from wallet_utils import (initialize_wallet, local_address, balances, verify_usdc_payment,
                          USDC, CHAIN_ID)

initialize_wallet()
api = FastAPI(title="Student Fort Worth Dining A2A Agent")
TASKS = {}
TASK_INFO = {}
USED_PAYMENTS = set()
LOCK = threading.RLock()
RESEARCH_POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix="restaurant-research")


@api.get("/.well-known/agent-card.json")
def get_card():
    return agent_card()


@api.get("/health")
def health():
    return {"status":"ok"}


def background_research(tid):
    with LOCK:
        info = dict(TASK_INFO[tid])
    try:
        answer = restaurant_research(info["food"], info["specialty"])
        result = {"action":"recommendation", "food":info["food"],
                  "agentName":info["name"],"recommendation":answer,
                  "txHash":info["txHash"]}
        updated = task_record("completed", result, task_id=tid,
                              context_id=info["contextId"],name="Restaurant recommendation")
    except Exception as exc:
        updated = task_record("failed", {"error":str(exc)[:400]},task_id=tid,context_id=info["contextId"])
    with LOCK:
        TASKS[tid] = updated


def accept_message(incoming):
    parts = data_parts(incoming.get("parts", []))
    if not parts:
        raise ValueError("Service requires a structured A2A data part")
    data = parts[0]
    action = data.get("action")
    if action == "request_recommendation":
        p = profile()
        if not p.get("specialty") or not isinstance(p.get("priceCents"),int) or not 1<=p["priceCents"]<=100:
            raise ValueError("Seller must register its food specialty and service price first")
        food = str(data.get("food") or "").strip()
        buyer = str(data.get("buyerWallet") or "")
        from web3 import Web3
        if not food or not Web3.is_address(buyer):
            raise ValueError("Missing food or valid buyer wallet")
        buyer = Web3.to_checksum_address(buyer)
        quote = {"action":"payment_required", "priceCents":p["priceCents"],
                 "walletAddress":local_address(), "chainId":CHAIN_ID,
                 "tokenContract":USDC, "currency":"USDC"}
        task = task_record("input-required",quote)
        with LOCK:
            TASKS[task["id"]] = task
            TASK_INFO[task["id"]] = {"buyer":buyer,"food":food,
                    "priceCents":p["priceCents"],"name":p["name"],
                    "specialty":p["specialty"],"contextId":task["contextId"]}
        return task
    if action == "payment_proof":
        tid = incoming.get("taskId")
        if not tid:
            raise ValueError("payment_proof must reference original A2A taskId")
        with LOCK:
            task = TASKS.get(tid)
            info = TASK_INFO.get(tid)
            if not task or not info:
                raise LookupError("Unknown A2A task ID")
            if task["status"]["state"] != "input-required":
                return task
            if incoming.get("contextId") != info["contextId"]:
                raise ValueError("Incorrect A2A contextId")
        txhash = str(data.get("txHash") or "").strip()
        if not txhash.startswith("0x") or len(txhash) != 66:
            raise ValueError("Invalid Base Sepolia transaction hash")
        # Validate on-chain payment before proceeding. The first valid task owns this txhash.
        verify_usdc_payment(txhash, info["buyer"], local_address(), info["priceCents"]/100)
        with LOCK:
            if txhash.lower() in USED_PAYMENTS:
                raise ValueError("Payment transaction was already used for a different task")
            if TASKS[tid]["status"]["state"] != "input-required":
                return TASKS[tid]
            USED_PAYMENTS.add(txhash.lower())
            TASK_INFO[tid]["txHash"] = txhash
            TASKS[tid] = task_record("working", {"action":"search_started"},
                        task_id=tid,context_id=info["contextId"])
            output = TASKS[tid]
        RESEARCH_POOL.submit(background_research, tid)
        return output
    raise ValueError("Unknown student service action")


@api.post("/")
def a2a_endpoint(payload:dict):
    request_id = payload.get("id")
    try:
        if payload.get("jsonrpc") != "2.0":
            raise ValueError("Expected JSON-RPC 2.0")
        method = payload.get("method")
        if method == "message/send":
            return JSONResponse(result_envelope(request_id, accept_message(payload.get("params",{}).get("message",{}))))
        if method in ("tasks/get", "tasks/cancel"):
            tid = payload.get("params",{}).get("id")
            with LOCK:
                task = TASKS.get(tid)
                if not task:
                    return JSONResponse(error_envelope(request_id,-32001,"Task not found"))
                if method == "tasks/cancel":
                    if task["status"]["state"] in ("completed","failed","canceled"):
                        return JSONResponse(error_envelope(request_id,-32002,"Task is already terminal"))
                    # A verified paid task cannot be canceled; no refund mechanism in this demo.
                    if task["status"]["state"] == "working":
                        return JSONResponse(error_envelope(request_id,-32002,"Paid research task cannot be canceled"))
                    task["status"]["state"]="canceled"
                return JSONResponse(result_envelope(request_id, task))
        return JSONResponse(error_envelope(request_id,-32601,"Method not found"))
    except (ValueError,LookupError,TypeError) as exc:
        return JSONResponse(error_envelope(request_id,-32602,str(exc)))
    except Exception as exc:
        return JSONResponse(error_envelope(request_id,-32603,str(exc)))


def wallet_display():
    try:
        b = balances()
        return (f"**Base Sepolia (84532)**  \n**Wallet:** `{b['address']}`  \n"
                f"**Test USDC:** {b['usdc']}  \n**Gas ETH:** {b['eth']}  \n"
                "[Fund test USDC](https://faucet.circle.com/) · [Base Sepolia explorer](https://sepolia.basescan.org/)")
    except Exception as exc:
        return f"**Wallet:** `{local_address()}`  \nBalance temporarily unavailable: {str(exc)[:160]}"


def directory_display():
    try:
        items = list_registry()
    except Exception as exc:
        return "**Registry unavailable:** " + str(exc)
    if not items:
        return "No student agents registered yet. Tell your agent its food specialty and price to register."
    lines=[]
    for item in sorted(items,key=lambda r:(r["priceCents"],r["name"].lower())):
        lines.append(f"### {item['name']} · ${item['priceCents']/100:.2f} test USDC\n"
                     f"**Specialty:** {item['specialty']}  \n{item['description']}  \n"
                     f"**A2A URL:** `{item['url']}`  \n**Wallet:** `{item['walletAddress']}`\n\n---")
    return "\n".join(lines)


def respond(user_text, history):
    new_history = handle_chat(user_text,history)
    return new_history, "", wallet_display(), directory_display()


def refresh():
    return wallet_display(), directory_display()


def build_ui():
    with gr.Blocks(title="Fort Worth Dining · A2A Agent Marketplace") as demo:
        gr.Markdown("# Fort Worth Dining · A2A Agent Marketplace\nYour agent discovers the cheapest qualified dining researcher, pays test USDC on Base Sepolia and returns the result in chat.")
        with gr.Row():
            with gr.Column(scale=3):
                balance = gr.Markdown("Loading wallet...")
                chat = gr.Chatbot(height=510, label="My Agent")  # Gradio 6: no `type=` argument
                entry = gr.Textbox(label="Message",placeholder="Example: Where can I find the best salad in Fort Worth?",lines=2)
                with gr.Row():
                    send_button = gr.Button("Send", variant="primary")
                    clear_button = gr.Button("Clear chat", variant="secondary")
            with gr.Column(scale=2):
                gr.Markdown("## Available Agent Cards")
                refresh_button = gr.Button("Refresh directory and wallet balances")
                directory = gr.Markdown("Loading registry...")
        send_button.click(fn=respond,inputs=[entry,chat],outputs=[chat,entry,balance,directory],concurrency_limit=None)
        entry.submit(fn=respond,inputs=[entry,chat],outputs=[chat,entry,balance,directory],concurrency_limit=None)
        clear_button.click(fn=lambda: ([],""),inputs=[],outputs=[chat,entry])
        refresh_button.click(fn=refresh,inputs=[],outputs=[balance,directory])
        demo.load(fn=refresh,inputs=[],outputs=[balance,directory])
    return demo


if __name__ == "__main__":
    runner = threading.Thread(target=lambda:uvicorn.run(api,host="0.0.0.0",port=8000,log_level="info"),daemon=True)
    runner.start()
    build_ui().queue().launch(server_name="0.0.0.0",server_port=7860,share=False)
