import csv
import datetime
import os
import re
import socket
import struct
import threading
import time
from netmiko import ConnectHandler

# --- 參數設定 ---
VERSION = "v2.1 (Dynamic Extension Fallback for Text Backup)"
CSV_FILE = 'devices.csv'
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MAX_RETRIES = 3 

TIMESTAMP_DIR = datetime.datetime.now().strftime("%Y%m%d_%H%M")
CURRENT_BACKUP_DIR = os.path.join(BASE_DIR, "network_backups", TIMESTAMP_DIR)
# ----------------

def get_local_ip_fallback(target_host):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect((target_host, 1))
        local_ip = s.getsockname()[0]
    except Exception:
        local_ip = "127.0.0.1"
    finally:
        s.close()
    return local_ip

class GlobalTFTPServer:
    """高相容性 TFTP 伺服器 (無視 OACK 選項，強迫相容舊型設備)"""
    def __init__(self, save_dir):
        self.save_dir = save_dir
        self.sock = None
        self.running = False
        self.current_bind_ip = '0.0.0.0'
        self.completed_transfers = set() # 僅記錄成功完成的純檔名

    def start(self):
        if self.running: return
        os.makedirs(self.save_dir, exist_ok=True)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            self.sock.bind(('0.0.0.0', 69))
            self.running = True
            threading.Thread(target=self._listen_loop, daemon=True).start()
            print("[*] 內建 TFTP 伺服器已啟動 (強制標準相容模式)")
        except PermissionError:
            print("[!] TFTP 啟動失敗: 權限不足！請使用系統管理員權限執行。")
        except OSError as e:
            if e.errno in (98, 10048):
                print("[!] TFTP 啟動失敗: Port 69 已被佔用，請關閉 Tftpd64 等軟體。")
            else:
                print(f"[!] TFTP 啟動失敗: {e}")

    def stop(self):
        self.running = False
        if self.sock:
            try: self.sock.close()
            except: pass

    def _listen_loop(self):
        self.sock.settimeout(1.0) 
        while self.running:
            try:
                data, addr = self.sock.recvfrom(2048)
                if len(data) < 4: continue
                
                opcode = struct.unpack("!H", data[0:2])[0]
                
                if opcode == 2:  # 收到 WRQ (寫入請求)
                    parts = data[2:].split(b'\x00')
                    filename = parts[0].decode('utf-8', errors='ignore')
                    
                    safe_filename = os.path.basename(filename) 
                    save_path = os.path.join(self.save_dir, safe_filename)
                    
                    print(f"\n    [TFTP] 收到來自 {addr[0]} 的備份請求: {safe_filename}")
                    threading.Thread(target=self._handle_transfer, args=(addr, save_path, safe_filename), daemon=True).start()
                    
            except socket.timeout:
                continue
            except OSError:
                if not self.running: break
            except Exception:
                pass

    def _handle_transfer(self, client_addr, save_path, safe_filename):
        transfer_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            transfer_sock.bind((self.current_bind_ip, 0))
        except Exception:
            transfer_sock.bind(('0.0.0.0', 0))
            
        # 關鍵修正：無視設備的所有選項，永遠只回覆最傳統的 ACK 0
        blksize = 512
        init_packet = struct.pack("!HH", 4, 0)

        try: 
            transfer_sock.sendto(init_packet, client_addr)
        except Exception as e: 
            print(f"    [TFTP Error] 發送初始回應失敗: {e}")
            transfer_sock.close()
            return
            
        expected_block = 1
        last_active = time.time()
        transfer_sock.settimeout(2.0)
        has_written_data = False # 用於追蹤是否有真正寫入資料
        
        try:
            with open(save_path, "wb") as f:
                while self.running:
                    if time.time() - last_active > 15:
                        print(f"    [TFTP Error] 傳輸超時中斷。")
                        break
                        
                    try:
                        packet, addr = transfer_sock.recvfrom(blksize + 128)
                        if addr[0] != client_addr[0]: continue  
                            
                        if len(packet) < 4: continue
                        op, block = struct.unpack("!HH", packet[:4])
                        
                        if op == 3:  # DATA 封包
                            if block == expected_block:
                                f.write(packet[4:])
                                has_written_data = True
                                transfer_sock.sendto(struct.pack("!HH", 4, block), client_addr)
                                expected_block += 1
                                last_active = time.time() 
                                
                                # EOF 判斷：資料長度小於 512 代表最後一包
                                if len(packet[4:]) < blksize:
                                    print(f"    [TFTP] 二進位檔案 [{safe_filename}] 傳輸完成！")
                                    self.completed_transfers.add(safe_filename) # 註冊成功
                                    break
                            elif block < expected_block:
                                transfer_sock.sendto(struct.pack("!HH", 4, block), client_addr)
                                
                        elif op == 5:  # ERROR 封包
                            error_msg = packet[4:].split(b'\x00')[0].decode('utf-8', errors='ignore')
                            print(f"    [TFTP Error] 設備端回報錯誤: {error_msg}")
                            break
                            
                    except ConnectionResetError:
                        break
                    except socket.timeout:
                        try:
                            transfer_sock.sendto(struct.pack("!HH", 4, expected_block - 1), client_addr)
                        except: pass
                        continue
        finally:
            transfer_sock.close()
            # 如果連 1 位元組都沒寫入就結束了，把 0KB 垃圾檔刪除
            if not has_written_data and os.path.exists(save_path):
                try: os.remove(save_path)
                except: pass

