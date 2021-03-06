import os
import tempfile
import time

from mock import Mock, patch
import pytest

from clicast.cast import Cast, CastReader, url_content, _url_content_cache_file


CAST_URL = 'https://raw.githubusercontent.com/maxzheng/clicast/master/test/example.cast'
CAST_FILE = os.path.join(os.path.dirname(__file__), 'example.cast')

class TestCast(object):
  def test_from_file(self):
    cast = Cast.from_file(CAST_FILE)

    assert cast.alert == 'We found a big bad bug. Please try not to step on it!! Icky...\nNo worries. It will be fixed soon! :)'
    assert cast.alert_exit
    assert [m.message for m in cast.messages] == [
      'Version 0.1 has been released! If you upgrade, you will get:\n'
      '1) Cool feature 1\n'
      '2) Cool feature 2\n'
      'So what are you waiting for? :)',
      'Version 0.2 has been released! Upgrade today to get cool features.',
      'There is a small bug over there, so watch out!',
      '[-f\\b] A bug that affects the -f option. (applies only if `clicast.filters.match_cli_args` filter is used)'
    ]

  def test_save(self):
    from_content = open(CAST_FILE).read()
    cast = Cast.from_file(CAST_FILE)

    to_cast_file = os.path.join(tempfile.gettempdir(), 'clicast.to_file_test.cast')
    try:
      cast.save(to_cast_file)
      to_content = open(to_cast_file).read()
      assert from_content == to_content
    finally:
      if os.path.exists(to_cast_file):
        os.unlink(to_cast_file)

  def test_from_url(self):
    cast = Cast.from_url(CAST_URL)
    assert cast.messages

  def test_add_msg(self):
    cast = Cast()
    cast.add_msg('Message 1')
    cast.add_msg('Message Alert', alert=True)
    cast.add_msg('Message 2')

    assert cast.alert == 'Message Alert'
    assert cast.alert_exit == False
    assert [(m.key, m.message) for m in cast.messages] == [
      ('1', 'Message 1'),
      ('2', 'Message 2')
    ]

    cast.add_msg('Message Alert Exit', alert_exit=True)

    assert cast.alert == 'Message Alert Exit'
    assert cast.alert_exit == True

  def test_del_msg(self):
    cast = Cast()
    cast.add_msg('Message 1')
    cast.add_msg('Message 2')
    cast.add_msg('Message Alert', alert_exit=True)
    cast.del_msg()

    assert cast.alert == 'Message Alert'
    assert cast.alert_exit == True
    assert [(m.key, m.message) for m in cast.messages] == [('2', 'Message 2')]

    del_count = cast.del_msg(100)
    assert del_count == 1

    cast.add_msg('Message 3')
    cast.add_msg('Message 4')
    cast.add_msg('Message 5')
    cast.del_msg(2)
    cast.del_msg(alert=True)

    assert not cast.alert
    assert not cast.alert_exit
    assert [(m.key, m.message) for m in cast.messages] == [('5', 'Message 5')]

    cast_file = os.path.join(tempfile.gettempdir(), 'clicast.to_file_test.cast')
    try:
      cast.save(cast_file)
      cast = Cast.from_file(cast_file)
      cast.del_msg(100)

      cast.save(cast_file)
      cast = Cast.from_file(cast_file)
      cast.add_msg('Message 6')

      assert str(cast) == '[Messages]\n6: Message 6'
    finally:
      if os.path.exists(cast_file):
        os.unlink(cast_file)

  def test_filter(self):
    def msg_filter(msg, alert=False):
      if 'small bug' in msg:
        return msg
    cast = Cast.from_file(CAST_FILE, msg_filter)
    assert str(cast) == '[Messages]\n3: There is a small bug over there, so watch out!'


class TestCastReader(object):
  def setup_class(cls):
    CastReader.READ_MSG_FILE = '/tmp/clicast.test.read'
    if os.path.exists(CastReader.READ_MSG_FILE):
      os.unlink(CastReader.READ_MSG_FILE)

  def test_new_messages(self):
    cast = Cast.from_file(CAST_FILE)

    reader = CastReader(cast)
    assert reader.new_messages() == [
      'We found a big bad bug. Please try not to step on it!! Icky...\nNo worries. It will be fixed soon! :)',
      'Version 0.1 has been released! If you upgrade, you will get:\n'
      '1) Cool feature 1\n'
      '2) Cool feature 2\n'
      'So what are you waiting for? :)',
      'Version 0.2 has been released! Upgrade today to get cool features.',
      'There is a small bug over there, so watch out!',
      '[-f\\b] A bug that affects the -f option. (applies only if `clicast.filters.match_cli_args` filter is used)'
    ]

def test_url_content():
  assert '[Messages]' in url_content(CAST_URL)

  with patch('requests.get') as requests_get:
    mock_response = Mock()
    mock_response.text = '[Messages]\n1: Test Message'
    requests_get.return_value = mock_response

    assert str(url_content('url1', cache_duration=1)) == mock_response.text

    cached_text = mock_response.text
    mock_response.text = '[Messages]\n1: Test Message Updated'

    # This should return cached content
    assert str(url_content('url1', cache_duration=1)) == cached_text
    requests_get.assert_called_once_with('url1')

    assert str(url_content('url2', cache_duration=1)) == mock_response.text

    time.sleep(1)

    assert str(url_content('url1', cache_duration=1)) == mock_response.text
    assert requests_get.call_count == 3

    # No content,it should raise
    cache_file = _url_content_cache_file('url3')
    if os.path.exists(cache_file):
      os.unlink(cache_file)

    requests_get.side_effect = Exception
    with pytest.raises(Exception):
      assert str(url_content('url3', from_cache_on_error=True)) == mock_response.text

    requests_get.side_effect = None
    assert str(url_content('url3', from_cache_on_error=True)) == mock_response.text

    requests_get.side_effect = Exception
    assert str(url_content('url3', from_cache_on_error=True)) == mock_response.text
