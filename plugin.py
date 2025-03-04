#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Ecowatt plugin for Domoticz
# Author: MrErwan,
# Version:    0.0.1: alpha..

"""
<plugin key="RL-TUYASHW" name="Ronelabs - TUYA SHW device control plugin" author="Ronelabs" version="0.0.2" externallink="https://github.com/Erwanweb/TuyaSHW">
      <description>
        <h2>Ronelabs's TUYA SHW Boiler plugin for domoticz</h2><br/>
        Easily implement in Domoticz TUYA SHW Boiler<br/>
        <h3>Set-up and Configuration</h3>
    </description>
    <params>
        <param field="Username" label="Tuya Device ID" width="200px" required="true" default=""/>
        <param field="Password" label="Tuya Device Local Key" width="200px" required="true" default=""/>
        <param field="Mode1" label="Tuya Device local IP Adress" width="200px" required="true" default=""/>
        <param field="Mode2" label="Tuya Version" width="50px">
            <options>
                <option label="3.5" value="3.5"/>
                <option label="3.4" value="3.4"  default="true"/>
                <option label="3.3" value="3.3"/>
                <option label="3.2" value="3.2"/>
            </options>
        </param>
        <param field="Mode3" label="Cold water temp. Inlet" width="50px" required="true" default="18"/>
        <param field="Mode6" label="Logging Level" width="200px">
            <options>
                <option label="Normal" value="Normal"  default="true"/>
                <option label="Verbose" value="Verbose"/>
                <option label="Debug - Python Only" value="2"/>
                <option label="Debug - Basic" value="62"/>
                <option label="Debug - Basic+Messages" value="126"/>
                <option label="Debug - Connections Only" value="16"/>
                <option label="Debug - Connections+Queue" value="144"/>
                <option label="Debug - All" value="-1"/>
            </options>
        </param>
    </params>
</plugin>
"""
import Domoticz
import json
import requests
import urllib.parse as parse
import urllib.request as request
from datetime import datetime, timedelta
import time
import math
import base64
import itertools
import subprocess
import os
import subprocess
from typing import Any
import tinytuya
import math

try:
    from Domoticz import Devices, Images, Parameters, Settings
except ImportError:
    pass

class deviceparam:

    def __init__(self, unit, nvalue, svalue):
        self.unit = unit
        self.nvalue = nvalue
        self.svalue = svalue


