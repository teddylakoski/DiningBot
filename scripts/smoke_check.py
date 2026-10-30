"""Offline student startup / Gradio 6 / chat-history sanity checks (no OpenAI/chain payment)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gradio as gr
from student_logic import normalize_history, agent_card
from a2a_wire import task_record, status_data, task_artifact_data
from app import build_ui

assert gr.__version__.startswith("6."), f"Expected Gradio 6, got {gr.__version__}"
assert normalize_history([
    {"role":"user", "content":[{"type":"text", "text":"first question"}]},
    {"role":"assistant", "content":"answer"},
    {"role":"user", "content":"second question"},
]) == [
    {"role":"user","content":"first question"},
    {"role":"assistant","content":"answer"},
    {"role":"user","content":"second question"},
]
quote = task_record("input-required", {"priceCents": 25})
assert status_data(quote)[0]["priceCents"] == 25
reply = task_record("completed", {"recommendation":"Test recommendation"})
assert task_artifact_data(reply)["recommendation"] == "Test recommendation"
assert agent_card()["protocolVersion"] == "0.3.0"
assert build_ui() is not None
print(f"PASS: Gradio {gr.__version__}; chat history; UI; A2A messages; Agent Card")
