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
import broadlink
import sys
import time
import string
import re
import sqlite3

__author__ = 'pmyadlowsky'
LOGGER = getLogger(__name__)

# Each skill is contained within its own class, which inherits base methods
# from the MycroftSkill class.  You extend this class as shown below.

# TODO: Change "Template" to a unique name for your skill
class BlackBeanSkill(MycroftSkill):

    # The constructor of the skill, which calls MycroftSkill's constructor
	def __init__(self):
		super(BlackBeanSkill, self).__init__(name="BlackBeanSkill")
		self.controller_name = "blackbean"
		self.controller = None
		self.controller_timeout = None
		self.database = "/home/pmy/BlackBeanControl/bean.db"
        
        # Initialize working variables used within the skill.
		self.count = 0

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
	@intent_handler(IntentBuilder("").require("Hello").require("World"))
	def handle_hello_world_intent(self, message):
        # In this case, respond by simply speaking a canned response.
        # Mycroft will randomly speak one of the lines from the file
        #    dialogs/en-us/hello.world.dialog
		self.speak_dialog("hello.world")

	@intent_handler(IntentBuilder("").require("Count").require("Dir"))
	def handle_count_intent(self, message):
		if message.data["Dir"] == "up":
			self.count += 1
		else:  # assume "down"
			self.count -= 1
		self.speak_dialog("count.is.now", data={"count": self.count})

	@intent_handler(IntentBuilder("").require("Bean"))
	def handle_bean_intent(self, message);
		self.speak_dialog("echo.bean")

    # The "stop" method defines what Mycroft does when told to stop during
    # the skill's execution. In this case, since the skill's functionality
    # is extremely simple, there is no need to override it.  If you DO
    # need to implement stop, you should return True to indicate you handled
    # it.
    #
    # def stop(self):
    #    return False
	def open_controller(name):
		dbh = sqlite3.connect(self.database)
		c = dbh.cursor()
		c.execute("""select ip_addr, port, mac_addr, device_type, timeout
				from controllers
				where (name='%s')""" % name)
		data = c.fetchone()
		if data == None:
			LOG.debug("no such controller '" + name + "'")
			dbh.close()
			return
		self.controller = broadlink.rm((str(data[0]), data[1]),
							str(data[2]), data[3])
		self.controller_timeout = data[4]
		dbh.close()
		return

	def parse_command(src):
		parts = src.split(':') # device, cmd
		if len(parts) != 2:
			LOG.debug("malformed command: '" + src + "'")
			return (None, None)
		return (parts[0], parts[1])

	def initialize():
		self.open_controller(self.controller_name)
		LOG.debug("IR controller opened")

# The "create_skill()" method is used to create an instance of the skill.
# Note that it's outside the class itself.
def create_skill():
	return BlackBeanSkill()
