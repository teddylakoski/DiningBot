"""Small, inspectable A2A v0.3 JSON-RPC helper for this classroom exercise.

Implements the JSON-RPC transport and messages used by the two repositories.
It is NOT a drop-in replacement for the full official A2A SDK.
"""
from __future__ import annotations
import uuid
import requests


def new_id():
    return str(uuid.uuid4())


def message(data=None, text=None, task_id=None, context_id=None):
    parts = []
    if text is not None:
        parts.append({"kind": "text", "text": str(text)})
    if data is not None:
        parts.append({"kind": "data", "data": data})
    result = {"messageId": new_id(), "role": "user", "parts": parts}
    if task_id:
        result["taskId"] = task_id
    if context_id:
        result["contextId"] = context_id
    return result


def invoke(url, method, params, timeout=25):
    payload = {"jsonrpc": "2.0", "id": new_id(), "method": method, "params": params}
    response = requests.post(url, json=payload, timeout=timeout)
    response.raise_for_status()
    obj = response.json()
    if "error" in obj:
        err = obj["error"]
        raise RuntimeError(f"A2A {method}: {err.get('message',err)}")
    return obj["result"]


def send(url, data, task_id=None, context_id=None):
    return invoke(url, "message/send", {"message": message(data=data,task_id=task_id,context_id=context_id)})


def get_task(url, task_id):
    return invoke(url, "tasks/get", {"id": task_id})


def data_parts(parts):
    return [part.get("data", {}) for part in (parts or []) if part.get("kind") == "data"]


def task_artifact_data(task):
    for artifact in task.get("artifacts", []):
        values = data_parts(artifact.get("parts", []))
        if values:
            return values[0]
    return {}


def status_data(task):
    return data_parts((task.get("status", {}).get("message") or {}).get("parts", []))


def task_record(state, data=None, *, task_id=None, context_id=None, name="Result", message_text=None):
    tid = task_id or new_id()
    cid = context_id or new_id()
    status = {"state": state}
    if message_text is not None:
        status["message"] = {"messageId": new_id(), "role": "agent", "parts": [{"kind": "text", "text": message_text}]}
    elif data is not None and state != "completed":
        status["message"] = {"messageId": new_id(), "role": "agent", "parts": [{"kind": "data", "data": data}]}
    task = {"kind": "task", "id": tid, "contextId": cid, "status": status}
    if data is not None and state == "completed":
        task["artifacts"] = [{"artifactId": new_id(), "name": name, "parts": [{"kind": "data", "data": data}]}]
    return task


def result_envelope(request_id, result):
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def error_envelope(request_id, code, text):
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": text}}
