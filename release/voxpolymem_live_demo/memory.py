"""Small online adapter around the separate, frozen VoxPolyMem v1 core.

This module intentionally does not modify or copy the benchmark executor.
Its stored nodes and route trace are inspectable in the demo UI.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import re
import sys
import tempfile
from threading import RLock
from typing import Any
from urllib import error, request
from uuid import UUID, uuid4


def session_id(value: str | None) -> str:
    if value:
        try:
            return str(UUID(value))
        except (ValueError, TypeError) as exc:
            raise ValueError("Invalid session ID") from exc
    return str(uuid4())


def _tokens(text: str) -> list[str]:
    words = re.findall(r"[a-z0-9_]+|[\u3400-\u9fff]", text.lower())
    return words + [words[i] + words[i + 1] for i in range(len(words) - 1)]


def rank_bm25(query: str, rows: list[dict[str, Any]], limit: int = 30) -> list[dict[str, Any]]:
    """Dependency-free BM25 for the live adapter, not a dense-search proxy."""
    if not rows:
        return []
    query_terms = list(dict.fromkeys(_tokens(query)))
    if not query_terms:
        return []
    docs = [Counter(_tokens(str(row.get("retrieval_text") or row.get("text") or ""))) for row in rows]
    lengths = [sum(doc.values()) for doc in docs]
    avg_len = max(1.0, sum(lengths) / len(lengths))
    frequency = Counter(term for doc in docs for term in doc)
    scored = []
    for index, doc in enumerate(docs):
        score = 0.0
        for term in query_terms:
            count = doc.get(term, 0)
            if not count:
                continue
            idf = math.log(1 + (len(docs) - frequency[term] + 0.5) / (frequency[term] + 0.5))
            score += idf * (count * 2.2) / (count + 1.2 * (0.25 + 0.75 * lengths[index] / avg_len))
        if score > 0:
            scored.append((score, index))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [dict(rows[index], search_score=round(score, 5)) for score, index in scored[:limit]]


def _json_object(text: str) -> dict[str, Any]:
    candidate = text.strip()
    if candidate.startswith("```"):
        candidate = re.sub(r"^```(?:json)?\s*|\s*```$", "", candidate, flags=re.I)
    try:
        value = json.loads(candidate)
    except json.JSONDecodeError:
        start, end = candidate.find("{"), candidate.rfind("}")
        value = json.loads(candidate[start:end + 1]) if 0 <= start < end else {}
    return value if isinstance(value, dict) else {}


class ModelClient:
    def __init__(self, api_key: str = "", base_url: str = "https://api.openai.com/v1", model: str = "gpt-4.1-mini"):
        self.api_key = api_key.strip()
        self.base_url = base_url.rstrip("/")
        self.model = model

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def chat(self, messages: list[dict[str, str]], max_tokens: int = 900) -> str:
        if not self.available:
            raise RuntimeError("LLM is not configured")
        payload = json.dumps({
            "model": self.model, "messages": messages, "temperature": 0,
            "max_tokens": max_tokens,
        }).encode("utf-8")
        req = request.Request(
            f"{self.base_url}/chat/completions", data=payload,
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
        )
        try:
            with request.urlopen(req, timeout=120) as response:
                result = json.load(response)
        except error.HTTPError as exc:
            detail = exc.read(500).decode("utf-8", errors="replace")
            raise RuntimeError(f"LLM HTTP {exc.code}: {detail}") from exc
        return str(result["choices"][0]["message"]["content"] or "")

    def transcribe(self, audio: bytes, filename: str, model: str) -> str:
        if not self.available:
            raise RuntimeError("ASR is not configured")
        boundary = "----VoxPolyMem" + uuid4().hex
        chunks = []
        for field, value in (("model", model),):
            chunks.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{field}\"\r\n\r\n{value}\r\n".encode())
        chunks.append((
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
            f"filename=\"{filename}\"\r\nContent-Type: application/octet-stream\r\n\r\n"
        ).encode() + audio + b"\r\n")
        chunks.append(f"--{boundary}--\r\n".encode())
        req = request.Request(
            f"{self.base_url}/audio/transcriptions", data=b"".join(chunks),
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": f"multipart/form-data; boundary={boundary}"},
        )
        try:
            with request.urlopen(req, timeout=180) as response:
                result = json.load(response)
        except error.HTTPError as exc:
            detail = exc.read(500).decode("utf-8", errors="replace")
            raise RuntimeError(f"ASR HTTP {exc.code}: {detail}") from exc
        return str(result.get("text") or "").strip()


class SessionStore:
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = RLock()

    def get(self, sid: str) -> dict[str, Any]:
        sid = session_id(sid)
        path = self.root / f"{sid}.json"
        with self.lock:
            if path.exists():
                return json.loads(path.read_text(encoding="utf-8"))
            return {"session_id": sid, "turns": [], "facts": [], "collections": [], "questions": [], "speaker_labels": {}}

    def save(self, state: dict[str, Any]) -> None:
        sid = session_id(state["session_id"])
        with self.lock:
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=self.root, suffix=".tmp", delete=False) as handle:
                json.dump(state, handle, ensure_ascii=False, indent=2)
                tmp_path = Path(handle.name)
            tmp_path.replace(self.root / f"{sid}.json")


class DemoEngine:
    def __init__(self, store: SessionStore, model: ModelClient, source: Path | None = None, top_k: int = 20):
        self.store = store
        self.model = model
        self.operation_lock = RLock()
        self.top_k = max(1, min(30, top_k))
        self.source = source.resolve() if source and source.is_dir() else None
        self.frozen = False
        if self.source and (self.source / "core" / "planner.py").exists():
            sys.path.insert(0, str(self.source))
            from core.planner import unified_hybrid_plan
            from core.iterative_retrieval import retrieve_iteratively
            self._plan = unified_hybrid_plan
            self._retrieve_iteratively = retrieve_iteratively
            self.frozen = True

    def status(self) -> dict[str, Any]:
        return {
            "model_connected": self.model.available,
            "model": self.model.model if self.model.available else None,
            "frozen_core_loaded": self.frozen,
            "retrieval": "frozen planner + demo BM25 executor" if self.frozen and self.model.available else "demo BM25 fallback",
            "top_k": self.top_k,
            "dense_enabled": False,
        }

    def ingest(self, sid: str, text: str, speaker: str = "", audio_name: str | None = None, acoustic_id: str | None = None, speaker_match: dict[str, Any] | None = None) -> dict[str, Any]:
        with self.operation_lock:
            return self._ingest(sid, text, speaker, audio_name, acoustic_id, speaker_match)

    def _ingest(self, sid: str, text: str, speaker: str, audio_name: str | None, acoustic_id: str | None, speaker_match: dict[str, Any] | None) -> dict[str, Any]:
        text = " ".join(text.strip().split())
        if not text or len(text) > 10000:
            raise ValueError("Turn text must contain 1–10,000 characters")
        state = self.store.get(sid)
        labels = state.setdefault("speaker_labels", {})
        supplied_name = speaker.strip()[:80]
        if acoustic_id and supplied_name:
            labels[acoustic_id] = supplied_name
            for previous in state["turns"]:
                if previous.get("acoustic_id") == acoustic_id:
                    previous["speaker"] = supplied_name
        resolved_speaker = labels.get(acoustic_id, acoustic_id) if acoustic_id else supplied_name or "Unknown speaker"
        turn_id = f"T{len(state['turns']) + 1:04d}"
        turn = {
            "id": turn_id, "text": text,
            "speaker": resolved_speaker,
            "acoustic_id": acoustic_id,
            "speaker_source": "acoustic" if acoustic_id else "manual" if supplied_name else "unknown",
            "speaker_match": speaker_match if acoustic_id else None,
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "audio_name": audio_name,
        }
        state["turns"].append(turn)
        self.store.save(state)  # Raw evidence survives an extraction/provider failure.
        warning = None
        if self.model.available:
            try:
                self._extract(state)
            except Exception as exc:
                warning = f"Raw turn saved; fact extraction failed: {exc}"
        self.store.save(state)
        return {"state": state, "turn": turn, "warning": warning}

    def bind_speaker(self, sid: str, acoustic_id: str, label: str) -> dict[str, Any]:
        with self.operation_lock:
            state = self.store.get(sid)
            acoustic_id = acoustic_id.strip()
            label = " ".join(label.strip().split())[:80]
            if not label:
                raise ValueError("Speaker name cannot be empty")
            if acoustic_id not in {row.get("acoustic_id") for row in state["turns"] if row.get("acoustic_id")}:
                raise ValueError("Unknown acoustic speaker ID")
            old_label = state.setdefault("speaker_labels", {}).get(acoustic_id, acoustic_id)
            state["speaker_labels"][acoustic_id] = label
            for row in state["turns"]:
                if row.get("acoustic_id") == acoustic_id:
                    row["speaker"] = label
            for fact in state["facts"]:
                if fact.get("speaker") == old_label:
                    fact["speaker"] = label
            self.store.save(state)
            return {"state": state, "acoustic_id": acoustic_id, "label": label,
                    "warning": "Existing fact text was not rewritten; only speaker metadata changed."}

    def _extract(self, state: dict[str, Any]) -> None:
        window = state["turns"][-12:]
        lines = [f"[{row['id']}] {row['timestamp']} {row['speaker']}: {row['text']}" for row in window]
        prompt = (
            "Extract only durable, grounded atomic facts from this dialogue window. "
            "Use adjacent turns to resolve pronouns, relative time, replies, updates, and speaker attribution. "
            "Each fact must cite the exact supporting turn IDs in refer_ids; do not guess. "
            "Also give a short event label for the newest turn, or null. "
            "Return JSON only: {\"facts\":[{\"text\":\"...\",\"speaker\":\"...\","
            "\"refer_ids\":[\"T0001\"],\"context_operations\":[]}],\"event_label\":null}.\n\n"
            + "\n".join(lines)
        )
        result = _json_object(self.model.chat([
            {"role": "system", "content": "You write evidence-grounded conversational memory. Never invent evidence IDs."},
            {"role": "user", "content": prompt},
        ], max_tokens=1100))
        valid_ids = {row["id"] for row in window}
        existing = {(row["text"].lower(), tuple(row["refer_ids"])) for row in state["facts"]}
        for item in result.get("facts", [])[:8]:
            if not isinstance(item, dict):
                continue
            fact_text = " ".join(str(item.get("text") or "").split())
            refs = list(dict.fromkeys(str(ref) for ref in item.get("refer_ids", []) if str(ref) in valid_ids))
            if not fact_text or not refs or len(fact_text) > 800:
                continue
            key = (fact_text.lower(), tuple(refs))
            if key in existing:
                continue
            existing.add(key)
            state["facts"].append({
                "id": f"F{len(state['facts']) + 1:04d}", "text": fact_text,
                "speaker": str(item.get("speaker") or "")[:80], "refer_ids": refs,
                "context_operations": [str(x)[:40] for x in item.get("context_operations", [])[:4]],
            })
        label = str(result.get("event_label") or "").strip()[:80]
        if label:
            collection = next((row for row in state["collections"] if row["label"].lower() == label.lower()), None)
            if collection is None:
                collection = {"id": f"C{len(state['collections']) + 1:04d}", "label": label, "refer_ids": []}
                state["collections"].append(collection)
            newest_id = state["turns"][-1]["id"]
            if newest_id not in collection["refer_ids"]:
                collection["refer_ids"].append(newest_id)

    def _execute(self, state: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
        turns_by_id = {row["id"]: row for row in state["turns"]}
        scores: dict[str, float] = defaultdict(float)
        channels: dict[str, list[str]] = defaultdict(list)
        trace = []
        routes = list(plan.get("routes") or [])
        floor_query = str(plan.get("rewritten_query") or "")
        if not any(
            route.get("layer") == "raw" and "bm25" in route.get("retrievers", [])
            and str(route.get("query") or floor_query) == floor_query
            for route in routes
        ):
            routes.append({"layer": "raw", "retrievers": ["bm25"], "query": floor_query, "safety_floor": True})
        for route in routes:
            layer = str(route.get("layer") or "")
            query = str(route.get("query") or floor_query)
            source_rows = (
                state["turns"] if layer == "raw" else
                state["facts"] if layer == "fact" else
                state["collections"] if layer == "collection" else []
            )
            prepared = [
                {**row, "retrieval_text": (
                    f"{row.get('speaker', '')} {row.get('text', '')}" if layer != "collection"
                    else str(row.get("label") or "") + " " + " ".join(
                        turns_by_id[ref]["text"] for ref in row.get("refer_ids", []) if ref in turns_by_id
                    )
                )} for row in source_rows
            ]
            for retriever in route.get("retrievers", []):
                channel = f"{layer}.{retriever}"
                if retriever != "bm25":
                    trace.append({"channel": channel, "status": "not_connected", "hits": 0})
                    continue
                ranked = rank_bm25(query, prepared, 30)
                trace.append({"channel": channel, "status": "ok", "hits": len(ranked), "safety_floor": bool(route.get("safety_floor"))})
                for rank, row in enumerate(ranked, 1):
                    refs = [row["id"]] if layer == "raw" else row.get("refer_ids", [])
                    for ref in refs:
                        if ref not in turns_by_id:
                            continue
                        scores[ref] += (0.75 if layer == "fact" else 1.0) / (60 + rank)
                        if channel not in channels[ref]:
                            channels[ref].append(channel)
        ranked_ids = sorted(scores, key=lambda ref: (-scores[ref], -int(ref[1:])))[:self.top_k]
        rows = [{
            "mem_id": ref, "refer_ids": [ref], "text": turns_by_id[ref]["text"],
            "speaker": turns_by_id[ref]["speaker"], "timestamp": turns_by_id[ref]["timestamp"],
            "retrieval_channels": channels[ref], "score": round(scores[ref], 6),
        } for ref in ranked_ids]
        if plan.get("sort_by") == "time":
            rows.sort(key=lambda row: row["timestamp"])
        return {"context": rows, "trace": trace, "memory_image_candidates": [], "need_memory_images": False}

    def ask(self, sid: str, question: str, asker: str = "", asker_acoustic_id: str | None = None) -> dict[str, Any]:
        with self.operation_lock:
            return self._ask(sid, question, asker, asker_acoustic_id)

    def _ask(self, sid: str, question: str, asker: str, asker_acoustic_id: str | None) -> dict[str, Any]:
        question = " ".join(question.strip().split())
        if not question or len(question) > 3000:
            raise ValueError("Question must contain 1–3,000 characters")
        state = self.store.get(sid)
        if not state["turns"]:
            raise ValueError("Record at least one turn first")
        if asker_acoustic_id and not asker.strip():
            asker = state.get("speaker_labels", {}).get(asker_acoustic_id, asker_acoustic_id)
        retrieval_question = f"Asker: {asker.strip()}. {question}" if asker.strip() else question
        warning = None
        if self.model.available and self.frozen:
            try:
                plan = self._plan(retrieval_question, False, self.model.chat)
            except Exception as exc:
                plan = {"strategy": "demo_fallback", "rewritten_query": retrieval_question, "routes": [{"layer": "raw", "retrievers": ["bm25"], "query": retrieval_question}], "sort_by": "score"}
                warning = f"Planner failed; BM25 fallback used: {exc}"
        else:
            plan = {"strategy": "demo_fallback", "rewritten_query": retrieval_question, "routes": [{"layer": "raw", "retrievers": ["bm25"], "query": retrieval_question}], "sort_by": "score"}
        execute = lambda route_plan: self._execute(state, route_plan)
        if self.model.available and self.frozen:
            try:
                result = self._retrieve_iteratively(
                    question=retrieval_question, has_question_image=False, initial_plan=plan,
                    execute=execute, call_router=self.model.chat, top_k=self.top_k,
                    environ={"MPMEM_ITERATIVE_MAX_ROUNDS": "3", "MPMEM_ITERATIVE_ROUND_BUDGETS": f"{self.top_k},6,4"},
                )
            except Exception as exc:
                result = execute(plan)
                warning = f"Iterative retrieval failed; first round retained: {exc}"
        else:
            result = execute(plan)
        evidence = result.get("context", [])
        if self.model.available:
            context = "\n".join(f"[{row['mem_id']}] {row['speaker']} at {row['timestamp']}: {row['text']}" for row in evidence)
            try:
                answer = self.model.chat([
                    {"role": "system", "content": "Answer only from the supplied raw-turn evidence. Cite supporting turn IDs in square brackets. If evidence is insufficient, say so. Do not treat event or fact retrieval nodes as independent evidence."},
                    {"role": "user", "content": f"Asker: {asker or 'unspecified'}\nQuestion: {question}\n\nRaw evidence:\n{context or '(none)'}"},
                ], max_tokens=600)
            except Exception as exc:
                answer = "Answer generation unavailable. Review the retrieved evidence below."
                warning = f"Answer generation failed: {exc}"
        else:
            answer = "Offline preview: retrieved evidence is shown below. Configure an LLM to generate an answer."
        record = {
            "id": f"Q{len(state['questions']) + 1:04d}", "question": question, "asker": asker.strip(),
            "asker_acoustic_id": asker_acoustic_id,
            "answer": answer, "evidence": evidence, "plan": result.get("route_plan", plan),
            "trace": result.get("trace", []), "iterative": result.get("iterative_retrieval"),
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"), "warning": warning,
        }
        state["questions"].append(record)
        self.store.save(state)
        return {"state": state, "question": record}
