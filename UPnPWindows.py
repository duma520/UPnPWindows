import sys
import socket
import urllib.parse
import threading
import time
import os
import mimetypes
from xml.etree import ElementTree as ET
from http.server import BaseHTTPRequestHandler, HTTPServer, SimpleHTTPRequestHandler
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QLabel, QListWidget, QPushButton, 
                             QTextEdit, QFileDialog, QMessageBox, QTabWidget,
                             QSlider, QGroupBox, QComboBox, QCheckBox)
from PyQt5.QtCore import Qt, QTimer, QUrl, QDir
from PyQt5.QtGui import QIcon, QDesktopServices
from PyQt5.QtMultimedia import QMediaPlayer, QMediaContent
from PyQt5.QtMultimediaWidgets import QVideoWidget
import requests
import uuid
import ipaddress
import netifaces

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
        self.udn = ""
        self.icon_url = ""
        self.model_name = ""
        self.manufacturer = ""
        self.load_device_info()

    def load_device_info(self):
        try:
            response = requests.get(self.location, timeout=3)
            root = ET.fromstring(response.content)
            
            device = root.find(".//{urn:schemas-upnp-org:device-1-0}device")
            if device is not None:
                self.friendly_name = device.findtext("{urn:schemas-upnp-org:device-1-0}friendlyName", "")
                self.device_type = device.findtext("{urn:schemas-upnp-org:device-1-0}deviceType", "")
                self.udn = device.findtext("{urn:schemas-upnp-org:device-1-0}UDN", "")
                self.model_name = device.findtext("{urn:schemas-upnp-org:device-1-0}modelName", "")
                self.manufacturer = device.findtext("{urn:schemas-upnp-org:device-1-0}manufacturer", "")
                
                # 获取图标
                icon_list = device.find("{urn:schemas-upnp-org:device-1-0}iconList")
                if icon_list is not None:
                    icon = icon_list.find("{urn:schemas-upnp-org:device-1-0}icon")
                    if icon is not None:
                        icon_url = icon.findtext("{urn:schemas-upnp-org:device-1-0}url", "")
                        parsed_location = urllib.parse.urlparse(self.location)
                        base_url = f"{parsed_location.scheme}://{parsed_location.netloc}"
                        self.icon_url = urllib.parse.urljoin(base_url, icon_url)
                
                # 获取服务
                service_list = device.find("{urn:schemas-upnp-org:device-1-0}serviceList")
                if service_list is not None:
                    for service in service_list.findall("{urn:schemas-upnp-org:device-1-0}service"):
                        service_type = service.findtext("{urn:schemas-upnp-org:device-1-0}serviceType", "")
                        control_url = service.findtext("{urn:schemas-upnp-org:device-1-0}controlURL", "")
                        event_sub_url = service.findtext("{urn:schemas-upnp-org:device-1-0}eventSubURL", "")
                        scpd_url = service.findtext("{urn:schemas-upnp-org:device-1-0}SCPDURL", "")
                        
                        parsed_location = urllib.parse.urlparse(self.location)
                        base_url = f"{parsed_location.scheme}://{parsed_location.netloc}"
                        
                        control_url = urllib.parse.urljoin(base_url, control_url)
                        event_sub_url = urllib.parse.urljoin(base_url, event_sub_url)
                        scpd_url = urllib.parse.urljoin(base_url, scpd_url)
                        
                        self.services[service_type] = {
                            'controlURL': control_url,
                            'eventSubURL': event_sub_url,
                            'SCPDURL': scpd_url
                        }
                        
                        if "AVTransport" in service_type:
                            self.control_url = control_url
                            self.event_sub_url = event_sub_url
                            self.scpd_url = scpd_url
        except Exception as e:
            print(f"加载设备信息错误: {e}")

    def send_soap_request(self, service_type, action, params):
        """发送SOAP请求"""
        if service_type not in self.services:
            return None
            
        headers = {
            'Content-Type': 'text/xml; charset="utf-8"',
            'SOAPAction': f'"{service_type}#{action}"'
        }
        
        param_elements = ""
        for key, value in params.items():
            param_elements += f"<{key}>{value}</{key}>"
        
        body = f"""
        <?xml version="1.0" encoding="utf-8"?>
        <s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" 
                    s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">
            <s:Body>
                <u:{action} xmlns:u="{service_type}">
                    {param_elements}
                </u:{action}>
            </s:Body>
        </s:Envelope>
        """
        
        try:
            response = requests.post(self.services[service_type]['controlURL'], 
                                  data=body, headers=headers, timeout=3)
            if response.status_code == 200:
                return ET.fromstring(response.content)
            return None
        except Exception as e:
            print(f"SOAP请求错误: {e}")
            return None

    def play_media(self, media_url, title="Media", mime_type="video/mp4"):
        """播放媒体"""
        if not self.control_url:
            return False
        
        # 设置媒体URI
        set_uri_params = {
            "InstanceID": "0",
            "CurrentURI": media_url,
            "CurrentURIMetaData": f"""
            &lt;DIDL-Lite xmlns="urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/" 
                        xmlns:dc="http://purl.org/dc/elements/1.1/" 
                        xmlns:upnp="urn:schemas-upnp-org:metadata-1-0/upnp/"&gt;
                &lt;item id="1" parentID="0" restricted="0"&gt;
                    &lt;dc:title&gt;{title}&lt;/dc:title&gt;
                    &lt;upnp:class&gt;object.item.videoItem&lt;/upnp:class&gt;
                    &lt;res protocolInfo="http-get:*:{mime_type}:*"&gt;{media_url}&lt;/res&gt;
                &lt;/item&gt;
            &lt;/DIDL-Lite&gt;
            """
        }
        
        avt_service = next((k for k in self.services.keys() if "AVTransport" in k), None)
        if not avt_service:
            return False
            
        result = self.send_soap_request(avt_service, "SetAVTransportURI", set_uri_params)
        if not result:
            return False
        
        # 播放
        play_params = {
            "InstanceID": "0",
            "Speed": "1"
        }
        return self.send_soap_request(avt_service, "Play", play_params) is not None

    def get_media_info(self):
        """获取媒体信息"""
        avt_service = next((k for k in self.services.keys() if "AVTransport" in k), None)
        if not avt_service:
            return None
            
        params = {"InstanceID": "0"}
        result = self.send_soap_request(avt_service, "GetMediaInfo", params)
        if not result:
            return None
            
        return {
            "CurrentURI": result.findtext(".//CurrentURI", ""),
            "MediaDuration": result.findtext(".//MediaDuration", ""),
            "CurrentURIMetaData": result.findtext(".//CurrentURIMetaData", "")
        }

    def get_transport_info(self):
        """获取传输状态"""
        avt_service = next((k for k in self.services.keys() if "AVTransport" in k), None)
        if not avt_service:
            return None
            
        params = {"InstanceID": "0"}
        result = self.send_soap_request(avt_service, "GetTransportInfo", params)
        if not result:
            return None
            
        return {
            "CurrentTransportState": result.findtext(".//CurrentTransportState", ""),
            "CurrentTransportStatus": result.findtext(".//CurrentTransportStatus", ""),
            "CurrentSpeed": result.findtext(".//CurrentSpeed", "")
        }

    def get_position_info(self):
        """获取播放位置信息"""
        avt_service = next((k for k in self.services.keys() if "AVTransport" in k), None)
        if not avt_service:
            return None
            
        params = {"InstanceID": "0"}
        result = self.send_soap_request(avt_service, "GetPositionInfo", params)
        if not result:
            return None
            
        return {
            "Track": result.findtext(".//Track", ""),
            "TrackDuration": result.findtext(".//TrackDuration", ""),
            "TrackMetaData": result.findtext(".//TrackMetaData", ""),
            "TrackURI": result.findtext(".//TrackURI", ""),
            "RelTime": result.findtext(".//RelTime", ""),
            "AbsTime": result.findtext(".//AbsTime", ""),
            "RelCount": result.findtext(".//RelCount", ""),
            "AbsCount": result.findtext(".//AbsCount", "")
        }

    def control_media(self, action):
        """控制媒体播放"""
        avt_service = next((k for k in self.services.keys() if "AVTransport" in k), None)
        if not avt_service:
            return False
            
        params = {"InstanceID": "0"}
        
        if action == "pause":
            return self.send_soap_request(avt_service, "Pause", params) is not None
        elif action == "stop":
            return self.send_soap_request(avt_service, "Stop", params) is not None
        elif action == "play":
            params["Speed"] = "1"
            return self.send_soap_request(avt_service, "Play", params) is not None
        elif action == "seek":
            # 需要额外参数
            return False
        else:
            return False

    def set_volume(self, volume):
        """设置音量"""
        rcs_service = next((k for k in self.services.keys() if "RenderingControl" in k), None)
        if not rcs_service:
            return False
            
        params = {
            "InstanceID": "0",
            "Channel": "Master",
            "DesiredVolume": str(volume)
        }
        return self.send_soap_request(rcs_service, "SetVolume", params) is not None

    def get_volume(self):
        """获取音量"""
        rcs_service = next((k for k in self.services.keys() if "RenderingControl" in k), None)
        if not rcs_service:
            return None
            
        params = {
            "InstanceID": "0",
            "Channel": "Master"
        }
        result = self.send_soap_request(rcs_service, "GetVolume", params)
        if not result:
            return None
            
        return result.findtext(".//CurrentVolume", "")

