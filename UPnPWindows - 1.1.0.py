import socket
import threading
import time
import xml.etree.ElementTree as ET
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse
from tkinter import *
from tkinter import ttk, messagebox
import urllib.request
import io
import re
import uuid

class UPnPDevice:
    def __init__(self, usn, location, st):
        self.usn = usn
        self.location = location
        self.st = st
        self.friendly_name = ""
        self.services = {}
        self.base_url = ""
        self.control_url = ""
        self.event_sub_url = ""
        self.scpd_url = ""
        self.icon_url = ""
        self.load_device_info()

    def load_device_info(self):
        try:
            with urllib.request.urlopen(self.location) as response:
                device_xml = response.read().decode('utf-8')
                root = ET.fromstring(device_xml)
                
                # 获取设备基本信息
                device_info = root.find('.//{urn:schemas-upnp-org:device-1-0}device')
                if device_info is not None:
                    friendly_name = device_info.find('{urn:schemas-upnp-org:device-1-0}friendlyName')
                    if friendly_name is not None:
                        self.friendly_name = friendly_name.text
                
                # 解析URL
                url_base = root.find('.//{urn:schemas-upnp-org:device-1-0}URLBase')
                if url_base is not None:
                    self.base_url = url_base.text
                else:
                    parsed = urlparse(self.location)
                    self.base_url = f"{parsed.scheme}://{parsed.netloc}"
                
                # 查找媒体渲染器服务
                service = root.find('.//{urn:schemas-upnp-org:device-1-0}service['
                                  '{urn:schemas-upnp-org:device-1-0}serviceType="urn:schemas-upnp-org:service:AVTransport:1"]')
                if service is not None:
                    scpd_url = service.find('{urn:schemas-upnp-org:device-1-0}SCPDURL')
                    control_url = service.find('{urn:schemas-upnp-org:device-1-0}controlURL')
                    event_sub_url = service.find('{urn:schemas-upnp-org:device-1-0}eventSubURL')
                    
                    if scpd_url is not None:
                        self.scpd_url = self.make_absolute_url(scpd_url.text)
                    if control_url is not None:
                        self.control_url = self.make_absolute_url(control_url.text)
                    if event_sub_url is not None:
                        self.event_sub_url = self.make_absolute_url(event_sub_url.text)
                
                # 查找图标
                icon = root.find('.//{urn:schemas-upnp-org:device-1-0}icon')
                if icon is not None:
                    icon_url = icon.find('{urn:schemas-upnp-org:device-1-0}url')
                    if icon_url is not None:
                        self.icon_url = self.make_absolute_url(icon_url.text)
        except Exception as e:
            print(f"加载设备信息错误: {e}")

    def make_absolute_url(self, url):
        if url.startswith('http'):
            return url
        return self.base_url.rstrip('/') + '/' + url.lstrip('/')

    def __str__(self):
        return f"{self.friendly_name} ({self.usn})"

class UPnPDiscovery:
    def __init__(self):
        self.devices = {}
        self.running = False
        self.socket = None

    def discover(self, timeout=3):
        self.devices = {}
        self.running = True
        
        # 设置多播套接字
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.socket.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        
        # 绑定到多播地址
        self.socket.bind(('', 1900))
        
        # 加入多播组
        mreq = socket.inet_aton("239.255.255.250") + socket.inet_aton("0.0.0.0")
        self.socket.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
        
        # 发送搜索请求
        search_msg = (
            "M-SEARCH * HTTP/1.1\r\n"
            "HOST: 239.255.255.250:1900\r\n"
            "MAN: \"ssdp:discover\"\r\n"
            "MX: 3\r\n"
            "ST: ssdp:all\r\n"
            "\r\n"
        )
        self.socket.sendto(search_msg.encode(), ("239.255.255.250", 1900))
        
        # 设置超时
        self.socket.settimeout(timeout)
        
        # 接收响应
        start_time = time.time()
        while self.running and (time.time() - start_time) < timeout:
            try:
                data, addr = self.socket.recvfrom(1024)
                self.process_response(data.decode('utf-8'))
            except socket.timeout:
                continue
        
        self.socket.close()
        return list(self.devices.values())

    def process_response(self, response):
        headers = {}
        for line in response.split('\r\n')[1:]:
            if ':' in line:
                key, value = line.split(':', 1)
                headers[key.strip().upper()] = value.strip()
        
        if 'LOCATION' in headers and 'USN' in headers and 'ST' in headers:
            usn = headers['USN']
            if usn not in self.devices:
                self.devices[usn] = UPnPDevice(usn, headers['LOCATION'], headers['ST'])

    def stop(self):
        self.running = False