global_tftp = GlobalTFTPServer(CURRENT_BACKUP_DIR)

def clean_hostname(prompt):
    if not prompt: return "Unknown_Host"
    name = re.sub(r'^(telnet|ssh)@', '', prompt)
    if '@' in name and '[' in name: 
        name = name.split('@')[-1].split(']')[0]
    name = name.split('(')[0].split(' ')[0].split(':')[0]
    return name.replace('#', '').replace('>', '').replace('[', '').replace(']', '').replace('$', '').strip()

def clean_config_content(config_text, hostname):
    if not config_text: return ""
    cleaned = config_text.replace('\x1b[0K', '').replace('\x1b[K', '')
    lines = cleaned.splitlines()
    final_lines = []
    
    skip_keys = [
        "show running-config", "show run", "/export", "show config current_config", 
        "show config running", "show full-configuration", "set cli pager off", 
        "set cli config-output-format set", "set output standard", "disable clipaging",
        "Building configuration", "Current Configuration", "More:", "--More--", 
        "a All", "Next Page", "CTRL+C", "Quit:", "config system console", "Command:", "Invalid input"
    ]
    
    for line in lines:
        clean_line = line.strip()
        if not clean_line or any(key.lower() in clean_line.lower() for key in skip_keys):
            continue
        if len(clean_line) < 60 and (clean_line.endswith('#') or clean_line.endswith('>')):
            if hostname.lower() in clean_line.lower():
                continue
        final_lines.append(line)
    return "\n".join(final_lines).strip()

