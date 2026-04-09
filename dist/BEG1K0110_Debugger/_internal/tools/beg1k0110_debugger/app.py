from __future__ import annotations

import queue
import threading
import time
import tkinter as tk
from dataclasses import dataclass
from tkinter import messagebox, ttk
from tkinter.scrolledtext import ScrolledText

try:
    import can
except ImportError:
    can = None

from .protocol import (
    BEG_CONTROL_PRESETS,
    BEG_READ_PRESETS,
    CHARGER_CONTROL_PRESETS,
    CHARGER_READ_PRESETS,
    PROTOCOLS,
    CommandPreset,
    build_beg_payload,
    build_charger_voltage_current_payload,
    charger_request_id,
    charger_response_id,
    decode_beg_payload,
    decode_charger_payload,
    format_can_id,
    format_payload,
    is_charger_frame,
    now_text,
    parse_int,
    parse_payload_hex,
    resolve_beg_arbitration_id,
)


BITRATES = [125000, 250000, 500000, 1000000]
CHANNELS = [f"PCAN_USBBUS{i}" for i in range(1, 9)]
BEG_SCOPES = ("broadcast", "group", "module")


@dataclass
class PollItem:
    protocol_name: str
    metric_name: str
    arbitration_id: int
    data: bytes
    interval: float
    next_due: float = 0.0


class CanWorker:
    def __init__(self, event_queue: queue.Queue):
        self.event_queue = event_queue
        self.command_queue: queue.Queue = queue.Queue()
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.bus = None
        self.connected = False
        self.poll_items: list[PollItem] = []

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        self.command_queue.put(("shutdown", {}))
        self.thread.join(timeout=1.0)
        self._disconnect()

    def connect(self, channel: str, bitrate: int) -> None:
        self.command_queue.put(("connect", {"channel": channel, "bitrate": bitrate}))

    def disconnect(self) -> None:
        self.command_queue.put(("disconnect", {}))

    def send(
        self, arbitration_id: int, data: bytes, protocol_name: str, description: str
    ) -> None:
        self.command_queue.put(
            (
                "send",
                {
                    "arbitration_id": arbitration_id,
                    "data": data,
                    "protocol_name": protocol_name,
                    "description": description,
                },
            )
        )

    def set_poll_items(self, items: list[PollItem]) -> None:
        self.command_queue.put(("poll", {"items": items}))

    def _emit(self, kind: str, **payload: object) -> None:
        self.event_queue.put((kind, payload))

    def _connect(self, channel: str, bitrate: int) -> None:
        if can is None:
            raise RuntimeError(
                "缺少 python-can，请先安装: pip install python-can[pcan]"
            )
        self._disconnect()
        self.bus = can.Bus(interface="pcan", channel=channel, bitrate=bitrate)
        self.connected = True
        self._emit("connection", connected=True, channel=channel, bitrate=bitrate)

    def _disconnect(self) -> None:
        if self.bus is not None:
            try:
                self.bus.shutdown()
            except Exception:
                pass
        self.bus = None
        was_connected = self.connected
        self.connected = False
        if was_connected:
            self._emit("connection", connected=False)

    def _send_frame(
        self, arbitration_id: int, data: bytes, protocol_name: str, description: str
    ) -> None:
        if self.bus is None:
            raise RuntimeError("尚未连接 CAN 适配器")
        msg = can.Message(arbitration_id=arbitration_id, data=data, is_extended_id=True)
        self.bus.send(msg)
        self._emit(
            "tx",
            arbitration_id=arbitration_id,
            data=bytes(data),
            protocol_name=protocol_name,
            description=description,
        )

    def _run(self) -> None:
        while not self.stop_event.is_set():
            self._drain_commands()
            if self.connected and self.bus is not None:
                self._run_polling()
                self._receive_once()
            else:
                time.sleep(0.05)

    def _drain_commands(self) -> None:
        while True:
            try:
                action, payload = self.command_queue.get_nowait()
            except queue.Empty:
                return

            try:
                if action == "connect":
                    self._connect(payload["channel"], payload["bitrate"])
                elif action == "disconnect":
                    self._disconnect()
                elif action == "send":
                    self._send_frame(
                        payload["arbitration_id"],
                        payload["data"],
                        payload["protocol_name"],
                        payload["description"],
                    )
                elif action == "poll":
                    self.poll_items = payload["items"]
                    now = time.monotonic()
                    for item in self.poll_items:
                        item.next_due = now
                elif action == "shutdown":
                    return
            except Exception as exc:
                self._emit("error", message=str(exc))

    def _run_polling(self) -> None:
        if not self.poll_items:
            return
        now = time.monotonic()
        for item in self.poll_items:
            if now < item.next_due:
                continue
            item.next_due = now + item.interval
            try:
                self._send_frame(
                    item.arbitration_id,
                    item.data,
                    item.protocol_name,
                    f"轮询 {item.metric_name}",
                )
            except Exception as exc:
                self._emit(
                    "error",
                    message=f"轮询 {item.protocol_name}/{item.metric_name} 失败: {exc}",
                )
            time.sleep(0.02)

    def _receive_once(self) -> None:
        if self.bus is None:
            return
        try:
            message = self.bus.recv(timeout=0.05)
        except Exception as exc:
            self._emit("error", message=f"接收失败: {exc}")
            return
        if message is None:
            return
        self._emit(
            "rx",
            arbitration_id=message.arbitration_id,
            data=bytes(message.data),
        )