class UPnPDiscoverer:
    def __init__(self):
        self.devices = []
        self.running = False
        self.socket = None
        self.search_targets = [
            "urn:schemas-upnp-org:device:MediaRenderer:1",
            "urn:schemas-upnp-org:service:AVTransport:1",
            "urn:schemas-upnp-org:service:RenderingControl:1",
            "ssdp:all"
        ]

    def discover(self, timeout=3):
        """发现UPnP设备"""
        self.devices = []
        self.running = True
        
        multicast_group = "239.255.255.250"
        server_port = 1900
        
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.socket.settimeout(timeout)
        
        try:
            for target in self.search_targets:
                search_msg = (
                    f"M-SEARCH * HTTP/1.1\r\n"
                    f"HOST: {multicast_group}:{server_port}\r\n"
                    f"MAN: \"ssdp:discover\"\r\n"
                    f"MX: {timeout}\r\n"
                    f"ST: {target}\r\n"
                    f"\r\n"
                ).encode('utf-8')
                
                self.socket.sendto(search_msg, (multicast_group, server_port))
            
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
        
        # 去重
        unique_devices = {}
        for device in self.devices:
            unique_devices[device.usn] = device
        self.devices = list(unique_devices.values())
        
        return self.devices

    def parse_response(self, response):
        """解析SSDP响应"""
        lines = response.split('\r\n')
        headers = {}
        
        for line in lines:
            if ':' in line:
                key, value = line.split(':', 1)
                headers[key.strip().upper()] = value.strip()
        
        if 'LOCATION' in headers and 'USN' in headers and ('ST' in headers or 'NT' in headers):
            st = headers.get('ST', headers.get('NT', ''))
            existing = next((d for d in self.devices if d.usn == headers['USN']), None)
            if not existing:
                device = UPnPDevice(headers['LOCATION'], headers['USN'], st)
                self.devices.append(device)

    def stop(self):
        """停止发现过程"""
        self.running = False
        if self.socket:
            self.socket.close()

class MediaFileServer(HTTPServer):
    """用于提供本地媒体文件的HTTP服务器"""
    def __init__(self, base_path, port=0, handler_class=SimpleHTTPRequestHandler):
        self.base_path = base_path
        self.port = port
        super().__init__(("0.0.0.0", port), handler_class)
        
    def serve_forever(self, poll_interval=0.5):
        os.chdir(self.base_path)
        print(f"文件服务器运行在 http://{self.server_name}:{self.server_port}")
        super().serve_forever(poll_interval)

