import psutil
import json
import subprocess
import mraa
import time
import paho.mqtt.client as mqtt
import logging

TACHO_PIN = 16
PWM_PIN = 11
PWM_PERIOD = 40
PW_MAX = 35
PW_INIT = 20
PW_MIN = 5
TEMP_MAX = 35
TEMP_MIN = 30

# configure logger ----------------------------------------------------------------------------------------------------#
logger = logging.getLogger(__name__)
"""
If other logger handlers will have other msg level than WARING (which is default), then root logger need to set 
msg level to DEBUG, otherwise it's default level WARNING will filter out all logger handlers DEBUG and INFO messages
"""
logger.setLevel(logging.DEBUG)
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.DEBUG)
console_format = logging.Formatter('%(asctime)s | %(levelname)-8s | %(message)s')
console_handler.setFormatter(console_format)
# configure file handler
file_handler = logging.FileHandler('/etc/openhab2/scripts/rock.log')
file_handler.setLevel(logging.DEBUG)
file_format = logging.Formatter('%(asctime)s | %(levelname)-8s | %(message)s')
file_handler.setFormatter(file_format)
# add handlers to logger with name: __name__
logger.addHandler(console_handler)
logger.addHandler(file_handler)
# ---------------------------------------------------------------------------------------------------------------------#


class RockInfo(object):

    def __init__(self):
        self.data = {}
        self.json_data = None
        self.get_soc_temp()

    def get_soc_temp(self):
        temps = psutil.sensors_temperatures()
        soc_temp_1 = temps['soc-thermal']  # get list with soc temp params
        soc_temp_1 = soc_temp_1[0]  # get first list item - names tuple
        soc_temp_1 = soc_temp_1[1]  # get second tuple item - current (temp)
        soc_temp_2 = subprocess.Popen("cat /sys/class/thermal/thermal_zone0/temp", shell=True, stdout=subprocess.PIPE)
        soc_temp_2 = soc_temp_2.stdout.read().decode('utf-8')
        soc_temp_2 = (int(soc_temp_2) / 1000)
        self.data["soc_temp_1"] = round(soc_temp_1, 2)
        self.data["soc_temp_2"] = round(soc_temp_2, 2)
        self.data["soc_temp"]   = round((soc_temp_1 + soc_temp_2) / 2, 2)
        return self.data["soc_temp"]

    def get_nvme_temp(self):
        pass


