# TODO: Add an appropriate license to your skill before publishing.  See
# the LICENSE file for more information.

# Below is the list of outside modules you'll be using in your skill.
# They might be built-in to Python, from mycroft-core or from external
# libraries.  If you use an external library, be sure to include it
# in the requirements.txt file so the library is installed properly
# when the skill gets installed later by a user.

from adapt.intent import IntentBuilder
from mycroft.skills.core import MycroftSkill, intent_handler
from mycroft.util.log import LOG
from mycroft.util.log import getLogger
import broadlink
import sys
import os
import time
import binascii
import string
import threading
import queue
import re
import mysql.connector

__author__ = 'pmyadlowsky'
LOGGER = getLogger(__name__)
Digits = {
	'one': 1,
	'two': 2,
	'three': 3,
	'four': 4,
	'for': 4,
	'five': 5,
	'six': 6,
	'seven': 7,
	'eight': 8,
	'nine': 9,
	'ten': 10
	}

# Each skill is contained within its own class, which inherits base methods
# from the MycroftSkill class.  You extend this class as shown below.

class BlackBeanSkill(MycroftSkill):

    # The constructor of the skill, which calls MycroftSkill's constructor
	def __init__(self):
		super(BlackBeanSkill, self).__init__(name="BlackBeanSkill")
		self.controller = None
		self.use_command_thread = True
		self.controller_thread = None
		self.scan_thread = None
		self.scanning = False
		self.controller_thread_running = False
		self.command_queue = queue.Queue()

    # The "handle_xxxx_intent" function is triggered by Mycroft when the
    # skill's intent is matched.  The intent is defined by the IntentBuilder()
    # pieces, and is triggered when the user's utterance matches the pattern
    # defined by the keywords.  In this case, the match occurs when one word
    # is found from each of the files:
    #    vocab/en-us/Hello.voc
    #    vocab/en-us/World.voc
    # In this example that means it would match on utterances like:
    #   'Hello world'
    #   'Howdy you great big world'
    #   'Greetings planet earth'

    # The "stop" method defines what Mycroft does when told to stop during
    # the skill's execution. In this case, since the skill's functionality
    # is extremely simple, there is no need to override it.  If you DO
    # need to implement stop, you should return True to indicate you handled
    # it.
    #
	def stop(self):
		if self.controller_thread_running:
			self.controller_thread_running = False
			self.controller_thread.join()
		self.stop_scan_thread()
		return True

	def probe_net(self):
		# Try to determine interface wlan0's IP address,
		# then use that and nmap to populate the ARP cache.
		# This is to help mycroft skills look up local
		# device IP addresses by their MAC addresses.
		pipe = os.popen("ip addr|grep wlan0|grep inet")
		line = pipe.read()
		pipe.close()
		match = re.search("inet ([0-9\\.]+)", line)
		if match:
			LOG.info("PROBE LOCAL NET...")
			ip_addr = match.group(1)
			os.system("/usr/bin/nmap >/dev/null 2>&1 -sn " +
				re.sub("\\d+$", "0/24", ip_addr))
			LOG.info("PROBE DONE")
		else:
			LOG.info("could not determine local wifi network")

	def mac_array(self, mac_address):
		# convert colon-delimited hex MAC address to byte array
		parts = mac_address.split(":")
		array = bytearray()
		for piece in parts:
			array.append(int(piece, 16))
		return array

	def open_db(self):
		return mysql.connector.connect(
			user=self.settings.get("ir-database-user", "root"),
			database=self.settings.get("ir-database", "black-bean")
			)

	def find_ip(self, mac_address):
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

	def open_controller(self, name):
		# open IR controller
		dbh = self.open_db()
		c = dbh.cursor()
		c.execute("""select ip_addr, port, mac_addr, device_type, timeout
				from controllers
				where (name='%s')""" % name)
		data = c.fetchone()
		dbh.close()
		if data == None:
			LOG.info("no such controller '" + name + "'")
			return None
		mac_addr = str(data[2])
		ip_addr = self.find_ip(mac_addr)
		if ip_addr == None:
			ip_addr = str(data[0])
			LOG.info("couldn't discover controller '" + name +
				"' IP address, fall back to database setting " + ip_addr)
		port = int(data[1])
		dev = int(data[3])
		mac_bytes = self.mac_array(str(data[2]))
		controller = broadlink.rm((ip_addr, port), mac_bytes, dev)
		try:
			controller.auth()
		except:
			controller = None
		return controller

	def parse_command(self, src):
		parts = src.split(':') # device, cmd
		if len(parts) != 2:
			LOG.debug("malformed command: '" + src + "'")
			return (None, None)
		return (parts[0], parts[1])

	def get_device_id(self, device, cursor):
		cursor.execute("select id from devices where name='%s'" % device)
		data = cursor.fetchone()
		if data == None:
			return None
		else:
			return int(data[0])

	def get_command_code(self, command):
		# look up IR code for given device and command
		(device, cmd) = self.parse_command(command)
		if device == None:
			return None
		dbh = self.open_db()
		c = dbh.cursor()
		dev_id = self.get_device_id(device, c)
		if dev_id == None:
			LOG.info("no such device '" + device + "'")
			dbh.close()
			return None
		c.execute("""select code
				from commands
				where (command='%s')
				and (device=%d)""" % (cmd, dev_id))
		data = c.fetchone()
		if data == None:
			LOG.info("no such command for '" + device + "': '" + cmd + "'")
			dbh.close()
			return None
		code = str(data[0])
		dbh.close()
		return code

	def is_delay(self, cmd):
		# command stream may embed msec delays coded as "(<n>)"
		m = re.search("^\((\d+)\)$", cmd)
		if m:
			return (True, int(m.group(1)))
		else:
			return (False, 0)

	def collect_command_codes(self, command, history):
		# recursively collect IR codes from command stream
		(delay, ms) = self.is_delay(command)
		if delay:
			return [command]
		code = self.get_command_code(command)
		if code == None:
			return []
		m = re.search("^\\[([^\\]\\[]+)\\]$", code)
		if m: # command sequence
			if command in history: # infinite recursion
				LOG.info("command loop detected: " + command)
				return []
			else: # remember this command
				history.append(command)
			group = m.group(1).split(",")
			bag = []
			for cmd in group:
				bag.extend(self.collect_command_codes(cmd, history))
			return bag
		else: # IR code
			return [code]

	def send_command(self, command_list):
		# send IR code sequence to IR controller
		command_stream = command_list.split(",")
		commands = []
		for cmd in command_stream:
			commands.extend(self.collect_command_codes(cmd, []))
		for cmd in commands:
			(delay, msec) = self.is_delay(cmd)
			if delay:
				time.sleep(msec / 1000.0)
			else:
				decoded = binascii.a2b_hex(cmd)
				if self.use_command_thread:
					self.command_queue.put(decoded)
				else:
					self.controller.send_data(decoded)

	def pruned_message(self, msg_obj, verb_keys):
		# remove known verbs found in utterance, returning
		# the remainder
		words = msg_obj.data['utterance'].split(" ")
		for key in verb_keys:
			words.remove(msg_obj.data[key])
		return words

	def wring_number(self, words):
		# search words for numeric content, reduce and evaluate
		if len(words) == 0:
			return None
		dgt = []
		for word in words:
			if word in Digits:
				dgt.append(str(Digits[word]))
			else:
				dgt.append(word)
		mash = re.sub("[^\\d]", "", "".join(dgt)) # strip non-digits
		if mash == "":
			return None
		else:
			return int(mash)
			
	def compose_intent(self, verbs):
		# compose intent object from list of vocab verbs
		builder = IntentBuilder("_".join(verbs))
		for verb in verbs:
			builder.require(verb)
		return builder.build()
		
	def repeat_command(self, command, reps):
			if reps == None:
				return command
			command_stream = []
			for i in range(reps):
				command_stream.append(command)
			return ",".join(command_stream)

	def vary_command(self, command, digits):
			if digits == None:
				return command
			command_stream = []
			for digit in str(digits):
				command_stream.append(command + digit)
			return ",".join(command_stream)

	def compose_handler(self, verbs, directives, command, response):
		# compose intent handler as a closure
		def handler(message):
