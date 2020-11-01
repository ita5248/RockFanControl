# RockFanControl
Rock Fan Control - PWM Noctua.
Python script to control PWM Noctua 5V fan. Runs in crontab after system startup. 
After every iteration pushes json data pack via MQTT for home assistant. 
Initial version, still working on temperature contro algorithim. Now it's very basic: temperature is measures every 120s, 
then moveing average for 5 last measurements is calculated. If temperature is is confirmed 3 time to be above threshold (or below) then PWM is changed to speed up / slow down fan.
Temeperature threshold is hysteresis.
GPIO and PWM control done by mraa for ROCK PI 4 MODEL B.