def run_backup(device_params):
    ip = device_params['host']
    d_type = device_params.get('device_type', 'generic').lower()
    is_old_dlink = False 
    
    for attempt in range(1, MAX_RETRIES + 1):
        net_connect = None
        try:
            print(f"\n[*] [{attempt}/{MAX_RETRIES}] 連線至: {ip} ({d_type})...")
            
            device_params['global_delay_factor'] = 4
            device_params['timeout'] = 30
            device_params['session_timeout'] = 60
            
            if 'fortinet' in d_type or 'dlink' in d_type:
                device_params['global_delay_factor'] = 6
                device_params['fast_cli'] = False

            try:
                net_connect = ConnectHandler(**device_params)
            except Exception as e:
                if 'dlink' in d_type and ('Pattern not detected' in str(e) or 'timeout' in str(e).lower()):
                    fallback_type = 'cisco_ios_telnet' if 'telnet' in device_params['device_type'] else 'cisco_ios'
                    device_params['device_type'] = fallback_type
                    net_connect = ConnectHandler(**device_params)
                    is_old_dlink = True 
                else:
                    raise e

            prompt = net_connect.find_prompt()
            hostname = clean_hostname(prompt)
            print(f"    [>] 主機識別: {hostname}")

            ext = ".cfg"
            if 'mikrotik' in d_type: ext = ".rsc"
            elif 'paloalto' in d_type: ext = ".set"
            elif 'fortinet' in d_type: ext = ".conf"
            elif 'dlink' in d_type: ext = ".bin" # D-Link 強制改為 .bin
            
            filename = f"{ip}_{hostname}_{datetime.datetime.now().strftime('%Y%m%d')}{ext}"
            filepath = os.path.join(CURRENT_BACKUP_DIR, filename)

            if 'fortinet' in d_type:
                net_connect.send_command("config system console", expect_string=r'[#>]')
                net_connect.send_command("set output standard", expect_string=r'[#>]')
                net_connect.send_command("end", expect_string=r'[#>]')
                cmd_list = ["show full-configuration"]
            elif 'dlink' in d_type:
                if is_old_dlink:
                    cmd_list = ["USE_TFTP_MODE_URL", "USE_TFTP_MODE_IP"]
                else:
                    net_connect.send_command("disable clipaging", expect_string=r'[#>]')
                    cmd_list = ["show config current_config", "show running-config", "USE_TFTP_MODE_URL", "USE_TFTP_MODE_IP"]
            elif 'paloalto' in d_type:
                net_connect.send_command("set cli pager off", expect_string=r'[#>]')
                net_connect.send_command("set cli config-output-format set", expect_string=r'[#>]')
                cmd_list = ["show config running"]
            elif 'mikrotik' in d_type:
                cmd_list = ["/export"]
            else:
                if ">" in prompt:
                    net_connect.enable()
                if 'cisco' in d_type:
                    net_connect.send_command("terminal length 0")
                cmd_list = ["show running-config"]

            config_data = ""
            tftp_success = False

            for cmd in cmd_list:
                if cmd.startswith("USE_TFTP_MODE"):
                    local_ip = None
                    try:
                        local_ip = net_connect.remote_conn.get_socket().getsockname()[0]
                    except:
                        try: local_ip = net_connect.remote_conn.transport.sock.getsockname()[0]
                        except: local_ip = get_local_ip_fallback(ip)
                            
                    global_tftp.current_bind_ip = local_ip
                    global_tftp.completed_transfers.discard(filename) # 確保清除舊快取
                    
                    if cmd == "USE_TFTP_MODE_URL":
                        tftp_cmd = f"upload cfg_toTFTP tftp://{local_ip}/{filename}"
                    elif cmd == "USE_TFTP_MODE_IP":
                        tftp_cmd = f"upload cfg_toTFTP {local_ip} {filename}"
                        
                    print(f"    [+] 寫入指令: {tftp_cmd}")
                    net_connect.write_channel(f"{tftp_cmd}\n")
                    
                    print("    [+] 等待二進位檔案完整傳輸 (上限 40 秒)...")
                    wait_time = 0
                    while wait_time < 40:
                        # 精準比對純檔名是否已由 TFTP Server 註冊成功
                        if filename in global_tftp.completed_transfers:
                            tftp_success = True
                            break
                            
                        try:
                            net_connect.read_channel() # 保持讀取避免連線閒置
                        except:
                            pass
                            
                        time.sleep(1)
                        wait_time += 1
                        
                    if tftp_success:
                        break 
                    else:
                        print(f"    [!] 指令超時或未回應，嘗試下一個指令...")
                    continue

                print(f"    [+] 嘗試指令: {cmd}")
                net_connect.write_channel(f"{cmd}\n")
                time.sleep(3)
                
                temp_data = ""
                idle_count = 0
                while idle_count < 12:
                    new_data = net_connect.read_channel()
                    if new_data:
                        temp_data += new_data
                        print(f"    [+] 接收文字中: {len(temp_data)} bytes", end="\r")
                        idle_count = 0
                        if any(x in new_data for x in ["Next Page", "a All", "Quit:"]):
                            net_connect.write_channel("a") 
                        elif any(x in new_data for x in ["More:", "--More--"]):
                            net_connect.write_channel(" ") 
                    else:
                        idle_count += 1
                        time.sleep(1)
                
                if "Invalid input" not in temp_data and "Unknown command" not in temp_data and "Incomplete command" not in temp_data and len(temp_data) > 500:
                    config_data = temp_data
                    break

            if tftp_success:
                print(f"\n[OK] {ip} 透過內建 TFTP 備份完成")
                return True

            final_config = clean_config_content(config_data, hostname)
            if len(final_config) < 300:
                raise ValueError("備份內容過短或所有指令皆失敗")

            # === 修正副檔名問題：若退回到文字備份，確保將 .bin 改回 .cfg ===
            if filepath.endswith('.bin'):
                filepath = filepath[:-4] + ".cfg"
            # =======================================================

            with open(filepath, "w", encoding="utf-8") as f:
                f.write(final_config)
            print(f"\n[OK] {ip} 文字備份成功")
            return True

        except Exception as e:
            print(f"\n[!] {ip} 失敗: {str(e)}")
            if attempt < MAX_RETRIES: time.sleep(3)
        finally:
            if net_connect:
                try: net_connect.disconnect()
                except: pass
    return False

