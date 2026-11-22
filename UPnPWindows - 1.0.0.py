import sys
import socket
import urllib.parse
import threading
import time
from xml.etree import ElementTree as ET
from http.server import BaseHTTPRequestHandler, HTTPServer
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QLabel, QListWidget, QPushButton, 
                             QTextEdit, QFileDialog, QMessageBox, QTabWidget)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QIcon
import requests

class UPnPDevice:
    def __init__(self, location, usn, st):
        self.location = location
        self.usn = usn
        self.st = st
        self.friendly_name = ""
        self.services = {}
        self.base_url = ""
        self.control_url = ""
        self.event_sub_url = ""
        self.scpd_url = ""
        self.device_type = ""
        self.load_device_info()

    def load_device_info(self):
        try:
            response = requests.get(self.location, timeout=3)
            root = ET.fromstring(response.content)
            
            # 获取设备基本信息
            device = root.find(".//{urn:schemas-upnp-org:device-1-0}device")
            if device is not None:
                friendly_name = device.find("{urn:schemas-upnp-org:device-1-0}friendlyName")
                if friendly_name is not None:
                    self.friendly_name = friendly_name.text
                
                device_type = device.find("{urn:schemas-upnp-org:device-1-0}deviceType")
                if device_type is not None:
                    self.device_type = device_type.text
                
                # 获取服务信息
                service_list = device.find("{urn:schemas-upnp-org:device-1-0}serviceList")
                if service_list is not None:
                    for service in service_list.findall("{urn:schemas-upnp-org:device-1-0}service"):
                        service_type = service.find("{urn:schemas-upnp-org:device-1-0}serviceType").text
                        control_url = service.find("{urn:schemas-upnp-org:device-1-0}controlURL").text
                        event_sub_url = service.find("{urn:schemas-upnp-org:device-1-0}eventSubURL").text
                        scpd_url = service.find("{urn:schemas-upnp-org:device-1-0}SCPDURL").text
                        
                        # 解析URL
                        parsed_location = urllib.parse.urlparse(self.location)
                        base_url = f"{parsed_location.scheme}://{parsed_location.netloc}"
                        
                        # 构建完整URL
                        control_url = urllib.parse.urljoin(base_url, control_url)
                        event_sub_url = urllib.parse.urljoin(base_url, event_sub_url)
                        scpd_url = urllib.parse.urljoin(base_url, scpd_url)
                        
                        self.services[service_type] = {
                            'controlURL': control_url,
                            'eventSubURL': event_sub_url,
                            'SCPDURL': scpd_url
                        }
                        
                        # 如果是AVTransport服务，记录下来
                        if "AVTransport" in service_type:
                            self.control_url = control_url
                            self.event_sub_url = event_sub_url
                            self.scpd_url = scpd_url
        except Exception as e:
            print(f"加载设备信息错误: {e}")

    def play_media(self, media_url, title="Media", mime_type="video/mp4"):
        """向设备发送播放媒体指令"""
        if not self.control_url:
            return False
        
        headers = {
            'Content-Type': 'text/xml; charset="utf-8"',
            'SOAPAction': '"urn:schemas-upnp-org:service:AVTransport:1#SetAVTransportURI"'
        }
        
        body = f"""
        <?xml version="1.0" encoding="utf-8"?>
        <s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">
            <s:Body>
                <u:SetAVTransportURI xmlns:u="urn:schemas-upnp-org:service:AVTransport:1">
                    <InstanceID>0</InstanceID>
                    <CurrentURI>{media_url}</CurrentURI>
                    <CurrentURIMetaData>
                        &lt;DIDL-Lite xmlns="urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:upnp="urn:schemas-upnp-org:metadata-1-0/upnp/"&gt;
                            &lt;item id="1" parentID="0" restricted="0"&gt;
                                &lt;dc:title&gt;{title}&lt;/dc:title&gt;
                                &lt;upnp:class&gt;object.item.videoItem&lt;/upnp:class&gt;
                                &lt;res protocolInfo="http-get:*:{mime_type}:*"&gt;{media_url}&lt;/res&gt;
                            &lt;/item&gt;
                        &lt;/DIDL-Lite&gt;
                    </CurrentURIMetaData>
                </u:SetAVTransportURI>
            </s:Body>
        </s:Envelope>
        """
        
        try:
            response = requests.post(self.control_url, data=body, headers=headers, timeout=3)
            if response.status_code == 200:
                # 发送播放命令
                play_body = """
                <?xml version="1.0" encoding="utf-8"?>
                <s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">
                    <s:Body>
                        <u:Play xmlns:u="urn:schemas-upnp-org:service:AVTransport:1">
                            <InstanceID>0</InstanceID>
                            <Speed>1</Speed>
                        </u:Play>
                    </s:Body>
                </s:Envelope>
                """
                play_response = requests.post(self.control_url, data=play_body, headers=headers, timeout=3)
                return play_response.status_code == 200
            return False
        except Exception as e:
            print(f"播放媒体错误: {e}")
            return False

