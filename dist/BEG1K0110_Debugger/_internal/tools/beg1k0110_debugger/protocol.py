from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable


@dataclass(frozen=True)
class CommandPreset:
    name: str
    description: str
    kind: str
    scope_hint: str = "module"
    value_unit: str = ""
    signed: bool = False
    default_value: int = 0
    byte0: int = 0
    byte1: int = 0
    request_id_template: str = ""
    response_id_template: str = ""
    request_data: bytes = b""

    @property
    def key(self) -> tuple[int, int]:
        return (self.byte0, self.byte1)


@dataclass(frozen=True)
class ProtocolDefinition:
    name: str
    display_name: str
    templates: dict[str, str]
    read_presets: tuple[CommandPreset, ...]
    control_presets: tuple[CommandPreset, ...]


BEG_DEFAULT_TEMPLATES = {
    "broadcast": "0x02A43FF0",
    "group": "0x02E4{addr:02X}F0",
    "module": "0x02A4{addr:02X}F0",
}


BEG_READ_PRESETS: tuple[CommandPreset, ...] = (
    CommandPreset(
        "系统直流电压",
        "读取系统直流侧电压",
        "beg",
        scope_hint="broadcast",
        value_unit="mV",
        byte0=0x10,
        byte1=0x01,
    ),
    CommandPreset(
        "系统直流总电流",
        "读取系统直流侧总电流",
        "beg",
        scope_hint="broadcast",
        value_unit="mA",
        byte0=0x10,
        byte1=0x02,
    ),
    CommandPreset(
        "模块直流电压",
        "读取模块直流侧电压",
        "beg",
        value_unit="mV",
        byte0=0x11,
        byte1=0x01,
    ),
    CommandPreset(
        "模块直流电流",
        "读取模块直流侧电流",
        "beg",
        value_unit="mA",
        byte0=0x11,
        byte1=0x02,
    ),
    CommandPreset("模块状态", "读取模块状态字", "beg", byte0=0x11, byte1=0x10),
    CommandPreset("逆变状态", "读取逆变状态字", "beg", byte0=0x11, byte1=0x11),
    CommandPreset(
        "总有功功率",
        "读取总有功功率",
        "beg",
        value_unit="mW",
        signed=True,
        byte0=0x21,
        byte1=0x08,
    ),
    CommandPreset(
        "总无功功率",
        "读取总无功功率",
        "beg",
        value_unit="mVA",
        signed=True,
        byte0=0x21,
        byte1=0x0C,
    ),
    CommandPreset(
        "系统高压侧电压",
        "读取系统直流高压侧电压",
        "beg",
        scope_hint="broadcast",
        value_unit="mV",
        byte0=0x40,
        byte1=0x01,
    ),
    CommandPreset(
        "DCDC高压侧电压",
        "读取 DCDC 模块直流高压侧电压",
        "beg",
        value_unit="mV",
        byte0=0x41,
        byte1=0x01,
    ),
    CommandPreset(
        "DCDC高压侧电流",
        "读取 DCDC 模块直流高压侧电流",
        "beg",
        value_unit="mA",
        signed=True,
        byte0=0x41,
        byte1=0x02,
    ),
)