class MediaReceiverHandler(BaseHTTPRequestHandler):
    """DLNA接收器HTTP处理器"""
    def __init__(self, request, client_address, server):
        self.media_player = server.media_player
        self.received_media = server.received_media
        super().__init__(request, client_address, server)
    
    def do_GET(self):
        if self.path == '/description.xml':
            self.send_response(200)
            self.send_header('Content-Type', 'text/xml')
            self.end_headers()
            
            local_ip = self.server.server_address[0]
            port = self.server.server_address[1]
            
            description = f"""
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
                    <UDN>uuid:{self.server.uuid}</UDN>
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
        elif self.path == '/AVTransport.xml':
            self.send_response(200)
            self.send_header('Content-Type', 'text/xml')
            self.end_headers()
            self.wfile.write(self.generate_scpd("AVTransport").encode('utf-8'))
        elif self.path == '/ConnectionManager.xml':
            self.send_response(200)
            self.send_header('Content-Type', 'text/xml')
            self.end_headers()
            self.wfile.write(self.generate_scpd("ConnectionManager").encode('utf-8'))
        elif self.path == '/RenderingControl.xml':
            self.send_response(200)
            self.send_header('Content-Type', 'text/xml')
            self.end_headers()
            self.wfile.write(self.generate_scpd("RenderingControl").encode('utf-8'))
        else:
            self.send_response(404)
            self.end_headers()

    def generate_scpd(self, service_type):
        """生成服务描述文档"""
        if service_type == "AVTransport":
            return """
            <scpd xmlns="urn:schemas-upnp-org:service-1-0">
                <specVersion>
                    <major>1</major>
                    <minor>0</minor>
                </specVersion>
                <actionList>
                    <action>
                        <name>SetAVTransportURI</name>
                        <argumentList>
                            <argument>
                                <name>InstanceID</name>
                                <direction>in</direction>
                                <relatedStateVariable>A_ARG_TYPE_InstanceID</relatedStateVariable>
                            </argument>
                            <argument>
                                <name>CurrentURI</name>
                                <direction>in</direction>
                                <relatedStateVariable>AVTransportURI</relatedStateVariable>
                            </argument>
                            <argument>
                                <name>CurrentURIMetaData</name>
                                <direction>in</direction>
                                <relatedStateVariable>AVTransportURIMetaData</relatedStateVariable>
                            </argument>
                        </argumentList>
                    </action>
                    <action>
                        <name>Play</name>
                        <argumentList>
                            <argument>
                                <name>InstanceID</name>
                                <direction>in</direction>
                                <relatedStateVariable>A_ARG_TYPE_InstanceID</relatedStateVariable>
                            </argument>
                            <argument>
                                <name>Speed</name>
                                <direction>in</direction>
                                <relatedStateVariable>TransportPlaySpeed</relatedStateVariable>
                            </argument>
                        </argumentList>
                    </action>
                    <action>
                        <name>Pause</name>
                        <argumentList>
                            <argument>
                                <name>InstanceID</name>
                                <direction>in</direction>
                                <relatedStateVariable>A_ARG_TYPE_InstanceID</relatedStateVariable>
                            </argument>
                        </argumentList>
                    </action>
                    <action>
                        <name>Stop</name>
                        <argumentList>
                            <argument>
                                <name>InstanceID</name>
                                <direction>in</direction>
                                <relatedStateVariable>A_ARG_TYPE_InstanceID</relatedStateVariable>
                            </argument>
                        </argumentList>
                    </action>
                    <action>
                        <name>GetMediaInfo</name>
                        <argumentList>
                            <argument>
                                <name>InstanceID</name>
                                <direction>in</direction>
                                <relatedStateVariable>A_ARG_TYPE_InstanceID</relatedStateVariable>
                            </argument>
                            <argument>
                                <name>NrTracks</name>
                                <direction>out</direction>
                                <relatedStateVariable>NumberOfTracks</relatedStateVariable>
                            </argument>
                            <argument>
                                <name>MediaDuration</name>
                                <direction>out</direction>
                                <relatedStateVariable>CurrentMediaDuration</relatedStateVariable>
                            </argument>
                            <argument>
                                <name>CurrentURI</name>
                                <direction>out</direction>
                                <relatedStateVariable>AVTransportURI</relatedStateVariable>
                            </argument>
                            <argument>
                                <name>CurrentURIMetaData</name>
                                <direction>out</direction>
                                <relatedStateVariable>AVTransportURIMetaData</relatedStateVariable>
                            </argument>
                        </argumentList>
                    </action>
                    <action>
                        <name>GetTransportInfo</name>
                        <argumentList>
                            <argument>
                                <name>InstanceID</name>
                                <direction>in</direction>
                                <relatedStateVariable>A_ARG_TYPE_InstanceID</relatedStateVariable>
                            </argument>
                            <argument>
                                <name>CurrentTransportState</name>
                                <direction>out</direction>
                                <relatedStateVariable>TransportState</relatedStateVariable>
                            </argument>
                            <argument>
                                <name>CurrentTransportStatus</name>
                                <direction>out</direction>
                                <relatedStateVariable>TransportStatus</relatedStateVariable>
                            </argument>
                            <argument>
                                <name>CurrentSpeed</name>
                                <direction>out</direction>
                                <relatedStateVariable>TransportPlaySpeed</relatedStateVariable>
                            </argument>
                        </argumentList>
                    </action>
                    <action>
                        <name>GetPositionInfo</name>
                        <argumentList>
                            <argument>
                                <name>InstanceID</name>
                                <direction>in</direction>
                                <relatedStateVariable>A_ARG_TYPE_InstanceID</relatedStateVariable>
                            </argument>
                            <argument>
                                <name>Track</name>
                                <direction>out</direction>
                                <relatedStateVariable>CurrentTrack</relatedStateVariable>
                            </argument>
                            <argument>
                                <name>TrackDuration</name>
                                <direction>out</direction>
                                <relatedStateVariable>CurrentTrackDuration</relatedStateVariable>
                            </argument>
                            <argument>
                                <name>TrackMetaData</name>
                                <direction>out</direction>
                                <relatedStateVariable>CurrentTrackMetaData</relatedStateVariable>
                            </argument>
                            <argument>
                                <name>TrackURI</name>
                                <direction>out</direction>
                                <relatedStateVariable>CurrentTrackURI</relatedStateVariable>
                            </argument>
                            <argument>
                                <name>RelTime</name>
                                <direction>out</direction>
                                <relatedStateVariable>RelativeTimePosition</relatedStateVariable>
                            </argument>
                            <argument>
                                <name>AbsTime</name>
                                <direction>out</direction>
                                <relatedStateVariable>AbsoluteTimePosition</relatedStateVariable>
                            </argument>
                            <argument>
                                <name>RelCount</name>
                                <direction>out</direction>
                                <relatedStateVariable>RelativeCounterPosition</relatedStateVariable>
                            </argument>
                            <argument>
                                <name>AbsCount</name>
                                <direction>out</direction>
                                <relatedStateVariable>AbsoluteCounterPosition</relatedStateVariable>
                            </argument>
                        </argumentList>
                    </action>
                </actionList>
                <serviceStateTable>
                    <stateVariable sendEvents="yes">
                        <name>TransportState</name>
                        <dataType>string</dataType>
                        <allowedValueList>
                            <allowedValue>STOPPED</allowedValue>
                            <allowedValue>PLAYING</allowedValue>
                            <allowedValue>PAUSED_PLAYBACK</allowedValue>
                            <allowedValue>TRANSITIONING</allowedValue>
                            <allowedValue>NO_MEDIA_PRESENT</allowedValue>
                        </allowedValueList>
                    </stateVariable>
                    <stateVariable sendEvents="yes">
                        <name>TransportStatus</name>
                        <dataType>string</dataType>
                        <allowedValueList>
                            <allowedValue>OK</allowedValue>
                            <allowedValue>ERROR_OCCURRED</allowedValue>
                        </allowedValueList>
                    </stateVariable>
                    <stateVariable sendEvents="no">
                        <name>TransportPlaySpeed</name>
                        <dataType>string</dataType>
                        <allowedValueList>
                            <allowedValue>1</allowedValue>
                        </allowedValueList>
                    </stateVariable>
                    <stateVariable sendEvents="no">
                        <name>AVTransportURI</name>
                        <dataType>string</dataType>
                    </stateVariable>
                    <stateVariable sendEvents="no">
                        <name>AVTransportURIMetaData</name>
                        <dataType>string</dataType>
                    </stateVariable>
                    <stateVariable sendEvents="no">
                        <name>CurrentMediaDuration</name>
                        <dataType>string</dataType>
                    </stateVariable>
                    <stateVariable sendEvents="no">
                        <name>NumberOfTracks</name>
                        <dataType>ui4</dataType>
                        <defaultValue>0</defaultValue>
                    </stateVariable>
                    <stateVariable sendEvents="no">
                        <name>CurrentTrack</name>
                        <dataType>ui4</dataType>
                        <defaultValue>0</defaultValue>
                    </stateVariable>
                    <stateVariable sendEvents="no">
                        <name>CurrentTrackDuration</name>
                        <dataType>string</dataType>
                    </stateVariable>
                    <stateVariable sendEvents="no">
                        <name>CurrentTrackMetaData</name>
                        <dataType>string</dataType>
                    </stateVariable>
                    <stateVariable sendEvents="no">
                        <name>CurrentTrackURI</name>
                        <dataType>string</dataType>
                    </stateVariable>
                    <stateVariable sendEvents="no">
                        <name>RelativeTimePosition</name>
                        <dataType>string</dataType>
                    </stateVariable>
                    <stateVariable sendEvents="no">
                        <name>AbsoluteTimePosition</name>
                        <dataType>string</dataType>
                    </stateVariable>
                    <stateVariable sendEvents="no">
                        <name>RelativeCounterPosition</name>
                        <dataType>i4</dataType>
                    </stateVariable>
                    <stateVariable sendEvents="no">
                        <name>AbsoluteCounterPosition</name>
                        <dataType>i4</dataType>
                    </stateVariable>
                    <stateVariable sendEvents="no">
                        <name>A_ARG_TYPE_InstanceID</name>
                        <dataType>ui4</dataType>
                    </stateVariable>
                </serviceStateTable>
            </scpd>
            """
        elif service_type == "ConnectionManager":
            return """
            <scpd xmlns="urn:schemas-upnp-org:service-1-0">
                <specVersion>
                    <major>1</major>
                    <minor>0</minor>
                </specVersion>
                <actionList>
                    <action>
                        <name>GetProtocolInfo</name>
                        <argumentList>
                            <argument>
                                <name>Source</name>
                                <direction>out</direction>
                                <relatedStateVariable>SourceProtocolInfo</relatedStateVariable>
                            </argument>
                            <argument>
                                <name>Sink</name>
                                <direction>out</direction>
                                <relatedStateVariable>SinkProtocolInfo</relatedStateVariable>
                            </argument>
                        </argumentList>
                    </action>
                </actionList>
                <serviceStateTable>
                    <stateVariable sendEvents="no">
                        <name>SourceProtocolInfo</name>
                        <dataType>string</dataType>
                        <defaultValue>http-get:*:*:*</defaultValue>
                    </stateVariable>
                    <stateVariable sendEvents="no">
                        <name>SinkProtocolInfo</name>
                        <dataType>string</dataType>
                        <defaultValue></defaultValue>
                    </stateVariable>
                </serviceStateTable>
            </scpd>
            """
        elif service_type == "RenderingControl":
            return """
            <scpd xmlns="urn:schemas-upnp-org:service-1-0">
                <specVersion>
                    <major>1</major>
                    <minor>0</minor>
                </specVersion>
                <actionList>
                    <action>
                        <name>GetVolume</name>
                        <argumentList>
                            <argument>
                                <name>InstanceID</name>
                                <direction>in</direction>
                                <relatedStateVariable>A_ARG_TYPE_InstanceID</relatedStateVariable>
                            </argument>
                            <argument>
                                <name>Channel</name>
                                <direction>in</direction>
                                <relatedStateVariable>A_ARG_TYPE_Channel</relatedStateVariable>
                            </argument>
                            <argument>
                                <name>CurrentVolume</name>
                                <direction>out</direction>
                                <relatedStateVariable>Volume</relatedStateVariable>
                            </argument>
                        </argumentList>
                    </action>
                    <action>
                        <name>SetVolume</name>
                        <argumentList>
                            <argument>
                                <name>InstanceID</name>
                                <direction>in</direction>
                                <relatedStateVariable>A_ARG_TYPE_InstanceID</relatedStateVariable>
                            </argument>
                            <argument>
                                <name>Channel</name>
                                <direction>in</direction>
                                <relatedStateVariable>A_ARG_TYPE_Channel</relatedStateVariable>
                            </argument>
                            <argument>
                                <name>DesiredVolume</name>
                                <direction>in</direction>
                                <relatedStateVariable>Volume</relatedStateVariable>
                            </argument>
                        </argumentList>
                    </action>
                </actionList>
                <serviceStateTable>
                    <stateVariable sendEvents="no">
                        <name>Volume</name>
                        <dataType>ui2</dataType>
                        <defaultValue>50</defaultValue>
                        <allowedValueRange>
                            <minimum>0</minimum>
                            <maximum>100</maximum>
                            <step>1</step>
                        </allowedValueRange>
                    </stateVariable>
                    <stateVariable sendEvents="no">
                        <name>A_ARG_TYPE_Channel</name>
                        <dataType>string</dataType>
                        <allowedValueList>
                            <allowedValue>Master</allowedValue>
                        </allowedValueList>
                    </stateVariable>
                    <stateVariable sendEvents="no">
                        <name>A_ARG_TYPE_InstanceID</name>
                        <dataType>ui4</dataType>
                    </stateVariable>
                </serviceStateTable>
            </scpd>
            """
        return ""

    def do_POST(self):
        """处理POST请求（控制命令）"""
        content_length = int(self.headers['Content-Length'])
        post_data = self.rfile.read(content_length)
        
        try:
            root = ET.fromstring(post_data)
            body = root.find(".//{http://schemas.xmlsoap.org/soap/envelope/}Body")
            if body is None:
                raise ValueError("Invalid SOAP request")
                
            action = body.getchildren()[0]
            action_name = action.tag.split('}')[-1]
            service_type = action.tag.split('}')[0].strip('{')
            
            self.send_response(200)
            self.send_header('Content-Type', 'text/xml; charset="utf-8"')
            self.end_headers()
            
            # 处理不同的动作
            if action_name == "SetAVTransportURI":
                instance_id = action.findtext(".//InstanceID", "0")
                current_uri = action.findtext(".//CurrentURI", "")
                current_meta = action.findtext(".//CurrentURIMetaData", "")
                
                # 解析元数据获取标题
                title = "未知媒体"
                if current_meta:
                    try:
                        meta_xml = ET.fromstring(current_meta.replace("&lt;", "<").replace("&gt;", ">"))
                        title_elem = meta_xml.find(".//{http://purl.org/dc/elements/1.1/}title")
                        if title_elem is not None:
                            title = title_elem.text
                    except:
                        pass
                
                # 添加到接收媒体列表
                self.received_media.append({
                    "title": title,
                    "url": current_uri,
                    "metadata": current_meta
                })
                
                # 设置媒体URI
                if self.media_player:
                    self.media_player.setMedia(QMediaContent(QUrl(current_uri)))
                
                response = f"""
                <s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">
                    <s:Body>
                        <u:SetAVTransportURIResponse xmlns:u="{service_type}">
                            <InstanceID>{instance_id}</InstanceID>
                        </u:SetAVTransportURIResponse>
                    </s:Body>
                </s:Envelope>
                """
            
            elif action_name == "Play":
                instance_id = action.findtext(".//InstanceID", "0")
                speed = action.findtext(".//Speed", "1")
                
                # 播放媒体
                if self.media_player:
                    self.media_player.play()
                
                response = f"""
                <s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">
                    <s:Body>
                        <u:PlayResponse xmlns:u="{service_type}">
                            <InstanceID>{instance_id}</InstanceID>
                        </u:PlayResponse>
                    </s:Body>
                </s:Envelope>
                """
            
            elif action_name == "Pause":
                instance_id = action.findtext(".//InstanceID", "0")
                
                # 暂停媒体
                if self.media_player:
                    self.media_player.pause()
                
                response = f"""
                <s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">
                    <s:Body>
                        <u:PauseResponse xmlns:u="{service_type}">
                            <InstanceID>{instance_id}</InstanceID>
                        </u:PauseResponse>
                    </s:Body>
                </s:Envelope>
                """
            
            elif action_name == "Stop":
                instance_id = action.findtext(".//InstanceID", "0")
                
                # 停止媒体
                if self.media_player:
                    self.media_player.stop()
                
                response = f"""
                <s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">
                    <s:Body>
                        <u:StopResponse xmlns:u="{service_type}">
                            <InstanceID>{instance_id}</InstanceID>
                        </u:StopResponse>
                    </s:Body>
                </s:Envelope>
                """
            
            elif action_name == "GetMediaInfo":
                instance_id = action.findtext(".//InstanceID", "0")
                
                current_uri = ""
                media_duration = "00:00:00"
                current_meta = ""
                
                if self.media_player and self.media_player.media().isValid():
                    current_uri = self.media_player.media().request().url().toString()
                    media_duration = "00:00:00"  # 实际应用中应该获取真实时长
                    current_meta = ""
                
                response = f"""
                <s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">
                    <s:Body>
                        <u:GetMediaInfoResponse xmlns:u="{service_type}">
                            <InstanceID>{instance_id}</InstanceID>
                            <NrTracks>1</NrTracks>
                            <MediaDuration>{media_duration}</MediaDuration>
                            <CurrentURI>{current_uri}</CurrentURI>
                            <CurrentURIMetaData>{current_meta}</CurrentURIMetaData>
                        </u:GetMediaInfoResponse>
                    </s:Body>
                </s:Envelope>
                """
            
            elif action_name == "GetTransportInfo":
                instance_id = action.findtext(".//InstanceID", "0")
                
                transport_state = "NO_MEDIA_PRESENT"
                transport_status = "OK"
                speed = "1"
                
                if self.media_player:
                    state = self.media_player.state()
                    if state == QMediaPlayer.PlayingState:
                        transport_state = "PLAYING"
                    elif state == QMediaPlayer.PausedState:
                        transport_state = "PAUSED_PLAYBACK"
                    elif state == QMediaPlayer.StoppedState:
                        transport_state = "STOPPED"
                
                response = f"""
                <s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">
                    <s:Body>
                        <u:GetTransportInfoResponse xmlns:u="{service_type}">
                            <InstanceID>{instance_id}</InstanceID>
                            <CurrentTransportState>{transport_state}</CurrentTransportState>
                            <CurrentTransportStatus>{transport_status}</CurrentTransportStatus>
                            <CurrentSpeed>{speed}</CurrentSpeed>
                        </u:GetTransportInfoResponse>
                    </s:Body>
                </s:Envelope>
                """
            
            elif action_name == "GetPositionInfo":
                instance_id = action.findtext(".//InstanceID", "0")
                
                track = "1"
                track_duration = "00:00:00"
                track_meta = ""
                track_uri = ""
                rel_time = "00:00:00"
                abs_time = "00:00:00"
                rel_count = "0"
                abs_count = "0"
                
                if self.media_player and self.media_player.media().isValid():
                    track_uri = self.media_player.media().request().url().toString()
                    position = self.media_player.position()
                    rel_time = self.format_time(position)
                    abs_time = self.format_time(position)
                
                response = f"""
                <s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">
                    <s:Body>
                        <u:GetPositionInfoResponse xmlns:u="{service_type}">
                            <InstanceID>{instance_id}</InstanceID>
                            <Track>{track}</Track>
                            <TrackDuration>{track_duration}</TrackDuration>
                            <TrackMetaData>{track_meta}</TrackMetaData>
                            <TrackURI>{track_uri}</TrackURI>
                            <RelTime>{rel_time}</RelTime>
                            <AbsTime>{abs_time}</AbsTime>
                            <RelCount>{rel_count}</RelCount>
                            <AbsCount>{abs_count}</AbsCount>
                        </u:GetPositionInfoResponse>
                    </s:Body>
                </s:Envelope>
                """
            
            elif action_name == "GetVolume":
                instance_id = action.findtext(".//InstanceID", "0")
                channel = action.findtext(".//Channel", "Master")
                
                current_volume = "50"
                if self.media_player:
                    current_volume = str(self.media_player.volume())
                
                response = f"""
                <s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">
                    <s:Body>
                        <u:GetVolumeResponse xmlns:u="{service_type}">
                            <InstanceID>{instance_id}</InstanceID>
                            <Channel>{channel}</Channel>
                            <CurrentVolume>{current_volume}</CurrentVolume>
                        </u:GetVolumeResponse>
                    </s:Body>
                </s:Envelope>
                """
            
            elif action_name == "SetVolume":
                instance_id = action.findtext(".//InstanceID", "0")
                channel = action.findtext(".//Channel", "Master")
                desired_volume = action.findtext(".//DesiredVolume", "50")
                
                # 设置音量
                if self.media_player:
                    self.media_player.setVolume(int(desired_volume))
                
                response = f"""
                <s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">
                    <s:Body>
                        <u:SetVolumeResponse xmlns:u="{service_type}">
                            <InstanceID>{instance_id}</InstanceID>
                            <Channel>{channel}</Channel>
                        </u:SetVolumeResponse>
                    </s:Body>
                </s:Envelope>
                """
            
            elif action_name == "GetProtocolInfo":
                response = f"""
                <s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">
                    <s:Body>
                        <u:GetProtocolInfoResponse xmlns:u="{service_type}">
                            <Source>http-get:*:*:*</Source>
                            <Sink></Sink>
                        </u:GetProtocolInfoResponse>
                    </s:Body>
                </s:Envelope>
                """
            
            else:
                # 默认响应
                response = f"""
                <s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">
                    <s:Body>
                        <u:{action_name}Response xmlns:u="{service_type}">
                            <InstanceID>0</InstanceID>
                        </u:{action_name}Response>
                    </s:Body>
                </s:Envelope>
                """
            
            self.wfile.write(response.encode('utf-8'))
            
        except Exception as e:
            print(f"处理POST请求错误: {e}")
            self.send_response(500)
            self.end_headers()

    def format_time(self, milliseconds):
        """格式化时间(HH:MM:SS)"""
        seconds = milliseconds // 1000
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        seconds = seconds % 60
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

class MediaReceiverServer(HTTPServer):
    """DLNA接收器服务器"""
    def __init__(self, port, media_player, received_media):
        self.port = port
        self.uuid = str(uuid.uuid4())
        self.media_player = media_player
        self.received_media = received_media
        super().__init__(('0.0.0.0', port), MediaReceiverHandler)
        
    def serve_forever(self, poll_interval=0.5):
        print(f"DLNA接收器运行在 http://{self.server_name}:{self.server_port}")
        super().serve_forever(poll_interval)

class LocalFileServer(threading.Thread):
    """本地文件服务器线程"""
    def __init__(self, port=8000):
        super().__init__(daemon=True)
        self.port = port
        self.server = None
        self.base_path = ""
        
    def set_base_path(self, path):
        """设置基础路径"""
        self.base_path = path
        
    def run(self):
        """运行文件服务器"""
        if not self.base_path:
            return
            
        self.server = MediaFileServer(self.base_path, self.port)
        self.server.serve_forever()
        
    def stop(self):
        """停止文件服务器"""
        if self.server:
            self.server.shutdown()
            self.server.server_close()

class DLNAApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("DLNA/UPnP投屏工具")
        self.setGeometry(100, 100, 1000, 700)
        
        # 初始化变量
        self.discoverer = UPnPDiscoverer()
        self.receiver_server = None
        self.receiver_thread = None
        self.file_server = LocalFileServer()
        self.current_device = None
        self.received_media = []
        self.selected_media_path = ""
        self.local_ip = self.get_local_ip()
        
        # 创建媒体播放器
        self.media_player = QMediaPlayer()
        self.video_widget = QVideoWidget()
        self.media_player.setVideoOutput(self.video_widget)
        
        # 创建主界面
        self.init_ui()
        
        # 启动设备发现
        self.discover_devices()
        
        # 启动状态更新定时器
        self.status_timer = QTimer()
        self.status_timer.timeout.connect(self.update_device_status)
        self.status_timer.start(1000)
        
    def init_ui(self):
        """初始化用户界面"""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
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
        
        # 设备信息组
        device_group = QGroupBox("设备信息")
        device_layout = QVBoxLayout(device_group)
        
        # 设备列表
        self.device_list = QListWidget()
        self.device_list.itemSelectionChanged.connect(self.on_device_selected)
        device_layout.addWidget(self.device_list)
        
        # 刷新按钮
        refresh_btn = QPushButton("刷新设备列表")
        refresh_btn.clicked.connect(self.discover_devices)
        device_layout.addWidget(refresh_btn)
        
        layout.addWidget(device_group)
        
        # 设备详情
        self.device_details = QTextEdit()
        self.device_details.setReadOnly(True)
        self.device_details.setMaximumHeight(100)
        layout.addWidget(self.device_details)
        
        # 媒体选择组
        media_group = QGroupBox("媒体选择")
        media_layout = QVBoxLayout(media_group)
        
        # 媒体路径
        path_layout = QHBoxLayout()
        path_layout.addWidget(QLabel("媒体文件或URL:"))
        
        self.media_path = QTextEdit()
        self.media_path.setMaximumHeight(60)
        path_layout.addWidget(self.media_path, 1)
        
        browse_btn = QPushButton("浏览...")
        browse_btn.clicked.connect(self.browse_media)
        path_layout.addWidget(browse_btn)
        
        media_layout.addLayout(path_layout)
        
        # 媒体信息
        self.media_info = QTextEdit()
        self.media_info.setReadOnly(True)
        self.media_info.setMaximumHeight(60)
        media_layout.addWidget(self.media_info)
        
        # 投屏控制按钮
        control_layout = QHBoxLayout()
        
        self.cast_btn = QPushButton("开始投屏")
        self.cast_btn.clicked.connect(self.start_casting)
        control_layout.addWidget(self.cast_btn)
        
        self.stop_btn = QPushButton("停止")
        self.stop_btn.clicked.connect(self.stop_casting)
        control_layout.addWidget(self.stop_btn)
        
        self.pause_btn = QPushButton("暂停")
        self.pause_btn.clicked.connect(self.pause_casting)
        control_layout.addWidget(self.pause_btn)
        
        media_layout.addLayout(control_layout)
        
        # 音量控制
        volume_layout = QHBoxLayout()
        volume_layout.addWidget(QLabel("音量:"))
        
        self.volume_slider = QSlider(Qt.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(50)
        self.volume_slider.valueChanged.connect(self.set_device_volume)
        volume_layout.addWidget(self.volume_slider)
        
        media_layout.addLayout(volume_layout)
        
        layout.addWidget(media_group)
        
        # 日志区域
        log_group = QGroupBox("操作日志")
        log_layout = QVBoxLayout(log_group)
        
        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        log_layout.addWidget(self.log_area)
        
        layout.addWidget(log_group)
    
    def init_receive_tab(self, tab):
        """初始化接收标签页"""
        layout = QVBoxLayout(tab)
        
        # 接收服务器状态
        server_group = QGroupBox("接收服务")
        server_layout = QVBoxLayout(server_group)
        
        self.receiver_status = QLabel("接收服务未运行")
        server_layout.addWidget(self.receiver_status)
        
        # 网络信息
        self.network_info = QLabel(f"本地IP: {self.local_ip}")
        server_layout.addWidget(self.network_info)
        
        # 启动/停止按钮
        self.receiver_btn = QPushButton("启动接收服务")
        self.receiver_btn.clicked.connect(self.toggle_receiver)
        server_layout.addWidget(self.receiver_btn)
        
        layout.addWidget(server_group)
        
        # 视频播放器
        player_group = QGroupBox("媒体播放器")
        player_layout = QVBoxLayout(player_group)
        
        player_layout.addWidget(self.video_widget)
        
        # 播放控制
        play_control_layout = QHBoxLayout()
        
        self.play_btn = QPushButton("播放")
        self.play_btn.clicked.connect(self.play_received_media)
        play_control_layout.addWidget(self.play_btn)
        
        self.receive_pause_btn = QPushButton("暂停")
        self.receive_pause_btn.clicked.connect(self.pause_received_media)
        play_control_layout.addWidget(self.receive_pause_btn)
        
        self.receive_stop_btn = QPushButton("停止")
        self.receive_stop_btn.clicked.connect(self.stop_received_media)
        play_control_layout.addWidget(self.receive_stop_btn)
        
        player_layout.addLayout(play_control_layout)
        
        # 音量控制
        receive_volume_layout = QHBoxLayout()
        receive_volume_layout.addWidget(QLabel("音量:"))
        
        self.receive_volume_slider = QSlider(Qt.Horizontal)
        self.receive_volume_slider.setRange(0, 100)
        self.receive_volume_slider.setValue(50)
        self.receive_volume_slider.valueChanged.connect(self.set_receiver_volume)
        receive_volume_layout.addWidget(self.receive_volume_slider)
        
        player_layout.addLayout(receive_volume_layout)
        
        layout.addWidget(player_group)
        
        # 接收到的媒体
        media_group = QGroupBox("接收到的媒体")
        media_layout = QVBoxLayout(media_group)
        
        self.received_media_list = QListWidget()
        self.received_media_list.itemDoubleClicked.connect(self.play_received_media)
        media_layout.addWidget(self.received_media_list)
        
        layout.addWidget(media_group)
    
    def init_settings_tab(self, tab):
        """初始化设置标签页"""
        layout = QVBoxLayout(tab)
        
        # 网络设置
        network_group = QGroupBox("网络设置")
        network_layout = QVBoxLayout(network_group)
        
        # 发现超时
        timeout_layout = QHBoxLayout()
        timeout_layout.addWidget(QLabel("设备发现超时(秒):"))
        
        self.timeout_input = QComboBox()
        self.timeout_input.addItems(["1", "2", "3", "5", "10"])
        self.timeout_input.setCurrentText("3")
        timeout_layout.addWidget(self.timeout_input)
        
        network_layout.addLayout(timeout_layout)
        
        # 接收端口
        port_layout = QHBoxLayout()
        port_layout.addWidget(QLabel("接收服务端口:"))
        
        self.port_input = QComboBox()
        self.port_input.addItems(["8000", "8001", "8080", "8888"])
        self.port_input.setCurrentText("8000")
        port_layout.addWidget(self.port_input)
        
        network_layout.addLayout(port_layout)
        
        # 文件服务器端口
        file_port_layout = QHBoxLayout()
        file_port_layout.addWidget(QLabel("文件服务器端口:"))
        
        self.file_port_input = QComboBox()
        self.file_port_input.addItems(["8000", "8001", "8080", "8888"])
        self.file_port_input.setCurrentText("8000")
        file_port_layout.addWidget(self.file_port_input)
        
        network_layout.addLayout(file_port_layout)
        
        # 网络接口
        interface_layout = QHBoxLayout()
        interface_layout.addWidget(QLabel("网络接口:"))
        
        self.interface_combo = QComboBox()
        interfaces = self.get_network_interfaces()
        for iface in interfaces:
            self.interface_combo.addItem(f"{iface['name']} ({iface['ip']})", iface['name'])
        interface_layout.addWidget(self.interface_combo)
        
        network_layout.addLayout(interface_layout)
        
        layout.addWidget(network_group)
        
        # 其他设置
        other_group = QGroupBox("其他设置")
        other_layout = QVBoxLayout(other_group)
        
        # 自动刷新
        self.auto_refresh_check = QCheckBox("自动刷新设备列表")
        other_layout.addWidget(self.auto_refresh_check)
        
        # 保存日志
        self.save_log_check = QCheckBox("保存操作日志到文件")
        other_layout.addWidget(self.save_log_check)
        
        layout.addWidget(other_group)
        
        # 保存按钮
        save_btn = QPushButton("保存设置")
        save_btn.clicked.connect(self.save_settings)
        layout.addWidget(save_btn)
        
        # 关于信息
        about_group = QGroupBox("关于")
        about_layout = QVBoxLayout(about_group)
        
        about_layout.addWidget(QLabel("DLNA/UPnP投屏工具 v1.0"))
        about_layout.addWidget(QLabel("作者: Python DLNA项目"))
        about_layout.addWidget(QLabel("协议: GPL v3"))
        
        layout.addWidget(about_group)
        
        # 底部空白
        layout.addStretch()
    
    def get_local_ip(self):
        """获取本地IP地址"""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except:
            return "127.0.0.1"
    
    def get_network_interfaces(self):
        """获取网络接口信息"""
        interfaces = []
        for iface in netifaces.interfaces():
            addrs = netifaces.ifaddresses(iface)
            if netifaces.AF_INET in addrs:
                for addr in addrs[netifaces.AF_INET]:
                    if 'addr' in addr and not addr['addr'].startswith('127.'):
                        interfaces.append({
                            'name': iface,
                            'ip': addr['addr']
                        })
        return interfaces or [{'name': 'eth0', 'ip': self.local_ip}]
    
    def discover_devices(self):
        """发现DLNA设备"""
        self.device_list.clear()
        self.log("正在搜索DLNA设备...")
        
        def discover_thread():
            devices = self.discoverer.discover(timeout=int(self.timeout_input.currentText()))
            
            self.device_list.clear()
            for device in devices:
                self.device_list.addItem(f"{device.friendly_name} ({device.device_type})")
            
            self.log(f"发现 {len(devices)} 个DLNA设备")
        
        threading.Thread(target=discover_thread, daemon=True).start()
    
    def on_device_selected(self):
        """设备选择变化"""
        if self.device_list.currentRow() == -1:
            self.current_device = None
            self.device_details.clear()
            return
        
        self.current_device = self.discoverer.devices[self.device_list.currentRow()]
        
        details = [
            f"名称: {self.current_device.friendly_name}",
            f"类型: {self.current_device.device_type}",
            f"制造商: {self.current_device.manufacturer}",
            f"型号: {self.current_device.model_name}",
            f"UDN: {self.current_device.udn}",
            f"控制URL: {self.current_device.control_url}"
        ]
        
        self.device_details.setPlainText("\n".join(details))
        
        # 获取设备音量
        volume = self.current_device.get_volume()
        if volume:
            self.volume_slider.setValue(int(volume))
    
    def browse_media(self):
        """浏览选择媒体文件"""
        file_dialog = QFileDialog()
        file_path, _ = file_dialog.getOpenFileName(self, "选择媒体文件", "", 
                                                  "媒体文件 (*.mp4 *.avi *.mkv *.mp3 *.mov *.wmv *.flv);;所有文件 (*.*)")
        
        if file_path:
            self.selected_media_path = file_path
            self.media_path.setText(file_path)
            
            # 获取文件信息
            file_info = QDir(file_path)
            file_name = file_info.dirName()
            file_size = os.path.getsize(file_path) / (1024 * 1024)  # MB
            
            mime_type, _ = mimetypes.guess_type(file_path)
            if not mime_type:
                mime_type = "application/octet-stream"
            
            self.media_info.setPlainText(
                f"文件名: {file_name}\n"
                f"大小: {file_size:.2f} MB\n"
                f"类型: {mime_type}"
            )
    
    def start_casting(self):
        """开始投屏"""
        if not self.current_device:
            QMessageBox.warning(self, "警告", "请先选择一个DLNA设备")
            return
        
        media_url = self.media_path.toPlainText()
        if not media_url:
            QMessageBox.warning(self, "警告", "请输入媒体文件路径或URL")
            return
        
        # 如果是本地文件，启动文件服务器
        if not media_url.startswith(('http://', 'https://')):
            if not os.path.exists(media_url):
                QMessageBox.warning(self, "警告", "文件不存在")
                return
                
            # 设置文件服务器基础路径
            file_dir = os.path.dirname(media_url)
            file_name = os.path.basename(media_url)
            self.file_server.set_base_path(file_dir)
            
            # 启动文件服务器
            if not self.file_server.is_alive():
                self.file_server.port = int(self.file_port_input.currentText())
                self.file_server.start()
                time.sleep(1)  # 等待服务器启动
                
            media_url = f"http://{self.local_ip}:{self.file_server.port}/{file_name}"
        
        def cast_thread():
            self.log(f"正在向 {self.current_device.friendly_name} 投屏: {media_url}")
            
            # 获取文件名作为标题
            title = os.path.splitext(os.path.basename(media_url))[0]
            
            # 获取MIME类型
            mime_type, _ = mimetypes.guess_type(media_url)
            if not mime_type:
                mime_type = "video/mp4" if media_url.lower().endswith(('.mp4', '.avi', '.mkv')) else "audio/mpeg"
            
            success = self.current_device.play_media(media_url, title, mime_type)
            
            if success:
                self.log("投屏成功")
            else:
                self.log("投屏失败")
        
        threading.Thread(target=cast_thread, daemon=True).start()
    
    def stop_casting(self):
        """停止投屏"""
        if not self.current_device:
            return
            
        if self.current_device.control_media("stop"):
            self.log("已发送停止命令")
        else:
            self.log("停止命令发送失败")
    
    def pause_casting(self):
        """暂停投屏"""
        if not self.current_device:
            return
            
        if self.current_device.control_media("pause"):
            self.log("已发送暂停命令")
        else:
            self.log("暂停命令发送失败")
    
    def set_device_volume(self, volume):
        """设置设备音量"""
        if not self.current_device:
            return
            
        if self.current_device.set_volume(volume):
            self.log(f"音量设置为 {volume}")
        else:
            self.log("音量设置失败")
    
    def toggle_receiver(self):
        """切换接收服务状态"""
        if self.receiver_server is None:
            # 启动接收服务
            port = int(self.port_input.currentText())
            
            try:
                self.receiver_server = MediaReceiverServer(port, self.media_player, self.received_media)
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
            if self.receiver_thread:
                self.receiver_thread.join()
                self.receiver_thread = None
            
            self.receiver_status.setText("接收服务未运行")
            self.receiver_btn.setText("启动接收服务")
            self.log("DLNA接收服务已停止")
    
    def advertise_receiver(self, port):
        """在网络上宣告我们的接收服务"""
        def advertise():
            multicast_group = "239.255.255.250"
            server_port = 1900
            
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            
            notify_msg = (
                "NOTIFY * HTTP/1.1\r\n"
                "HOST: 239.255.255.250:1900\r\n"
                "CACHE-CONTROL: max-age=1800\r\n"
                "LOCATION: http://{}:{}/description.xml\r\n"
                "NT: urn:schemas-upnp-org:device:MediaRenderer:1\r\n"
                "NTS: ssdp:alive\r\n"
                "SERVER: Python DLNA Receiver/1.0\r\n"
                "USN: uuid:{}::urn:schemas-upnp-org:device:MediaRenderer:1\r\n"
                "\r\n"
            ).format(self.local_ip, port, self.receiver_server.uuid).encode('utf-8')
            
            while self.receiver_server is not None:
                sock.sendto(notify_msg, (multicast_group, server_port))
                time.sleep(30)  # 每30秒发送一次
            
            sock.close()
        
        threading.Thread(target=advertise, daemon=True).start()
    
    def play_received_media(self):
        """播放接收到的媒体"""
        if not self.received_media:
            return
            
        selected_item = self.received_media_list.currentRow()
        if selected_item == -1:
            selected_item = 0
            
        media = self.received_media[selected_item]
        media_url = media['url']
        
        self.media_player.setMedia(QMediaContent(QUrl(media_url)))
        self.media_player.play()
        self.log(f"正在播放: {media['title']}")
    
    def pause_received_media(self):
        """暂停接收的媒体"""
        self.media_player.pause()
        self.log("播放已暂停")
    
    def stop_received_media(self):
        """停止接收的媒体"""
        self.media_player.stop()
        self.log("播放已停止")
    
    def set_receiver_volume(self, volume):
        """设置接收器音量"""
        self.media_player.setVolume(volume)
        self.log(f"接收器音量设置为 {volume}")
    
    def update_device_status(self):
        """更新设备状态"""
        if not self.current_device:
            return
            
        # 获取设备状态
        transport_info = self.current_device.get_transport_info()
        position_info = self.current_device.get_position_info()
        
        if transport_info and position_info:
            status = [
                f"状态: {transport_info['CurrentTransportState']}",
                f"速度: {transport_info['CurrentSpeed']}",
                f"位置: {position_info['RelTime']} / {position_info['TrackDuration']}"
            ]
            self.device_details.append("\n".join(status))
    
    def save_settings(self):
        """保存设置"""
        self.log("设置已保存")
        QMessageBox.information(self, "成功", "设置已保存")
    
    def log(self, message):
        """记录日志"""
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        self.log_area.append(f"[{timestamp}] {message}")
        self.log_area.verticalScrollBar().setValue(self.log_area.verticalScrollBar().maximum())
        
        # 如果启用了日志保存，写入文件
        if self.save_log_check.isChecked():
            with open("dlna_log.txt", "a", encoding="utf-8") as f:
                f.write(f"[{timestamp}] {message}\n")
    
    def closeEvent(self, event):
        """关闭窗口事件"""
        # 停止接收服务
        if self.receiver_server is not None:
            self.receiver_server.shutdown()
            self.receiver_server.server_close()
            if self.receiver_thread:
                self.receiver_thread.join()
        
        # 停止文件服务器
        self.file_server.stop()
        
        # 停止设备发现
        self.discoverer.stop()
        
        # 停止媒体播放
        self.media_player.stop()
        
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    
    # 设置中文样式
    app.setStyle("Fusion")
    
    window = DLNAApp()
    window.show()
    
    sys.exit(app.exec_())