class BasePlugin:

    def __init__(self):

        self.debug = False
        self.CheckDeviceRequest = datetime.now()
        self.SpecFolder = ""
        self.powerOn = 0
        self.forced = 0
        self.setpoint = 60
        self.watertemp = 20
        self.TempMini = 18
        self.Volume = 0
        return


    def onStart(self):

        # setup the appropriate logging level
        try:
            debuglevel = int(Parameters["Mode6"])
        except ValueError:
            debuglevel = 0
            self.loglevel = Parameters["Mode6"]
        if debuglevel != 0:
            self.debug = True
            Domoticz.Debugging(debuglevel)
            DumpConfigToLog()
            self.loglevel = "Verbose"
        else:
            self.debug = False
            Domoticz.Debugging(0)

        # create the child devices if these do not exist yet
        devicecreated = []
        if 1 not in Devices:
            Options = {"LevelActions": "||",
                       "LevelNames": "Off|Manual|Auto",
                       "LevelOffHidden": "false",
                       "SelectorStyle": "0"}
            Domoticz.Device(Name="SHW Control", Unit=1, TypeName="Selector Switch", Switchtype=18, Image=15,
                            Options=Options, Used=1).Create()
            devicecreated.append(deviceparam(1, 0, "0"))  # default is Off state
        if 2 not in Devices:
            Domoticz.Device(Name="SHW Setpoint", Unit=2, Type=242, Subtype=1, Used=1).Create()
            devicecreated.append(deviceparam(2, 0, "20"))  # default is 20 degrees
        if 3 not in Devices:
            Domoticz.Device(Name="SHW temp", Unit=3, TypeName="Temperature", Used=1).Create()
            devicecreated.append(deviceparam(3, 0, "20"))  # default is 20 degrees
        if 4 not in Devices:
            Domoticz.Device(Name="SHW Volume", Unit=4, Type=243, Subtype=6, Used=1).Create()
            devicecreated.append(deviceparam(4, 0, "0"))  # default is 0

        # if any device has been created in onStart(), now is time to update its defaults
        for device in devicecreated:
            Devices[device.unit].Update(nValue=device.nvalue, sValue=device.svalue)

        # build Tuya device params
        self.DEVICE_ID = Parameters["Username"]
        self.LOCAL_KEY = Parameters["Password"]
        self.IP_ADDRESS = Parameters["Mode1"]
        self.VERSION = Parameters["Mode2"]

        # set cold water temp
        self.TempMini = round(float(Parameters["Mode3"]))

        # check Device status
        self.checkdevice()

        # Set domoticz heartbeat to 20 s (onheattbeat() will be called every 20 )
        Domoticz.Heartbeat(20)

    def onStop(self):

        Domoticz.Debugging(0)

    def onCommand(self, Unit, Command, Level, Color):

        Domoticz.Debug("onCommand called for Unit {}: Command '{}', Level: {}".format(Unit, Command, Level))

        if (Unit == 1):
            Devices[1].Update(nValue=self.powerOn, sValue=str(Level))
            if (Devices[1].sValue == "20"):  # Mode auto
                self.powerOn = 1
                self.forced = 0
                Devices[1].Update(nValue=1, sValue="20")
            elif (Devices[1].sValue == "10"):  # Manual Mode
                self.powerOn = 1
                self.forced = 1
                Devices[1].Update(nValue=1, sValue="10")
            else:  # Off
                Devices[1].Update(nValue=0, sValue="0")
                self.powerOn = 0
                self.forced = 0
            # Update devices
            Devices[1].Update(nValue=self.powerOn, sValue=Devices[1].sValue)
            Devices[2].Update(nValue=self.powerOn, sValue=Devices[2].sValue)

        if (Unit == 2):  # Setpoint
            Devices[2].Update(nValue=self.powerOn, sValue=str(Level))

        self.setpoint = round(float(Devices[2].sValue))

        self.tuyaorder()

# ---------------------------------------------
    def onHeartbeat(self):

        Domoticz.Debug("onHeartbeat Called...")

        if not all(device in Devices for device in (1, 2, 3, 4)):
            Domoticz.Error("one or more devices required by the plugin is/are missing, please check domoticz device creation settings and restart !")
            return

        now = datetime.now()

        if self.CheckDeviceRequest + timedelta(minutes=5) <= now:
            self.checkdevice()
        
        self.checkvolume()

# ---------------------------------------------
    def checkdevice(self):

        self.CheckDeviceRequest = datetime.now()
        d = tinytuya.Device(self.DEVICE_ID, self.IP_ADDRESS, self.LOCAL_KEY, version=float(self.VERSION))
        Domoticz.Debug(f'sending : tinytuya.Device({d})')
        # lecture
        data = d.status()
        # maj des valeurs des widgets si ok
        if "dps" in data :
            power = str(data['dps']['1'])
            if power == "True" :
                power = "ON"
                self.powerOn = 1
                if self.forced == 1 :
                    Devices[1].Update(nValue=self.powerOn, sValue="10")
                else :
                    Devices[1].Update(nValue=self.powerOn, sValue="20")
            else:
                power = "OFF"
                self.powerOn = 0
                self.forced = 0 #forcing auto mode if using tuya app to turn on the device
                Devices[1].Update(nValue=self.powerOn, sValue="0")
            self.setpoint = str(data['dps']['2'])
            Devices[2].Update(nValue=self.powerOn, sValue="{}".format(str(self.setpoint)))
            self.watertemp = str(data['dps']['3'])
            Devices[3].Update(nValue=self.powerOn, sValue="{}".format(str(self.watertemp)))
            Domoticz.Debug("device is {}, set at {} and actual temp is {}".format(str(power), str(self.setpoint), str(self.watertemp)))
        else :
            Domoticz.Error("Tuya Device Datas not received - Please check device params and network")
       