BEG_CONTROL_PRESETS: tuple[CommandPreset, ...] = (
    CommandPreset(
        "工作模式-整流",
        "设置工作模式为整流模式(0xA0)",
        "beg",
        default_value=0xA0,
        byte0=0x21,
        byte1=0x10,
    ),
    CommandPreset(
        "工作模式-并网",
        "设置工作模式为并网模式(0xA1)",
        "beg",
        default_value=0xA1,
        byte0=0x21,
        byte1=0x10,
    ),
    CommandPreset(
        "工作模式-离网",
        "设置工作模式为离网模式(0xA2)",
        "beg",
        default_value=0xA2,
        byte0=0x21,
        byte1=0x10,
    ),
    CommandPreset(
        "储能模式-使能",
        "使能储能模式",
        "beg",
        default_value=0xA1,
        byte0=0x21,
        byte1=0x18,
    ),
    CommandPreset(
        "储能模式-不使能",
        "关闭储能模式",
        "beg",
        default_value=0xA0,
        byte0=0x21,
        byte1=0x18,
    ),
    CommandPreset(
        "设置模块电压",
        "设置模块电压(mV)",
        "beg",
        value_unit="mV",
        default_value=800000,
        byte0=0x11,
        byte1=0x01,
    ),
    CommandPreset(
        "设置模块电流",
        "设置模块电流(mA)",
        "beg",
        value_unit="mA",
        default_value=10000,
        byte0=0x11,
        byte1=0x02,
    ),
    CommandPreset(
        "直流起机",
        "设置 PCS 模块直流起机",
        "beg",
        default_value=0xA0,
        byte0=0x11,
        byte1=0x27,
    ),
    CommandPreset(
        "交流调度",
        "设置 PCS 模块交流调度",
        "beg",
        default_value=0xA1,
        byte0=0x31,
        byte1=0x11,
    ),
    CommandPreset(
        "直流调度",
        "设置 PCS 模块直流调度",
        "beg",
        default_value=0xA0,
        byte0=0x31,
        byte1=0x11,
    ),
    CommandPreset(
        "开关机-开机",
        "下发开机命令",
        "beg",
        default_value=0xA0,
        byte0=0x11,
        byte1=0x10,
    ),
    CommandPreset(
        "开关机-关机",
        "下发关机命令",
        "beg",
        default_value=0xA1,
        byte0=0x11,
        byte1=0x10,
    ),
    CommandPreset(
        "CAN静默-正常",
        "设置CAN静默为正常模式",
        "beg",
        default_value=0xA0,
        byte0=0x11,
        byte1=0x1E,
    ),
    CommandPreset(
        "降噪模式-功率",
        "设置降噪模式为功率模式",
        "beg",
        default_value=0xA0,
        byte0=0x11,
        byte1=0x33,
    ),
    CommandPreset(
        "降噪模式-降噪",
        "设置降噪模式为降噪",
        "beg",
        default_value=0xA1,
        byte0=0x11,
        byte1=0x33,
    ),
    CommandPreset(
        "高低压模式-低压",
        "设置高低压模式为低压并联",
        "beg",
        default_value=0xA0,
        byte0=0x11,
        byte1=0x26,
    ),
    CommandPreset(
        "高低压模式-高压",
        "设置高低压模式为高压串联",
        "beg",
        default_value=0xA1,
        byte0=0x11,
        byte1=0x26,
    ),
    CommandPreset(
        "设置直流电压",
        "设置直流电压",
        "beg",
        scope_hint="broadcast",
        value_unit="mV",
        default_value=1_000_000,
        byte0=0x10,
        byte1=0x01,
    ),
    CommandPreset(
        "设置有功功率",
        "设置 AC 有功功率",
        "beg",
        value_unit="mW",
        signed=True,
        default_value=50_000_000,
        byte0=0x31,
        byte1=0x23,
    ),
    CommandPreset(
        "设置充电结束电压",
        "设置电池充电结束电压",
        "beg",
        value_unit="mV",
        default_value=1_000_000,
        byte0=0x51,
        byte1=0x01,
    ),
    CommandPreset(
        "设置充电过流点",
        "设置电池充电过流点",
        "beg",
        scope_hint="broadcast",
        value_unit="mA",
        default_value=115_000,
        byte0=0x51,
        byte1=0x02,
    ),
    CommandPreset(
        "设置放电结束电压",
        "设置电池放电结束电压",
        "beg",
        value_unit="mV",
        default_value=560_000,
        byte0=0x51,
        byte1=0x03,
    ),
    CommandPreset(
        "设置放电过流点",
        "设置电池放电过流点",
        "beg",
        scope_hint="broadcast",
        value_unit="mA",
        default_value=115_000,
        byte0=0x51,
        byte1=0x04,
    ),
    CommandPreset(
        "设置DOD电压",
        "设置电池 DOD 电压",
        "beg",
        value_unit="mV",
        default_value=600_000,
        byte0=0x51,
        byte1=0x05,
    ),
)


