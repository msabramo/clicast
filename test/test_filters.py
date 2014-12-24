import pytest

from clicast.filters import match_cli_args, match_program_and_subcommands


def test_match_cli_args():
  msg_text = 'Message for -b option\nLine 2'
  msg = '[ -b \w+] %s' % msg_text

  assert match_cli_args(msg, cli_args='./cli-command -b bug -i issue') == msg_text
  assert match_cli_args(msg, cli_args='./cli-command -i issue') == None


@pytest.mark.parametrize('msg', ['[program] Message', '[sc|subcommand] Message'])
def test_match_program_and_sub_commands(msg):
  assert match_program_and_subcommands(msg, cli_args='./program subcommand') == 'Message'
  assert match_program_and_subcommands(msg, cli_args='./program sc') == 'Message'
  assert match_program_and_subcommands(msg, cli_args='./anotherprogram prefixsubcommand -p program -s subcommand') == None
  assert match_program_and_subcommands(msg, cli_args='./anotherprogram scsuffix -p program -s subcommand') == None
