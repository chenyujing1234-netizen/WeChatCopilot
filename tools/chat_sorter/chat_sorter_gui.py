"""文件传输助手聊天分类工具——tkinter 界面。

流程：确认源文件、素材根目录与 LLM 配置 -> 点“分析”（LLM 逐批判断，只推荐不写盘）
-> 在表格中查看/修改每条消息的目标目录 -> 点“确认写入”才真正写入。
LLM 配置保存在脚本旁的 llm_config.json，下次启动自动加载。
"""

from __future__ import annotations

import json
import queue
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk

import chat_sorter_core as core

DEFAULT_SOURCE = (
    r"D:\weChat_assistance\素材\我\我的微信导出数据\wxid_jzemtwvdyvml21"
    r"\structured_data\chat_txt\文件传输助手.txt"
)
DEFAULT_ROOT = r"D:\weChat_assistance\素材"
DEFAULT_OUTPUT = "微信聊天记录.txt"
# 默认使用智谱 GLM 的 OpenAI 兼容地址（与 ContextBuddy 内置服务商一致），可改成任意兼容服务
DEFAULT_BASE_URL = "https://open.bigmodel.cn/api/paas/v4"
DEFAULT_MODEL = "glm-4.6"
CONFIG_PATH = Path(__file__).with_name("llm_config.json")
UNCLASSIFIED = "未分类"