#			LOG.info("HMSG " + str(message.data))
			words = self.pruned_message(message, verbs)
			count = self.wring_number(words)
			LOG.info("PRUNED " + str(words))
			LOG.info("DIRECTIVES " + str(directives))
			command_stream = command
			for directive in directives:
				if directive == "REP":
					command_stream = self.repeat_command(command, count)
				elif directive == "DIGITS":
					command_stream = self.vary_command(command, count)
#			LOG.info("STREAM " + command_stream)
			if command == "":
				LOG.info("NULL COMMAND")
			else:
				self.send_command(command_stream)
			self.speak_dialog(response)
		return handler
			
	def add_command(self, verbs, device_command, response):
		proper_verbs = []
		directives = []
		for verb in verbs:
			if verb[0] == '#':
				directives.append(verb[1:])
			else:
				proper_verbs.append(verb)
		self.register_intent(
			self.compose_intent(proper_verbs),
			self.compose_handler(proper_verbs, directives,
				device_command, response))

	def process_commands(self):
		LOG.info("ENTER COMMAND THREAD")
		self.controller_thread_running = True
		while self.controller_thread_running:
			try:
				code = self.command_queue.get(timeout=2.0)
				if self.controller != None:
					LOG.info("send " + str(len(code)) + " bytes")
					self.controller.send_data(code)
			except queue.Empty:
				continue
			except Exception as exc:
				LOG.info("PROCESS LOOP FAILED: " + str(exc))
				break
		LOG.info("EXIT COMMAND THREAD")
		return

	def channel_scanner(self, command):
		interval = int(self.settings.get("scan-interval", "10"))
		LOG.info("SCAN INTERVAL " + str(interval))
		self.scanning = True
		while self.scanning:
			LOG.info("SCAN " + command)
			self.send_command(command)
			for i in range(interval):
				time.sleep(1.0)
				if not self.scanning:
					break
		LOG.info("SCANNER STOPPED")
		return

	def initialize(self):
		# compose verbal command grammar and command responses
		self.probe_net()
		if self.use_command_thread:
			self.controller_thread = \
				threading.Thread(None, self.process_commands)
			self.controller_thread.start()
		self.add_command(["TV", "Power"], "TV:PWR", "power.toggle")
		self.add_command(["TV", "Mute"], "TV:MUTE", "mute.toggle")
		self.add_command(["Channel", "Up"], "TV:CH+", "next.channel")
		self.add_command(["Channel", "Down"], "TV:CH-", "previous.channel")
		self.add_command(["Channel", "#DIGITS"],
			"TV:CHAN", "change.channel")
		self.add_command(["TV", "Volume", "Up", "#REP"],
			"TV:VOL+", "volume.up")
		self.add_command(["TV", "Volume", "Down", "#REP"],
			"TV:VOL-", "volume.down")
		self.register_intent(self.compose_intent(["TV", "Controllers"]),
			self.handle_find_controllers)
		self.register_intent(
			self.compose_intent(["Scan", "Channel", "Up"]),
			self.handle_start_scan_forward)
		self.register_intent(
			self.compose_intent(["Scan", "Channel", "Down"]),
			self.handle_start_scan_back)
		self.register_intent(self.compose_intent(["Stop", "Scan"]),
			self.handle_stop_scan)
		self.find_controllers()
		name = self.settings.get("default-controller", "blackbean")
		self.controller = self.open_controller(name)
		if self.controller == None:
			LOG.info("IR controller '" + name + "' unresponsive")
		else:
			LOG.info("IR controller '" + name + "' opened")

	def update_controller_ipaddr(self, cursor, cname, ip):
		query = "update controllers set ip_addr='" + ip + "'" + \
			" where (name='" + cname + "')"
		cursor.execute(query)

	def find_controllers(self):
		dbh = self.open_db()
		c = dbh.cursor()
		c.execute("select name, mac_addr from controllers")
		rows = c.fetchall()
		for row in rows:
			name = str(row[0])
			mac = str(row[1])
			ip = self.find_ip(mac)
			if ip == None:
				ip_display = "<unknown IP>"
			else:
				ip_display = ip
			controller = self.open_controller(name)
			if controller == None:
				status = "not ready"
			else:
				if ip != None:
					self.update_controller_ipaddr(c, name, ip)
				status = "ready"
			LOG.info("IR controller '" + name + "' at " +
				ip_display + ": " + status)
		dbh.close()

	def handle_find_controllers(self, message):
		self.find_controllers()
		self.speak_dialog("scan.controllers")

	def stop_scan_thread(self):
		if self.scanning:
			self.scanning = False
			self.scan_thread.join()

	def handle_start_scan_forward(self, message):
		self.stop_scan_thread()
		self.scan_thread = threading.Thread(
			target=self.channel_scanner, args=("TV:CH+",))
		self.scan_thread.start()
		self.speak_dialog("begin.scanning")
		return

	def handle_start_scan_back(self, message):
		self.stop_scan_thread()
		self.scan_thread = threading.Thread(
			target=self.channel_scanner, args=("TV:CH-",))
		self.scan_thread.start()
		self.speak_dialog("begin.scanning")
		return

	def handle_stop_scan(self, message):
		self.stop_scan_thread()
		self.speak_dialog("stop.scanning")
		return
		
# The "create_skill()" method is used to create an instance of the skill.
# Note that it's outside the class itself.
def create_skill():
	return BlackBeanSkill()
