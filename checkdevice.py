# Checking variable of tuya device
import tinytuya
import tuyadevice

d = tinytuya.Device(tuyadevice.DEVICE_ID, tuyadevice.IP_ADDRESS, tuyadevice.LOCAL_KEY, version=tuyadevice.VERSION)
data = d.status() 
#print('Device status: %r' % data)
print('Dictionary %r' % data)
print('State (bool, true is ON) %r' % data['dps']['1'])
