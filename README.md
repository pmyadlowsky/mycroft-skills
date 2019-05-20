# <img src='https://raw.githack.com/FortAwesome/Font-Awesome/master/svgs/solid/robot.svg' card_color='#40DBB0' width='50' height='50' style='vertical-align:bottom'/> Black Bean
Skill for Broadlink Black Bean infrared controller

## About
This skill uses the [python-broadlink](https://github.com/mjg59/python-broadlink) RM2 IR controller API to drive a Broadlink Black Bean RM Mini3, mainly for TV control though could certainly be adapted for other appliance types.

One objective is to make this skill as data-driven as possible, so intent handlers are composed at initialization time by generating them as closures rather than hard-coding them. A data grammar is devised that should cover a wide range of control needs.

Configuration data for IR controllers, IR receivers (devices) and device commands is stored in sqlite3 database ~/.mycroft/skills/BlackBeanSkill/config.db
## Examples

## Credits

## Category
**IoT**

## Tags
#blackbean
#ircontrol
