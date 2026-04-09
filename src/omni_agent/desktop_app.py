"""Native macOS desktop app entrypoint built with Tkinter.

This module intentionally avoids the browser UI. It starts the existing FastAPI
backend locally and renders a lightweight native chat workspace window.
"""

from __future__ import annotations

import json
import os
import queue
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
import tkinter as tk
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText
import uvicorn

from .utils.paths import claude_skills_root


APP_HOST = "127.0.0.1"
APP_PORT = 8765
API_BASE = f"http://{APP_HOST}:{APP_PORT}"
APP_DIR = Path.home() / "Library" / "Application Support" / "OBS Agent Desktop"
SESSIONS_FILE = APP_DIR / "sessions.json"


@dataclass
class DesktopMessage:
    role: str
    content: str
    timestamp: float = field(default_factory=time.time)


@dataclass
class DesktopSession:
    id: str
    title: str = "New thread"
    messages: List[DesktopMessage] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def preview(self) -> str:
        if not self.messages:
            return "Start a new thread..."
        return self.messages[-1].content.strip().replace("\n", " ")[:60] or "Empty message"


class BackendServer:
    def __init__(self) -> None:
        self.server: Optional[uvicorn.Server] = None
        self.thread: Optional[threading.Thread] = None

    def ensure_running(self) -> None:
        if self._is_healthy():
            return

        os.environ.setdefault("SKILLS_DIR", str(claude_skills_root()))
        from omni_agent.api import app

        config = uvicorn.Config(
            app,
            host=APP_HOST,
            port=APP_PORT,
            log_level="warning",
            access_log=False,
        )
        self.server = uvicorn.Server(config)
        self.thread = threading.Thread(target=self.server.run, daemon=True)
        self.thread.start()

        deadline = time.time() + 45
        while time.time() < deadline:
            if self._is_healthy():
                return
            time.sleep(0.4)
        raise RuntimeError("Desktop backend failed to start on localhost:8765")

    def stop(self) -> None:
        if self.server is not None:
            self.server.should_exit = True

    def _is_healthy(self) -> bool:
        try:
            response = requests.get(f"{API_BASE}/health", timeout=1.5)
            return response.ok
        except requests.RequestException:
            return False


