# swcfgtotxt
一鍵備份交換器設定檔

<img width="557" height="213" alt="image01" src="https://github.com/user-attachments/assets/a48c13c2-c641-4f08-9d61-2e340134d42d" />


# 🚀 Network Device Config Auto-Backup Tool (網路設備自動備份系統)

![OS](https://img.shields.io/badge/OS-Windows%20%7C%20Linux%20%7C%20macOS-blue)
![Python](https://img.shields.io/badge/Python-3.8+-yellow)
![License](https://img.shields.io/badge/License-MIT-green)

**Network Device Config Auto-Backup Tool** 是一個基於 Python 開發的跨品牌網路設備自動備份腳本。專為解決複雜網路環境下的自動化備份痛點而設計。

本系統最大的特色在於**內建了高相容性的 TFTP 伺服器**，並具備**「雙軌備份與智慧退回 (Fallback)」**機制。無論設備是支援高速的二進位檔案匯出，還是僅支援傳統終端機純文字顯示，本腳本都能自動判斷並完美完成備份。

---

## ✨ 核心特色功能

* 🖧 **內建高相容 TFTP Server**：無須額外安裝第三方 TFTP 軟體。動態綁定本機 IP，完美解決舊型設備 TFTP 傳輸卡死的問題。
* 🔄 **雙軌備份與智慧退回 (Fallback)**：
  * **優先嘗試 TFTP**：若設備支援（如 D-Link），優先發送 TFTP 上傳指令，並將設定檔儲存為 `.bin` 二進位格式。
  * **動態退回文字備份**：若 TFTP 指令超時或失敗，系統會自動無縫切換為「終端機文字擷取」模式。
  * **副檔名自動校正**：當啟動退回機制改用文字備份時，程式會自動將原本預設的 `.bin` 副檔名修正回 `.cfg`，避免檔案格式混淆。
* ✂️ **分頁符號自動處理**：針對不同品牌自動適配分頁處理（如 Cisco 的 `terminal length 0`、D-Link 的 `disable clipaging` 或自動發送空白鍵/a鍵換頁）。
* 📊 **批次作業與成效統計**：
  * 支援讀取 `devices.csv` 進行全網自動備份。
  * 任務結束後自動產生**任務摘要**，包含：成功/失敗數量、失敗 IP 列表、以及**精確的執行花費時間（時/分/秒）**。
* 📂 **自動化歸檔**：備份檔案會依照 `YYYYMMDD_HHMM/` 的時間戳記自動建立資料夾，檔名包含 IP、主機名稱與日期。

---

## 🛠️ 開發語言與技術棧

* **核心語言**：Python 3.8+
* **網路連線模組**：`netmiko` (處理 SSH/Telnet 自動化互動)
* **內建協定實作**：`socket`, `struct` (自建高相容 TFTP Server)
* **資料處理**：`csv`, `re`

---

## 🖧 已測試支援品牌 (Supported Devices)

本腳本已針對以下設備型號/作業系統進行測試與優化：

* **D-Link**：支援舊版 Telnet 與新版 SSH，支援 TFTP (`.bin`) 與純文字 (`.cfg`) 備份。內建舊版提示字元異常降級處理。
* **Cisco IOS / IOS-XE**：Router, Switch (`.cfg`)。
* **Fortinet FortiGate**：完整設定檔備份 (`.conf`)。
* **Palo Alto Networks**：設定檔備份 (`.set`)。
* **MikroTik**：匯出備份 (`.rsc`)。

> **註：** 理論上只要是 `netmiko` 支援的設備，皆可透過在 CSV 中填寫對應的 `device_type` 進行純文字備份。

---

## 📦 安裝與執行 (環境建置)

請先確保你的電腦已安裝 **Python 3.8 或以上版本**。

### 1. 複製專案
```bash
git clone [https://github.com/YourUsername/Network-Backup-Tool.git](https://github.com/YourUsername/Network-Backup-Tool.git)
cd Network-Backup-Tool

```

### 2. 安裝必要的 Python 模組

本程式核心依賴 `netmiko`，請透過 `pip` 進行安裝：

```bash
pip install netmiko

```

*(註：其餘如 `socket`, `struct`, `threading` 等皆為 Python 內建標準函式庫，無需額外安裝)*

### 3. 準備設定檔

在主程式同一目錄下建立一個名為 `devices.csv` 的檔案。若要在批次備份中**暫時跳過**某台設備，只需在該 IP 前面加上 `#` 符號。

**`devices.csv` 格式範例：**

| ip | device_type | username | password | secret |
| --- | --- | --- | --- | --- |
| 192.168.1.10 | cisco_ios | admin | pass123 | enable123 |
| 192.168.1.11 | dlink | admin | pass123 |  |
| 192.168.1.12 | fortinet | admin | pass123 |  |
| #192.168.1.13 | cisco_ios_telnet | admin | pass123 |  |

> **參數說明：**
> * `device_type`: 必須符合 `netmiko` 的設備類型定義（如 `cisco_ios`, `dlink`, `fortinet` 等，Telnet 設備請加上 `_telnet`）。
> 
> 

---

## 📖 操作簡易說明

1. **確認 Port 69 未被佔用**：執行前請關閉電腦上其他 TFTP 軟體（如 Tftpd64）。
2. **權限要求**：**強烈建議以系統管理員身分 (Administrator / root) 執行**，因為啟動內建 TFTP 伺服器需要綁定特權連接埠 (Port 69)。

### 執行主程式

```bash
python swcfgtotxt.py

```

### 互動式主選單

執行後會出現以下選單：

```text
============================== 網路設備自動備份系統 ==============================
1) 選擇指定 IP 下載 (序號選單) - 適合單台設備除錯與測試
2) 依照 CSV 設定檔全部下載 - 適合定期排程或全面備份
3) 結束程式

```

---

## 📂 備份目錄結構

系統會自動以執行的「日期_時間」建立資料夾，妥善分類所有設定檔：

```text
Project_Folder/
├── swcfgtotxt.py      
├── devices.csv           
└── network_backups/      
    ├── 20260520_0800/
    │   ├── 192.168.1.10_CoreSwitch_20260520.cfg    # 文字備份
    │   ├── 192.168.1.11_EdgeSwitch_20260520.bin    # 二進位 TFTP 備份
    │   └── 192.168.1.12_Firewall_20260520.conf
    └── 20260521_0800/

```

---

## ⚠️ 常見問題與除錯

* **`[!] TFTP 啟動失敗: 權限不足！`**
* 在 Windows 上請「以系統管理員身分執行」命令提示字元；Linux/macOS 上請使用 `sudo` 執行。


* **`[!] TFTP 啟動失敗: Port 69 已被佔用`**
* 請檢查是否背景有其他 TFTP 伺服器正在執行，將其關閉後再重新執行本程式。


* **遇到 "Pattern not detected" 或超時錯誤？**
* 腳本內建了針對舊版 D-Link 的相容機制，若偵測到提示字元異常，會自動降級並嘗試替換連線指令。請確保設備網路暢通，並允許執行此腳本的電腦 IP 進行 TFTP 傳輸。



---

## 📜 授權條款

本專案採用 [MIT License](https://www.google.com/search?q=LICENSE) 授權。您可以自由使用、複製、修改、合併、出版發行、散佈、再授權及販售軟體及軟體的副本。

```

```