class UPnPDiscoverer:
    def __init__(self):
        self.devices = []
        self.running = False
        self.socket = None

    def discover(self, search_target="ssdp:all", timeout=3):
        """发现UPnP设备"""
        self.devices = []
        self.running = True
        
        # 设置多播地址和端口
        multicast_group = "239.255.255.250"
        server_port = 1900
        
        # 创建UDP套接字
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.socket.settimeout(timeout)
        
        try:
            # 发送搜索请求
            search_msg = (
                f"M-SEARCH * HTTP/1.1\r\n"
                f"HOST: {multicast_group}:{server_port}\r\n"
                f"MAN: \"ssdp:discover\"\r\n"
                f"MX: {timeout}\r\n"
                f"ST: {search_target}\r\n"
                f"\r\n"
            ).encode('utf-8')
            
            self.socket.sendto(search_msg, (multicast_group, server_port))
            
            # 接收响应
            start_time = time.time()
            while self.running and (time.time() - start_time) < timeout:
                try:
                    data, addr = self.socket.recvfrom(4096)
                    response = data.decode('utf-8')
                    self.parse_response(response)
                except socket.timeout:
                    continue
        finally:
            self.socket.close()
            self.socket = None
        
        return self.devices

    def parse_response(self, response):
        """解析SSDP响应"""
        lines = response.split('\r\n')
        headers = {}
        
        for line in lines:
            if ':' in line:
                key, value = line.split(':', 1)
                headers[key.strip().upper()] = value.strip()
        
        if 'LOCATION' in headers and 'USN' in headers and 'ST' in headers:
            # 检查是否已经存在该设备
            existing = next((d for d in self.devices if d.usn == headers['USN']), None)
            if not existing:
                device = UPnPDevice(headers['LOCATION'], headers['USN'], headers['ST'])
                self.devices.append(device)

    def stop(self):
        """停止发现过程"""
        self.running = False
        if self.socket:
            self.socket.close()

class MediaReceiverHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        """处理GET请求"""
        if self.path == '/description.xml':
            self.send_response(200)
            self.send_header('Content-Type', 'text/xml')
            self.end_headers()
            
            # 返回设备描述文件
            description = """
            <root xmlns="urn:schemas-upnp-org:device-1-0">
                <specVersion>
                    <major>1</major>
                    <minor>0</minor>
                </specVersion>
                <device>
                    <deviceType>urn:schemas-upnp-org:device:MediaRenderer:1</deviceType>
                    <friendlyName>Python DLNA 接收器</friendlyName>
                    <manufacturer>Python DLNA</manufacturer>
                    <modelName>DLNA Receiver</modelName>
                    <UDN>uuid:PythonDLNAReceiver-1_0-123456789</UDN>
                    <serviceList>
                        <service>
                            <serviceType>urn:schemas-upnp-org:service:AVTransport:1</serviceType>
                            <serviceId>urn:upnp-org:serviceId:AVTransport</serviceId>
                            <controlURL>/upnp/control/AVTransport</controlURL>
                            <eventSubURL>/upnp/event/AVTransport</eventSubURL>
                            <SCPDURL>/AVTransport.xml</SCPDURL>
                        </service>
                        <service>
                            <serviceType>urn:schemas-upnp-org:service:ConnectionManager:1</serviceType>
                            <serviceId>urn:upnp-org:serviceId:ConnectionManager</serviceId>
                            <controlURL>/upnp/control/ConnectionManager</controlURL>
                            <eventSubURL>/upnp/event/ConnectionManager</eventSubURL>
                            <SCPDURL>/ConnectionManager.xml</SCPDURL>
                        </service>
                        <service>
                            <serviceType>urn:schemas-upnp-org:service:RenderingControl:1</serviceType>
                            <serviceId>urn:upnp-org:serviceId:RenderingControl</serviceId>
                            <controlURL>/upnp/control/RenderingControl</controlURL>
                            <eventSubURL>/upnp/event/RenderingControl</eventSubURL>
                            <SCPDURL>/RenderingControl.xml</SCPDURL>
                        </service>
                    </serviceList>
                </device>
            </root>
            """
            self.wfile.write(description.encode('utf-8'))
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        """处理POST请求（控制命令）"""
        content_length = int(self.headers['Content-Length'])
        post_data = self.rfile.read(content_length)
        
        # 解析SOAP请求
        try:
            root = ET.fromstring(post_data)
            action = root.find(".//{http://schemas.xmlsoap.org/soap/envelope/}Body").getchildren()[0]
            action_name = action.tag.split('}')[-1]
            
            self.send_response(200)
            self.send_header('Content-Type', 'text/xml; charset="utf-8"')
            self.end_headers()
            
            # 构造响应
            response = f"""
            <s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">
                <s:Body>
                    <u:{action_name}Response xmlns:u="urn:schemas-upnp-org:service:AVTransport:1">
                        <InstanceID>0</InstanceID>
                    </u:{action_name}Response>
                </s:Body>
            </s:Envelope>
            """
            self.wfile.write(response.encode('utf-8'))
            
            # 如果是设置媒体URI的命令，记录下来
            if action_name == "SetAVTransportURI":
                current_uri = action.find(".//CurrentURI").text
                print(f"收到投屏请求: {current_uri}")
                # 这里可以添加处理媒体URL的逻辑
                
        except Exception as e:
            print(f"处理POST请求错误: {e}")
            self.send_response(500)
            self.end_headers()

class DLNAApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("DLNA/UPnP投屏工具")
        self.setGeometry(100, 100, 800, 600)
        
        # 初始化变量
        self.discoverer = UPnPDiscoverer()
        self.receiver_server = None
        self.receiver_thread = None
        
        # 创建主界面
        self.init_ui()
        
        # 启动设备发现
        self.discover_devices()
        
    def init_ui(self):
        """初始化用户界面"""
        # 创建主窗口部件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # 主布局
        main_layout = QVBoxLayout(central_widget)
        
        # 标签页
        tab_widget = QTabWidget()
        main_layout.addWidget(tab_widget)
        
        # 投屏标签页
        cast_tab = QWidget()
        tab_widget.addTab(cast_tab, "投屏")
        
        # 接收标签页
        receive_tab = QWidget()
        tab_widget.addTab(receive_tab, "接收")
        
        # 设置标签页
        settings_tab = QWidget()
        tab_widget.addTab(settings_tab, "设置")
        
        # 初始化各个标签页
        self.init_cast_tab(cast_tab)
        self.init_receive_tab(receive_tab)
        self.init_settings_tab(settings_tab)
        
        # 状态栏
        self.statusBar().showMessage("就绪")
    
    def init_cast_tab(self, tab):
        """初始化投屏标签页"""
        layout = QVBoxLayout(tab)
        
        # 设备列表
        self.device_list = QListWidget()
        layout.addWidget(QLabel("可用的DLNA设备:"))
        layout.addWidget(self.device_list)
        
        # 刷新按钮
        refresh_btn = QPushButton("刷新设备列表")
        refresh_btn.clicked.connect(self.discover_devices)
        layout.addWidget(refresh_btn)
        
        # 媒体选择
        media_layout = QHBoxLayout()
        media_layout.addWidget(QLabel("媒体文件或URL:"))
        
        self.media_path = QTextEdit()
        self.media_path.setMaximumHeight(60)
        media_layout.addWidget(self.media_path, 1)
        
        browse_btn = QPushButton("浏览...")
        browse_btn.clicked.connect(self.browse_media)
        media_layout.addWidget(browse_btn)
        
        layout.addLayout(media_layout)
        
        # 投屏按钮
        cast_btn = QPushButton("开始投屏")
        cast_btn.clicked.connect(self.start_casting)
        layout.addWidget(cast_btn)
        
        # 日志区域
        layout.addWidget(QLabel("操作日志:"))
        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        layout.addWidget(self.log_area, 1)
    
    def init_receive_tab(self, tab):
        """初始化接收标签页"""
        layout = QVBoxLayout(tab)
        
        # 接收服务器状态
        self.receiver_status = QLabel("接收服务未运行")
        layout.addWidget(self.receiver_status)
        
        # 启动/停止按钮
        self.receiver_btn = QPushButton("启动接收服务")
        self.receiver_btn.clicked.connect(self.toggle_receiver)
        layout.addWidget(self.receiver_btn)
        
        # 接收到的媒体
        layout.addWidget(QLabel("接收到的媒体:"))
        self.received_media = QListWidget()
        layout.addWidget(self.received_media, 1)
        
        # 播放按钮
        play_btn = QPushButton("播放选中媒体")
        play_btn.clicked.connect(self.play_received_media)
        layout.addWidget(play_btn)
    
    def init_settings_tab(self, tab):
        """初始化设置标签页"""
        layout = QVBoxLayout(tab)
        
        # 网络设置
        layout.addWidget(QLabel("网络设置:"))
        
        # 发现超时
        timeout_layout = QHBoxLayout()
        timeout_layout.addWidget(QLabel("设备发现超时(秒):"))
        
        self.timeout_input = QTextEdit()
        self.timeout_input.setMaximumHeight(30)
        self.timeout_input.setText("3")
        timeout_layout.addWidget(self.timeout_input)
        
        layout.addLayout(timeout_layout)
        
        # 接收端口
        port_layout = QHBoxLayout()
        port_layout.addWidget(QLabel("接收服务端口:"))
        
        self.port_input = QTextEdit()
        self.port_input.setMaximumHeight(30)
        self.port_input.setText("8000")
        port_layout.addWidget(self.port_input)
        
        layout.addLayout(port_layout)
        
        # 保存按钮
        save_btn = QPushButton("保存设置")
        save_btn.clicked.connect(self.save_settings)
        layout.addWidget(save_btn)
        
        # 关于信息
        layout.addStretch()
        layout.addWidget(QLabel("DLNA/UPnP投屏工具 v1.0"))
        layout.addWidget(QLabel("作者: Python DLNA项目"))
    
    def discover_devices(self):
        """发现DLNA设备"""
        self.device_list.clear()
        self.log("正在搜索DLNA设备...")
        
        # 在后台执行设备发现
        def discover_thread():
            devices = self.discoverer.discover(timeout=int(self.timeout_input.toPlainText()))
            
            # 更新UI
            self.device_list.clear()
            for device in devices:
                self.device_list.addItem(f"{device.friendly_name} ({device.device_type})")
            
            self.log(f"发现 {len(devices)} 个DLNA设备")
        
        threading.Thread(target=discover_thread, daemon=True).start()
    
    def browse_media(self):
        """浏览选择媒体文件"""
        file_dialog = QFileDialog()
        file_path, _ = file_dialog.getOpenFileName(self, "选择媒体文件", "", 
                                                  "媒体文件 (*.mp4 *.avi *.mkv *.mp3);;所有文件 (*.*)")
        
        if file_path:
            self.media_path.setText(file_path)
    
    def start_casting(self):
        """开始投屏"""
        if self.device_list.currentRow() == -1:
            QMessageBox.warning(self, "警告", "请先选择一个DLNA设备")
            return
        
        media_url = self.media_path.toPlainText()
        if not media_url:
            QMessageBox.warning(self, "警告", "请输入媒体文件路径或URL")
            return
        
        # 获取选中的设备
        selected_device = self.discoverer.devices[self.device_list.currentRow()]
        
        # 如果是本地文件，需要启动HTTP服务器提供文件
        if not media_url.startswith(('http://', 'https://')):
            # 这里简化处理，实际应用中应该启动一个简单的HTTP服务器
            QMessageBox.information(self, "提示", "本地文件投屏需要额外的HTTP服务器支持，此功能将在未来版本中实现")
            return
        
        # 在后台执行投屏
        def cast_thread():
            self.log(f"正在向 {selected_device.friendly_name} 投屏: {media_url}")
            success = selected_device.play_media(media_url, "投屏媒体")
            
            if success:
                self.log("投屏成功")
            else:
                self.log("投屏失败")
        
        threading.Thread(target=cast_thread, daemon=True).start()
    
    def toggle_receiver(self):
        """切换接收服务状态"""
        if self.receiver_server is None:
            # 启动接收服务
            port = int(self.port_input.toPlainText())
            
            try:
                self.receiver_server = HTTPServer(('0.0.0.0', port), MediaReceiverHandler)
                self.receiver_thread = threading.Thread(target=self.receiver_server.serve_forever, daemon=True)
                self.receiver_thread.start()
                
                self.receiver_status.setText(f"接收服务运行在端口 {port}")
                self.receiver_btn.setText("停止接收服务")
                self.log(f"DLNA接收服务已启动，端口: {port}")
                
                # 在网络上宣告我们的接收服务
                self.advertise_receiver(port)
            except Exception as e:
                QMessageBox.critical(self, "错误", f"无法启动接收服务: {str(e)}")
                self.receiver_server = None
        else:
            # 停止接收服务
            self.receiver_server.shutdown()
            self.receiver_server.server_close()
            self.receiver_server = None
            self.receiver_thread.join()
            self.receiver_thread = None
            
            self.receiver_status.setText("接收服务未运行")
            self.receiver_btn.setText("启动接收服务")
            self.log("DLNA接收服务已停止")
    
    def advertise_receiver(self, port):
        """在网络上宣告我们的接收服务"""
        def advertise():
            # 设置多播地址和端口
            multicast_group = "239.255.255.250"
            server_port = 1900
            
            # 创建UDP套接字
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            
            # 发送宣告消息
            notify_msg = (
                "NOTIFY * HTTP/1.1\r\n"
                "HOST: 239.255.255.250:1900\r\n"
                "CACHE-CONTROL: max-age=1800\r\n"
                "LOCATION: http://{}:{}/description.xml\r\n"
                "NT: urn:schemas-upnp-org:device:MediaRenderer:1\r\n"
                "NTS: ssdp:alive\r\n"
                "SERVER: Python DLNA Receiver/1.0\r\n"
                "USN: uuid:PythonDLNAReceiver-1_0-123456789::urn:schemas-upnp-org:device:MediaRenderer:1\r\n"
                "\r\n"
            ).format(socket.gethostbyname(socket.gethostname()), port).encode('utf-8')
            
            while self.receiver_server is not None:
                sock.sendto(notify_msg, (multicast_group, server_port))
                time.sleep(30)  # 每30秒发送一次
            
            sock.close()
        
        threading.Thread(target=advertise, daemon=True).start()
    
    def play_received_media(self):
        """播放接收到的媒体"""
        if self.received_media.currentRow() == -1:
            QMessageBox.warning(self, "警告", "请先选择要播放的媒体")
            return
        
        # 这里应该实现媒体播放逻辑
        QMessageBox.information(self, "提示", "媒体播放功能将在未来版本中实现")
    
    def save_settings(self):
        """保存设置"""
        try:
            timeout = int(self.timeout_input.toPlainText())
            port = int(self.port_input.toPlainText())
            
            if timeout < 1 or timeout > 10:
                raise ValueError("超时时间应在1-10秒之间")
            if port < 1024 or port > 65535:
                raise ValueError("端口号应在1024-65535之间")
            
            self.log("设置已保存")
            QMessageBox.information(self, "成功", "设置已保存")
        except ValueError as e:
            QMessageBox.warning(self, "错误", str(e))
    
    def log(self, message):
        """记录日志"""
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        self.log_area.append(f"[{timestamp}] {message}")
        self.log_area.verticalScrollBar().setValue(self.log_area.verticalScrollBar().maximum())
    
    def closeEvent(self, event):
        """关闭窗口事件"""
        if self.receiver_server is not None:
            self.receiver_server.shutdown()
            self.receiver_server.server_close()
            self.receiver_thread.join()
        
        self.discoverer.stop()
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon(":/icons/app_icon.png"))  # 如果有图标资源的话
    
    # 设置中文样式
    app.setStyle("Fusion")
    
    window = DLNAApp()
    window.show()
    
    sys.exit(app.exec_())