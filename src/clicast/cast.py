import base64
from ConfigParser import ConfigParser
import os
import re
from StringIO import StringIO
import sys
import time
import tempfile

import requests


class CastError(Exception):
  pass


class Cast(object):
  """ Represents all cast options/messages. """

  ALERT_SECTION = 'Alert'
  MESSAGES_SECTION = 'Messages'
  ALERT_MSG_KEY = 'message'
  ALERT_EXIT_KEY = 'exit'
  MESSAGE_NEXT_KEY = '_next_key'

  class CastMessage(object):
    """ Represents a single message in a cast. """
    def __init__(self, key, message):
      """
      :param str key: Message key
      :param str message: The actual message
      """
      self.key = key
      self.message = message
    def __cmp__(a, b):
      try:
        return cmp(int(a.key), int(b.key))
      except Exception:
        return cmp(a.key, b.key)

  def __init__(self, alert=None, alert_exit=False, messages=None, next_msg_key=None):
    """
    :param str alert: Alert message
    :param bool alert_exit: Should client CLI exit. Ignored unless alert message is set.
    :param list(tuple) messages: List of tuple of (key, message)
    :param str next_msg_key: Next message key to use
    """
    self.alert = alert
    self.alert_exit = alert and alert_exit
    self.messages = messages and sorted([self.CastMessage(*m) for m in messages]) or []
    self._next_msg_key = next_msg_key and int(next_msg_key)

    # Always set this so that it can be used in :meth:`self.save`
    if self.messages and not self._next_msg_key:
      self._next_msg_key = int(self.next_msg_key(reserve_next=False))

  def add_msg(self, msg, alert=False, alert_exit=False):
    """
    :param str msg: The message to add or set
    :param bool alert: Indicates this is the alert message to set.
    :param bool alert_exit: Indicates this is the alert should request client to exit.
    """
    if alert or alert_exit:
      self.alert = msg
      self.alert_exit = alert_exit
    else:
      self.messages.append(self.CastMessage(self.next_msg_key(), msg))

  def del_msg(self, count=1, alert=False):
    if alert:
      self.alert = None
      self.alert_exit = None
      return 1
    else:
      before_count = len(self.messages)
      self.messages = self.messages[count:]
      return before_count - len(self.messages)

  def next_msg_key(self, reserve_next=True):
    """
      Returns the next message key and optionally reserves next one (default)

      :param bool reserve_next: Indicates the key after next should be reserved. Default behavior.
    """
    if not self._next_msg_key:
      keys = []

      for m in self.messages:
        try:
          keys.append(int(m.key))
        except Exception:
          pass

      if keys:
        self._next_msg_key = keys[-1] + 1
      else:
        self._next_msg_key = 1

    next_key = str(self._next_msg_key)

    if reserve_next:
      self._next_msg_key += 1

    return next_key

  @classmethod
  def from_string(cls, cast, msg_filter=None):
    """ Create a :class:`Cast` from the given string.

    :param str cast: Cast content
    :param callable msg_filter: Filter messages with callable that accepts message string and alert boolean (True for
                                alert message). It should return the original or an updated message, or None if the
                                message should be ignored.
    """
    cast_fp = StringIO(cast)
    parser = ConfigParser()
    parser.readfp(cast_fp)

    alert_msg = None
    alert_exit = None

    if cls.ALERT_SECTION in parser.sections():
      for key, value in parser.items(cls.ALERT_SECTION):
        if cls.ALERT_MSG_KEY == key:
          if msg_filter:
            value = msg_filter(value, True)
          alert_msg = value
        elif cls.ALERT_EXIT_KEY == key:
          alert_exit = bool(value)
        else:
          raise CastError('Invalid key "%s" in %s section', key, cls.ALERT_SECTION)

    messages = []
    next_msg_key = None

    if cls.MESSAGES_SECTION in parser.sections():
      for key, value in parser.items(cls.MESSAGES_SECTION):
        if key == cls.MESSAGE_NEXT_KEY:
          next_msg_key = value
        else:
          if msg_filter:
            value = msg_filter(value)
          if value:
            messages.append((key, value))

    return cls(alert_msg, alert_exit, messages, next_msg_key)

  @classmethod
  def from_file(cls, cast_file, msg_filter=None):
    """ Create a :class:`Cast` from the given file. """
    with open(cast_file) as fp:
      return cls.from_string(fp.read(), msg_filter)

  @classmethod
  def from_url(cls, cast_url, msg_filter=None, cache_duration=None):
    """ Create a :class:`Cast` from the given url and optionally cache locally for given interval. """
    return cls.from_string(url_content(cast_url, cache_duration), msg_filter)

  def __str__(self):
    parser = ConfigParser()

    if self.alert:
      parser.add_section(self.ALERT_SECTION)
      parser.set(self.ALERT_SECTION, self.ALERT_MSG_KEY, self.alert)
      if self.alert_exit:
        parser.set(self.ALERT_SECTION, self.ALERT_EXIT_KEY, True)

    if self.messages:
      parser.add_section(self.MESSAGES_SECTION)
      for msg in self.messages:
        parser.set(self.MESSAGES_SECTION, msg.key, msg.message)

    elif self._next_msg_key:
      parser.add_section(self.MESSAGES_SECTION)
      parser.set(self.MESSAGES_SECTION, self.MESSAGE_NEXT_KEY, self._next_msg_key)

    sio = StringIO()
    parser.write(sio)

    # And a bit of black magic to avoid writing our own parser / compensate for ConfigParser's lack of option
    tabspaces = len(str(self._next_msg_key)) + 2 if self._next_msg_key else 3
    content = sio.getvalue()
    content = _re_sub_multiline('^([\w]+) = ', '\\1: ', content)
    content = re.sub('\t', ' ' * tabspaces, content)

    return content.strip()

  def save(self, cast_file):
    """ Save the cast data to the given file. """
    with open(cast_file, 'w') as fp:
      fp.write(str(self) + '\n')


