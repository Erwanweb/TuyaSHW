# Usage of TinyTuya for GIA SANITARY HOT WATER BOILER
import tinytuya
import tuyadevice
import tuyaorder

d = tinytuya.Device(tuyadevice.DEVICE_ID, tuyadevice.IP_ADDRESS, tuyadevice.LOCAL_KEY, version=tuyadevice.VERSION)

# Set device on or off
d.set_value(1, tuyaorder.Power)
# Set device setpoint
d.set_value (2, tuyaorder.Setpoint)
