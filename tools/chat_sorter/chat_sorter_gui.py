"""文件传输助手聊天分类工具——tkinter 界面。

流程：选好源文件与素材根目录 -> 点“加载”先展示全部消息，双击“涉及人物”列
标注聊天人物（从列表选择或新增）-> 点“分析”（LLM 把人物标注一并考虑，
逐批推荐目录，只推荐不写盘）-> 在表格中查看/修改目标目录 -> 点“确认写入”
把消息连同人物标注一起追加到各目录的 txt。
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
# 分类缓存：同一消息上次分析过就不再调 LLM，用户确认过的目录直接沿用
CACHE_PATH = Path(__file__).with_name("classify_cache.json")
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

        self.assignments: list[dict] = []  # [{"message", "result", "target"}]
        self.candidates: list[core.CandidateDir] = []
        self.cand_by_display: dict[str, core.CandidateDir] = {}
        self._queue: queue.Queue = queue.Queue()
        self._cancel_event: threading.Event | None = None  # 分析运行中的取消信号
        self._analysis_started: float = 0.0  # 本轮分析开始时刻（monotonic），用于显示已用秒数
        self._msg_index: dict[int, int] = {}  # id(消息) -> 行号，用于把批次结果映射回表格行
        self._noise_count = 0  # 系统/附件消息数（分析开始即已知，无需等 LLM）
        self._cache: dict = {}  # 分类缓存 entries（加载时从磁盘读取）
        self._custom_people: list[str] = []  # 用户新增的列表外人物（持久化在缓存文件）
        self._msg_people: dict[str, list[str]] = {}  # message_key -> 人物标注（持久化，重启后恢复）
        self._loaded_sig: tuple | None = None  # 已加载数据的 (源文件, 根目录, 深度)
        self._dir_editor: ttk.Combobox | None = None  # 行内目录编辑器（双击“推荐目录”列出现）
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
        self.load_btn = ttk.Button(out_row, text="加 载", command=self._load_data)
        self.load_btn.pack(side="left", padx=(18, 4))
        self.analyze_btn = ttk.Button(out_row, text="分 析", command=self._start_analysis)
        self.analyze_btn.pack(side="left", padx=(0, 4))

        self.status_var = tk.StringVar(
            value="先点“加 载”展示全部消息，双击“涉及人物”列标注聊天人物，再点“分 析”让 LLM 推荐目录（分析不写任何文件）。"
        )
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

        # 列表区：先建容器，Treeview 必须以容器为父级，
        # 否则列表会被排到主窗口底部，中间只剩一片空白
        tree_frame = ttk.Frame(self)
        tree_frame.pack(fill="both", expand=True, padx=10, pady=4)

        columns = ("idx", "time", "preview", "people", "dir", "reason")
        self.tree = ttk.Treeview(tree_frame, columns=columns, show="headings", selectmode="extended")
        for col, text, width, anchor in (
            ("idx", "序号", 52, "e"),
            ("time", "时间", 132, "w"),
            ("preview", "内容预览", 380, "w"),
            ("people", "涉及人物（双击标注）", 140, "w"),
            ("dir", "推荐目录（可修改）", 220, "w"),
            ("reason", "LLM 理由", 190, "w"),
        ):
            self.tree.heading(col, text=text)
            self.tree.column(col, width=width, anchor=anchor, stretch=(col == "preview"))
        self.tree.tag_configure("noise", foreground="#888888")
        self.tree.tag_configure("unmatched", foreground="#b06000")
        self.tree.tag_configure("pending", foreground="#7a7aa0")  # 分析中、尚未出结果的行
        self.tree.bind("<Double-1>", self._on_tree_double_click)
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

    def _load_data(self) -> bool:
        """解析源文件 + 扫描候选目录 + 读取人物标注缓存，先把所有数据展示到表格。

        缓存命中的消息（上次分析过/已确认写入）直接定稿显示；分析前即可标注
        “涉及人物”与手动指定目录。返回是否加载成功。
        """
        if self._cancel_event is not None:
            messagebox.showinfo("分析进行中", "请等本轮分析结束后再重新加载数据。")
            return False
        src = self.src_var.get().strip()
        root = self.root_var.get().strip()
        if not src or not Path(src).is_file():
            messagebox.showerror("缺少源文件", "请先选择有效的会话 txt 文件。")
            return False
        if not root or not Path(root).is_dir():
            messagebox.showerror("缺少素材根目录", "请先选择有效的素材根目录。")
            return False
        depth = max(1, min(5, int(self.depth_var.get() or 1)))
        try:
            messages = core.parse_chat_txt(src)
            candidates = core.scan_candidate_dirs(root, max_depth=depth)
        except Exception as exc:
            messagebox.showerror("加载失败", str(exc))
            return False

        cache_data = core.load_cache_data(CACHE_PATH)
        self._cache = cache_data["entries"]
        self._custom_people = cache_data["people"]
        self._msg_people = cache_data["msg_people"]
        for m in messages:  # 恢复上次标注的人物
            key = core.message_key(m)
            if key in self._msg_people:
                m.people = list(self._msg_people[key])

        self.candidates = candidates
        self.cand_by_display = {core.display_rel(c): c for c in candidates}
        self.assignments = [{"message": m, "result": None, "target": None} for m in messages]
        self._msg_index = {id(m): i for i, m in enumerate(messages)}
        self._noise_count = sum(1 for m in messages if core.is_noise_content(m.content))
        self._loaded_sig = (src, root, depth)
        self._populate_rows_initial()

        self.dir_combo.configure(values=[UNCLASSIFIED] + list(self.cand_by_display))
        self.dir_combo.set(UNCLASSIFIED)
        self.dir_combo.configure(state="readonly")
        self.apply_btn.configure(state="normal")
        self.status_var.set(
            f"已加载 {len(messages)} 条消息、{len(candidates)} 个候选目录。"
            "双击“涉及人物”列可标注聊天人物；点“分 析”让 LLM 结合人物推荐目录。"
        )
        return True

    def _populate_rows_initial(self) -> None:
        """把当前 assignments 全部填进表格：缓存命中/系统附件直接定稿，其余待分析。"""
        self.tree.delete(*self.tree.get_children())
        cached_hits = 0
        for i, item in enumerate(self.assignments):
            msg = item["message"]
            preview = msg.content.replace("\\n", " ")
            if len(preview) > 70:
                preview = preview[:70] + "…"
            people_text = "、".join(msg.people)
            hit = None
            if not core.is_noise_content(msg.content):
                hit = core.cache_lookup(self._cache, msg, self.cand_by_display)
            if hit is not None:
                # 缓存命中：上次分析过（或已确认写入）直接显示，不再调 LLM
                item["result"] = hit
                item["target"] = hit.candidate
                cached_hits += 1
                values = (
                    i + 1, msg.time_str, preview, people_text,
                    core.display_rel(hit.candidate) if hit.candidate else UNCLASSIFIED,
                    hit.reason,
                )
                tag = () if hit.candidate else "unmatched"
            elif core.is_noise_content(msg.content):
                values = (i + 1, msg.time_str, preview, people_text, UNCLASSIFIED, "系统/附件消息，自动跳过")
                tag = "noise"
            else:
                values = (i + 1, msg.time_str, preview, people_text, "未分析", "")
                tag = "pending"
            self.tree.insert("", "end", iid=str(i), values=values, tags=(tag,))
        return cached_hits

    def _save_cache_file(self) -> None:
        """把分类缓存、人物名单与消息人物标注整体落盘（失败不打断界面）。"""
        try:
            core.save_cache(
                CACHE_PATH, self._cache,
                people=self._custom_people, msg_people=self._msg_people,
            )
        except OSError:
            pass

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
        depth = max(1, min(5, int(self.depth_var.get() or 1)))
        if self._loaded_sig != (src, root, depth) and not self._load_data():
            return  # 首次或源/根目录/深度变了：先加载展示，再开始分析
        cfg = {
            "source": src,
            "root": root,
            "base_url": self.base_var.get().strip(),
            "model": self.model_var.get().strip(),
            "api_key": api_key,
            "concurrency": max(1, min(8, int(self.conc_var.get() or 4))),
            "batch_size": max(5, min(50, int(self.batch_var.get() or 20))),
            "max_depth": depth,
            "output_name": self.out_var.get().strip(),
        }
        save_llm_config(cfg)
        self._cancel_event = threading.Event()
        self._analysis_started = time.monotonic()
        # 运行中按钮变为“停止”，可随时中止剩余批次（已完成的结果仍然保留）
        self.analyze_btn.configure(text="停 止", command=self._cancel_analysis)
        self.load_btn.configure(state="disabled")
        self.confirm_btn.configure(state="disabled")
        self.apply_btn.configure(state="disabled")
        self.dir_combo.configure(state="disabled")
        hits = sum(1 for a in self.assignments if a["result"] is not None)
        todo = len(self.assignments) - self._noise_count - hits
        self.status_var.set(f"已命中缓存 {hits} 条，本次需 LLM 分析 {todo} 条…")
        messages = [item["message"] for item in self.assignments]
        threading.Thread(
            target=self._analyze_worker, args=(cfg, messages, self.candidates), daemon=True
        ).start()

    def _cancel_analysis(self) -> None:
        if self._cancel_event is not None:
            self._cancel_event.set()
        self.analyze_btn.configure(state="disabled")
        self.status_var.set("正在停止：等待进行中的 LLM 批次结束后，返回已完成的分类…")

    def _analyze_worker(self, cfg: dict, messages: list, candidates: list) -> None:
        try:
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
                progress_cb=lambda done, total, failed, chunk: self._queue.put(
                    ("progress", done, total, failed, chunk)
                ),
                cancel_event=self._cancel_event,
                cache=self._cache,
            )
            # 本轮新结果连同人物名单与标注落盘，下次不再重复分析
            self._save_cache_file()
            self._queue.put(("done", results))
        except Exception as exc:
            self._queue.put(("error", str(exc)))

    def _poll_queue(self) -> None:
        try:
            while True:
                item = self._queue.get_nowait()
                kind = item[0]
                if kind == "progress":
                    self._on_batch_progress(item[1], item[2], item[3], item[4])
                elif kind == "done":
                    self._on_analysis_done(item[1])
                else:
                    self._on_analysis_failed(item[1])
        except queue.Empty:
            pass
        self.after(100, self._poll_queue)

    def _tag_for_result(self, res) -> tuple:
        if core.is_noise_content(res.message.content):
            return ("noise",)
        return () if res.candidate else ("unmatched",)

    def _apply_result_to_row(self, idx: int, res) -> None:
        """把一条分类结果写回 assignments 与表格行。"""
        item = self.assignments[idx]
        item["result"] = res
        item["target"] = res.candidate
        values = list(self.tree.item(str(idx), "values"))
        values[4] = core.display_rel(res.candidate) if res.candidate else UNCLASSIFIED
        values[5] = res.reason
        self.tree.item(str(idx), values=values, tags=(self._tag_for_result(res),))

    def _on_batch_progress(self, done: int, total: int, failed: int, chunk) -> None:
        # 实时刷新：本批结果一到就更新对应行
        for res in chunk:
            idx = self._msg_index.get(id(res.message))
            if idx is not None:
                self._apply_result_to_row(idx, res)
        elapsed = max(0, int(time.monotonic() - self._analysis_started))
        extra = f"（{failed} 失败）" if failed else ""
        shown = sum(1 for a in self.assignments if a["result"] is not None) + self._noise_count
        self.status_var.set(
            f"LLM 分类中：已完成 {done}/{total} 批{extra} · "
            f"已出结果 {shown}/{len(self.assignments)} 条 · 已用 {elapsed} 秒…"
        )

    def _on_analysis_failed(self, error: str) -> None:
        self._cancel_event = None
        self.analyze_btn.configure(text="分 析", command=self._start_analysis, state="normal")
        self.load_btn.configure(state="normal")
        # 中途失败：尚未出结果的行标“分析中止”，已出结果的行保持原样
        for i, item in enumerate(self.assignments):
            if item["result"] is None and not core.is_noise_content(item["message"].content):
                values = list(self.tree.item(str(i), "values"))
                values[4] = UNCLASSIFIED
                values[5] = "分析中止"
                self.tree.item(str(i), values=values, tags=("unmatched",))
        self.status_var.set("分析失败，请检查路径与 API 配置后重试。")
        messagebox.showerror("分析失败", error)

    def _on_analysis_done(self, results) -> None:
        self._cancel_event = None
        self.analyze_btn.configure(text="分 析", command=self._start_analysis)
        self.load_btn.configure(state="normal")
        # 用最终结果全量刷新一遍（补齐系统/附件行等所有行），保证与整体结果一致
        for i, res in enumerate(results):
            if i < len(self.assignments):
                self._apply_result_to_row(i, res)
        self.dir_combo.configure(state="readonly")
        self.apply_btn.configure(state="normal")
        self.analyze_btn.configure(state="normal")
        self.confirm_btn.configure(state="normal")
        self.status_var.set(
            core.summarize(results)
            + "  双击“推荐目录”改目录；双击“涉及人物”标注人物（改完再分析会把新人物考虑进去）；双击其他位置看详情。"
        )
        self._refresh_confirm_label()

    def _on_tree_double_click(self, event) -> None:
        """双击分发：#4“涉及人物”列开标注对话框，#5“推荐目录”列行内改目录，其余看详情。"""
        if self.tree.identify("region", event.x, event.y) != "cell":
            self._show_detail(event)
            return
        col = self.tree.identify_column(event.x)
        row = self.tree.identify_row(event.y)
        if not row:
            self._show_detail(event)
            return
        if col == "#4":
            self._edit_people(row)
        elif col == "#5":
            self._begin_dir_edit(row)
        else:
            self._show_detail(event)

    def _people_choices(self, extra: list[str] | None = None) -> list[str]:
        """人物候选名单：顶层候选目录名 + 用户新增人物 + 所有已标注过的人物。"""
        names = {c.rel_display for c in self.candidates if c.depth == 1}
        names.update(self._custom_people)
        for people in self._msg_people.values():
            names.update(people)
        if extra:
            names.update(extra)
        return sorted(names)

    def _edit_people(self, row: str) -> None:
        """双击“涉及人物”列：弹窗多选标注该消息的聊天人物，可新增列表外人物。"""
        if self._cancel_event is not None:
            self.status_var.set("分析进行中，请等本轮结束后再标注人物。")
            return
        if not self.assignments:
            messagebox.showinfo("未加载数据", "请先点击“加 载”展示消息。")
            return
        item = self.assignments[int(row)]
        msg = item["message"]
        win = tk.Toplevel(self)
        win.title(f"标注涉及人物 - 第 {int(row) + 1} 条")
        win.geometry("360x430")
        win.transient(self)
        ttk.Label(win, text="勾选该消息涉及的聊天人物（可多选）：", padding=(10, 10, 10, 4)).pack(anchor="w")

        list_frame = ttk.Frame(win)
        list_frame.pack(fill="both", expand=True, padx=10)
        listbox = tk.Listbox(list_frame, selectmode="multiple", exportselection=False)
        scroll = ttk.Scrollbar(list_frame, orient="vertical", command=listbox.yview)
        listbox.configure(yscrollcommand=scroll.set)
        listbox.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        def selected_names() -> set[str]:
            return {listbox.get(i) for i in listbox.curselection()}

        def refill(select: set[str]) -> None:
            listbox.delete(0, "end")
            for name in self._people_choices(sorted(select)):
                listbox.insert("end", name)
                if name in select:
                    listbox.selection_set("end")

        refill(set(msg.people))

        add_row = ttk.Frame(win, padding=(10, 6))
        add_row.pack(fill="x")
        new_var = tk.StringVar()
        entry = ttk.Entry(add_row, textvariable=new_var)
        entry.pack(side="left", fill="x", expand=True)
        entry.focus_set()

        def add_person() -> None:
            name = new_var.get().strip()
            if not name:
                return
            if name not in self._custom_people and name not in {
                c.rel_display for c in self.candidates if c.depth == 1
            }:
                self._custom_people.append(name)  # 列表外人物持久保存，下次仍在
                self._save_cache_file()
            entry.delete(0, "end")
            refill(selected_names() | {name})
            entry.focus_set()

        ttk.Button(add_row, text="新增并勾选", command=add_person).pack(side="left", padx=(6, 0))
        win.bind("<Return>", lambda _e: add_person())

        btn_row = ttk.Frame(win, padding=(10, 6))
        btn_row.pack()

        def commit() -> None:
            self._commit_people(row, sorted(selected_names()))
            win.destroy()

        ttk.Button(btn_row, text="确 定", command=commit).pack(side="left", padx=6)
        ttk.Button(btn_row, text="取 消", command=win.destroy).pack(side="left", padx=6)
        win.protocol("WM_DELETE_WINDOW", win.destroy)

    def _commit_people(self, row: str, people: list[str]) -> None:
        """把人物标注应用到消息、持久化缓存与表格行（由标注对话框“确定”调用）。"""
        item = self.assignments[int(row)]
        msg = item["message"]
        msg.people = core.normalize_people(people)
        self._msg_people[core.message_key(msg)] = list(msg.people)
        self._save_cache_file()
        values = list(self.tree.item(row, "values"))
        values[3] = "、".join(msg.people)
        self.tree.item(row, values=values)
        self.status_var.set(
            f"第 {int(row) + 1} 条消息已标注人物：{'、'.join(msg.people) or '无'}"
            "（下次“分 析”会把这些人物考虑进去）"
        )

    def _begin_dir_edit(self, row: str) -> None:
        if self._cancel_event is not None:
            self.status_var.set("分析进行中，请等本轮结束后再修改目录。")
            return
        if not self.cand_by_display:
            messagebox.showinfo("无候选目录", "尚未扫描到候选目录，请先点击“加 载”。")
            return
        self._end_dir_edit()  # 同一时间只保留一个编辑器
        bbox = self.tree.bbox(row, column="#5")
        if not bbox:
            return
        x, y, w, h = bbox
        item = self.assignments[int(row)]
        current = core.display_rel(item["target"]) if item["target"] else UNCLASSIFIED
        editor = ttk.Combobox(
            self.tree,
            state="readonly",
            values=[UNCLASSIFIED] + list(self.cand_by_display),
        )
        editor.set(current)
        editor.place(x=x, y=y, width=max(w, 200), height=h)
        editor.focus_set()
        editor.bind("<<ComboboxSelected>>", lambda _e: self._commit_dir_edit(row))
        editor.bind("<Return>", lambda _e: self._commit_dir_edit(row))
        editor.bind("<Escape>", lambda _e: self._end_dir_edit())
        editor.bind("<FocusOut>", lambda _e: self._end_dir_edit())
        self._dir_editor = editor

    def _commit_dir_edit(self, row: str) -> None:
        if self._dir_editor is None:
            return
        choice = self._dir_editor.get()
        self._end_dir_edit()
        target = None if choice == UNCLASSIFIED else self.cand_by_display.get(choice)
        if choice != UNCLASSIFIED and target is None:
            return  # 只能从候选列表中选
        item = self.assignments[int(row)]
        item["target"] = target
        values = list(self.tree.item(row, "values"))
        values[4] = core.display_rel(target) if target else UNCLASSIFIED
        values[5] = "手动指定" if target else ""
        self.tree.item(row, values=values)
        if target:
            self.tree.item(row, tags=())
        self._refresh_confirm_label()

    def _end_dir_edit(self) -> None:
        editor, self._dir_editor = self._dir_editor, None
        if editor is not None:
            editor.destroy()

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
            values[4] = core.display_rel(target) if target else UNCLASSIFIED
            values[5] = "手动指定" if target else ""
            self.tree.item(iid, values=values)
            if target:
                self.tree.item(iid, tags=())
        self._refresh_confirm_label()

    def _refresh_confirm_label(self) -> None:
        count = sum(1 for item in self.assignments if item["target"])
        self.confirm_btn.configure(text=f"确认写入（{count} 条）")

    def _confirm_write(self) -> None:
        pairs = [(item["target"], item["message"]) for item in self.assignments if item["target"]]
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
        # 已写入的消息记入缓存：下次分析直接显示确认过的目录，不再调 LLM
        for item in self.assignments:
            if item["target"] is None:
                continue
            key = core.message_key(item["message"])
            old = self._cache.get(key)
            old_reason = str(old.get("reason") or "") if isinstance(old, dict) else ""
            self._cache[key] = {
                "dir": core.display_rel(item["target"]),
                "reason": old_reason,
                "confirmed": True,
                "people": list(item["message"].people),
            }
        self._save_cache_file()

    def _show_detail(self, _event) -> None:
        selected = self.tree.selection()
        if not selected:
            return
        item = self.assignments[int(selected[0])]
        msg = item["message"]
        reason = item["result"].reason if item["result"] else ""
        win = tk.Toplevel(self)
        win.title(f"消息详情 - {msg.time_str}")
        win.geometry("820x560")
        header = (
            f"时间: {msg.time_str}\n发送者: {msg.sender_display} ({msg.sender_username})\n"
            f"涉及人物: {'、'.join(msg.people) or '（未标注）'}\n"
            f"当前目标目录: {core.display_rel(item['target']) if item['target'] else UNCLASSIFIED}\n"
            f"LLM 理由: {reason}\n" + "-" * 60 + "\n\n"
        )
        text = scrolledtext.ScrolledText(win, wrap="word")
        text.pack(fill="both", expand=True)
        text.insert("1.0", header + msg.content.replace("\\n", "\n"))
        text.configure(state="disabled")


if __name__ == "__main__":
    ChatSorterApp().mainloop()