# ---------------------------------------------
    def tuyaorder(self):

        if self.powerOn == 1 :
            Power = 'On'
        else :
            Power = 'Off'
        Setpoint = self.setpoint
        Domoticz.Debug(f"Setting Tuya order at {Power} - {Setpoint}")
        d = tinytuya.Device(self.DEVICE_ID, self.IP_ADDRESS, self.LOCAL_KEY, version=float(self.VERSION))
        # Set device on or off
        if self.powerOn == 1 :
            d.set_value(1, True)
        else :
            d.set_value(1, False)
        # Set device setpoint
        d.set_value(2, Setpoint)
        Domoticz.Debug("TUYA Device Setted")
        self.CheckDeviceRequest = datetime.now()

# ---------------------------------------------
    def checkvolume(self):

        # self.TempMini =
        Setpoint = round(float(Devices[2].sValue))
        watertemp = round(float(Devices[3].sValue))

        if watertemp <= self.TempMini :
            self.Volume = 0
        elif watertemp >= Setpoint :
            self.Volume = 100
        else:
            watertemp = watertemp + 1
            # Fonction exponentielle ajustée
            base = 0.75  # Augmentation rapide
            normalized_temp = (watertemp - self.TempMini) / (Setpoint - self.TempMini)
            # Ajustement manuel
            self.Volume = round(min(max(100 * (math.exp(3 * normalized_temp * math.log(base)) - 1) / (math.exp(3 * math.log(base)) - 1), 0),100))
        # updating widget
        Devices[4].Update(nValue=self.powerOn, sValue="{}".format(str(self.Volume)))

#-------------------------------------------------------------------------------------------------------------
global _plugin
_plugin = BasePlugin()


def onStart():
    global _plugin
    _plugin.onStart()


def onStop():
    global _plugin
    _plugin.onStop()


def onCommand(Unit, Command, Level, Color):
    global _plugin
    _plugin.onCommand(Unit, Command, Level, Color)


def onHeartbeat():
    global _plugin
    _plugin.onHeartbeat()

# Plugin utility functions ---------------------------------------------------

def parseCSV(strCSV):
    listvals = []
    for value in strCSV.split(","):
        try:
            val = int(value)
            listvals.append(val)
        except ValueError:
            try:
                val = float(value)
                listvals.append(val)
            except ValueError:
                Domoticz.Error(f"Skipping non-numeric value: {value}")
    return listvals

def CheckParam(name, value, default):

    try:
        param = int(value)
    except ValueError:
        param = default
        Domoticz.Error("Parameter '{}' has an invalid value of '{}' ! defaut of '{}' is instead used.".format(name, value, default))
    return param

def DomoticzAPI(APICall):

    resultJson = None
    url = f"http://127.0.0.1:8080/json.htm?{parse.quote(APICall, safe='&=')}"
    try:
        Domoticz.Debug(f"Domoticz API request: {url}")
        req = request.Request(url)
        response = request.urlopen(req)
        if response.status == 200:
            resultJson = json.loads(response.read().decode('utf-8'))
            if resultJson.get("status") != "OK":
                Domoticz.Error(f"Domoticz API returned an error: status = {resultJson.get('status')}")
                resultJson = None
        else:
            Domoticz.Error(f"Domoticz API: HTTP error = {response.status}")
    except urllib.error.HTTPError as e:
        Domoticz.Error(f"HTTP error calling '{url}': {e}")
    except urllib.error.URLError as e:
        Domoticz.Error(f"URL error calling '{url}': {e}")
    except json.JSONDecodeError as e:
        Domoticz.Error(f"JSON decoding error: {e}")
    except Exception as e:
        Domoticz.Error(f"Error calling '{url}': {e}")

    return resultJson


# Generic helper functions
def DumpConfigToLog():
    for x in Parameters:
        if Parameters[x] != "":
            Domoticz.Debug("'" + x + "':'" + str(Parameters[x]) + "'")
    Domoticz.Debug("Device count: " + str(len(Devices)))
    for x in Devices:
        Domoticz.Debug("Device:           " + str(x) + " - " + str(Devices[x]))
        Domoticz.Debug("Device ID:       '" + str(Devices[x].ID) + "'")
        Domoticz.Debug("Device Name:     '" + Devices[x].Name + "'")
        Domoticz.Debug("Device nValue:    " + str(Devices[x].nValue))
        Domoticz.Debug("Device sValue:   '" + Devices[x].sValue + "'")
        Domoticz.Debug("Device LastLevel: " + str(Devices[x].LastLevel))
    return