class DLNAController:
    def __init__(self):
        self.uuid = str(uuid.uuid4())
        self.server = None
        self.server_thread = None

    def play_media(self, device, media_url, media_type="video/mp4"):
        # 设置AVTransport服务
        set_url_action = f"""
        <?xml version="1.0" encoding="utf-8"?>
        <s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">
            <s:Body>
                <u:SetAVTransportURI xmlns:u="urn:schemas-upnp-org:service:AVTransport:1">
                    <InstanceID>0</InstanceID>
                    <CurrentURI>{media_url}</CurrentURI>
                    <CurrentURIMetaData>
                        &lt;DIDL-Lite xmlns="urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:upnp="urn:schemas-upnp-org:metadata-1-0/upnp/"&gt;
                            &lt;item id="1" parentID="0" restricted="0"&gt;
                                &lt;dc:title&gt;Media&lt;/dc:title&gt;
                                &lt;dc:creator&gt;Unknown&lt;/dc:creator&gt;
                                &lt;upnp:class&gt;object.item.videoItem&lt;/upnp:class&gt;
                                &lt;res protocolInfo="http-get:*:{media_type}:*"&gt;{media_url}&lt;/res&gt;
                            &lt;/item&gt;
                        &lt;/DIDL-Lite&gt;
                    </CurrentURIMetaData>
                </u:SetAVTransportURI>
            </s:Body>
        </s:Envelope>
        """
        
        # 发送设置URL请求
        headers = {
            'Content-Type': 'text/xml; charset=utf-8',
            'SOAPAction': '"urn:schemas-upnp-org:service:AVTransport:1#SetAVTransportURI"'
        }
        
        try:
            req = urllib.request.Request(device.control_url, data=set_url_action.encode('utf-8'), headers=headers)
            with urllib.request.urlopen(req) as response:
                response.read()
        except Exception as e:
            print(f"设置AVTransportURI错误: {e}")
            return False
        
        # 发送播放请求
        play_action = """
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
        
        try:
            req = urllib.request.Request(device.control_url, data=play_action.encode('utf-8'), headers=headers)
            with urllib.request.urlopen(req) as response:
                response.read()
            return True
        except Exception as e:
            print(f"播放错误: {e}")
            return False

    def start_receiver_server(self, port=8000):
        class DLNAReceiverHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path == '/description.xml':
                    self.send_response(200)
                    self.send_header('Content-type', 'text/xml')
                    self.end_headers()
                    
                    uuid = self.server.controller.uuid
                    response = f"""
                    <root xmlns="urn:schemas-upnp-org:device-1-0">
                        <specVersion>
                            <major>1</major>
                            <minor>0</minor>
                        </specVersion>
                        <device>
                            <deviceType>urn:schemas-upnp-org:device:MediaRenderer:1</deviceType>
                            <friendlyName>Python DLNA Receiver</friendlyName>
                            <manufacturer>Python DLNA</manufacturer>
                            <manufacturerURL>https://python.org</manufacturerURL>
                            <modelDescription>Python DLNA Receiver</modelDescription>
                            <modelName>Python DLNA Receiver</modelName>
                            <modelNumber>1.0</modelNumber>
                            <modelURL>https://python.org</modelURL>
                            <serialNumber>123456789</serialNumber>
                            <UDN>uuid:{uuid}</UDN>
                            <serviceList>
                                <service>
                                    <serviceType>urn:schemas-upnp-org:service:AVTransport:1</serviceType>
                                    <serviceId>urn:upnp-org:serviceId:AVTransport</serviceId>
                                    <SCPDURL>/AVTransport/scpd.xml</SCPDURL>
                                    <controlURL>/AVTransport/control</controlURL>
                                    <eventSubURL>/AVTransport/event</eventSubURL>
                                </service>
                                <service>
                                    <serviceType>urn:schemas-upnp-org:service:ConnectionManager:1</serviceType>
                                    <serviceId>urn:upnp-org:serviceId:ConnectionManager</serviceId>
                                    <SCPDURL>/ConnectionManager/scpd.xml</SCPDURL>
                                    <controlURL>/ConnectionManager/control</controlURL>
                                    <eventSubURL>/ConnectionManager/event</eventSubURL>
                                </service>
                                <service>
                                    <serviceType>urn:schemas-upnp-org:service:RenderingControl:1</serviceType>
                                    <serviceId>urn:upnp-org:serviceId:RenderingControl</serviceId>
                                    <SCPDURL>/RenderingControl/scpd.xml</SCPDURL>
                                    <controlURL>/RenderingControl/control</controlURL>
                                    <eventSubURL>/RenderingControl/event</eventSubURL>
                                </service>
                            </serviceList>
                        </device>
                    </root>
                    """
                    self.wfile.write(response.encode('utf-8'))
                else:
                    self.send_response(404)
                    self.end_headers()

            def do_POST(self):
                content_length = int(self.headers['Content-Length'])
                post_data = self.rfile.read(content_length).decode('utf-8')
                
                # 这里应该解析SOAP请求并处理
                # 简化处理，只打印接收到的内容
                print(f"接收到投屏请求: {post_data}")
                
                self.send_response(200)
                self.send_header('Content-type', 'text/xml')
                self.end_headers()
                self.wfile.write(b"<s:Envelope xmlns:s=\"http://schemas.xmlsoap.org/soap/envelope/\"><s:Body></s:Body></s:Envelope>")

        self.server = HTTPServer(('0.0.0.0', port), DLNAReceiverHandler)
        self.server.controller = self
        
        def run_server():
            self.server.serve_forever()
        
        self.server_thread = threading.Thread(target=run_server)
        self.server_thread.daemon = True
        self.server_thread.start()

    def stop_receiver_server(self):
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            self.server = None

class DLNAApp:
    def __init__(self, root):
        self.root = root
        self.root.title("DLNA/UPnP投屏工具")
        self.root.geometry("800x600")
        
        self.controller = DLNAController()
        self.discovery = UPnPDiscovery()
        self.devices = []
        self.current_device = None
        
        self.create_widgets()
        
        # 启动设备发现
        self.refresh_devices()
        
        # 启动接收服务器
        self.controller.start_receiver_server()

    def create_widgets(self):
        # 设备列表框架
        device_frame = ttk.LabelFrame(self.root, text="可用的DLNA设备", padding=10)
        device_frame.pack(fill=BOTH, expand=True, padx=10, pady=5)
        
        # 设备列表
        self.device_tree = ttk.Treeview(device_frame, columns=('type'), show='headings')
        self.device_tree.heading('#0', text='设备名称')
        self.device_tree.heading('type', text='设备类型')
        self.device_tree.pack(fill=BOTH, expand=True)
        
        # 绑定选择事件
        self.device_tree.bind('<<TreeviewSelect>>', self.on_device_select)
        
        # 控制按钮框架
        button_frame = ttk.Frame(self.root)
        button_frame.pack(fill=X, padx=10, pady=5)
        
        # 刷新按钮
        refresh_btn = ttk.Button(button_frame, text="刷新设备列表", command=self.refresh_devices)
        refresh_btn.pack(side=LEFT, padx=5)
        
        # 投屏按钮
        self.cast_btn = ttk.Button(button_frame, text="投屏到选中设备", command=self.cast_to_device, state=DISABLED)
        self.cast_btn.pack(side=LEFT, padx=5)
        
        # 接收投屏框架
        receiver_frame = ttk.LabelFrame(self.root, text="接收投屏", padding=10)
        receiver_frame.pack(fill=BOTH, expand=True, padx=10, pady=5)
        
        # 接收状态
        self.receiver_status = ttk.Label(receiver_frame, text="接收服务器已启动，等待投屏...")
        self.receiver_status.pack(anchor=W)
        
        # 媒体URL输入
        url_frame = ttk.Frame(receiver_frame)
        url_frame.pack(fill=X, pady=5)
        
        ttk.Label(url_frame, text="媒体URL:").pack(side=LEFT)
        self.media_url = ttk.Entry(url_frame)
        self.media_url.pack(side=LEFT, fill=X, expand=True, padx=5)
        
        # 媒体类型选择
        type_frame = ttk.Frame(receiver_frame)
        type_frame.pack(fill=X, pady=5)
        
        ttk.Label(type_frame, text="媒体类型:").pack(side=LEFT)
        self.media_type = ttk.Combobox(type_frame, values=["video/mp4", "video/avi", "video/mkv", "audio/mp3", "audio/wav"])
        self.media_type.set("video/mp4")
        self.media_type.pack(side=LEFT, fill=X, expand=True, padx=5)

    def refresh_devices(self):
        self.device_tree.delete(*self.device_tree.get_children())
        self.devices = self.discovery.discover()
        
        for device in self.devices:
            self.device_tree.insert('', 'end', text=device.friendly_name, values=(device.st,))

    def on_device_select(self, event):
        selection = self.device_tree.selection()
        if selection:
            item = self.device_tree.item(selection[0])
            device_name = item['text']
            
            for device in self.devices:
                if device.friendly_name == device_name:
                    self.current_device = device
                    self.cast_btn['state'] = NORMAL
                    break

    def cast_to_device(self):
        if not self.current_device:
            messagebox.showerror("错误", "请先选择一个设备")
            return
        
        media_url = self.media_url.get()
        if not media_url:
            messagebox.showerror("错误", "请输入媒体URL")
            return
        
        media_type = self.media_type.get()
        
        success = self.controller.play_media(self.current_device, media_url, media_type)
        if success:
            messagebox.showinfo("成功", f"已开始投放到 {self.current_device.friendly_name}")
        else:
            messagebox.showerror("错误", "投屏失败，请检查设备和URL")

    def on_close(self):
        self.controller.stop_receiver_server()
        self.root.destroy()

if __name__ == "__main__":
    root = Tk()
    app = DLNAApp(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()