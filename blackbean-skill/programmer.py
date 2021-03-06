#! /usr/bin/python3

# This utility constructs a database of devices and commands,
# then uses an IR controller to collect IR codes to be associated
# with their respective device commands.

import sys
import re
import broadlink
import signal
import sqlite3
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

def get_list(pat, force_upcase = True):
	while True:
		line = sys.stdin.readline().strip()
		if len(line) == 0:
			return []
		if force_upcase:
			items = list(map(upcase, re.split(pat, line)))
		else:
			items = re.split(pat, line)
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

def init_db(dbh):
	file = open("schema.sqlite3")
	sql = file.read()
	file.close()
	c = dbh.cursor()
	c.executescript(sql)
	c.close()

def open_db():
	path = "/home/mycroft/.mycroft/skills/BlackBeanSkill/config.db"
	dbh = sqlite3.connect(path)
	c = dbh.cursor()
	try:
		c.execute("select count(*) from controllers")
		c.execute("select count(*) from devices")
		c.execute("select count(*) from commands")
		c.close()
	except sqlite3.OperationalError:
		print("initialize database at ", path)
		c.close()
		init_db(dbh)
		dbh.close()
		return open_db()
	except:
		print("unexpected error: ", sys.exc_info()[0])
		dbh.close()
		return None
	return dbh

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
	c.close()
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

def command_seq(commands):
	return "[" + ",".join(commands) + "]"

def get_device_id(device, cursor):
	cursor.execute("select id from devices where name='%s'" % device)
	data = cursor.fetchone()
	if data == None:
		return None
	else:
		return int(data[0])

def get_controller_id(controller, cursor):
	cursor.execute("""select id from controllers
		where name='%s'""" % controller['name'])
	data = cursor.fetchone()
	if data == None:
		return None
	else:
		return int(data[0])

def learn_device(device, commands, controller, timeout):
	db = None
	for command in commands:
		while True:
			prompt("Learn " + device + ":" + command)
			ir_code = learn(controller, timeout)
			if ir_code == None:
				sys.stdout.write("failed\n")
				continue
			else:
				if db == None:
					db = {}
				db[device + ":" + command] = ir_code
				sys.stdout.write("got it\n")
				break
	return db

def validate_command(device_cmd, cursor):
	try:
		(device, cmd) = device_cmd.split(":")
	except:
		print("invalid DEV:CMD command")
		return False
	cursor.execute("""select commands.id as id
		from commands, devices
		where (devices.name='%s')
		and (commands.command='%s')
		and (commands.device=devices.id)""" % (device, cmd))
	data = cursor.fetchone()
	return (data != None)
	
def get_command_list(device):
	while True:
		prompt("List commands for device/group '" + device + "':")
		commands = get_list("[, ]")
		if len(commands) == 0:
			return []
		prompt("Commands for '" + device + "': " +
			", ".join(commands) + ": correct?")
		if yesno():
			return commands

def dump_controller(obj):
	print("Controller '" + obj['name'] + "':")
	print("\tIP address:  " + obj['ip_addr'])
	print("\tMAC address: " + obj['mac_addr'])
	print("\tIP port:     " + str(obj['port']))
	print("\ttimeout:     " + str(obj['timeout']))
	print("\tdevice type: " + str(obj['device_type']))

def save_device(cursor, device, command_set, command_db):
	dev_id = get_device_id(device, cursor)
	if dev_id == None:
		cursor.execute("insert into devices (name) values ('" +
			device + "')")
		dev_id = cursor.lastrowid
	print("\n" + device + "(" + str(dev_id) + "):")
	for command in command_set:
		cursor.execute("delete from commands where (device=" +
			str(dev_id) + ") and (command='" + command + "')")
		key = device + ":" + command
		cursor.execute("""insert into commands (device, command, code)
			values (%d, '%s', '%s')""" %
				(dev_id, command, command_db[key]))
		print("\t" + command + ": " + str(command_db[key]))

def save_controller(cursor, controller):
	con_id = get_controller_id(controller, cursor)
	if con_id == None:
		c.execute("insert into controllers (name) values ('" +
			controller['name'] + "')")
		con_id = c.lastrowid
	cursor.execute("""update controllers set
			ip_addr='%s',
			mac_addr='%s',
			port=%d,
			timeout=%d,
			device_type=%d
			where id=%d""" % (controller['ip_addr'],
				controller['mac_addr'], 
				int(controller['port']),
				int(controller['timeout']),
				int(controller['device_type']), con_id))

def test_controller(timeout):
	print("point and shoot...")
	controller = open_controller("blackbean")
	ir_code = learn(controller, timeout)
	print(str(ir_code))

signal.signal(signal.SIGINT, cancel)
signal.signal(signal.SIGTERM, cancel)

learn_timeout = 20
devices = []
device_groups = []
controllers = []

header("Set up controllers")

while True:
	prompt("List of controllers:")
	items = get_list("[^\\w]", force_upcase=False)
	if len(items) == 0:
		break
	prompt("Controllers " + ", ".join(items) + ": correct?")
	if yesno():
		for item in items:
			controllers.append({'name': item})
		break

if len(controllers) > 0:
	dbh = open_db()
	c = dbh.cursor()
	for controller in controllers:
		while True:
			print("Configure controller '" + controller['name'] + "'...")
			prompt("\tIP address:")
			controller['ip_addr'] = sys.stdin.readline().strip()
			prompt("\tMAC address:")
			controller['mac_addr'] = sys.stdin.readline().strip()
			prompt("\tIP port:")
			controller['port'] = int(sys.stdin.readline().strip())
			prompt("\ttimeout:")
			controller['timeout'] = int(sys.stdin.readline().strip())
			prompt("\tdevice type:")
			controller['device_type'] = int(sys.stdin.readline().strip())
			dump_controller(controller)
			prompt("configuration correct?")
			if yesno():
				save_controller(c, controller)
				break
	c.close()
	dbh.commit()
	dbh.close

header("Set up devices/groups")

while True:
	prompt("List of devices ('@' marks device group):")
	items = get_list("[^\\w@]")
	if len(items) == 0:
		break
	prompt("Devices " + ", ".join(items) + ": correct?")
	if yesno():
		for item in items:
			match = re.search("^@(.+)", item)
			if match:
				device_groups.append(match.group(1))
			else:
				devices.append(item)
		break

if len(devices) > 0:
	header("Set up device commands")
	command_set = {}
	for device in devices:
		command_set[device] = get_command_list(device)
	controller = open_controller("blackbean")
	header("Aim remote at IR receiver (hit Enter when ready)...")
	sys.stdin.readline()
	dbh = open_db()
	c = dbh.cursor()
	for device in devices:
		db = learn_device(device, command_set[device],
					controller, learn_timeout)
		if db != None:
			save_device(c, device, command_set[device], db)
	c.close()
	dbh.commit()
	dbh.close()
	print("\nDevice IR programming done.")

if len(device_groups) > 0:
	header("Set up device group commands")
	command_set = {}
	for device in device_groups:
		command_set[device] = get_command_list(device)
	dbh = open_db()
	c = dbh.cursor()
	db = {}
	for device in device_groups:
		for command in command_set[device]:
			prompt("Command sequence for " + device + ":" + command)
			cmds = get_list("[, ]")
			valid = True
			for cmd in cmds:
				if not validate_command(cmd, c):
					valid = False
					break
			if valid:
				db[device + ":" + command] = command_seq(cmds)
		save_device(c, device, command_set[device], db)
	c.close()
	dbh.commit()
	dbh.close()

header("Done.")