CHARGER_READ_PRESETS: tuple[CommandPreset, ...] = (
    CommandPreset(
        "模块电压电流",
        "查询 charger 模块电压电流",
        "raw",
        request_id_template="0x0289{addr:02X}F0",
        response_id_template="0x0289F0{addr:02X}",
        request_data=b"\x00\x00\x00\x00\x00\x00\x00\x00",
    ),
    CommandPreset(
        "模块状态",
        "查询 charger 模块状态",
        "raw",
        request_id_template="0x0284{addr:02X}F0",
        response_id_template="0x0284F0{addr:02X}",
        request_data=b"\x00\x00\x00\x00\x00\x00\x00\x00",
    ),
)


CHARGER_CONTROL_PRESETS: tuple[CommandPreset, ...] = (
    CommandPreset(
        "所有模块开机",
        "广播 charger 所有模块开机",
        "raw",
        scope_hint="broadcast",
        request_id_template="0x029A3FF0",
        request_data=b"\x00\x00\x00\x00\x00\x00\x00\x00",
    ),
    CommandPreset(
        "所有模块关机",
        "广播 charger 所有模块关机",
        "raw",
        scope_hint="broadcast",
        request_id_template="0x029A3FF0",
        request_data=b"\x01\x00\x00\x00\x00\x00\x00\x00",
    ),
    CommandPreset(
        "广播设置750V15A",
        "广播设置 charger 为 750V 15A",
        "raw",
        scope_hint="broadcast",
        request_id_template="0x029C3FF0",
        request_data=b"\x00\x0b\x71\xb0\x00\x00\x3a\x98",
    ),
    CommandPreset(
        "广播设置电压电流",
        "广播设置 charger 电压电流(自定义)",
        "voltage_current",
        scope_hint="broadcast",
        request_id_template="0x029C3FF0",
        default_value=750000,
        byte0=15000,
    ),
    CommandPreset(
        "设置模块电压电流",
        "设置指定 charger 模块电压电流(自定义)",
        "voltage_current",
        scope_hint="module",
        request_id_template="0x029C{addr:02X}F0",
        default_value=750000,
        byte0=15000,
    ),
    CommandPreset(
        "模块休眠",
        "设置指定 charger 模块休眠",
        "raw",
        request_id_template="0x0299{addr:02X}F0",
        request_data=b"\x01\x00\x00\x00\x00\x00\x00\x00",
    ),
    CommandPreset(
        "模块查询电压电流",
        "向指定 charger 模块发送电压电流查询",
        "raw",
        request_id_template="0x0289{addr:02X}F0",
        response_id_template="0x0289F0{addr:02X}",
        request_data=b"\x00\x00\x00\x00\x00\x00\x00\x00",
    ),
    CommandPreset(
        "模块查询状态",
        "向指定 charger 模块发送状态查询",
        "raw",
        request_id_template="0x0284{addr:02X}F0",
        response_id_template="0x0284F0{addr:02X}",
        request_data=b"\x00\x00\x00\x00\x00\x00\x00\x00",
    ),
)


PROTOCOLS = {
    "beg1k0110": ProtocolDefinition(
        name="beg1k0110",
        display_name="BEG1K0110",
        templates=BEG_DEFAULT_TEMPLATES,
        read_presets=BEG_READ_PRESETS,
        control_presets=BEG_CONTROL_PRESETS,
    ),
    "charger": ProtocolDefinition(
        name="charger",
        display_name="charger",
        templates={},
        read_presets=CHARGER_READ_PRESETS,
        control_presets=CHARGER_CONTROL_PRESETS,
    ),
}