class OBSDesktopApp:
    def __init__(self) -> None:
        APP_DIR.mkdir(parents=True, exist_ok=True)
        self.backend = BackendServer()
        self.event_queue: "queue.Queue[tuple[str, Any]]" = queue.Queue()
        self.sessions: List[DesktopSession] = self._load_sessions()
        self.current_session_id: Optional[str] = None
        self.is_sending = False

        self.root = tk.Tk()
        self.root.title("OBS Agent")
        self.root.geometry("1320x860")
        self.root.minsize(1100, 720)
        self.root.configure(bg="#141414")
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        self._build_styles()
        self._build_ui()

        self.backend.ensure_running()
        self._set_status("Runtime online", "#68c08b")
        self.root.after(80, self._process_queue)

        if not self.sessions:
            self._create_session()
        else:
            self._switch_session(self.sessions[0].id)

    def _build_styles(self) -> None:
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("Sidebar.TFrame", background="#191919")
        style.configure("Main.TFrame", background="#141414")
        style.configure("Panel.TFrame", background="#1a1a1a")
        style.configure(
            "Sidebar.TButton",
            background="#202020",
            foreground="#ece6da",
            borderwidth=0,
            padding=10,
        )
        style.map("Sidebar.TButton", background=[("active", "#2a2a2a")])
        style.configure(
            "Action.TButton",
            background="#e9dfd0",
            foreground="#151515",
            padding=10,
            borderwidth=0,
        )
        style.map("Action.TButton", background=[("active", "#f2e9dc")])

    def _build_ui(self) -> None:
        shell = ttk.Frame(self.root, style="Main.TFrame")
        shell.pack(fill="both", expand=True)

        self.sidebar = ttk.Frame(shell, style="Sidebar.TFrame", width=280)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)

        self.main = ttk.Frame(shell, style="Main.TFrame")
        self.main.pack(side="left", fill="both", expand=True)

        self._build_sidebar()
        self._build_main()

    def _build_sidebar(self) -> None:
        top = ttk.Frame(self.sidebar, style="Sidebar.TFrame")
        top.pack(fill="x", padx=18, pady=(18, 12))

        search = ttk.Entry(top)
        search.insert(0, "Search")
        search.configure(state="readonly")
        search.pack(fill="x")

        new_thread = ttk.Button(
            self.sidebar,
            text="+  New thread",
            style="Sidebar.TButton",
            command=self._create_session,
        )
        new_thread.pack(fill="x", padx=18, pady=(8, 8))

        history_label = tk.Label(
            self.sidebar,
            text="THREADS",
            bg="#191919",
            fg="#7f7b74",
            font=("SF Pro Text", 12, "bold"),
            anchor="w",
        )
        history_label.pack(fill="x", padx=18, pady=(16, 8))

        self.thread_list = tk.Listbox(
            self.sidebar,
            bg="#171717",
            fg="#ece6da",
            highlightthickness=0,
            borderwidth=0,
            selectbackground="#25221d",
            selectforeground="#f4efe5",
            activestyle="none",
            font=("SF Pro Text", 14),
        )
        self.thread_list.pack(fill="both", expand=True, padx=18, pady=(0, 18))
        self.thread_list.bind("<<ListboxSelect>>", self._on_select_session)

    def _build_main(self) -> None:
        top = ttk.Frame(self.main, style="Main.TFrame")
        top.pack(fill="x", padx=28, pady=(22, 10))

        title_wrap = ttk.Frame(top, style="Main.TFrame")
        title_wrap.pack(side="left", fill="x", expand=True)

        self.title_label = tk.Label(
            title_wrap,
            text="New thread",
            bg="#141414",
            fg="#f2eee6",
            font=("SF Pro Display", 28, "bold"),
            anchor="w",
        )
        self.title_label.pack(anchor="w")

        self.status_label = tk.Label(
            top,
            text="Starting backend…",
            bg="#141414",
            fg="#8b877f",
            font=("SF Pro Text", 13),
            anchor="e",
        )
        self.status_label.pack(side="right")

        transcript_wrap = ttk.Frame(self.main, style="Panel.TFrame")
        transcript_wrap.pack(fill="both", expand=True, padx=28, pady=(0, 18))

        self.transcript = ScrolledText(
            transcript_wrap,
            wrap="word",
            bg="#171717",
            fg="#f2eee6",
            insertbackground="#f2eee6",
            relief="flat",
            borderwidth=0,
            padx=22,
            pady=18,
            font=("SF Pro Text", 15),
        )
        self.transcript.pack(fill="both", expand=True)
        self.transcript.configure(state="disabled")
        self._configure_transcript_tags()

        composer = ttk.Frame(self.main, style="Panel.TFrame")
        composer.pack(fill="x", padx=28, pady=(0, 22))

        self.input = tk.Text(
            composer,
            height=4,
            wrap="word",
            bg="#1a1a1a",
            fg="#f2eee6",
            insertbackground="#f2eee6",
            relief="flat",
            borderwidth=0,
            padx=18,
            pady=16,
            font=("SF Pro Text", 15),
        )
        self.input.pack(fill="x", padx=10, pady=(10, 8))
        self.input.bind("<Command-Return>", lambda _e: self._submit())
        self.input.bind("<Control-Return>", lambda _e: self._submit())

        bottom = ttk.Frame(composer, style="Panel.TFrame")
        bottom.pack(fill="x", padx=10, pady=(0, 10))

        self.hint_label = tk.Label(
            bottom,
            text="Return 换行，Command+Return 发送",
            bg="#1a1a1a",
            fg="#8b877f",
            font=("SF Pro Text", 12),
        )
        self.hint_label.pack(side="left")

        self.send_button = ttk.Button(
            bottom,
            text="Send",
            style="Action.TButton",
            command=self._submit,
        )
        self.send_button.pack(side="right")

    def _configure_transcript_tags(self) -> None:
        self.transcript.tag_configure("user_label", foreground="#8d8881", font=("SF Pro Text", 12, "bold"))
        self.transcript.tag_configure("assistant_label", foreground="#d9c8aa", font=("SF Pro Text", 12, "bold"))
        self.transcript.tag_configure("body", foreground="#f2eee6", font=("SF Pro Text", 15))
        self.transcript.tag_configure("divider", spacing1=10, spacing3=18)

    def _submit(self) -> str:
        if self.is_sending:
            return "break"
        content = self.input.get("1.0", "end").strip()
        if not content or not self.current_session_id:
            return "break"

        session = self._get_current_session()
        if session is None:
            return "break"

        self.is_sending = True
        self.send_button.configure(text="Sending…")
        self._set_status("Thinking…", "#d9c9ab")
        self._append_message(session, "user", content)
        if len(session.messages) == 1:
            session.title = content[:36]
        self._render_threads()
        self._render_session()

        self.input.delete("1.0", "end")
        threading.Thread(target=self._stream_reply, args=(session.id, content), daemon=True).start()
        return "break"

    def _stream_reply(self, session_id: str, content: str) -> None:
        payload = {
            "tool_name": "chat",
            "parameters": {
                "message": content,
                "session_id": session_id,
                "mode": "agent",
                "permission_mode": "ask",
                "permission_confirmed": False,
                "tool_context": "workspace",
                "context": "Focus on the current workspace, local files, directories, code structure, and repository state.",
            },
        }
        assistant_buffer = ""
        try:
            response = requests.post(f"{API_BASE}/chat/stream", json=payload, stream=True, timeout=120)
            response.raise_for_status()
            for line in response.iter_lines(decode_unicode=True):
                if not line or not line.startswith("data: "):
                    continue
                payload = json.loads(line[6:])
                if payload.get("type") == "answer_delta":
                    assistant_buffer += payload.get("delta", "")
                    self.event_queue.put(("assistant_delta", {"session_id": session_id, "content": assistant_buffer}))
                elif payload.get("error"):
                    self.event_queue.put(("error", {"session_id": session_id, "content": payload["error"]}))
                    return
                elif payload.get("done"):
                    self.event_queue.put(("done", {"session_id": session_id}))
                    return
        except Exception as exc:  # noqa: BLE001
            self.event_queue.put(("error", {"session_id": session_id, "content": str(exc)}))

    def _process_queue(self) -> None:
        try:
            while True:
                event_type, payload = self.event_queue.get_nowait()
                session_id = payload.get("session_id")
                session = self._find_session(session_id)
                if session is None:
                    continue

                if event_type == "assistant_delta":
                    if session.messages and session.messages[-1].role == "assistant":
                        session.messages[-1].content = payload["content"]
                    else:
                        session.messages.append(DesktopMessage(role="assistant", content=payload["content"]))
                    session.updated_at = time.time()
                elif event_type == "error":
                    session.messages.append(DesktopMessage(role="assistant", content=f"请求失败: {payload['content']}"))
                    session.updated_at = time.time()
                    self.is_sending = False
                    self._set_status("Request failed", "#e88a8a")
                elif event_type == "done":
                    self.is_sending = False
                    self._set_status("Runtime online", "#68c08b")

                if not self.is_sending:
                    self.send_button.configure(text="Send")
                self._render_threads()
                if session_id == self.current_session_id:
                    self._render_session()
        except queue.Empty:
            pass
        finally:
            self.root.after(80, self._process_queue)

    def _append_message(self, session: DesktopSession, role: str, content: str) -> None:
        session.messages.append(DesktopMessage(role=role, content=content))
        session.updated_at = time.time()
        self._persist_sessions()

    def _render_threads(self) -> None:
        self.thread_list.delete(0, "end")
        ordered = sorted(self.sessions, key=lambda item: item.updated_at, reverse=True)
        self.sessions = ordered
        selected_index = 0
        for index, session in enumerate(ordered):
            label = f"{session.title}\n{session.preview()}"
            self.thread_list.insert("end", label)
            if session.id == self.current_session_id:
                selected_index = index
        if ordered:
            self.thread_list.selection_clear(0, "end")
            self.thread_list.selection_set(selected_index)

    def _render_session(self) -> None:
        session = self._get_current_session()
        if session is None:
            return
        self.title_label.configure(text=session.title)
        self.transcript.configure(state="normal")
        self.transcript.delete("1.0", "end")
        for message in session.messages:
            label_tag = "user_label" if message.role == "user" else "assistant_label"
            label = "USER" if message.role == "user" else "OBS"
            self.transcript.insert("end", f"{label}\n", label_tag)
            self.transcript.insert("end", f"{message.content}\n\n", ("body", "divider"))
        self.transcript.configure(state="disabled")
        self.transcript.see("end")
        self._persist_sessions()

    def _create_session(self) -> None:
        session = DesktopSession(id=f"session_{uuid.uuid4().hex[:10]}")
        self.sessions.insert(0, session)
        self.current_session_id = session.id
        self._render_threads()
        self._render_session()

    def _switch_session(self, session_id: str) -> None:
        self.current_session_id = session_id
        self._render_threads()
        self._render_session()

    def _on_select_session(self, _event: Any) -> None:
        selection = self.thread_list.curselection()
        if not selection:
            return
        index = selection[0]
        ordered = sorted(self.sessions, key=lambda item: item.updated_at, reverse=True)
        if 0 <= index < len(ordered):
            self._switch_session(ordered[index].id)

    def _find_session(self, session_id: Optional[str]) -> Optional[DesktopSession]:
        if session_id is None:
            return None
        for session in self.sessions:
            if session.id == session_id:
                return session
        return None

    def _get_current_session(self) -> Optional[DesktopSession]:
        return self._find_session(self.current_session_id)

    def _load_sessions(self) -> List[DesktopSession]:
        if not SESSIONS_FILE.exists():
            return []
        try:
            raw = json.loads(SESSIONS_FILE.read_text())
            sessions: List[DesktopSession] = []
            for item in raw:
                sessions.append(
                    DesktopSession(
                        id=item["id"],
                        title=item.get("title", "New thread"),
                        messages=[
                            DesktopMessage(role=msg["role"], content=msg["content"], timestamp=msg.get("timestamp", time.time()))
                            for msg in item.get("messages", [])
                        ],
                        created_at=item.get("created_at", time.time()),
                        updated_at=item.get("updated_at", time.time()),
                    )
                )
            return sessions
        except Exception:  # noqa: BLE001
            return []

    def _persist_sessions(self) -> None:
        payload = [
            {
                "id": session.id,
                "title": session.title,
                "messages": [
                    {"role": msg.role, "content": msg.content, "timestamp": msg.timestamp}
                    for msg in session.messages
                ],
                "created_at": session.created_at,
                "updated_at": session.updated_at,
            }
            for session in self.sessions
        ]
        SESSIONS_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2))

    def _set_status(self, text: str, color: str) -> None:
        self.status_label.configure(text=text, fg=color)

    def on_close(self) -> None:
        self._persist_sessions()
        self.backend.stop()
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


def run_desktop_app() -> None:
    app = OBSDesktopApp()
    app.run()
