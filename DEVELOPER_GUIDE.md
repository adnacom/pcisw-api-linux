# Adnacom Monitor SDK — Developer Guide

## Table of Contents

1. [Overview](#1-overview)
2. [System Requirements](#2-system-requirements)
3. [Installation](#3-installation)
4. [Quick Start](#4-quick-start)
5. [Device Discovery](#5-device-discovery)
6. [API Reference — DeviceDataReader](#6-api-reference--devicedatareader)
   - [read_device_info](#61-read_device_info)
   - [read_brd_fw_info](#62-read_brd_fw_info)
   - [read_pcie_port_info](#63-read_pcie_port_info)
   - [read_cable_info](#64-read_cable_info)
   - [read_qsfp_info](#65-read_qsfp_info)
   - [read_upload_fw_version](#66-read_upload_fw_version)
   - [read_sram_crc](#67-read_sram_crc)
   - [read_flash_crc](#68-read_flash_crc)
   - [read_programming_status](#69-read_programming_status)
   - [start_firmware_programming](#610-start_firmware_programming)
   - [switch_boot_to_new_fw](#611-switch_boot_to_new_fw)
   - [write_file_to_sram](#612-write_file_to_sram)
7. [API Reference — Helpers](#7-api-reference--helpers)
   - [get_transceiver_channel_count](#71-get_transceiver_channel_count)
8. [Error Handling](#8-error-handling)
9. [Worked Examples](#9-worked-examples)
    - [Device Health Monitor](#91-device-health-monitor)
    - [QSFP Optical Monitor](#92-qsfp-optical-monitor)
    - [Cable Port Diagnostics](#93-cable-port-diagnostics)
    - [Firmware Update Workflow](#94-firmware-update-workflow)

---

## 1. Overview

The Adnacom Monitor SDK provides a Python API for monitoring and managing Adnacom PCIe
host adapter cards. It targets cards based on the PLX PEX switch family — PEX8718,
PEX8725, and PEX8734 (board models H3, H12, H14, H18, H25, R34).

The SDK exposes one public module:

| Module | Purpose |
|---|---|
| `adnacom_monitor.Protocol` | Device data reader — reads board info, transceiver status, cable diagnostics, and manages firmware updates |

All hardware access goes through `Protocol.DeviceDataReader`.

---

## 2. System Requirements

- **OS:** Linux x86_64 (kernel 4.15+)
- **Python:** 3.10 – 3.13 (the SDK ships pre-compiled extension modules for CPython 3.10, 3.11, 3.12 and 3.13; the import system selects the one matching the running interpreter)
- **Privileges:** Root access (or a udev rule granting group access to the device)
- **GTK3:** Required only if using `adnacom_monitor.firmware.FirmwarePage` (the GUI widget)
- **Hardware:** Adnacom PCIe host adapter with a mapped BAR0 resource
  (`/sys/bus/pci/devices/<BDF>/resource0` must exist)

### Running without root — udev rule

To allow a non-root user to access Adnacom devices, create
`/etc/udev/rules.d/99-adnacom.rules`:

```
SUBSYSTEM=="pci", ATTR{vendor}=="0x10b5", ATTR{device}=="0x8718", GROUP="adnacom", MODE="0660"
SUBSYSTEM=="pci", ATTR{vendor}=="0x10b5", ATTR{device}=="0x8725", GROUP="adnacom", MODE="0660"
```

Then add your user to the group and reload rules:

```bash
sudo groupadd --force adnacom
sudo usermod -aG adnacom $USER
sudo udevadm control --reload
sudo udevadm trigger
# Log out and back in for the group change to take effect
```

---

## 3. Installation

### From the SDK package

```bash
pip install adnacom-monitor
```

### From source

```bash
git clone <repository-url>
cd adnacom_monitor_sdk
pip install .
```

### Verify installation

```python
from adnacom_monitor.Protocol import DeviceDataReader
print("SDK installed correctly")
```

---

## 4. Quick Start

The following example reads basic device information from the first available Adnacom card:

```python
import subprocess
import re
from adnacom_monitor.Protocol import DeviceDataReader

VENDOR_ID = 0x10B5
DEVICE_IDS = (0x8718, 0x8725)

def find_adnacom_devices():
    """Return a list of BDF strings for all present Adnacom cards."""
    devices = []
    try:
        out = subprocess.check_output(["lspci", "-Dn"], text=True)
        for line in out.splitlines():
            # Format: 0000:03:00.0 0604: 10b5:8718 (rev 0b)
            match = re.match(r"(\S+)\s+\S+:\s+([0-9a-f]{4}):([0-9a-f]{4})", line)
            if match:
                bdf = match.group(1)
                vendor = int(match.group(2), 16)
                device = int(match.group(3), 16)
                if vendor == VENDOR_ID and device in DEVICE_IDS:
                    devices.append(bdf)
    except Exception:
        pass
    return devices

devices = find_adnacom_devices()
if not devices:
    print("No Adnacom devices found.")
else:
    bdf = devices[0]
    info = DeviceDataReader.read_device_info(bdf)
    print(f"Board:    {info['board']}")
    print(f"Firmware: {info['fw_rev']}")
    print(f"Serial:   {info['serial']}")
    print(f"State:    {info['brd_state']}")
    print(f"PEX Temp: {info['pex_temp']} °C")
```

---

## 5. Device Discovery

All `DeviceDataReader` methods accept a **BDF** (Bus:Device.Function) string in the
format `"DDDD:BB:SS.F"`, for example `"0000:03:00.0"`.

The device must have a mapped BAR0 resource at:
```
/sys/bus/pci/devices/<BDF>/resource0
```

Use `lspci` to enumerate compatible devices:

```bash
lspci -Dn | grep -E "10b5:(8718|8725)"
# 0000:03:00.0 0604: 10b5:8718 (rev 0b)
```

Or discover programmatically (see Quick Start above). Pass the BDF string directly to
any `DeviceDataReader` method.

---

## 6. API Reference — DeviceDataReader

```python
from adnacom_monitor.Protocol import DeviceDataReader
```

All methods are **static** — no instantiation needed. Every method opens and closes the
device within a single call. Calls are safe to make from multiple threads as long as each
thread uses a different BDF.

> **One process per device at a time.** Do not query a device from a script while the
> Adnacom Monitor GUI (or another script) is also polling the same BDF. Concurrent
> processes can interleave their requests and return mismatched values (for example an
> "Unknown" board or an implausible firmware version). Close the GUI before running
> SDK scripts against the same device.

---

### 6.1 `read_device_info`

```python
DeviceDataReader.read_device_info(bdf: str) -> dict
```

Reads a comprehensive snapshot of board identification, status, and power data.

**Parameters**

| Name | Type | Description |
|---|---|---|
| `bdf` | `str` | Device BDF string, e.g. `"0000:03:00.0"` |

**Returns** — `dict` with the following keys:

| Key | Type | Description |
|---|---|---|
| `board` | `str` | Board model (`"H18"`, `"H3"`, `"R34"`, etc.) |
| `mode` | `str` | Operating mode (`"Host"` or `"Remote"`) |
| `hw_rev` | `str` | Hardware revision, e.g. `"1.0.0"` |
| `fw_rev` | `str` | Firmware version, e.g. `"1.2.1024"` |
| `serial` | `str` | Serial number (hex-formatted) |
| `switch` | `str` | PCIe switch model (`"PEX8718"`, `"PEX8725"`, `"PEX8734"`) |
| `downstream_cnt` | `int` | Number of downstream cable ports |
| `upstream_cnt` | `int` | Number of upstream PCIe ports |
| `dip_sw_cnt` | `int` | Number of DIP switch banks |
| `sw1_setting` | `int` | DIP switch S1 state (bitmask, bit 0 = position 1) |
| `sw2_setting` | `int` | DIP switch S2 state (bitmask) |
| `brd_state` | `str` | Board power state (`"On"`, `"Standby"`, `"Reset"`, etc.) |
| `cpu_temp` | `int` | CPU temperature in °C |
| `pex_temp` | `int` | PCIe switch temperature in °C |
| `board_uptime` | `int` | Board uptime in milliseconds |
| `assy_rev` | `int` | Assembly revision byte |
| `reset_len` | `int` | Last reset duration in milliseconds |
| `enum_time` | `int` | PCIe enumeration time in milliseconds |
| `run_time` | `int` or `str` | Board run time in milliseconds (`"N/A"` if the firmware does not report it) |
| `since_reset` | `int` or `str` | Time since the last reset in milliseconds (`"N/A"` if not reported) |
| `reset_cnt` | `int` or `str` | Number of resets (`"N/A"` if not reported) |
| `main_3v3` | `float` | 3.3 V rail voltage |
| `rail_12v_v` | `float` | 12 V slot rail voltage |
| `rail_3v3aux_v` | `float` | 3.3 Vaux slot rail voltage |
| `cpu_1v8` | `float` | CPU 1.8 V rail voltage |
| `pex_1v8` | `float` | PEX 1.8 V rail voltage |
| `pex_0v9` | `float` | PEX 0.9 V rail voltage |
| `pex_0v9analog` | `float` | PEX 0.9 VA (analog) rail voltage |
| `rail_12v_i` | `float` | 12 V rail current in amps |
| `rail_3v3aux_i` | `float` | 3.3 Vaux rail current in amps |

**Example**

```python
info = DeviceDataReader.read_device_info("0000:03:00.0")

print(f"Board:         {info['board']}")
print(f"Firmware:      {info['fw_rev']}")
print(f"Serial:        {info['serial']}")
print(f"State:         {info['brd_state']}")
print(f"PEX Temp:      {info['pex_temp']} °C")
print(f"12V Rail:      {info['rail_12v_v']:.2f} V  {info['rail_12v_i']:.2f} A")
print(f"Cable Ports:   {info['downstream_cnt']}")

# DIP switch S1 — read individual positions
sw1 = info['sw1_setting']
for pos in range(8):
    state = "ON" if (sw1 >> pos) & 1 else "OFF"
    print(f"  S1 position {pos + 1}: {state}")
```

---

### 6.2 `read_brd_fw_info`

```python
DeviceDataReader.read_brd_fw_info(bdf: str) -> dict
```

Lightweight read of board name and firmware version only. Use this instead of
`read_device_info` when you only need to identify the device (e.g. before a firmware
update) to minimise device access time.

**Returns** — `dict`:

| Key | Type | Description |
|---|---|---|
| `board` | `str` | Board model |
| `fw_rev` | `str` | Current firmware version string |

**Example**

```python
info = DeviceDataReader.read_brd_fw_info("0000:03:00.0")
print(f"{info['board']}  fw {info['fw_rev']}")
```

---

### 6.3 `read_pcie_port_info`

```python
DeviceDataReader.read_pcie_port_info(bdf: str) -> dict
```

Reads the PCIe link status of the upstream host slot (Port 0).

**Returns** — `dict`:

| Key | Type | Description |
|---|---|---|
| `port` | `str` | Always `"0"` |
| `cap` | `str` | Maximum link capability, e.g. `"Gen3 x8"` |
| `link_state` | `str` | Negotiated link state, e.g. `"Gen3 x8"` or `"Down x0"` |

**Example**

```python
port = DeviceDataReader.read_pcie_port_info("0000:03:00.0")
print(f"PCIe slot: capable of {port['cap']}, running at {port['link_state']}")
```

---

### 6.4 `read_cable_info`

```python
DeviceDataReader.read_cable_info(bdf: str, port: int) -> dict
```

Reads link state and error counters for one downstream cable port.

**Parameters**

| Name | Type | Description |
|---|---|---|
| `bdf` | `str` | Device BDF string |
| `port` | `int` | Cable port number, from 1 to the board's `downstream_cnt` |

Use `read_device_info()["downstream_cnt"]` to determine how many ports the board has.
A port number outside the supported range raises `ValueError`.

**Returns** — `dict`:

| Key | Type | Description |
|---|---|---|
| `port` | `str` | Port number |
| `cap` | `str` | Max link capability or `"No QSFP"` if no transceiver |
| `link_state` | `str` | Negotiated link state or `"Down"` |
| `training` | `str` | Link training time, e.g. `"42 ms"` |
| `remote_up` | `str` | Time until remote side came up, e.g. `"120 ms"` |
| `recov_cnt` | `int` | Link recovery counter |
| `rx_errors` | `int` | Receiver error counter |
| `bad_tlp` | `int` | Bad TLP (Transaction Layer Packet) counter |
| `bad_dll` | `int` | Bad DLLP (Data Link Layer Packet) counter |
| `framing_err` | `int` | Framing error counter |
| `retrain` | `int` | Link retrain counter |
| `link_down` | `int` | Link-down event counter |

**Example**

```python
info = DeviceDataReader.read_device_info("0000:03:00.0")
port_count = info["downstream_cnt"]

for port_num in range(1, port_count + 1):
    cable = DeviceDataReader.read_cable_info("0000:03:00.0", port_num)

    print(f"Port {port_num}: {cable['link_state']}")
    if cable.get("recov_cnt", 0):
        print(f"  Recovery events: {cable['recov_cnt']}")
    if cable.get("link_down", 0):
        print(f"  Link-down events: {cable['link_down']}")
```

---

### 6.5 `read_qsfp_info`

```python
DeviceDataReader.read_qsfp_info(bdf: str, qsfp: int) -> dict
```

Reads the full status of one QSFP/CSFP/SFP transceiver module. Includes presence,
vendor identification, optical power levels, and alarm/warning thresholds.

**Parameters**

| Name | Type | Description |
|---|---|---|
| `bdf` | `str` | Device BDF string |
| `qsfp` | `int` | Transceiver index, starting at 0 (see the board counts below) |

**Board QSFP counts**

| Board | QSFP count |
|---|---|
| H3 | 4 |
| H12 | 2 |
| H14 | 1 |
| H18 | 2 |
| H25 | 2 |
| R34 | 2 |

**Returns** — `dict`:

*Presence and identification*

| Key | Type | Description |
|---|---|---|
| `port` | `str` | 1-based port number |
| `present` | `str` | `"Yes"` or `"No"` |
| `vendor` | `str` | Vendor name string |
| `part_num` | `str` | Part number and revision, e.g. `"FTLX8574D3BCL, Rev.A"` |
| `serial_num` | `str` | Module serial number |
| `technology` | `str` | Optical technology, e.g. `"850 nm VCSEL"`, `"Copper cable"` |
| `transceiver_type` | `int` | Type code: `0`=QSFP, `1`=SFP, `2`=CSFP |
| `state` | `str` | Module power state (`"On"` / `"Off"`) |
| `power_supply` | `str` | Module supply summary, e.g. `"3.32 V \| 0.50 A \| 1.7 W"` |
| `startup` | `str` | Module startup time, e.g. `"300 ms"` |
| `i2c_errors` | `int` | I²C error counter |
| `rx_los` | `int` | Receiver Loss-of-Signal bitmask |

*Squelch flags (read-only, reflect module capabilities)*

| Key | Type | Description |
|---|---|---|
| `tx_squelch` | `int` | `1` if Tx squelch is implemented |
| `rx_squelch_disable` | `int` | `1` if Rx squelch disable is supported |
| `tx_squelch_disable` | `int` | `1` if Tx squelch disable is supported |

*Live measurements*

| Key | Type | Description |
|---|---|---|
| `temp` | `float` | Internal temperature in °C |
| `vcc` | `float` | Supply voltage in V |
| `rx1`–`rx4` | `int` | Rx optical power per channel in μW |
| `tx1`–`tx4` | `float` | Tx bias current per channel in mA |
| `rx1_onoff`–`rx4_onoff` | `int` | `1` if the Rx channel is enabled |
| `tx1_onoff`–`tx4_onoff` | `int` | `1` if the Tx channel is enabled |

*Alarm / warning thresholds*

| Key | Description |
|---|---|
| `temp_ha` / `temp_la` | Temperature high/low alarm (°C) |
| `temp_hw` / `temp_lw` | Temperature high/low warning (°C) |
| `vcc_ha` / `vcc_la` | VCC high/low alarm (V) |
| `vcc_hw` / `vcc_lw` | VCC high/low warning (V) |
| `rx_pwr_ha` / `rx_pwr_la` | Rx power high/low alarm (μW) |
| `rx_pwr_hw` / `rx_pwr_lw` | Rx power high/low warning (μW) |
| `tx_bias_ha` / `tx_bias_la` | Tx bias high/low alarm (mA) |
| `tx_bias_hw` / `tx_bias_lw` | Tx bias high/low warning (mA) |

**Example**

```python
from adnacom_monitor.Protocol import DeviceDataReader, get_transceiver_channel_count

bdf = "0000:03:00.0"
info = DeviceDataReader.read_device_info(bdf)

board_qsfp_counts = {"H3": 4, "H12": 2, "H14": 1, "H18": 2, "H25": 2, "R34": 2}
qsfp_count = board_qsfp_counts.get(info["board"], 2)

for idx in range(qsfp_count):
    q = DeviceDataReader.read_qsfp_info(bdf, idx)

    if q["present"] != "Yes":
        print(f"QSFP {idx + 1}: not present")
        continue

    ch = get_transceiver_channel_count(q["transceiver_type"])
    print(f"QSFP {idx + 1}: {q['vendor']}  {q['part_num']}")
    print(f"  Temp: {q['temp']:.1f} °C  VCC: {q['vcc']:.2f} V")
    for c in range(1, ch + 1):
        print(f"  Rx{c}: {q[f'rx{c}']} μW   Tx{c}: {q[f'tx{c}']:.1f} mA")
```

---

### 6.6 `read_upload_fw_version`

```python
DeviceDataReader.read_upload_fw_version(bdf: str) -> str
```

Reads the firmware version embedded in a binary that has been uploaded to the device's
SRAM buffer (via `write_file_to_sram`). Call this after uploading and CRC-verifying a
firmware image, before triggering the flash programming step.

**Returns** — version string, e.g. `"1.3.2048"`. Returns `"0.0.0"` if the buffer is
empty or unreadable.

**Example**

```python
version = DeviceDataReader.read_upload_fw_version("0000:03:00.0")
print(f"Staged firmware version: {version}")
```

---

### 6.7 `read_sram_crc`

```python
DeviceDataReader.read_sram_crc(bdf: str) -> int
```

Reads the CRC verification result after a firmware binary has been written to the device's
SRAM. The device computes this CRC autonomously after the upload completes.

**Returns** — `int` CRC value. Interpret as follows:

| Value | Meaning |
|---|---|
| `0xAAAAAAAA` | CRC passed — binary is valid |
| `0x00000BAD` | CRC failed — binary is corrupt or incomplete |
| any other | CRC still being computed — poll again |

**Example**

```python
import time

for _ in range(30):          # Poll up to ~30 seconds
    crc = DeviceDataReader.read_sram_crc("0000:03:00.0")
    if crc == 0xAAAAAAAA:
        print("Upload verified")
        break
    elif crc == 0x00000BAD:
        print("Upload CRC failed — re-upload required")
        break
    time.sleep(1)
```

---

### 6.8 `read_flash_crc`

```python
DeviceDataReader.read_flash_crc(bdf: str) -> int
```

Reads the CRC verification result after firmware has been programmed into flash. Same
return value semantics as `read_sram_crc`.

**Example**

```python
crc = DeviceDataReader.read_flash_crc("0000:03:00.0")
if crc == 0xAAAAAAAA:
    print("Flash programming verified successfully")
```

---

### 6.9 `read_programming_status`

```python
DeviceDataReader.read_programming_status(bdf: str) -> dict
```

Reads the current status of an in-progress firmware flash operation.

**Returns** — `dict`:

| Key | Type | Description |
|---|---|---|
| `state` | `str` | Current state name (see table below) |
| `done` | `bool` | `True` when programming has completed |
| `progress` | `int` | Programming progress, 0–100 (percent) |

**State values**

| `state` | Meaning |
|---|---|
| `"UPDATE_IDLE"` | No update in progress |
| `"UPDATE_VERIFY_DATA"` | Verifying uploaded data |
| `"UPDATE_ERASE"` | Erasing flash sectors |
| `"UPDATE_PROGRAMM"` | Writing to flash |
| `"UPDATE_READY"` | Programming complete, ready to switch |
| `"UPDATE_VERIFY_FLASH"` | Verifying written flash |
| `"UPDATE_DATA_CRC_ERROR"` | Upload data CRC mismatch |
| `"UPDATE_FLASH_CRC_ERROR"` | Flash verification CRC mismatch |
| `"UPDATE_PROG_ERROR"` | Flash programming hardware error |

**Example**

```python
import time

while True:
    status = DeviceDataReader.read_programming_status("0000:03:00.0")
    print(f"  {status['state']}  {status['progress']}%")
    if status["done"]:
        print("Programming complete")
        break
    if "ERROR" in status["state"]:
        raise RuntimeError(f"Programming failed: {status['state']}")
    time.sleep(1)
```

---

### 6.10 `start_firmware_programming`

```python
DeviceDataReader.start_firmware_programming(bdf: str) -> bool
```

Triggers the device to begin programming the uploaded SRAM content into flash. Call this
only after `read_sram_crc` returns `0xAAAAAAAA`.

**Returns** — `True` if the trigger command was issued successfully.

**Raises** — `FileNotFoundError` if the device resource path does not exist.

**Example**

```python
if DeviceDataReader.start_firmware_programming("0000:03:00.0"):
    print("Flash programming started")
```

---

### 6.11 `switch_boot_to_new_fw`

```python
DeviceDataReader.switch_boot_to_new_fw(bdf: str) -> bool
```

Writes the firmware activation command and triggers a chip reset. The device reboots into
the newly programmed firmware. Call this only after `read_programming_status` returns
`done=True`.

> **Warning:** This command resets the PCIe device. The BDF may become temporarily
> unavailable. A host system restart may be required for the OS to re-enumerate the device.

**Returns** — `True` if the activation command was written successfully.

**Example**

```python
if DeviceDataReader.switch_boot_to_new_fw("0000:03:00.0"):
    print("Device reset triggered — new firmware will be active after host restart")
```

---

### 6.12 `write_file_to_sram`

```python
DeviceDataReader.write_file_to_sram(bdf: str, offset: int, firmware_data: list) -> None
```

Writes a chunk of firmware binary data to the device's SRAM upload buffer. Data must be
written in aligned chunks of up to 8 32-bit words at a time.

**Parameters**

| Name | Type | Description |
|---|---|---|
| `bdf` | `str` | Device BDF string |
| `offset` | `int` | Byte offset into the SRAM buffer (must be a multiple of 4) |
| `firmware_data` | `list[int]` | List of up to 8 unsigned 32-bit integers |

**Example** — uploading a complete firmware binary:

```python
def upload_firmware(bdf: str, firmware_path: str) -> bool:
    with open(firmware_path, "rb") as f:
        raw = f.read()

    if len(raw) > 0x40000:          # 256 KB limit
        raise ValueError("Firmware image exceeds 256 KB")

    # Pad to 4-byte boundary
    if len(raw) % 4:
        raw += b"\x00" * (4 - len(raw) % 4)

    # Convert to 32-bit little-endian word list
    words = [
        int.from_bytes(raw[i:i+4], "little")
        for i in range(0, len(raw), 4)
    ]

    # Write in chunks of 8 words (32 bytes)
    for i in range(0, len(words), 8):
        chunk = words[i:i+8]
        chunk += [0] * (8 - len(chunk))     # Pad last chunk if needed
        DeviceDataReader.write_file_to_sram(bdf, i * 4, chunk)

    return True
```

---

## 7. API Reference — Helpers

### 7.1 `get_transceiver_channel_count`

```python
from adnacom_monitor.Protocol import get_transceiver_channel_count

get_transceiver_channel_count(transceiver_type: int) -> int
```

Maps the `transceiver_type` integer from `read_qsfp_info` to a channel count.

| `transceiver_type` | Module type | Channels |
|---|---|---|
| `0` | QSFP | 4 |
| `1` | SFP | 1 |
| `2` | CSFP | 2 |
| other | Unknown (default) | 4 |

**Example**

```python
q = DeviceDataReader.read_qsfp_info(bdf, 0)
channels = get_transceiver_channel_count(q["transceiver_type"])
print(f"Module has {channels} Rx/Tx channels")
```

---

## 8. Error Handling

All `DeviceDataReader` methods can raise the following exceptions:

| Exception | Cause |
|---|---|
| `FileNotFoundError` | The device sysfs path does not exist (device not present or BDF wrong) |
| `IOError` | Failed to open or memory-map the device resource |
| `PermissionError` | Process does not have read/write access to the resource file |
| `subprocess.TimeoutExpired` | Device did not respond within the timeout |
| `RuntimeError` | The board did not complete a command in time ("Read timeout" / "Write timeout"), or the device is already open (programming logic error) |
| `adnacom_monitor.Protocol.CommandError` | Subclass of `RuntimeError`: the board rejected a command |

**Recommended pattern:**

```python
import subprocess

def safe_read(bdf: str) -> dict | None:
    try:
        return DeviceDataReader.read_device_info(bdf)
    except FileNotFoundError:
        print(f"Device {bdf} not found")
    except PermissionError:
        print("Permission denied — run as root or add udev rule")
    except subprocess.TimeoutExpired:
        print(f"Device {bdf} timed out")
    except Exception as e:
        print(f"Unexpected error: {e}")
    return None
```

---

## 9. Worked Examples

### 9.1 Device Health Monitor

Polls all Adnacom cards and prints a status line for each every 5 seconds.

```python
import time
import subprocess
import re
from adnacom_monitor.Protocol import DeviceDataReader


def find_adnacom_devices():
    devices = []
    try:
        out = subprocess.check_output(["lspci", "-Dn"], text=True)
        for line in out.splitlines():
            match = re.match(r"(\S+)\s+\S+:\s+10b5:(?:8718|8725)", line)
            if match:
                devices.append(match.group(1))
    except Exception:
        pass
    return devices


def print_health(bdf: str):
    try:
        info = DeviceDataReader.read_device_info(bdf)
        uptime_s = info["board_uptime"] // 1000
        h, m, s = uptime_s // 3600, (uptime_s % 3600) // 60, uptime_s % 60
        print(
            f"[{bdf}] {info['board']} fw={info['fw_rev']} "
            f"state={info['brd_state']} "
            f"Tcpu={info['cpu_temp']}°C Tpex={info['pex_temp']}°C "
            f"12V={info['rail_12v_v']:.2f}V "
            f"uptime={h:02d}:{m:02d}:{s:02d}"
        )
    except Exception as e:
        print(f"[{bdf}] ERROR: {e}")


devices = find_adnacom_devices()
if not devices:
    print("No Adnacom devices found")
else:
    while True:
        for bdf in devices:
            print_health(bdf)
        time.sleep(5)
```

---

### 9.2 QSFP Optical Monitor

Reads optical power and temperature for all transceivers on a card and flags any
threshold violations.

```python
from adnacom_monitor.Protocol import DeviceDataReader, get_transceiver_channel_count

BOARD_QSFP_COUNTS = {"H3": 4, "H12": 2, "H14": 1, "H18": 2, "H25": 2, "R34": 2}

def check_qsfp(bdf: str):
    info = DeviceDataReader.read_device_info(bdf)
    qsfp_count = BOARD_QSFP_COUNTS.get(info["board"], 2)

    for idx in range(qsfp_count):
        q = DeviceDataReader.read_qsfp_info(bdf, idx)

        port = idx + 1
        if q["present"] != "Yes":
            print(f"  Port {port}: no module")
            continue

        ch = get_transceiver_channel_count(q["transceiver_type"])
        warnings = []

        # Temperature check
        if q["temp"] >= q["temp_ha"]:
            warnings.append(f"TEMP HIGH ALARM ({q['temp']:.1f} >= {q['temp_ha']:.1f} °C)")
        elif q["temp"] >= q["temp_hw"]:
            warnings.append(f"temp high warning ({q['temp']:.1f} °C)")

        # Per-channel Rx power check
        for c in range(1, ch + 1):
            rx = q[f"rx{c}"]
            if rx <= q["rx_pwr_la"]:
                warnings.append(f"Rx{c} LOW ALARM ({rx} μW)")
            elif rx <= q["rx_pwr_lw"]:
                warnings.append(f"Rx{c} low warning ({rx} μW)")

        status = "  ".join(warnings) if warnings else "OK"
        print(f"  Port {port} [{q['vendor']}]: temp={q['temp']:.1f}°C  {status}")


bdf = "0000:03:00.0"
print(f"QSFP status for {bdf}:")
check_qsfp(bdf)
```

---

### 9.3 Cable Port Diagnostics

Reads error counters across all cable ports and reports any non-zero counts.

```python
from adnacom_monitor.Protocol import DeviceDataReader

def diagnose_ports(bdf: str):
    info = DeviceDataReader.read_device_info(bdf)
    port_count = info["downstream_cnt"]

    if port_count == 0:
        print("No downstream cable ports on this board")
        return

    error_fields = ["recov_cnt", "rx_errors", "bad_tlp", "bad_dll",
                    "framing_err", "retrain", "link_down"]

    for port_num in range(1, port_count + 1):
        cable = DeviceDataReader.read_cable_info(bdf, port_num)

        print(f"Port {port_num}: {cable['link_state']}  (max: {cable['cap']})")
        errors = {k: cable[k] for k in error_fields if cable.get(k, 0)}
        if errors:
            for name, value in errors.items():
                print(f"  {name}: {value}")
        else:
            print("  No errors")


diagnose_ports("0000:03:00.0")
```

---

### 9.4 Firmware Update Workflow

A complete, sequential firmware update — upload, verify, program, activate.

```python
import time
from adnacom_monitor.Protocol import DeviceDataReader

VALID_CRC   = 0xAAAAAAAA
INVALID_CRC = 0x00000BAD

def update_firmware(bdf: str, firmware_path: str):
    # 1 — Read current firmware version
    info = DeviceDataReader.read_brd_fw_info(bdf)
    print(f"Current firmware: {info['fw_rev']}  (board: {info['board']})")

    # 2 — Load and validate the binary
    with open(firmware_path, "rb") as f:
        raw = f.read()

    if len(raw) > 0x40000:
        raise ValueError(f"Firmware too large: {len(raw)} bytes (max 262144)")

    # Pad to 4-byte boundary
    if len(raw) % 4:
        raw += b"\x00" * (4 - len(raw) % 4)

    words = [int.from_bytes(raw[i:i+4], "little") for i in range(0, len(raw), 4)]

    # 3 — Upload to SRAM in 8-word chunks
    print(f"Uploading {len(raw)} bytes...")
    for i in range(0, len(words), 8):
        chunk = words[i:i+8]
        chunk += [0] * (8 - len(chunk))
        DeviceDataReader.write_file_to_sram(bdf, i * 4, chunk)
        if i % 512 == 0:
            pct = min(100, int(i / len(words) * 100))
            print(f"  {pct}%", end="\r", flush=True)
    print("  100% — upload complete")

    # 4 — Wait for CRC verification
    print("Verifying CRC...")
    for _ in range(30):
        crc = DeviceDataReader.read_sram_crc(bdf)
        if crc == VALID_CRC:
            print("  CRC passed")
            break
        elif crc == INVALID_CRC:
            raise RuntimeError("CRC verification failed — binary may be corrupt")
        time.sleep(1)
    else:
        raise TimeoutError("CRC verification timed out")

    # 5 — Read new version from upload buffer
    new_version = DeviceDataReader.read_upload_fw_version(bdf)
    print(f"Staged firmware version: {new_version}")

    # 6 — Start flash programming
    print("Programming flash...")
    DeviceDataReader.start_firmware_programming(bdf)

    for _ in range(120):
        status = DeviceDataReader.read_programming_status(bdf)
        print(f"  {status['state']}  {status['progress']}%", end="\r", flush=True)
        if status["done"]:
            print(f"\n  Programming complete")
            break
        if "ERROR" in status["state"]:
            raise RuntimeError(f"Programming failed: {status['state']}")
        time.sleep(1)
    else:
        raise TimeoutError("Flash programming timed out")

    # 7 — Verify flash CRC
    crc = DeviceDataReader.read_flash_crc(bdf)
    if crc != VALID_CRC:
        raise RuntimeError("Flash CRC verification failed")
    print("Flash CRC verified")

    # 8 — Activate new firmware (triggers device reset)
    print("Activating new firmware — device will reset...")
    DeviceDataReader.switch_boot_to_new_fw(bdf)
    print(f"Done. Restart the host to complete the update to firmware {new_version}.")


# Usage
update_firmware("0000:03:00.0", "/path/to/firmware.bin")
```