class CastReader(object):
  """ Reads a :class:`Cast` and keep track of read messages """

  READ_MSG_FILE = os.path.join(tempfile.gettempdir(), '%s.read_messages' % os.path.basename(sys.argv[0]))

  @classmethod
  def reset(cls):
    """ Resets read messages, so all messages will be displayed again. """
    if os.path.exists(cls.READ_MSG_FILE):
      os.unlink(cls.READ_MSG_FILE)

  def __init__(self, cast):
    self.cast = cast

  def show_messages(self, logger=None, header=None, footer=None):
    """ Print new messages to stdout unless a logger is given. """
    msgs = self.new_messages()

    if msgs:
      if logger:
        if header:
          logger.info(header)
        for msg in msgs:
          for line in msg.split('\n'):
            logger.info(line)
        if footer:
          logger.info(footer)

      else:
        if header:
          print header
        print '\n\n'.join(msgs)
        if footer:
          print footer

  def new_messages(self, mark_as_read=True):
    """
    :param bool mark_as_read: Mark new messages as read
    :ret list(str): List of new messages with alert being the first if any.
    """
    read_keys = self._read_msg_keys()
    new_messages = [m for m in self.cast.messages if m.key not in read_keys]

    if new_messages and mark_as_read:
      self._mark_as_read(new_messages)

    msgs = [m.message for m in new_messages]

    if self.cast.alert:
      msgs.insert(0, self.cast.alert)

    return msgs

  def _read_msg_keys(self):
    """ Set of read messages. """

    try:
      with open(self.READ_MSG_FILE) as fp:
        read_keys = fp.read()
        return set(read_keys.split())
    except Exception:
      return set()

  def _mark_as_read(self, messages):
    """ Mark the given list of :class:`CastMessage` as read. """

    keys = self._read_msg_keys()
    keys.update(m.key for m in messages)

    with open(self.READ_MSG_FILE, 'w') as fp:
      fp.write(' '.join(keys))


def _re_sub_multiline(pattern, repl, string):
  """ Simple hack to get multiline working in Python 2.6 and higher """
  try:
    content = re.sub(pattern, repl, string, flags=re.MULTILINE)
  except Exception:
    content = []
    for line in string.split('\n'):
      content.append(re.sub(pattern, repl, line))
    content = '\n'.join(content)

  return content


def _url_content_cache_file(url):
  return os.path.join(tempfile.gettempdir(), 'url-content-cache-%s' % base64.urlsafe_b64encode(url))


def url_content(url, cache_duration=None, from_cache_on_error=False):
  """
  Get content for the given URL

  :param str url: The URL to get content from
  :param int cache_duration: Optionally cache the content for the given duration to avoid downloading too often.
  :param bool from_cache_on_error: Return cached content on any HTTP request error if available.
  """
  cache_file = _url_content_cache_file(url)

  if cache_duration:
    if os.path.exists(cache_file):
      stat = os.stat(cache_file)
      cached_time = stat.st_mtime
      if time.time() - cached_time < cache_duration:
        with open(cache_file) as fp:
          return fp.read()

  try:
    response = requests.get(url)
    response.raise_for_status()
    content = response.text

  except Exception:
    if from_cache_on_error and os.path.exists(cache_file):
      with open(cache_file) as fp:
        return fp.read()
    else:
      raise


  if cache_duration or from_cache_on_error:
    with open(cache_file, 'w') as fp:
      fp.write(content)

  return content