def get_device_list():
    devices = []
    if not os.path.exists(CSV_FILE):
        return devices
    with open(CSV_FILE, mode='r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row and row.get('ip'):
                devices.append(row)
    return devices

def main():
    global_tftp.start()
    time.sleep(1)
    
    try:
        while True:
            print(f"\n{'='*30} 網路設備自動備份系統 {VERSION} {'='*30}")
            print("1) 選擇指定 IP 下載 (序號選單)")
            print("2) 依照 CSV 設定檔全部下載")
            print("3) 結束程式")
            choice = input("\n請輸入選項 (1-3): ").strip()

            if choice == '1':
                devices = get_device_list()
                if not devices:
                    print("[!] CSV 檔案不存在或無資料。")
                    continue
                
                header_fmt = "{:<5} {:<18} {:<30} {:<10}"
                print(f"\n" + header_fmt.format("序號", "IP 位址", "設備類型", "狀態"))
                print("-" * 70)
                
                for idx, dev in enumerate(devices, 1):
                    raw_ip = (dev.get('ip') or "").strip()
                    d_type = (dev.get('device_type') or "").strip()
                    status = "Skipped" if raw_ip.startswith('#') else "Active"
                    display_ip = raw_ip.lstrip('#')
                    print(header_fmt.format(idx, display_ip, d_type, status))
                
                try:
                    sub_choice = input(f"\n請輸入序號 (1-{len(devices)}) 進行備份，或輸入 0 回選單: ").strip()
                    if sub_choice == '0': continue
                    
                    selected_idx = int(sub_choice) - 1
                    if 0 <= selected_idx < len(devices):
                        target_dev = devices[selected_idx]
                        clean_ip = target_dev['ip'].lstrip('#').strip()
                        params = {
                            'device_type': (target_dev.get('device_type') or "").strip(),
                            'host': clean_ip,
                            'username': (target_dev.get('username') or "").strip(),
                            'password': (target_dev.get('password') or "").strip(),
                            'secret': (target_dev.get('secret') or "").strip(),
                        }
                        run_backup(params)
                    else:
                        print("[!] 序號超出範圍。")
                except ValueError:
                    print("[!] 請輸入數字序號。")

            elif choice == '2':
                devices = get_device_list()
                summary = {"success": 0, "fail": 0, "skipped": 0}
                failed_ips = []  
                
                start_time_ts = time.time()
                start_time_str = datetime.datetime.fromtimestamp(start_time_ts).strftime('%Y-%m-%d %H:%M:%S')
                
                for dev in devices:
                    raw_ip = dev['ip'].strip()
                    if raw_ip.startswith('#'):
                        summary["skipped"] += 1
                        continue
                    
                    params = {
                        'device_type': (dev.get('device_type') or "").strip(),
                        'host': raw_ip,
                        'username': (dev.get('username') or "").strip(),
                        'password': (dev.get('password') or "").strip(),
                        'secret': (dev.get('secret') or "").strip(),
                    }
                    if run_backup(params):
                        summary["success"] += 1
                    else:
                        summary["fail"] += 1
                        failed_ips.append(raw_ip)  
                
                end_time_ts = time.time()
                end_time_str = datetime.datetime.fromtimestamp(end_time_ts).strftime('%Y-%m-%d %H:%M:%S')
                
                elapsed_seconds = int(end_time_ts - start_time_ts)
                m, s = divmod(elapsed_seconds, 60)
                h, m = divmod(m, 60)
                if h > 0:
                    elapsed_str = f"{h}小時 {m}分 {s}秒"
                else:
                    elapsed_str = f"{m}分 {s}秒"
                
                print(f"\n" + "="*60)
                print(f"任務摘要 | 成功: {summary['success']} | 失敗: {summary['fail']} | 跳過: {summary['skipped']}")
                print(f"開始時間: {start_time_str}")
                print(f"結束時間: {end_time_str}")
                print(f"花費時間: {elapsed_str}")
                
                if failed_ips:
                    print("-" * 60)
                    print("[!] 以下設備備份失敗：")
                    for f_ip in failed_ips:
                        print(f"    - {f_ip}")
                        
                print("-" * 60)
                print(f"儲存目錄: {CURRENT_BACKUP_DIR}")
                print("="*60)

            elif choice == '3':
                print("程式結束。")
                break
            else:
                print("[!] 無效選項。")
    finally:
        global_tftp.stop()

if __name__ == "__main__":
    main()