def load_llm_config() -> dict:
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_llm_config(cfg: dict) -> None:
    try:
        CONFIG_PATH.write_text(
            json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except OSError:
        pass


class ChatSorterApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("微信聊天分类工具（文件传输助手·LLM 判定）")
        self.geometry("1180x780")
        self.minsize(960, 620)

        self.assignments: list[dict] = []  # [{"result": ClassifyResult, "target": CandidateDir|None}]
        self.candidates: list[core.CandidateDir] = []
        self.cand_by_display: dict[str, core.CandidateDir] = {}
        self._queue: queue.Queue = queue.Queue()
        self._cancel_event: threading.Event | None = None  # 分析运行中的取消信号
        self._analysis_started: float = 0.0  # 本轮分析开始时刻（monotonic），用于显示已用秒数
        cfg = load_llm_config()

        self._build_ui(cfg)
        self.after(100, self._poll_queue)

    # ---------- 界面搭建 ----------

    def _build_ui(self, cfg: dict) -> None:
        top = ttk.Frame(self, padding=(10, 8))
        top.pack(fill="x")
        top.columnconfigure(1, weight=1)

        ttk.Label(top, text="源文件:").grid(row=0, column=0, sticky="w", pady=2)
        self.src_var = tk.StringVar(value=cfg.get("source", DEFAULT_SOURCE))
        ttk.Entry(top, textvariable=self.src_var).grid(row=0, column=1, sticky="ew", padx=4)
        ttk.Button(top, text="浏览…", command=self._browse_source).grid(row=0, column=2)

        ttk.Label(top, text="素材根目录:").grid(row=1, column=0, sticky="w", pady=2)
        self.root_var = tk.StringVar(value=cfg.get("root", DEFAULT_ROOT))
        ttk.Entry(top, textvariable=self.root_var).grid(row=1, column=1, sticky="ew", padx=4)
        ttk.Button(top, text="浏览…", command=self._browse_root).grid(row=1, column=2)

        ttk.Label(top, text="LLM API:").grid(row=2, column=0, sticky="w", pady=2)
        api_row = ttk.Frame(top)
        api_row.grid(row=2, column=1, columnspan=2, sticky="ew")
        self.base_var = tk.StringVar(value=cfg.get("base_url", DEFAULT_BASE_URL))
        ttk.Entry(api_row, textvariable=self.base_var).pack(side="left", fill="x", expand=True, padx=(4, 8))
        ttk.Label(api_row, text="模型:").pack(side="left")
        self.model_var = tk.StringVar(value=cfg.get("model", DEFAULT_MODEL))
        ttk.Entry(api_row, textvariable=self.model_var, width=16).pack(side="left", padx=(3, 8))
        ttk.Label(api_row, text="密钥:").pack(side="left")
        self.key_var = tk.StringVar(value=cfg.get("api_key", ""))
        ttk.Entry(api_row, textvariable=self.key_var, show="*", width=26).pack(side="left", padx=3)
        ttk.Label(api_row, text="并发:").pack(side="left")
        self.conc_var = tk.IntVar(value=int(cfg.get("concurrency", 4)))

        ttk.Label(top, text="写入文件名:").grid(row=3, column=0, sticky="w", pady=2)
        out_row = ttk.Frame(top)
        out_row.grid(row=3, column=1, columnspan=2, sticky="ew")
        self.out_var = tk.StringVar(value=cfg.get("output_name", DEFAULT_OUTPUT))
        ttk.Entry(out_row, textvariable=self.out_var, width=24).pack(side="left", padx=(4, 14))
        ttk.Label(out_row, text="每批条数:").pack(side="left")
        self.batch_var = tk.IntVar(value=int(cfg.get("batch_size", 20)))
        ttk.Spinbox(out_row, from_=5, to=50, textvariable=self.batch_var, width=5).pack(side="left", padx=3)
        ttk.Spinbox(out_row, from_=1, to=8, textvariable=self.conc_var, width=5).pack(side="left", padx=(14, 0))
        ttk.Label(out_row, text="目录深度:").pack(side="left", padx=(14, 0))
        self.depth_var = tk.IntVar(value=int(cfg.get("max_depth", 1)))
        ttk.Spinbox(out_row, from_=1, to=5, textvariable=self.depth_var, width=5).pack(side="left", padx=3)
        self.analyze_btn = ttk.Button(out_row, text="分 析", command=self._start_analysis)
        self.analyze_btn.pack(side="left", padx=(18, 4))

        self.status_var = tk.StringVar(value="填好 API 密钥后点击“分析”。分析只由 LLM 做推荐，不会写任何文件。")
        ttk.Label(self, textvariable=self.status_var, padding=(12, 2)).pack(fill="x")

        # 目录下拉行：放在列表上方，方便查看与批量修改
        assign = ttk.Frame(self, padding=(10, 4))
        assign.pack(fill="x")
        ttk.Label(assign, text="将选中行的目标目录改为:").pack(side="left")
        self.dir_var = tk.StringVar(value=UNCLASSIFIED)
        self.dir_combo = ttk.Combobox(assign, textvariable=self.dir_var, state="disabled", width=44)
        self.dir_combo.pack(side="left", padx=4)
        self.apply_btn = ttk.Button(assign, text="应用到选中行", command=self._apply_target, state="disabled")
        self.apply_btn.pack(side="left")
        ttk.Button(
            assign, text="全选", command=lambda: self.tree.selection_set(self.tree.get_children())
        ).pack(side="left", padx=(12, 0))
        ttk.Button(
            assign, text="全不选", command=lambda: self.tree.selection_remove(self.tree.selection())
        ).pack(side="left")

        columns = ("idx", "time", "preview", "dir", "reason")
        self.tree = ttk.Treeview(self, columns=columns, show="headings", selectmode="extended")
        for col, text, width, anchor in (
            ("idx", "序号", 56, "e"),
            ("time", "时间", 138, "w"),
            ("preview", "内容预览", 430, "w"),
            ("dir", "推荐目录（可修改）", 250, "w"),
            ("reason", "LLM 理由", 190, "w"),
        ):
            self.tree.heading(col, text=text)
            self.tree.column(col, width=width, anchor=anchor, stretch=(col == "preview"))
        self.tree.tag_configure("noise", foreground="#888888")
        self.tree.tag_configure("unmatched", foreground="#b06000")
        self.tree.bind("<Double-1>", self._show_detail)

        tree_frame = ttk.Frame(self)
        tree_frame.pack(fill="both", expand=True, padx=10, pady=4)
        ybar = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=ybar.set)
        self.tree.pack(side="left", fill="both", expand=True)
        ybar.pack(side="right", fill="y")

        bottom = ttk.Frame(self, padding=(10, 6))
        bottom.pack(fill="x")
        self.confirm_btn = ttk.Button(bottom, text="确认写入", command=self._confirm_write, state="disabled")
        self.confirm_btn.pack(side="left")
        ttk.Label(
            bottom, text="“确认写入”后才会把消息真正追加到各目录的 txt 文件中（已存在的行自动跳过）。"
        ).pack(side="left", padx=10)

        self.result_text = scrolledtext.ScrolledText(self, height=9, wrap="word", state="disabled")
        self.result_text.pack(fill="both", padx=10, pady=(4, 10))

    # ---------- 事件处理 ----------

    def _browse_source(self) -> None:
        path = filedialog.askopenfilename(
            title="选择会话 txt 文件", filetypes=[("文本文件", "*.txt"), ("所有文件", "*.*")]
        )
        if path:
            self.src_var.set(path)

    def _browse_root(self) -> None:
        path = filedialog.askdirectory(title="选择素材根目录")
        if path:
            self.root_var.set(path)

    def _start_analysis(self) -> None:
        src = self.src_var.get().strip()
        root = self.root_var.get().strip()
        api_key = self.key_var.get().strip()
        if not src or not Path(src).is_file():
            messagebox.showerror("缺少源文件", "请先选择有效的会话 txt 文件。")
            return
        if not root or not Path(root).is_dir():
            messagebox.showerror("缺少素材根目录", "请先选择有效的素材根目录。")
            return
        if not api_key:
            messagebox.showerror("缺少 API 密钥", "请先填写 LLM API 密钥（OpenAI 兼容服务）。")
            return
        cfg = {
            "source": src,
            "root": root,
            "base_url": self.base_var.get().strip(),
            "model": self.model_var.get().strip(),
            "api_key": api_key,
            "concurrency": max(1, min(8, int(self.conc_var.get() or 4))),
            "batch_size": max(5, min(50, int(self.batch_var.get() or 20))),
            "max_depth": max(1, min(5, int(self.depth_var.get() or 1))),
            "output_name": self.out_var.get().strip(),
        }
        save_llm_config(cfg)
        self._cancel_event = threading.Event()
        self._analysis_started = time.monotonic()
        # 运行中按钮变为“停止”，可随时中止剩余批次（已完成的结果仍然保留）
        self.analyze_btn.configure(text="停 止", command=self._cancel_analysis)
        self.confirm_btn.configure(state="disabled")
        self.apply_btn.configure(state="disabled")
        self.dir_combo.configure(state="disabled")
        self.status_var.set("正在解析消息与扫描目录…")
        threading.Thread(target=self._analyze_worker, args=(cfg,), daemon=True).start()

    def _cancel_analysis(self) -> None:
        if self._cancel_event is not None:
            self._cancel_event.set()
        self.analyze_btn.configure(state="disabled")
        self.status_var.set("正在停止：等待进行中的 LLM 批次结束后，返回已完成的分类…")

    def _analyze_worker(self, cfg: dict) -> None:
        try:
            messages = core.parse_chat_txt(cfg["source"])
            candidates = core.scan_candidate_dirs(cfg["root"], max_depth=cfg.get("max_depth"))

            def call_llm(llm_messages: list[dict]) -> str:
                return core.openai_chat_call(
                    cfg["base_url"], cfg["api_key"], cfg["model"], llm_messages
                )

            results = core.classify_with_llm(
                messages,
                candidates,
                call_llm=call_llm,
                batch_size=cfg["batch_size"],
                concurrency=cfg["concurrency"],
                progress_cb=lambda done, total, failed: self._queue.put(
                    ("progress", done, total, failed)
                ),
                cancel_event=self._cancel_event,
            )
            self._queue.put(("done", results, candidates, ""))
        except Exception as exc:
            self._queue.put(("error", None, None, str(exc)))

    def _poll_queue(self) -> None:
        try:
            while True:
                item = self._queue.get_nowait()
                kind = item[0]
                if kind == "progress":
                    _, done, total, failed = item
                    elapsed = max(0, int(time.monotonic() - self._analysis_started))
                    extra = f"（{failed} 失败）" if failed else ""
                    self.status_var.set(
                        f"LLM 分类中：已完成 {done}/{total} 批{extra} · 已用 {elapsed} 秒…"
                    )
                elif kind == "done":
                    self._on_analysis_done(item[1], item[2])
                else:
                    self._on_analysis_failed(item[3])
        except queue.Empty:
            pass
        self.after(100, self._poll_queue)

    def _on_analysis_failed(self, error: str) -> None:
        self._cancel_event = None
        self.analyze_btn.configure(text="分 析", command=self._start_analysis, state="normal")
        self.status_var.set("分析失败，请检查路径与 API 配置后重试。")
        messagebox.showerror("分析失败", error)

    def _on_analysis_done(self, results, candidates) -> None:
        self._cancel_event = None
        self.analyze_btn.configure(text="分 析", command=self._start_analysis)
        self.candidates = candidates
        self.cand_by_display = {core.display_rel(c): c for c in candidates}
        self.assignments = [{"result": r, "target": r.candidate} for r in results]

        self.tree.delete(*self.tree.get_children())
        for i, item in enumerate(self.assignments, start=1):
            res = item["result"]
            preview = res.message.content.replace("\\n", " ")
            if len(preview) > 70:
                preview = preview[:70] + "…"
            target = core.display_rel(item["target"]) if item["target"] else UNCLASSIFIED
            if core.is_noise_content(res.message.content):
                tag = "noise"
            elif item["target"]:
                tag = ""
            else:
                tag = "unmatched"
            self.tree.insert(
                "", "end", iid=str(i - 1),
                values=(i, res.message.time_str, preview, target, res.reason),
                tags=(tag,),
            )

        self.dir_combo.configure(values=[UNCLASSIFIED] + list(self.cand_by_display))
        self.dir_combo.set(UNCLASSIFIED)
        self.dir_combo.configure(state="readonly")
        self.apply_btn.configure(state="normal")
        self.analyze_btn.configure(state="normal")
        self.confirm_btn.configure(state="normal")
        self.status_var.set(core.summarize(results) + "  双击行可查看完整内容。")
        self._refresh_confirm_label()

    def _apply_target(self) -> None:
        selected = self.tree.selection()
        if not selected:
            messagebox.showinfo("未选择行", "请先在表格中选择要修改目标目录的消息行。")
            return
        choice = self.dir_var.get()
        target = None if choice == UNCLASSIFIED else self.cand_by_display.get(choice)
        if choice != UNCLASSIFIED and target is None:
            messagebox.showerror("无效目录", "请从下拉框中选择有效的目录。")
            return
        for iid in selected:
            item = self.assignments[int(iid)]
            item["target"] = target
            values = list(self.tree.item(iid, "values"))
            values[3] = core.display_rel(target) if target else UNCLASSIFIED
            values[4] = "手动指定" if target else ""
            self.tree.item(iid, values=values)
            if target:
                self.tree.item(iid, tags=())
        self._refresh_confirm_label()

    def _refresh_confirm_label(self) -> None:
        count = sum(1 for item in self.assignments if item["target"])
        self.confirm_btn.configure(text=f"确认写入（{count} 条）")

    def _confirm_write(self) -> None:
        pairs = [(item["target"], item["result"].message) for item in self.assignments if item["target"]]
        unclassified = len(self.assignments) - len(pairs)
        if not pairs:
            messagebox.showinfo("没有可写入的消息", "当前没有消息被指定到任何目录（未分类的消息不会写入）。")
            return
        out_name = core.sanitize_output_name(self.out_var.get())
        if not messagebox.askyesno(
            "确认写入",
            f"即将把 {len(pairs)} 条消息追加写入到对应目录下的“{out_name}”（{unclassified} 条未分类将被跳过）。\n确定继续吗？",
        ):
            return
        try:
            reports = core.apply_writes(
                pairs, output_filename=self.out_var.get(), source_label=Path(self.src_var.get()).name
            )
        except Exception as exc:
            messagebox.showerror("写入失败", str(exc))
            return
        lines = []
        for rep in reports:
            state = (
                f"写入 {rep.written} 条，跳过已存在 {rep.skipped_existing} 条"
                if not rep.error
                else f"失败：{rep.error}"
            )
            lines.append(f"{state}\n  {rep.file_path}")
        total_written = sum(r.written for r in reports)
        lines.append(f"完成：共写入 {total_written} 条；未分类跳过 {unclassified} 条。")
        self.result_text.configure(state="normal")
        self.result_text.delete("1.0", "end")
        self.result_text.insert("1.0", "\n".join(lines))
        self.result_text.configure(state="disabled")
        self.status_var.set(f"写入完成：{total_written} 条新消息，重复行已自动跳过。")

    def _show_detail(self, _event) -> None:
        selected = self.tree.selection()
        if not selected:
            return
        item = self.assignments[int(selected[0])]
        msg = item["result"].message
        win = tk.Toplevel(self)
        win.title(f"消息详情 - {msg.time_str}")
        win.geometry("820x560")
        header = (
            f"时间: {msg.time_str}\n发送者: {msg.sender_display} ({msg.sender_username})\n"
            f"当前目标目录: {core.display_rel(item['target']) if item['target'] else UNCLASSIFIED}\n"
            f"LLM 理由: {item['result'].reason}\n" + "-" * 60 + "\n\n"
        )
        text = scrolledtext.ScrolledText(win, wrap="word")
        text.pack(fill="both", expand=True)
        text.insert("1.0", header + msg.content.replace("\\n", "\n"))
        text.configure(state="disabled")


if __name__ == "__main__":
    ChatSorterApp().mainloop()