class FanControl(object):

    def __init__(self):
        self.data = {}
        self.json_data = ""
        self.soc_temp_1 = 30
        self.soc_temp_2 = 30
        self.soc_temp_3 = 30
        self.soc_temp_4 = 30
        self.soc_temp_5 = 30
        self.soc_temp_med = 30
        self.update_soc_temp()

        # MQTT client
        self.client = None
        self.connect_mqtt()

        # init tacho
        self.tacho_pin = mraa.Gpio(TACHO_PIN)
        self.tacho_pin.dir(mraa.DIR_IN)

        # init pwm
        self.getting_cold = True
        self.pwm_period = PWM_PERIOD
        self.pwm_pulsewidth = PW_INIT
        self.fan_speed = 0
        self.pwm_pin = mraa.Pwm(PWM_PIN)
        self.pwm_pin.period_us(self.pwm_period)
        self.pwm_pin.enable(True)
        self.pwm_pin.pulsewidth_us(self.pwm_pulsewidth)
        self.data['pulsewidth'] = self.pwm_pulsewidth
        self.pwm_pin.read()
        time.sleep(5)
        self.get_fan_speed()
        self.json_pack()
        self.publish_mqtt()
        logger.info("Init: soc temperature: %.2f*C, pulsewidth: %d, fan speed: %drpm." % (self.data['soc_temp'],
                                                                                          self.data['pulsewidth'],
                                                                                          self.data['fan_speed']))
        time.sleep(10)

        # run script continuously
        self.run()

    def update_soc_temp(self):
        rock_info = RockInfo()
        self.soc_temp_5 = self.soc_temp_4
        self.soc_temp_4 = self.soc_temp_3
        self.soc_temp_3 = self.soc_temp_2
        self.soc_temp_2 = self.soc_temp_1
        self.soc_temp_1 = rock_info.get_soc_temp()
        self.soc_temp_med = round((self.soc_temp_1 +
                                   self.soc_temp_2 +
                                   self.soc_temp_3 +
                                   self.soc_temp_4 +
                                   self.soc_temp_5) / 5, 2)
        self.data['soc_temp'] = self.soc_temp_med
        # print(self.soc_temp_1, "soc temp 1\n",
        #       self.soc_temp_2, "soc temp 2\n",
        #       self.soc_temp_3, "soc temp 3\n",
        #       self.soc_temp_4, "soc temp 4\n",
        #       self.soc_temp_5, "soc temp 5\n",
        #       self.soc_temp_med, "soc temp med")

    def get_fan_speed(self):
        low = True
        pulse = 0

        time_start = time.time() * 1000
        while time.time() * 1000 - time_start < 500:
            while self.tacho_pin.read() == 0:
                low = True
            while self.tacho_pin.read() == 1:
                if low:
                    pulse += 1
                low = False
        #print("Pulse count %d." % pulse)
        fan_speed = (pulse * 2 * 60 / 2)
        self.fan_speed = fan_speed
        self.data['fan_speed'] = self.fan_speed

    def json_pack(self):
        self.json_data = json.dumps(self.data)
        #print(self.json_data)

    def connect_mqtt(self):
        self.client = mqtt.Client()
        self.client.username_pw_set('fan_control', 'f4nnoctuA')
        self.client.on_connect = self.on_connect
        self.client.connect("192.168.1.32", 1883, 60)

    @staticmethod
    def on_connect(self, userdata, flags, rc):
        print('connected (%s)')

    def publish_mqtt(self):
        self.client.connect("192.168.1.32", 1883, 60)
        self.client.publish("fan/data", self.json_data)

    def run(self):
        temp_confirm = 0
        while True:
            self.update_soc_temp()
            self.get_fan_speed()

            if self.getting_cold:
                logger.info("Getting cold - check if temp is below 30: current temperature %.2f > threshold %d : %s."
                            % (self.data['soc_temp'], TEMP_MIN, self.data['soc_temp'] > TEMP_MIN))
                if self.data['soc_temp'] > TEMP_MIN:
                    temp_confirm += 1 if temp_confirm != 3 else 3
                    logger.info("Getting cold - temp is above 30, need to speed up fan.")
                    logger.info("Current pulse width is %d and fan speed is %d rpm. Confirm is %d."
                                % (self.pwm_pulsewidth, self.fan_speed, temp_confirm))
                    if self.pwm_pulsewidth - 1 >= PW_MIN and temp_confirm == 3:
                        self.pwm_pulsewidth -= 1
                        temp_confirm = 0
                        self.pwm_pin.pulsewidth_us(self.pwm_pulsewidth)
                        self.get_fan_speed()
                        logger.info("After change pulse width is %d and fan speed is %d rpm."
                                    % (self.pwm_pulsewidth, self.fan_speed))
                    else:  # PWM pulsewidth would hit low value of 5
                        logger.info("Pulse width stays %d and fan speed is %d rpm."
                                    % (self.pwm_pulsewidth, self.fan_speed))
                else:
                    logger.info("Getting cold - temp is below 30, can slow down fan. Change getting_cold to False.")
                    self.getting_cold = False
                    temp_confirm = 0

            elif not self.getting_cold:
                logger.info("Getting hot - check if temp is above 35: current temperature %f < threshold %d : %s."
                            % (self.data['soc_temp'], TEMP_MAX, self.data['soc_temp'] < TEMP_MAX))

                if self.data['soc_temp'] < TEMP_MAX:
                    temp_confirm += 1 if temp_confirm != 3 else 3
                    logger.info("Getting hot - temp is below 35, can slow down fan.")
                    logger.info("Current pulse width is %d and fan speed is %d rpm. Confirm is %d."
                                % (self.pwm_pulsewidth, self.fan_speed, temp_confirm))
                    if self.pwm_pulsewidth + 1 <= PW_MAX and temp_confirm == 3:
                        self.pwm_pulsewidth += 1
                        temp_confirm = 0
                        self.pwm_pin.pulsewidth_us(self.pwm_pulsewidth)
                        self.get_fan_speed()
                        logger.info("After change pulse width is %d and fan speed is %d rpm."
                                    % (self.pwm_pulsewidth, self.fan_speed))
                    else:  # PWM pulsewidth would hit high value of 35
                        logger.info("Pulse width stays %d and fan speed is %d rpm."
                                    % (self.pwm_pulsewidth, self.fan_speed))
                else:
                    logger.info("Getting hot - temp is above 35, need to speed up fan. Change getting_cold to True.")
                    self.getting_cold = True
                    temp_confirm = 0

            self.data['pulsewidth'] = self.pwm_pulsewidth
            self.json_pack()
            logger.debug("Json pack: %s" % self.json_data)
            self.publish_mqtt()
            time.sleep(120)


if __name__ == "__main__":
    fan_control = FanControl()
