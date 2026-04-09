# BEG1K0110 + charger tkinter 调试工具

这是一个面向 `BEG1K0110` 与 `charger` 的简易 Python tkinter 调试程序，主要用于配合 **PEAK PCAN USB to CAN** 适配器在同一条总线上进行联调。

## 已实现能力

- 选择 `PCAN_USBBUSx` 接口
- 选择比特率（125k / 250k / 500k / 1M）
- 同一条总线上同时连接 `BEG1K0110` 与 `charger`
- `BEG1K0110` 支持地址类型：`broadcast` / `group` / `module`
- `BEG1K0110` 支持地址值输入、ID 模板编辑与最终 ID 预览
- `charger` 支持模块地址输入，并内置文档中可确认的演示命令
- 两套设备各自独立轮询与状态面板，同时共享一个 PCAN 通道
- `BEG1K0110` 支持构造帧发送：`Byte0 + Byte1 + Value`
- 两套设备都支持原始 CAN 帧发送：`CAN ID + 8字节数据`
- 实时显示 TX / RX / 错误日志

## 运行依赖

建议在新的虚拟环境中安装：

```bash
pip install python-can[pcan]
```

另外需要本机已正确安装 **PEAK PCAN 驱动 / PCAN-Basic**，并且适配器能被系统与 `python-can` 的 `pcan` 后端识别。运行目标环境是 Windows Python 3.14。

## 启动方式

在仓库根目录运行：

```bash
python run_beg1k0110_debugger.py
```

## BEG1K0110 地址模板说明

工具默认内置了 3 个 ID 模板，来自当前文档中的示例帧：

- `broadcast`: `0x02A43FF0`
- `group`: `0x02E4{addr:02X}F0`
- `module`: `0x02A4{addr:02X}F0`

由于现有资料并未完整给出 ID 编码规则，因此这部分被设计为 **可编辑模板**。

如果你现场使用的组地址 / 模块地址编码方式与默认值不同，直接在 GUI 中修改模板即可。

## charger 预置命令来源

目前内置的 charger 预设命令来自 `docs/charger` 中当前可确认的 3 页资料，主要包括：

- 所有模块开机 / 关机
- 广播设置 750V / 15A
- 指定模块休眠
- 指定模块查询电压电流
- 指定模块查询状态

这些预设都可以先载入到原始帧编辑区，再按现场需要微调后发送。

## 当前限制

- `BEG1K0110` 仍主要依赖当前整理文档里的 `Byte0 / Byte1 / Value` 风格命令
- `charger` 当前只覆盖现有图片中能确认的演示命令与查询帧
- `charger` 的完整 CAN ID 字段定义、更多命令映射、错误码和完整状态位仍需正式协议补齐
- 由于当前环境是 WSL，仓库内未做 PCAN 硬件联机测试；使用前应在 Windows 真机上验证驱动、通道和现场波特率
