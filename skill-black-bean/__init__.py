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
import re
import sqlite3

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
	'ten': 10,
	'alittle': 4,
	'alot': 10
	}

# Each skill is contained within its own class, which inherits base methods
# from the MycroftSkill class.  You extend this class as shown below.

class BlackBeanSkill(MycroftSkill):

    # The constructor of the skill, which calls MycroftSkill's constructor
	def __init__(self):
		super(BlackBeanSkill, self).__init__(name="BlackBeanSkill")
		self.controller_name = "blackbean"
		self.controller = None
		self.controller_timeout = None
		self.database = "/home/pmy/BlackBeanControl/bean.db"

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
    # def stop(self):
    #    return False
	def mac_array(self, mac_address):
		# convert colon-delimited hex MAC address to byte array
		parts = mac_address.split(":")
		array = bytearray()
		for piece in parts:
			array.append(int(piece, 16))
		return array
	def open_controller(self, name):
		# open Black Bean IR controller
		dbh = sqlite3.connect(self.database)
		c = dbh.cursor()
		c.execute("""select ip_addr, port, mac_addr, device_type, timeout
				from controllers
				where (name='%s')""" % name)
		data = c.fetchone()
		if data == None:
			LOG.info("no such controller '" + name + "'")
			dbh.close()
			return
		ip_addr = str(data[0])
		port = int(data[1])
		dev = int(data[3])
		mac_addr = self.mac_array(str(data[2]))
		self.controller = broadlink.rm((ip_addr, port), mac_addr, dev)
		self.controller.auth()
		self.controller_timeout = data[4]
		dbh.close()
		return

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
		dbh = sqlite3.connect(self.database)
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

	def collect_command_codes(self, command, history = []):
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
				LOG.info("command loop detected")
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
			commands.extend(self.collect_command_codes(cmd))
		for cmd in commands:
			(delay, msec) = self.is_delay(cmd)
			if delay:
				time.sleep(msec / 1000.0)
			else:
				decoded = binascii.a2b_hex(cmd)
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
				dgt.append(str(Digits['word']))
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
		
	def compose_handler(self, command, response):
		# compose intent handler as a closure
		def handler(message):
			LOG.info("HMSG " + str(message.data))
			self.send_command(command)
			self.speak_dialog(response)
		return handler
			
	def initialize(self):
		# compose verbal command grammar and command responses
		self.register_intent(
			self.compose_intent(["TV", "Power"]),
			self.compose_handler("TV:PWR", "bean.ok"))
		self.register_intent(
			self.compose_intent(["TV", "Mute"]),
			self.compose_handler("TV:MUTE", "bean.ok"))
		self.register_intent(
			self.compose_intent(["TV", "Channel", "Right"]),
			self.compose_handler("TV:CH+", "bean.ok"))
		self.register_intent(
			self.compose_intent(["TV", "Channel", "Left"]),
			self.compose_handler("TV:CH-", "bean.ok"))
		self.register_intent(
			self.compose_intent(["TV", "Volume", "Dir"]),
			self.handle_tv_volume_intent)
		self.open_controller(self.controller_name)
		LOG.info("IR controller opened: " + str(self.controller))

	def handle_tv_volume_intent(self, message):
		LOG.info("MSG " + str(message.data))
		direction = message.data['Dir']
		if (direction == "up") or (direction == "plus"):
			command = "TV:VOL+"
		else:
			command = "TV:VOL-"
		words = self.pruned_message(message, ["TV", "Volume", "Dir"])
		amount = self.wring_number(words)
		LOG.info("amount |" + str(amount) + "|")
		if amount == None:
			amount = 3
		LOG.info("VOLUME " + direction + " " + str(amount))
		self.speak_dialog("bean.ok")
		reps = []
		for i in range(amount):
			reps.append(command)
		self.send_command(",".join(reps))

# The "create_skill()" method is used to create an instance of the skill.
# Note that it's outside the class itself.
def create_skill():
	return BlackBeanSkill()