class BegContext:
    protocol_name = "beg1k0110"

    def __init__(self):
        self.display_name = PROTOCOLS[self.protocol_name].display_name
        self.scope_var = tk.StringVar(value="module")
        self.addr_var = tk.StringVar(value="0")
        self.poll_enabled_var = tk.BooleanVar(value=True)
        self.fast_var = tk.StringVar(value="1.0")
        self.slow_var = tk.StringVar(value="3.0")
        self.templates = {
            key: tk.StringVar(value=value)
            for key, value in PROTOCOLS[self.protocol_name].templates.items()
        }
        self.address_preview_var = tk.StringVar(value="-")
        self.status_tree: ttk.Treeview | None = None
        self.status_rows: dict[str, str] = {}


class ChargerContext:
    protocol_name = "charger"

    def __init__(self):
        self.display_name = PROTOCOLS[self.protocol_name].display_name
        self.addr_var = tk.StringVar(value="0")
        self.poll_enabled_var = tk.BooleanVar(value=True)
        self.fast_var = tk.StringVar(value="1.0")
        self.slow_var = tk.StringVar(value="3.0")
        self.status_tree: ttk.Treeview | None = None
        self.status_rows: dict[str, str] = {}


class MultiDeviceDebuggerApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("BEG1K0110 + charger CAN 调试工具")
        self.root.geometry("1480x920")

        self.events: queue.Queue = queue.Queue()
        self.worker = CanWorker(self.events)
        self.worker.start()

        self.channel_var = tk.StringVar(value=CHANNELS[0])
        self.bitrate_var = tk.StringVar(value=str(BITRATES[0]))
        self.connect_state_var = tk.StringVar(value="未连接")

        self.beg = BegContext()
        self.charger = ChargerContext()

        self.command_protocol_var = tk.StringVar(value="beg1k0110")
        self.command_preset_var = tk.StringVar(value=BEG_CONTROL_PRESETS[0].name)
        self.beg_byte0_var = tk.StringVar(value="0x11")
        self.beg_byte1_var = tk.StringVar(value="0x27")
        self.beg_value_var = tk.StringVar(value="0xA0")
        self.charger_voltage_var = tk.StringVar(value="750000")
        self.charger_current_var = tk.StringVar(value="15000")
        self.command_desc_var = tk.StringVar(value="PCS 模块直流起机")
        self.raw_id_var = tk.StringVar(value="0x02A400F0")
        self.raw_data_var = tk.StringVar(value="11 27 00 00 00 00 00 A0")
        self.raw_protocol_var = tk.StringVar(value="beg1k0110")

        self._build_ui()
        self._refresh_beg_preview()
        self._load_command_preset(BEG_CONTROL_PRESETS[0].name)
        self._refresh_poll_config()
        self.root.after(100, self._process_events)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(2, weight=1)

        self._build_connection_panel().grid(
            row=0, column=0, sticky="ew", padx=10, pady=(10, 0)
        )
        self._build_command_panel().grid(
            row=1, column=0, sticky="ew", padx=10, pady=(10, 0)
        )

        body = ttk.PanedWindow(self.root, orient="horizontal")
        body.grid(row=2, column=0, sticky="nsew", padx=10, pady=10)

        left = ttk.Frame(body)
        right = ttk.Frame(body)
        body.add(left, weight=3)
        body.add(right, weight=2)

        left.columnconfigure(0, weight=1)
        left.rowconfigure(0, weight=1)
        self._build_notebook(left).grid(row=0, column=0, sticky="nsew")

        right.columnconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)
        self._build_notes_panel(right).grid(row=0, column=0, sticky="ew")
        self._build_log_panel(right).grid(row=1, column=0, sticky="nsew", pady=(10, 0))

    def _build_connection_panel(self) -> ttk.LabelFrame:
        frame = ttk.LabelFrame(self.root, text="总线连接")
        ttk.Label(frame, text="接口").grid(row=0, column=0, sticky="w", padx=8, pady=6)
        ttk.Combobox(
            frame,
            textvariable=self.channel_var,
            values=CHANNELS,
            state="readonly",
            width=14,
        ).grid(row=0, column=1, sticky="ew", padx=8, pady=6)
        ttk.Label(frame, text="比特率").grid(
            row=0, column=2, sticky="w", padx=8, pady=6
        )
        ttk.Combobox(
            frame,
            textvariable=self.bitrate_var,
            values=[str(item) for item in BITRATES],
            state="readonly",
            width=12,
        ).grid(row=0, column=3, sticky="ew", padx=8, pady=6)
        ttk.Button(frame, text="连接", command=self._connect).grid(
            row=0, column=4, sticky="ew", padx=8, pady=6
        )
        ttk.Button(frame, text="断开", command=self.worker.disconnect).grid(
            row=0, column=5, sticky="ew", padx=8, pady=6
        )
        ttk.Label(frame, text="状态").grid(row=0, column=6, sticky="w", padx=8, pady=6)
        ttk.Label(frame, textvariable=self.connect_state_var).grid(
            row=0, column=7, sticky="w", padx=8, pady=6
        )
        for column in (1, 3, 7):
            frame.columnconfigure(column, weight=1)
        return frame

    def _build_command_panel(self) -> ttk.LabelFrame:
        frame = ttk.LabelFrame(self.root, text="命令发送")
        for column in range(8):
            frame.columnconfigure(column, weight=1)

        ttk.Label(frame, text="协议").grid(row=0, column=0, sticky="w", padx=8, pady=6)
        protocol_box = ttk.Combobox(
            frame,
            textvariable=self.command_protocol_var,
            values=["beg1k0110", "charger"],
            state="readonly",
            width=14,
        )
        protocol_box.grid(row=0, column=1, sticky="ew", padx=8, pady=6)
        protocol_box.bind(
            "<<ComboboxSelected>>", lambda _event: self._update_command_protocol()
        )

        ttk.Label(frame, text="预设").grid(row=0, column=2, sticky="w", padx=8, pady=6)
        self.command_preset_box = ttk.Combobox(
            frame, textvariable=self.command_preset_var, state="readonly"
        )
        self.command_preset_box.grid(
            row=0, column=3, columnspan=3, sticky="ew", padx=8, pady=6
        )
        self.command_preset_box.bind(
            "<<ComboboxSelected>>",
            lambda _event: self._load_command_preset(self.command_preset_var.get()),
        )
        ttk.Button(
            frame,
            text="载入预设",
            command=lambda: self._load_command_preset(self.command_preset_var.get()),
        ).grid(row=0, column=6, sticky="ew", padx=8, pady=6)
        ttk.Button(frame, text="按预设发送", command=self._send_loaded_preset).grid(
            row=0, column=7, sticky="ew", padx=8, pady=6
        )

        self.beg_construct_frame = ttk.Frame(frame)
        self.beg_construct_frame.grid(row=1, column=0, columnspan=8, sticky="ew")
        for column in range(6):
            self.beg_construct_frame.columnconfigure(column, weight=1)
        ttk.Label(self.beg_construct_frame, text="Byte0").grid(
            row=0, column=0, sticky="w", padx=8, pady=6
        )
        ttk.Entry(self.beg_construct_frame, textvariable=self.beg_byte0_var).grid(
            row=0, column=1, sticky="ew", padx=8, pady=6
        )
        ttk.Label(self.beg_construct_frame, text="Byte1").grid(
            row=0, column=2, sticky="w", padx=8, pady=6
        )
        ttk.Entry(self.beg_construct_frame, textvariable=self.beg_byte1_var).grid(
            row=0, column=3, sticky="ew", padx=8, pady=6
        )
        ttk.Label(self.beg_construct_frame, text="Value").grid(
            row=0, column=4, sticky="w", padx=8, pady=6
        )
        ttk.Entry(self.beg_construct_frame, textvariable=self.beg_value_var).grid(
            row=0, column=5, sticky="ew", padx=8, pady=6
        )

        self.beg_byte0_var.trace_add("write", lambda *_: self._update_beg_raw_preview())
        self.beg_byte1_var.trace_add("write", lambda *_: self._update_beg_raw_preview())
        self.beg_value_var.trace_add("write", lambda *_: self._update_beg_raw_preview())

        self.charger_construct_frame = ttk.Frame(frame)
        self.charger_construct_frame.grid(row=1, column=0, columnspan=8, sticky="ew")
        for column in range(6):
            self.charger_construct_frame.columnconfigure(column, weight=1)
        ttk.Label(self.charger_construct_frame, text="电压(mV)").grid(
            row=0, column=0, sticky="w", padx=8, pady=6
        )
        ttk.Entry(
            self.charger_construct_frame, textvariable=self.charger_voltage_var
        ).grid(row=0, column=1, sticky="ew", padx=8, pady=6)
        ttk.Label(self.charger_construct_frame, text="电流(mA)").grid(
            row=0, column=2, sticky="w", padx=8, pady=6
        )
        ttk.Entry(
            self.charger_construct_frame, textvariable=self.charger_current_var
        ).grid(row=0, column=3, sticky="ew", padx=8, pady=6)
        ttk.Label(self.charger_construct_frame, text="范围: 0~999999").grid(
            row=0, column=4, sticky="w", padx=8, pady=6
        )

        self.charger_voltage_var.trace_add(
            "write", lambda *_: self._update_charger_raw_preview()
        )
        self.charger_current_var.trace_add(
            "write", lambda *_: self._update_charger_raw_preview()
        )

        ttk.Label(frame, text="说明").grid(row=2, column=0, sticky="w", padx=8, pady=6)
        ttk.Entry(frame, textvariable=self.command_desc_var).grid(
            row=2, column=1, columnspan=7, sticky="ew", padx=8, pady=6
        )

        ttk.Separator(frame, orient="horizontal").grid(
            row=3, column=0, columnspan=8, sticky="ew", padx=8, pady=8
        )

        ttk.Label(frame, text="原始协议").grid(
            row=4, column=0, sticky="w", padx=8, pady=6
        )
        ttk.Combobox(
            frame,
            textvariable=self.raw_protocol_var,
            values=["beg1k0110", "charger"],
            state="readonly",
            width=14,
        ).grid(row=4, column=1, sticky="ew", padx=8, pady=6)
        ttk.Label(frame, text="原始 CAN ID").grid(
            row=4, column=2, sticky="w", padx=8, pady=6
        )
        ttk.Entry(frame, textvariable=self.raw_id_var).grid(
            row=4, column=3, columnspan=2, sticky="ew", padx=8, pady=6
        )
        ttk.Label(frame, text="原始 Data").grid(
            row=4, column=5, sticky="w", padx=8, pady=6
        )
        ttk.Entry(frame, textvariable=self.raw_data_var).grid(
            row=4, column=6, sticky="ew", padx=8, pady=6
        )
        ttk.Button(frame, text="发送原始帧", command=self._send_raw).grid(
            row=4, column=7, sticky="ew", padx=8, pady=6
        )

        self._update_command_protocol()
        return frame

    def _build_notebook(self, parent: ttk.Frame) -> ttk.Notebook:
        self.notebook = ttk.Notebook(parent)
        beg_tab = ttk.Frame(self.notebook)
        charger_tab = ttk.Frame(self.notebook)
        self.notebook.add(beg_tab, text="BEG1K0110")
        self.notebook.add(charger_tab, text="charger")
        self._build_beg_tab(beg_tab)
        self._build_charger_tab(charger_tab)
        self.notebook.bind(
            "<<NotebookTabChanged>>", lambda _event: self._select_current_protocol()
        )
        return self.notebook

    def _build_beg_tab(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(2, weight=1)

        target = ttk.LabelFrame(parent, text="BEG1K0110 目标")
        target.grid(row=0, column=0, sticky="ew", padx=8, pady=8)
        target.columnconfigure(1, weight=1)
        ttk.Label(target, text="地址类型").grid(
            row=0, column=0, sticky="w", padx=8, pady=6
        )
        scope_box = ttk.Combobox(
            target, textvariable=self.beg.scope_var, values=BEG_SCOPES, state="readonly"
        )
        scope_box.grid(row=0, column=1, sticky="ew", padx=8, pady=6)
        scope_box.bind(
            "<<ComboboxSelected>>", lambda _event: self._on_context_changed()
        )
        ttk.Label(target, text="地址值").grid(
            row=1, column=0, sticky="w", padx=8, pady=6
        )
        addr_entry = ttk.Entry(target, textvariable=self.beg.addr_var)
        addr_entry.grid(row=1, column=1, sticky="ew", padx=8, pady=6)
        addr_entry.bind("<KeyRelease>", lambda _event: self._on_context_changed())
        ttk.Label(target, text="最终 ID").grid(
            row=2, column=0, sticky="w", padx=8, pady=6
        )
        ttk.Label(target, textvariable=self.beg.address_preview_var).grid(
            row=2, column=1, sticky="w", padx=8, pady=6
        )

        templates = ttk.LabelFrame(parent, text="BEG1K0110 ID 模板")
        templates.grid(row=1, column=0, sticky="ew", padx=8)
        templates.columnconfigure(1, weight=1)
        for row, key in enumerate(("broadcast", "group", "module")):
            ttk.Label(templates, text=key).grid(
                row=row, column=0, sticky="w", padx=8, pady=6
            )
            entry = ttk.Entry(templates, textvariable=self.beg.templates[key])
            entry.grid(row=row, column=1, sticky="ew", padx=8, pady=6)
            entry.bind("<FocusOut>", lambda _event: self._on_context_changed())

        lower = ttk.PanedWindow(parent, orient="horizontal")
        lower.grid(row=2, column=0, sticky="nsew", padx=8, pady=8)
        left = ttk.Frame(lower)
        right = ttk.Frame(lower)
        lower.add(left, weight=1)
        lower.add(right, weight=3)

        left.columnconfigure(0, weight=1)
        self._build_poll_box(left, self.beg, self._on_context_changed).grid(
            row=0, column=0, sticky="ew"
        )
        quick = ttk.LabelFrame(left, text="常用读取")
        quick.grid(row=1, column=0, sticky="nsew", pady=(10, 0))
        quick.columnconfigure(0, weight=1)
        for index, preset in enumerate(BEG_READ_PRESETS):
            ttk.Button(
                quick,
                text=preset.name,
                command=lambda item=preset: self._send_beg_read(item),
            ).grid(row=index, column=0, sticky="ew", padx=8, pady=4)

        right.columnconfigure(0, weight=1)
        right.rowconfigure(0, weight=1)
        self.beg.status_tree = self._build_status_tree(right, BEG_READ_PRESETS)
        self.beg.status_tree.grid(row=0, column=0, sticky="nsew")
        for preset in BEG_READ_PRESETS:
            self.beg.status_rows[preset.name] = preset.name

    def _build_charger_tab(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(1, weight=1)

        target = ttk.LabelFrame(parent, text="charger 目标")
        target.grid(row=0, column=0, sticky="ew", padx=8, pady=8)
        target.columnconfigure(1, weight=1)
        ttk.Label(target, text="模块地址").grid(
            row=0, column=0, sticky="w", padx=8, pady=6
        )
        addr_entry = ttk.Entry(target, textvariable=self.charger.addr_var)
        addr_entry.grid(row=0, column=1, sticky="ew", padx=8, pady=6)
        addr_entry.bind("<KeyRelease>", lambda _event: self._on_context_changed())
        ttk.Label(target, text="可用范围").grid(
            row=1, column=0, sticky="w", padx=8, pady=6
        )
        ttk.Label(
            target, text="整流模块 0x00~0x3B，MPPT 模块 0x80~0xDF，广播 0x3F"
        ).grid(row=1, column=1, sticky="w", padx=8, pady=6)

        lower = ttk.PanedWindow(parent, orient="horizontal")
        lower.grid(row=1, column=0, sticky="nsew", padx=8, pady=8)
        left = ttk.Frame(lower)
        right = ttk.Frame(lower)
        lower.add(left, weight=1)
        lower.add(right, weight=3)

        left.columnconfigure(0, weight=1)
        self._build_poll_box(left, self.charger, self._on_context_changed).grid(
            row=0, column=0, sticky="ew"
        )
        quick = ttk.LabelFrame(left, text="常用读取")
        quick.grid(row=1, column=0, sticky="nsew", pady=(10, 0))
        quick.columnconfigure(0, weight=1)
        for index, preset in enumerate(CHARGER_READ_PRESETS):
            ttk.Button(
                quick,
                text=preset.name,
                command=lambda item=preset: self._send_charger_request(item),
            ).grid(row=index, column=0, sticky="ew", padx=8, pady=4)

        right.columnconfigure(0, weight=1)
        right.rowconfigure(0, weight=1)
        self.charger.status_tree = self._build_status_tree(right, CHARGER_READ_PRESETS)
        self.charger.status_tree.grid(row=0, column=0, sticky="nsew")
        for preset in CHARGER_READ_PRESETS:
            self.charger.status_rows[preset.name] = preset.name

    def _build_poll_box(self, parent: ttk.Frame, context, callback) -> ttk.LabelFrame:
        frame = ttk.LabelFrame(parent, text="轮询")
        ttk.Checkbutton(
            frame, text="启用轮询", variable=context.poll_enabled_var, command=callback
        ).grid(row=0, column=0, columnspan=2, sticky="w", padx=8, pady=6)
        ttk.Label(frame, text="快轮询(s)").grid(
            row=1, column=0, sticky="w", padx=8, pady=6
        )
        fast_entry = ttk.Entry(frame, textvariable=context.fast_var)
        fast_entry.grid(row=1, column=1, sticky="ew", padx=8, pady=6)
        fast_entry.bind("<FocusOut>", lambda _event: callback())
        ttk.Label(frame, text="慢轮询(s)").grid(
            row=2, column=0, sticky="w", padx=8, pady=6
        )
        slow_entry = ttk.Entry(frame, textvariable=context.slow_var)
        slow_entry.grid(row=2, column=1, sticky="ew", padx=8, pady=6)
        slow_entry.bind("<FocusOut>", lambda _event: callback())
        frame.columnconfigure(1, weight=1)
        return frame

    def _build_status_tree(
        self, parent: ttk.Frame, presets: tuple[CommandPreset, ...]
    ) -> ttk.Treeview:
        columns = ("name", "raw", "value", "time")
        tree = ttk.Treeview(parent, columns=columns, show="headings")
        titles = {
            "name": "项目",
            "raw": "原始数据",
            "value": "解析值",
            "time": "更新时间",
        }
        widths = {"name": 180, "raw": 220, "value": 260, "time": 100}
        for column in columns:
            tree.heading(column, text=titles[column])
            tree.column(column, width=widths[column], anchor="w")
        for preset in presets:
            tree.insert("", "end", iid=preset.name, values=(preset.name, "-", "-", "-"))
        return tree

    def _build_notes_panel(self, parent: ttk.Frame) -> ttk.LabelFrame:
        frame = ttk.LabelFrame(parent, text="运行说明")
        text = (
            "1. 本工具在一条 PCAN 总线上同时调试 BEG1K0110 与 charger。\n"
            "2. 连接层只建立一个 PCAN 通道，避免同一通道被重复初始化。\n"
            "3. charger 文档当前只有 3 页，已内置可确认的查询与控制演示命令。\n"
            "4. Windows Python 3.14 运行时需要本机先装 PEAK 驱动和 PCAN-Basic。\n"
            "5. 如果现场 ID 编码与 BEG1K0110 默认模板不同，可在对应标签页修改模板。"
        )
        ttk.Label(frame, text=text, justify="left", wraplength=460).pack(
            fill="both", expand=True, padx=8, pady=8
        )
        return frame

    def _build_log_panel(self, parent: ttk.Frame) -> ttk.LabelFrame:
        frame = ttk.LabelFrame(parent, text="总线日志")
        self.log_text = ScrolledText(frame, wrap="word")
        self.log_text.pack(fill="both", expand=True, padx=8, pady=8)
        return frame

    def _connect(self) -> None:
        try:
            bitrate = parse_int(self.bitrate_var.get())
        except ValueError as exc:
            messagebox.showerror("参数错误", str(exc))
            return
        self.worker.connect(self.channel_var.get(), bitrate)

    def _select_current_protocol(self) -> None:
        current_index = self.notebook.index(self.notebook.select())
        self.command_protocol_var.set("beg1k0110" if current_index == 0 else "charger")
        self._update_command_protocol()

    def _update_command_protocol(self) -> None:
        protocol_name = self.command_protocol_var.get()
        presets = (
            BEG_CONTROL_PRESETS
            if protocol_name == "beg1k0110"
            else CHARGER_CONTROL_PRESETS
        )
        self.command_preset_box.configure(values=[preset.name for preset in presets])
        self.command_preset_var.set(presets[0].name)
        if protocol_name == "beg1k0110":
            self.beg_construct_frame.grid()
            self.charger_construct_frame.grid_remove()
        else:
            self.beg_construct_frame.grid_remove()
            self.charger_construct_frame.grid()
        self._load_command_preset(self.command_preset_var.get())

    def _load_command_preset(self, name: str) -> None:
        protocol_name = self.command_protocol_var.get()
        presets = (
            BEG_CONTROL_PRESETS
            if protocol_name == "beg1k0110"
            else CHARGER_CONTROL_PRESETS
        )
        preset = next(item for item in presets if item.name == name)
        self.command_desc_var.set(preset.description)
        if protocol_name == "beg1k0110":
            self.beg_byte0_var.set(hex(preset.byte0))
            self.beg_byte1_var.set(hex(preset.byte1))
            self.beg_value_var.set(
                hex(preset.default_value)
                if preset.default_value <= 0xFFFF
                else str(preset.default_value)
            )
            try:
                arbitration_id = self._resolve_beg_id(preset.scope_hint)
                payload = build_beg_payload(
                    preset.byte0, preset.byte1, preset.default_value
                )
                self.raw_protocol_var.set("beg1k0110")
                self.raw_id_var.set(format_can_id(arbitration_id))
                self.raw_data_var.set(format_payload(payload))
            except Exception:
                pass
        else:
            try:
                if preset.kind == "voltage_current":
                    self.charger_voltage_var.set(str(preset.default_value))
                    self.charger_current_var.set(str(preset.byte0))
                arbitration_id, payload = self._build_charger_frame(preset)
                self.raw_protocol_var.set("charger")
                self.raw_id_var.set(format_can_id(arbitration_id))
                self.raw_data_var.set(format_payload(payload))
            except Exception:
                pass

    def _send_loaded_preset(self) -> None:
        if self.command_protocol_var.get() == "beg1k0110":
            self._send_beg_constructed()
            return
        presets = CHARGER_CONTROL_PRESETS
        preset = next(
            (p for p in presets if p.name == self.command_preset_var.get()), None
        )
        if preset is None:
            messagebox.showerror("错误", f"未找到预设: {self.command_preset_var.get()}")
            return
        try:
            arbitration_id, payload = self._build_charger_frame(preset)
        except Exception as exc:
            messagebox.showerror("参数错误", str(exc))
            return
        description = self.command_desc_var.get().strip() or "charger 预设"
        self.worker.send(arbitration_id, payload, "charger", description)

    def _resolve_beg_id(self, scope_override: str | None = None) -> int:
        scope = scope_override or self.beg.scope_var.get()
        addr = parse_int(self.beg.addr_var.get())
        templates = {key: var.get().strip() for key, var in self.beg.templates.items()}
        return resolve_beg_arbitration_id(scope, addr, templates)

    def _refresh_beg_preview(self) -> None:
        try:
            self.beg.address_preview_var.set(format_can_id(self._resolve_beg_id()))
        except Exception as exc:
            self.beg.address_preview_var.set(f"错误: {exc}")

    def _update_beg_raw_preview(self) -> None:
        if self.command_protocol_var.get() != "beg1k0110":
            return
        try:
            byte0 = parse_int(self.beg_byte0_var.get())
            byte1 = parse_int(self.beg_byte1_var.get())
            value = parse_int(self.beg_value_var.get())
            payload = build_beg_payload(byte0, byte1, value)
            self.raw_data_var.set(format_payload(payload))
        except Exception:
            pass

    def _update_charger_raw_preview(self) -> None:
        if self.command_protocol_var.get() != "charger":
            return
        try:
            voltage = parse_int(self.charger_voltage_var.get())
            current = parse_int(self.charger_current_var.get())
            payload = build_charger_voltage_current_payload(voltage, current)
            self.raw_data_var.set(format_payload(payload))
        except Exception:
            pass

    def _build_charger_frame(self, preset: CommandPreset) -> tuple[int, bytes]:
        addr = parse_int(self.charger.addr_var.get())
        target_addr = 0x3F if preset.scope_hint == "broadcast" else addr
        if preset.kind == "voltage_current":
            voltage = parse_int(self.charger_voltage_var.get())
            current = parse_int(self.charger_current_var.get())
            payload = build_charger_voltage_current_payload(voltage, current)
        else:
            payload = preset.request_data
        return charger_request_id(preset, target_addr), payload

    def _send_beg_constructed(self) -> None:
        try:
            arbitration_id = self._resolve_beg_id()
            byte0 = parse_int(self.beg_byte0_var.get())
            byte1 = parse_int(self.beg_byte1_var.get())
            value = parse_int(self.beg_value_var.get())
            if not 0 <= value <= 0xFFFFFFFF:
                raise ValueError("Value 必须在 0 到 0xFFFFFFFF 之间")
            payload = build_beg_payload(byte0, byte1, value)
        except Exception as exc:
            messagebox.showerror("参数错误", str(exc))
            return
        description = self.command_desc_var.get().strip() or "BEG1K0110 构造帧"
        self.worker.send(arbitration_id, payload, "beg1k0110", description)

    def _send_raw(
        self,
        protocol_name_override: str | None = None,
        description_override: str | None = None,
    ) -> None:
        try:
            arbitration_id = parse_int(self.raw_id_var.get())
            payload = parse_payload_hex(self.raw_data_var.get())
        except Exception as exc:
            messagebox.showerror("原始帧错误", str(exc))
            return
        protocol_name = protocol_name_override or self.raw_protocol_var.get()
        description = description_override or "原始帧"
        self.worker.send(arbitration_id, payload, protocol_name, description)

    def _send_beg_read(self, preset: CommandPreset) -> None:
        try:
            scope = (
                "broadcast"
                if preset.scope_hint == "broadcast"
                else self.beg.scope_var.get()
            )
            arbitration_id = self._resolve_beg_id(scope)
        except Exception as exc:
            messagebox.showerror("地址错误", str(exc))
            return
        payload = build_beg_payload(preset.byte0, preset.byte1, 0)
        self.worker.send(arbitration_id, payload, "beg1k0110", f"读取 {preset.name}")

    def _send_charger_request(self, preset: CommandPreset) -> None:
        try:
            arbitration_id, payload = self._build_charger_frame(preset)
        except Exception as exc:
            messagebox.showerror("charger 参数错误", str(exc))
            return
        self.worker.send(arbitration_id, payload, "charger", f"读取 {preset.name}")

    def _on_context_changed(self) -> None:
        self._refresh_beg_preview()
        self._refresh_poll_config()
        self._load_command_preset(self.command_preset_var.get())

    def _refresh_poll_config(self) -> None:
        poll_items: list[PollItem] = []
        try:
            if self.beg.poll_enabled_var.get():
                fast = float(self.beg.fast_var.get())
                slow = float(self.beg.slow_var.get())
                for preset in BEG_READ_PRESETS:
                    scope = (
                        "broadcast"
                        if preset.scope_hint == "broadcast"
                        else self.beg.scope_var.get()
                    )
                    arbitration_id = self._resolve_beg_id(scope)
                    interval = (
                        fast
                        if preset.name
                        in {
                            "系统直流电压",
                            "系统直流总电流",
                            "模块直流电压",
                            "模块直流电流",
                            "模块状态",
                            "逆变状态",
                        }
                        else slow
                    )
                    poll_items.append(
                        PollItem(
                            protocol_name="beg1k0110",
                            metric_name=preset.name,
                            arbitration_id=arbitration_id,
                            data=build_beg_payload(preset.byte0, preset.byte1, 0),
                            interval=interval,
                        )
                    )
            if self.charger.poll_enabled_var.get():
                fast = float(self.charger.fast_var.get())
                slow = float(self.charger.slow_var.get())
                for preset in CHARGER_READ_PRESETS:
                    interval = fast if preset.name == "模块状态" else slow
                    request_id, payload = self._build_charger_frame(preset)
                    poll_items.append(
                        PollItem(
                            protocol_name="charger",
                            metric_name=preset.name,
                            arbitration_id=request_id,
                            data=payload,
                            interval=interval,
                        )
                    )
        except Exception as exc:
            self._log("ERROR", f"轮询配置错误: {exc}")
            return
        self.worker.set_poll_items(poll_items)
        self._log(
            "INFO",
            f"已更新轮询配置，BEG={len(BEG_READ_PRESETS) if self.beg.poll_enabled_var.get() else 0} 项，charger={len(CHARGER_READ_PRESETS) if self.charger.poll_enabled_var.get() else 0} 项",
        )

    def _process_events(self) -> None:
        while True:
            try:
                kind, payload = self.events.get_nowait()
            except queue.Empty:
                break

            if kind == "connection":
                if payload["connected"]:
                    self.connect_state_var.set(
                        f"已连接 {payload['channel']} @ {payload['bitrate']}"
                    )
                    self._log(
                        "INFO", f"连接成功: {payload['channel']} @ {payload['bitrate']}"
                    )
                    self._refresh_poll_config()
                else:
                    self.connect_state_var.set("未连接")
                    self._log("INFO", "已断开连接")
            elif kind == "tx":
                self._log(
                    "TX",
                    f"[{payload['protocol_name']}] {format_can_id(payload['arbitration_id'])}  {format_payload(payload['data'])}  {payload['description']}",
                )
            elif kind == "rx":
                self._log(
                    "RX",
                    f"{format_can_id(payload['arbitration_id'])}  {format_payload(payload['data'])}",
                )
                self._route_frame(payload["arbitration_id"], payload["data"])
            elif kind == "error":
                self._log("ERROR", str(payload["message"]))

        self.root.after(100, self._process_events)

    def _route_frame(self, arbitration_id: int, payload: bytes) -> None:
        if self._update_charger_status(arbitration_id, payload):
            return
        if is_charger_frame(arbitration_id):
            return
        self._update_beg_status(payload)

    def _update_beg_status(self, payload: bytes) -> None:
        decoded = decode_beg_payload(payload)
        if decoded is None or self.beg.status_tree is None:
            return
        name, value = decoded
        self.beg.status_tree.item(
            name, values=(name, format_payload(payload), value, now_text())
        )

    def _update_charger_status(self, arbitration_id: int, payload: bytes) -> bool:
        if self.charger.status_tree is None:
            return False
        addr = parse_int(self.charger.addr_var.get()) & 0xFF
        matched = False
        for preset in CHARGER_READ_PRESETS:
            response_id = charger_response_id(preset, addr)
            if response_id is None or arbitration_id != response_id:
                continue
            value = decode_charger_payload(preset.name, payload)
            self.charger.status_tree.item(
                preset.name,
                values=(preset.name, format_payload(payload), value, now_text()),
            )
            matched = True
        return matched

    def _log(self, level: str, message: str) -> None:
        self.log_text.insert("end", f"[{now_text()}] [{level}] {message}\n")
        self.log_text.see("end")

    def _on_close(self) -> None:
        self.worker.stop()
        self.root.destroy()


def main() -> None:
    root = tk.Tk()
    app = MultiDeviceDebuggerApp(root)
    del app
    root.mainloop()


if __name__ == "__main__":
    main()