BEG_READ_LOOKUP = {preset.key: preset for preset in BEG_READ_PRESETS}
CHARGER_PREFIXES = (0x0284, 0x0289, 0x0299, 0x029A, 0x029C)


def parse_int(text: str) -> int:
    cleaned = text.strip()
    if not cleaned:
        return 0
    return int(cleaned, 0)


def format_can_id(can_id: int) -> str:
    return f"0x{can_id:08X}"


def format_payload(data: bytes | Iterable[int]) -> str:
    return " ".join(f"{byte:02X}" for byte in bytes(data))


def build_beg_payload(byte0: int, byte1: int, value: int = 0) -> bytes:
    return bytes([byte0 & 0xFF, byte1 & 0xFF, 0x00, 0x00]) + int(value).to_bytes(
        4, byteorder="big", signed=False
    )


def parse_payload_hex(hex_text: str) -> bytes:
    cleaned = hex_text.replace(" ", "").replace("_", "")
    if cleaned.startswith("0x"):
        cleaned = cleaned[2:]
    if len(cleaned) % 2 != 0:
        raise ValueError("数据长度必须是偶数个十六进制字符")
    payload = bytes.fromhex(cleaned)
    if not payload:
        raise ValueError("数据不能为空")
    if len(payload) > 8:
        raise ValueError("当前工具只支持 8 字节以内的标准 CAN 数据帧")
    return payload.ljust(8, b"\x00")


def render_arbitration_id(template: str, addr: int) -> int:
    return int(template.format(addr=addr & 0xFF), 0)


def resolve_beg_arbitration_id(scope: str, addr: int, templates: dict[str, str]) -> int:
    template = templates.get(scope)
    if template is None:
        raise ValueError(f"不支持的地址类型: {scope}")
    return render_arbitration_id(template, addr)


def build_charger_voltage_current_payload(voltage_mv: int, current_ma: int) -> bytes:
    """构建 charger 电压电流设置帧 (0x1B/0x1C).

    数据格式: 电压(mV, 4B大端) + 电流(mA, 4B大端)
    """
    voltage_bytes = int(voltage_mv).to_bytes(4, byteorder="big", signed=False)
    current_bytes = int(current_ma).to_bytes(4, byteorder="big", signed=False)
    return voltage_bytes + current_bytes


def decode_beg_payload(payload: bytes) -> tuple[str, str] | None:
    if len(payload) < 8:
        return None
    preset = BEG_READ_LOOKUP.get((payload[0], payload[1]))
    if preset is None:
        return None
    return preset.name, describe_beg_value(payload, preset)


def describe_beg_value(payload: bytes, preset: CommandPreset) -> str:
    if preset.name in {"模块状态", "逆变状态"}:
        return decode_beg_status_bytes(payload)
    tail = payload[4:8]
    value = int.from_bytes(tail, byteorder="big", signed=preset.signed)
    if preset.value_unit:
        return f"{value} {preset.value_unit}"
    return str(value)


def charger_response_id(preset: CommandPreset, addr: int) -> int | None:
    if not preset.response_id_template:
        return None
    return render_arbitration_id(preset.response_id_template, addr)


def charger_request_id(preset: CommandPreset, addr: int) -> int:
    return render_arbitration_id(preset.request_id_template, addr)


def decode_charger_payload(name: str, payload: bytes) -> str:
    if name == "模块电压电流" and len(payload) >= 8:
        voltage = int.from_bytes(payload[0:4], byteorder="big", signed=False)
        current = int.from_bytes(payload[4:8], byteorder="big", signed=False)
        return f"{voltage} mV / {current} mA"
    if name == "模块状态" and len(payload) >= 8:
        return (
            f"原始状态 {format_payload(payload)} | "
            f"组号字节={payload[2]:02X} 温度字节={payload[4]:02X} Walk字节={payload[6]:02X}"
        )
    return format_payload(payload)


