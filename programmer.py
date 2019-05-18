#! /usr/bin/python3

# This utility constructs a database of devices and commands,
# then uses an IR controller to collect IR codes to be associated
# with their respective device commands.

import sys
import re
import broadlink
import signal
import mysql.connector
import os
import time

def prompt(text):
	sys.stdout.write(text + " ")
	sys.stdout.flush()
	
def yesno():
	resp = sys.stdin.readline().strip()
	match = re.search("[yY]", resp)
	return match

def upcase(str):
	return str.upper()

def get_list(pat):
	while True:
		line = sys.stdin.readline().strip()
		if len(line) == 0:
			print("Please provide at least one item, or cancel out.")
			continue
		items = list(map(upcase, re.split(pat, line)))
		if len(items) == 0:
			print("Please provide at least one items, or cancel out.")
			continue
		return items

def header(text):
	print("\n---------------------")
	print(text + "...\n")

def cancel(signum, frame):
	print("\ncancelled")
	sys.exit(0)

def open_db():
	return mysql.connector.connect(user="root", database="black-bean")

def find_ip(mac_address):
	lmac_address = mac_address.lower()
	pipe = os.popen("/usr/sbin/arp -na")
	ip_address = None
	for line in pipe.read().split("\n"):
		match = re.search("\\(([^\\)]+)\\) at ([0-9a-f:]+)", line)
		if match and (match.group(2) == lmac_address):
			ip_address = match.group(1)
			break
	pipe.close
	return ip_address

def mac_array(mac_address):
	# convert colon-delimited hex MAC address to byte array
	parts = mac_address.split(":")
	array = bytearray()
	for piece in parts:
		array.append(int(piece, 16))
	return array

def open_controller(name):
	# open IR controller
	dbh = open_db()
	c = dbh.cursor()
	c.execute("""select ip_addr, port, mac_addr, device_type, timeout
			from controllers
			where (name='%s')""" % name)
	data = c.fetchone()
	dbh.close()
	if data == None:
		print("no such controller '" + name + "'")
		return None
	mac_addr = str(data[2])
	ip_addr = find_ip(mac_addr)
	if ip_addr == None:
		ip_addr = str(data[0])
		print("couldn't discover controller '" + name +
			"' IP address, fall back to database setting " + ip_addr)
	port = int(data[1])
	dev = int(data[3])
	mac_bytes = mac_array(str(data[2]))
	controller = broadlink.rm((ip_addr, port), mac_bytes, dev)
	try:
		controller.auth()
	except:
		controller = None
	return controller

def to_hex(byte_array):
	string = ""
	for byte in byte_array:
		string += "%02x" % byte
	return string

def learn(controller, timeout):
	controller.enter_learning()
	interval = 0.5
	ticks = int(timeout / interval)
	for i in range(ticks):
		learned = controller.check_data()
		if learned == None:
			time.sleep(interval)
			continue
	if learned == None:
		encoded = None
	else:
		encoded = to_hex(learned)
	return encoded

def test_controller(timeout):
	print("point and shoot...")
	controller = open_controller("blackbean")
	ir_code = learn(controller, timeout)
	print(str(ir_code))

signal.signal(signal.SIGINT, cancel)
signal.signal(signal.SIGTERM, cancel)

learn_timeout = 20

devices = []

header("Set up devices")

while True:
	prompt("List of devices:")
	devices = get_list("[^\\w]")
	prompt("Devices " + ", ".join(devices) + ": correct?")
	if yesno():
		break


header("Set up device commands")

command_set = {}

for device in devices:
	while True:
		prompt("List commands for device '" + device + "':")
		commands = get_list("[, ]")
		prompt("Commands for '" + device + "': " +
			", ".join(commands) + ": correct?")
		if yesno():
			command_set[device] = commands
			break

controller = open_controller("blackbean")
commands = {}

header("Get ready to learn (hit Enter)...")
sys.stdin.readline()

for device in devices:
	for command in command_set[device]:
		while True:
			prompt("Learn " + device + ":" + command)
			ir_code = learn(controller, learn_timeout)
			if ir_code == None:
				sys.stdout.write(" failed\n")
				continue
			else:
				commands[device + ":" + command] = ir_code
				sys.stdout.write(" got it\n")
				break

header("Building database...")

dbh = open_db()
c = dbh.cursor()
c.execute("delete from devices")
c.execute("delete from commands")

for device in devices:
	c.execute("insert into devices (name) values ('" + device + "')")
	dev_id = c.lastrowid
	print(device + "(" + str(dev_id) + "):")
	for command in command_set[device]:
		key = device + ":" + command
		c.execute("""insert into commands (device, command, code)
			values (%d, '%s', '%s')""" % (dev_id, command, commands[key]))
		print("\t" + command + ": " + commands[key])

dbh.commit()
c.close()
dbh.close()

header("Done.")
