"""Export curated training datasets (SFT and DPO) from RetailOps feedback and turn records."""
import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, Optional

from agent_protocol import SYSTEM


def connect_database(db_path: Optional[str] = None):
    """Connect to SQLite database."""
    if not db_path:
        root = Path(__file__).resolve().parents[2]
        candidates = [
            root / "artifacts" / "business.sqlite3",
            root / "data" / "business.sqlite3",
            Path("/opt/retailops/artifacts/business.sqlite3")
        ]
        for c in candidates:
            if c.is_file():
                db_path = str(c)
                break
    if not db_path or not Path(db_path).exists():
        raise FileNotFoundError(f"Database not found: {db_path or 'checked standard locations'}")
    
    conn = sqlite3.connect(Path(db_path).resolve().as_uri() + "?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def export_datasets(conn: Any, output_dir: Optional[str] = None, min_rating: int = 4) -> Dict[str, Any]:
    """Query feedback and turn records to produce SFT and DPO datasets."""
    root = Path(__file__).resolve().parents[2]
    out_path = Path(output_dir or root / "data")
    out_path.mkdir(parents=True, exist_ok=True)
    sft_file = out_path / "sft_dataset.jsonl"
    dpo_file = out_path / "dpo_dataset.jsonl"

    # 1. Fetch feedbacks
    feedbacks = [dict(r) for r in conn.execute("""
        SELECT * FROM conversation_feedback ORDER BY id ASC
    """).fetchall()]

    pos_turn_ids = set()
    neg_feedbacks_by_turn = {}
    high_csat_conv_ids = set()
    low_csat_conv_ids = set()
    handoff_turns = {}

    for fb in feedbacks:
        cid = fb["conversation_id"]
        tid = fb["turn_id"]
        ftype = fb["feedback_type"]
        rating = fb["rating"]
        sentiment = fb["sentiment_flag"]

        if ftype == "session_csat":
            if rating and rating >= min_rating:
                high_csat_conv_ids.add(cid)
            elif rating and rating <= 2:
                low_csat_conv_ids.add(cid)
        elif ftype == "turn_rating":
            if sentiment == "positive" or (rating and rating >= min_rating):
                if tid:
                    pos_turn_ids.add(tid)
            elif sentiment == "negative" or (rating and rating <= 2):
                if tid:
                    neg_feedbacks_by_turn[tid] = fb
        elif ftype == "human_handoff":
            if tid:
                handoff_turns[tid] = fb

    # 2. Fetch turns
    turns = [dict(r) for r in conn.execute("""
        SELECT id, conversation_id, messages, result, created_at
        FROM agent_turns ORDER BY id ASC
    """).fetchall()]

    sft_records = []
    dpo_records = []

    for t in turns:
        tid = t["id"]
        cid = t["conversation_id"]
        try:
            raw_messages = json.loads(t["messages"])
            result_obj = json.loads(t["result"])
        except Exception:
            continue

        # Criteria for SFT:
        # Either positive turn rating, or belongs to a high-CSAT session without negative feedback
        is_pos = (tid in pos_turn_ids) or (cid in high_csat_conv_ids and tid not in neg_feedbacks_by_turn)
        
        # Build ChatML training sample
        clean_messages = [{"role": "system", "content": SYSTEM}]
        for m in raw_messages:
            role = m.get("role")
            content = m.get("content")
            entry = {"role": role, "content": content}
            if "tool_calls" in m:
                entry["tool_calls"] = m["tool_calls"]
            elif role == "tool":
                entry["tool_name"] = m.get("tool_name")
            clean_messages.append(entry)

        if is_pos:
            if isinstance(raw_messages, list) and len(raw_messages) >= 2 and raw_messages[0].get("role") == "user" and raw_messages[-1].get("role") == "assistant":
                sft_records.append({"messages": clean_messages})

        # Criteria for DPO:
        # Turn received negative rating or triggered human handoff
        if tid in neg_feedbacks_by_turn or tid in handoff_turns:
            fb = neg_feedbacks_by_turn.get(tid) or handoff_turns.get(tid)
            # Find last user prompt
            user_prompts = [m["content"] for m in raw_messages if m.get("role") == "user"]
            rejected_content = result_obj.get("message") or ""
            if user_prompts and rejected_content:
                last_prompt = user_prompts[-1]
                reason = fb.get("reason_code") or "general_dissatisfaction"
                comment = fb.get("comment") or ""
                
                # Standardized high-quality fallback/rephrasing for chosen response
                chosen_content = (
                    f"Dạ em xin lỗi vì trải nghiệm chưa hoàn hảo. Về yêu cầu '{last_prompt}', "
                    "em đã ghi nhận phản hồi và đang kiểm tra kỹ lưỡng lại dữ liệu trên hệ thống để gửi thông tin chính xác nhất cho mình ngay ạ."
                )
                if comment and len(comment) > 10:
                    chosen_content += f" (Ghi chú tư vấn: {comment})"

                dpo_records.append({
                    "prompt": last_prompt,
                    "rejected": rejected_content,
                    "chosen": chosen_content,
                    "reason": reason,
                    "turn_id": tid,
                    "conversation_id": cid
                })

    # Write output files
    with open(sft_file, "w", encoding="utf-8") as f:
        for item in sft_records:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")

    with open(dpo_file, "w", encoding="utf-8") as f:
        for item in dpo_records:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")

    return {
        "sft_samples": len(sft_records),
        "dpo_samples": len(dpo_records),
        "sft_path": str(sft_file),
        "dpo_path": str(dpo_file)
    }