def decode_beg_status_bytes(status_bytes: bytes) -> str:
    """解析BEG1K0110模块状态和逆变状态的告警位"""
    if len(status_bytes) < 8:
        return format_payload(status_bytes)

    alerts = []

    byte2 = status_bytes[2]
    if byte2 & 0x01:
        alerts.append("电网故障")
    if byte2 & 0x02:
        alerts.append("模块过温")
    if byte2 & 0x04:
        alerts.append("直流欠压")
    if byte2 & 0x08:
        alerts.append("输出降载")
    if byte2 & 0x10:
        alerts.append("模块过流")
    if byte2 & 0x20:
        alerts.append("风扇故障")
    if byte2 & 0x40:
        alerts.append("直流过压")
    if byte2 & 0x80:
        alerts.append("交流过压")

    byte3 = status_bytes[3]
    if byte3 & 0x01:
        alerts.append("交流欠压")
    if byte3 & 0x02:
        alerts.append("交流过频")
    if byte3 & 0x04:
        alerts.append("交流欠频")
    if byte3 & 0x08:
        alerts.append("锁相失败")
    if byte3 & 0x10:
        alerts.append("模块故障")
    if byte3 & 0x20:
        alerts.append("模块保护")
    if byte3 & 0x40:
        alerts.append("模块告警")
    if byte3 & 0x80:
        alerts.append("模块待机")

    byte4 = status_bytes[4]
    if byte4 & 0x01:
        alerts.append("模块运行")
    if byte4 & 0x02:
        alerts.append("模块关机")
    if byte4 & 0x04:
        alerts.append("模块开机")
    if byte4 & 0x08:
        alerts.append("模块复位")
    if byte4 & 0x10:
        alerts.append("模块调试")
    if byte4 & 0x20:
        alerts.append("模块测试")
    if byte4 & 0x40:
        alerts.append("模块校准")
    if byte4 & 0x80:
        alerts.append("模块升级")

    byte5 = status_bytes[5]
    if byte5 & 0x01:
        alerts.append("直流过流")
    if byte5 & 0x02:
        alerts.append("交流过流")
    if byte5 & 0x04:
        alerts.append("功率模块故障")
    if byte5 & 0x08:
        alerts.append("控制板故障")
    if byte5 & 0x10:
        alerts.append("通讯故障")
    if byte5 & 0x20:
        alerts.append("风扇故障2")
    if byte5 & 0x40:
        alerts.append("过温降额")
    if byte5 & 0x80:
        alerts.append("过载降额")

    byte6 = status_bytes[6]
    if byte6 & 0x01:
        alerts.append("电网异常")
    if byte6 & 0x02:
        alerts.append("频率异常")
    if byte6 & 0x04:
        alerts.append("电压异常")
    if byte6 & 0x08:
        alerts.append("谐波异常")
    if byte6 & 0x10:
        alerts.append("不平衡")
    if byte6 & 0x20:
        alerts.append("需量超限")
    if byte6 & 0x40:
        alerts.append("反向有功")
    if byte6 & 0x80:
        alerts.append("无功超限")

    byte7 = status_bytes[7]
    if byte7 & 0x01:
        alerts.append("急停")
    if byte7 & 0x02:
        alerts.append("绝缘故障")
    if byte7 & 0x04:
        alerts.append("接地故障")
    if byte7 & 0x08:
        alerts.append("防雷故障")
    if byte7 & 0x10:
        alerts.append("烟感")
    if byte7 & 0x20:
        alerts.append("水浸")
    if byte7 & 0x40:
        alerts.append("门禁")
    if byte7 & 0x80:
        alerts.append("备用告警")

    if not alerts:
        return f"正常 [{format_payload(status_bytes)}]"
    return f"⚠️ {', '.join(alerts)} [{format_payload(status_bytes)}]"


def is_charger_frame(arbitration_id: int) -> bool:
    return ((arbitration_id >> 16) & 0xFFFF) in CHARGER_PREFIXES


def now_text() -> str:
    return datetime.now().strftime("%H:%M:%S")
